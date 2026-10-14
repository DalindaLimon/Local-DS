"""Shared FastAPI dependencies."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request

from app.config import Settings
from app.db import connect
from app.security import SESSION_COOKIE, session_user


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def optional_user(
    request: Request, conn: sqlite3.Connection = Depends(get_db), s: Settings = Depends(get_settings)
) -> sqlite3.Row | None:
    return session_user(conn, s.secret_key, request.cookies.get(SESSION_COOKIE))


def current_user(user: sqlite3.Row | None = Depends(optional_user)) -> sqlite3.Row:
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


def admin_user(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admins only")
    return user


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def is_https(request: Request, s: Settings) -> bool:
    if s.cookie_secure == "true":
        return True
    if s.cookie_secure == "false":
        return False
    return request.url.scheme == "https"
