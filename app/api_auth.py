"""Auth routes: first-run setup, login/logout, invites/registration, account."""

from __future__ import annotations

import secrets
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import __version__, ai
from app.config import Settings
from app.db import now, tx
from app.deps import client_ip, current_user, get_db, get_settings, is_https, optional_user
from app.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    create_session,
    delete_session,
    hash_password,
    needs_rehash,
    new_csrf_token,
    token_hash,
    validate_credentials,
    verify_password,
)

router = APIRouter(prefix="/api")


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=512)


class RegisterBody(Credentials):
    token: str = Field(max_length=128)


class PasswordChange(BaseModel):
    current: str = Field(max_length=512)
    new: str = Field(max_length=512)


class Prefs(BaseModel):
    feed_mode: Literal["latest", "foryou"] | None = None
    hide_seen: bool | None = None
    muted: bool | None = None
    theme: Literal["system", "dark", "black", "light"] | None = None
    accent: Literal["ember", "ocean", "forest", "grape", "rose", "gold"] | None = None
    layout: Literal["cards", "compact", "magazine"] | None = None


def user_public(u: sqlite3.Row) -> dict:
    return {
        "id": u["id"],
        "username": u["username"],
        "is_admin": bool(u["is_admin"]),
        "feed_mode": u["feed_mode"],
        "hide_seen": bool(u["hide_seen"]),
        "muted": bool(u["muted"]),
        "theme": u["theme"],
        "accent": u["accent"],
        "layout": u["layout"],
    }


def _set_session_cookie(response: Response, request: Request, s: Settings, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=s.session_days * 86400, httponly=True,
        secure=is_https(request, s), samesite="lax", path="/",
    )  # fmt: skip


def ensure_csrf_cookie(request: Request, response: Response, s: Settings) -> str:
    token = request.cookies.get(CSRF_COOKIE)
    if not token or len(token) > 64:
        token = new_csrf_token()
        response.set_cookie(
            CSRF_COOKIE, token, max_age=365 * 86400, httponly=False,
            secure=is_https(request, s), samesite="strict", path="/",
        )  # fmt: skip
    return token


def _user_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


@router.get("/state")
def state(
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
    user: sqlite3.Row | None = Depends(optional_user),
):
    csrf = ensure_csrf_cookie(request, response, s)
    response.headers["Cache-Control"] = "no-store"
    return {
        "setup_needed": _user_count(conn) == 0,
        "user": user_public(user) if user else None,
        "csrf": csrf,
        "version": __version__,
        "ai": ai.configured(s),
    }


def _login_response(request: Request, response: Response, conn, s: Settings, user_id: int) -> dict:
    token = create_session(conn, s.secret_key, user_id, s.session_days, request.headers.get("user-agent", ""))
    _set_session_cookie(response, request, s, token)
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return {"user": user_public(user)}


@router.post("/setup")
def setup(
    body: Credentials,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    err = validate_credentials(body.username, body.password)
    if err:
        raise HTTPException(400, err)
    with tx(conn):
        if _user_count(conn) > 0:
            raise HTTPException(403, "Setup is already complete")
        cur = conn.execute(
            "INSERT INTO users(username, pw_hash, is_admin, created_at) VALUES(?,?,1,?)",
            (body.username, hash_password(body.password), now()),
        )
    return _login_response(request, response, conn, s, cur.lastrowid)


@router.post("/login")
def login(
    body: Credentials,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    limiter = request.app.state.login_limiter
    ip = client_ip(request)
    wait = limiter.retry_after(ip, body.username)
    if wait:
        raise HTTPException(
            429, f"Too many attempts. Try again in {wait // 60 + 1} min.", headers={"Retry-After": str(wait)}
        )
    user = conn.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    if not verify_password(user["pw_hash"] if user else None, body.password) or not user:
        limiter.fail(ip, body.username)
        raise HTTPException(401, "Wrong username or password")
    limiter.success(ip, body.username)
    if needs_rehash(user["pw_hash"]):
        conn.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(body.password), user["id"]))
    return _login_response(request, response, conn, s, user["id"])


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    delete_session(conn, s.secret_key, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


def _invite_row(conn: sqlite3.Connection, s: Settings, token: str):
    return conn.execute(
        "SELECT * FROM invites WHERE token_hash=? AND used_at IS NULL AND expires_at > ?",
        (token_hash(s.secret_key, token), now()),
    ).fetchone()


@router.get("/invite/{token}")
def check_invite(token: str, conn: sqlite3.Connection = Depends(get_db), s: Settings = Depends(get_settings)):
    if len(token) > 128 or not _invite_row(conn, s, token):
        raise HTTPException(404, "This invite link is invalid, used or expired")
    return {"ok": True}


@router.post("/register")
def register(
    body: RegisterBody,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    limiter = request.app.state.login_limiter
    ip = client_ip(request)
    if limiter.retry_after(ip, "register:" + ip):
        raise HTTPException(429, "Too many attempts, try again later")
    err = validate_credentials(body.username, body.password)
    if err:
        raise HTTPException(400, err)
    with tx(conn):
        inv = _invite_row(conn, s, body.token)
        if not inv:
            limiter.fail(ip, "register:" + ip)
            raise HTTPException(404, "This invite link is invalid, used or expired")
        if conn.execute("SELECT 1 FROM users WHERE username=?", (body.username,)).fetchone():
            raise HTTPException(409, "That username is taken")
        cur = conn.execute(
            "INSERT INTO users(username, pw_hash, is_admin, created_at) VALUES(?,?,0,?)",
            (body.username, hash_password(body.password), now()),
        )
        conn.execute(
            "UPDATE invites SET used_by=?, used_at=? WHERE token_hash=?", (cur.lastrowid, now(), inv["token_hash"])
        )
    return _login_response(request, response, conn, s, cur.lastrowid)


@router.post("/account/password")
def change_password(
    body: PasswordChange,
    request: Request,
    response: Response,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    if not verify_password(user["pw_hash"], body.current):
        raise HTTPException(400, "Current password is wrong")
    err = validate_credentials(user["username"], body.new)
    if err:
        raise HTTPException(400, err)
    with tx(conn):
        conn.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(body.new), user["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    return _login_response(request, response, conn, s, user["id"])


@router.patch("/me/prefs")
def update_prefs(body: Prefs, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    if body.feed_mode is not None:
        conn.execute("UPDATE users SET feed_mode=? WHERE id=?", (body.feed_mode, user["id"]))
    if body.hide_seen is not None:
        conn.execute("UPDATE users SET hide_seen=? WHERE id=?", (int(body.hide_seen), user["id"]))
    if body.muted is not None:
        conn.execute("UPDATE users SET muted=? WHERE id=?", (int(body.muted), user["id"]))
    for col in ("theme", "accent", "layout"):
        if getattr(body, col) is not None:
            conn.execute(f"UPDATE users SET {col}=? WHERE id=?", (getattr(body, col), user["id"]))
    return {"user": user_public(conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())}


def new_invite(conn: sqlite3.Connection, s: Settings, created_by: int, hours: float, note: str = "") -> str:
    token = secrets.token_urlsafe(24)
    conn.execute(
        "INSERT INTO invites(token_hash, created_by, created_at, expires_at, note) VALUES(?,?,?,?,?)",
        (token_hash(s.secret_key, token), created_by, now(), now() + hours * 3600, note[:100]),
    )
    return token
