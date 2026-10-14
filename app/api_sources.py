"""Sources, discovery and admin routes."""

from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app import __version__, ai, discovery, jobs, retention, settings_store, shorts
from app import personalization as P
from app.api_auth import new_invite
from app.api_feed import invalidate_foryou, invalidate_foryou_all
from app.config import Settings
from app.db import kv_get, now, tx
from app.deps import admin_user, current_user, get_db, get_settings
from app.locks import guard
from app.sources import SourceError, add_source

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- sources


def _sources_payload(conn: sqlite3.Connection, user: sqlite3.Row) -> list[dict]:
    uid = user["id"]
    prefs = P.get_prefs(conn, uid)
    stats = conn.execute(
        """SELECT r.source_id, SUM(r.value=1) AS likes, SUM(r.value=-1) AS dislikes
           FROM reactions r LEFT JOIN user_source_prefs p ON p.user_id=r.user_id AND p.source_id=r.source_id
           WHERE r.user_id=? AND (p.reset_at IS NULL OR r.created_at >= p.reset_at) GROUP BY r.source_id""",
        (uid,),
    ).fetchall()
    stats_by = {r["source_id"]: (r["likes"] or 0, r["dislikes"] or 0) for r in stats}
    rows = conn.execute(
        """SELECT s.*,
             (SELECT COUNT(*) FROM items i WHERE i.source_id=s.id) AS item_count,
             (SELECT COUNT(*) FROM shorts sh WHERE sh.source_id=s.id AND sh.status='available') AS shorts_available,
             (SELECT COUNT(*) FROM shorts sh WHERE sh.source_id=s.id) AS shorts_total
           FROM sources s WHERE s.status != 'removed' ORDER BY lower(s.title)"""
    ).fetchall()
    active_weights = {
        r["id"]: (prefs[r["id"]]["weight"] if r["id"] in prefs else 1.0)
        for r in rows
        if r["enabled"] and not (r["id"] in prefs and prefs[r["id"]]["manual"] == "mute")
    }
    share = P.share_of_feed(active_weights)
    out = []
    for r in rows:
        p = prefs.get(r["id"])
        likes, dislikes = stats_by.get(r["id"], (0, 0))
        weight = p["weight"] if p else 1.0
        out.append(
            {
                "id": r["id"],
                "kind": r["kind"],
                "title": r["title"],
                "feed_url": r["feed_url"],
                "site_url": r["site_url"] or r["channel_url"],
                "icon": r["icon_url"],
                "enabled": bool(r["enabled"]),
                "rss_enabled": bool(r["rss_enabled"]),
                "shorts_enabled": bool(r["shorts_enabled"]),
                "topics": [t for t in (r["topics"] or "").split(",") if t],
                "status": r["status"],
                "last_fetched": r["last_fetched"],
                "last_error": r["last_error"],
                "backoff_until": r["backoff_until"] if (r["backoff_until"] or 0) > now() else None,
                "item_count": r["item_count"],
                "shorts_available": r["shorts_available"],
                "shorts_total": r["shorts_total"],
                "weight": round(weight, 2),
                "share": share.get(r["id"], 0.0),
                "manual": p["manual"] if p else None,
                "likes": likes,
                "dislikes": dislikes,
                "why": P.why_line(weight, likes, dislikes, p["manual"] if p else None),
            }
        )
    return out


@router.get("/sources")
def list_sources(user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return {"sources": _sources_payload(conn, user)}


class AddSourceBody(BaseModel):
    input: str = Field(min_length=1, max_length=2048)
    also_rss: bool = True
    topics: list[str] | None = Field(default=None, max_length=10)


@router.post("/sources")
async def create_source(
    body: AddSourceBody,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    topics = [t.strip().lower()[:30] for t in body.topics or [] if t.strip()] or None
    try:
        row, created = await run_in_threadpool(add_source, conn, s, body.input, user["id"], body.also_rss, topics)
    except SourceError as exc:
        raise HTTPException(400, str(exc)) from None
    if not created and row["status"] == "removed":
        with tx(conn):
            conn.execute("UPDATE sources SET status='new', enabled=1 WHERE id=?", (row["id"],))
        created = True
    if row["kind"] in ("rss", "reddit", "youtube") and row["rss_enabled"] and created:
        jobs.submit(jobs.rss_job, s, row["id"])
    if row["kind"] == "youtube" and created:
        jobs.submit(jobs.shorts_job, s, row["id"])
    payload = next((x for x in _sources_payload(conn, user) if x["id"] == row["id"]), None)
    return {"source": payload, "created": created}


class PatchSourceBody(BaseModel):
    enabled: bool | None = None
    rss_enabled: bool | None = None
    shorts_enabled: bool | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    manual: Literal["boost", "mute", "none"] | None = None


@router.patch("/sources/{source_id}")
def patch_source(
    source_id: int,
    body: PatchSourceBody,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    src = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not src:
        raise HTTPException(404, "Not found")
    with tx(conn):
        if body.enabled is not None:
            conn.execute("UPDATE sources SET enabled=? WHERE id=?", (int(body.enabled), source_id))
            if body.enabled:
                conn.execute("UPDATE sources SET backoff_until=NULL, error_count=0 WHERE id=?", (source_id,))
        if body.rss_enabled is not None:
            conn.execute("UPDATE sources SET rss_enabled=? WHERE id=?", (int(body.rss_enabled), source_id))
        if body.shorts_enabled is not None:
            if src["kind"] != "youtube":
                raise HTTPException(400, "Only YouTube sources have Shorts")
            conn.execute("UPDATE sources SET shorts_enabled=? WHERE id=?", (int(body.shorts_enabled), source_id))
        if body.title is not None:
            conn.execute("UPDATE sources SET title=? WHERE id=?", (body.title.strip(), source_id))
    if body.manual is not None:
        P.set_manual(conn, user["id"], source_id, None if body.manual == "none" else body.manual, s)
    invalidate_foryou(user["id"])
    return {"source": next(x for x in _sources_payload(conn, user) if x["id"] == source_id)}


@router.post("/sources/{source_id}/reset")
def reset_source(
    source_id: int,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    if not conn.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
        raise HTTPException(404, "Not found")
    P.reset_source(conn, user["id"], source_id, s)
    invalidate_foryou(user["id"])
    return {"source": next(x for x in _sources_payload(conn, user) if x["id"] == source_id)}


@router.post("/sources/{source_id}/refresh")
def refresh_source(
    source_id: int,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    src = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not src:
        raise HTTPException(404, "Not found")
    conn.execute("UPDATE sources SET backoff_until=NULL WHERE id=?", (source_id,))
    if src["rss_enabled"] and src["kind"] != "demo":
        jobs.submit(jobs.rss_job, s, source_id)
    if src["kind"] == "youtube" and src["shorts_enabled"]:
        jobs.submit(jobs.shorts_job, s, source_id)
    return {"ok": True}


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, user=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """Remove a source. Items nobody interacted with are deleted; items with comments or
    reactions are kept (with the source archived) so no comment or reaction is ever lost."""
    if not conn.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
        raise HTTPException(404, "Not found")
    with tx(conn):
        conn.execute(
            """DELETE FROM items WHERE source_id=?
               AND NOT EXISTS (SELECT 1 FROM comments c WHERE c.item_type='item' AND c.item_id=items.id)
               AND NOT EXISTS (SELECT 1 FROM reactions r WHERE r.item_type='item' AND r.item_id=items.id)""",
            (source_id,),
        )
        keep_items = conn.execute("SELECT COUNT(*) FROM items WHERE source_id=?", (source_id,)).fetchone()[0]
        keep_shorts = conn.execute("SELECT COUNT(*) FROM shorts WHERE source_id=?", (source_id,)).fetchone()[0]
        if keep_items or keep_shorts:
            conn.execute("UPDATE sources SET status='removed', enabled=0, shorts_enabled=0 WHERE id=?", (source_id,))
            archived = True
        else:
            conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
            archived = False
    return {"ok": True, "archived": archived}


# --------------------------------------------------------------------------- discover


@router.get("/discover/starter")
def discover_starter(user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    # Topic affinity orders the starter groups: what you like, dislike and comment on comes first or last.
    aff = discovery.topic_affinity(conn, user["id"])
    return {"items": discovery.starter_list(conn), "affinity": {k: round(v, 2) for k, v in aff.items()}}


@router.get("/discover/suggested")
def discover_suggested(
    kind: Literal["youtube", "reddit", "rss"] | None = None,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    return {"items": discovery.suggested(conn, user["id"], kind=kind)}


@router.get("/discover/search")
async def discover_search(
    q: str,
    kind: Literal["youtube", "reddit"] = "youtube",
    user=Depends(current_user),
    s: Settings = Depends(get_settings),
):
    q = q.strip()[:100]
    if len(q) < 2:
        return {"items": [], "error": None}
    try:
        if kind == "youtube":
            items = await run_in_threadpool(shorts.search_channels, q)
        else:
            items = await run_in_threadpool(discovery.search_reddit, q, s)
        return {"items": items, "error": None}
    except Exception as exc:
        return {"items": [], "error": f"Search failed: {exc}"[:200]}


# --------------------------------------------------------------------------- admin


@router.get("/admin/status")
def admin_status(
    request: Request,
    user=Depends(admin_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    users = [
        {"id": u["id"], "username": u["username"], "is_admin": bool(u["is_admin"]), "created_at": u["created_at"]}
        for u in conn.execute("SELECT * FROM users ORDER BY id")
    ]
    invites = [
        {
            "id": i["token_hash"][:12],
            "created_at": i["created_at"],
            "expires_at": i["expires_at"],
            "used_by": i["username"],
            "used_at": i["used_at"],
            "note": i["note"],
        }
        for i in conn.execute(
            """SELECT i.*, u.username FROM invites i LEFT JOIN users u ON u.id=i.used_by
               ORDER BY i.created_at DESC LIMIT 20"""
        )
    ]
    counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) AS n FROM shorts GROUP BY status")}
    return {
        "version": __version__,
        "ytdlp_version": kv_get(conn, "ytdlp_version", "unknown"),
        "shorts_status": kv_get(conn, "shorts_status", "No runs yet"),
        "disk": retention.disk_usage(s),
        "jobs": jobs.job_status,
        "in_use": guard.snapshot(),
        "shorts": counts,
        "items": conn.execute("SELECT COUNT(*) FROM items").fetchone()[0],
        "comments": conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0],
        "reactions": conn.execute("SELECT COUNT(*) FROM reactions").fetchone()[0],
        "users": users,
        "invites": invites,
        "settings": {
            "retention_days": s.retention_days,
            "keep_thumbnails": s.keep_thumbnails,
            "max_height": s.max_height,
            "min_free_disk_mb": s.min_free_disk_mb,
            "hwaccel": s.hwaccel,
            "vaapi_device": shorts.vaapi_device(s),
            "like_base": s.like_base,
            "dislike_factor": s.dislike_factor,
            "halflife_days": s.reaction_halflife_days,
            "min_weight": s.min_weight,
            "max_weight": s.max_weight,
            "explore_percent": s.explore_percent,
            "llm_base_url": s.llm_base_url or None,
            "llm_model": s.llm_model or None,
        },
    }


@router.get("/admin/settings")
def get_admin_settings(
    user=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db), s: Settings = Depends(get_settings)
):
    return settings_store.describe(s, conn)


class SettingsPatch(BaseModel):
    values: dict[str, bool | int | float | str | None] = Field(max_length=100)


@router.patch("/admin/settings")
def patch_admin_settings(
    body: SettingsPatch,
    user=Depends(admin_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    """Save setting overrides (null = back to the .env value). They apply immediately, no restart."""
    try:
        changed = settings_store.update(s, conn, body.values)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    if {"rss_interval_min", "shorts_interval_min"} & set(changed):
        jobs.reschedule(s)
    if set(changed) & {
        "like_base",
        "dislike_factor",
        "reaction_halflife_days",
        "min_weight",
        "max_weight",
        "boost_multiplier",
        "explore_percent",
        "foryou_halflife_hours",
        "foryou_window_days",
    }:
        P.recompute_all(conn, s)
        invalidate_foryou_all()
    return {**settings_store.describe(s, conn), "changed": changed, "ai": ai.configured(s)}


class InviteBody(BaseModel):
    hours: float = Field(default=72, gt=0, le=24 * 30)
    note: str = Field(default="", max_length=100)


@router.post("/admin/invites")
def create_invite(
    body: InviteBody,
    request: Request,
    user=Depends(admin_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    token = new_invite(conn, s, user["id"], body.hours, body.note)
    base = s.base_url.rstrip("/") if s.base_url else str(request.base_url).rstrip("/")
    return {"url": f"{base}/#/invite/{token}", "expires_at": now() + body.hours * 3600}


@router.delete("/admin/invites/{invite_id}")
def revoke_invite(invite_id: str, user=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    if len(invite_id) != 12:
        raise HTTPException(400, "Bad id")
    conn.execute("DELETE FROM invites WHERE substr(token_hash,1,12)=? AND used_at IS NULL", (invite_id,))
    return {"ok": True}


class UserPatch(BaseModel):
    is_admin: bool | None = None


@router.patch("/admin/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, user=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    if user_id == user["id"]:
        raise HTTPException(400, "You can't change your own admin flag")
    if body.is_admin is not None:
        conn.execute("UPDATE users SET is_admin=? WHERE id=?", (int(body.is_admin), user_id))
    return {"ok": True}


@router.delete("/admin/users/{user_id}")
def delete_user(user_id: int, user=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """Delete a user account. Their comments stay (shown as [deleted user])."""
    if user_id == user["id"]:
        raise HTTPException(400, "You can't delete yourself")
    with tx(conn):
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.execute(
            """UPDATE shorts SET
                 like_count=(SELECT COUNT(*) FROM reactions r WHERE r.item_type='short' AND r.item_id=shorts.id AND r.value=1),
                 dislike_count=(SELECT COUNT(*) FROM reactions r WHERE r.item_type='short' AND r.item_id=shorts.id AND r.value=-1)"""
        )
    return {"ok": True}


@router.post("/admin/refresh")
def admin_refresh(user=Depends(admin_user), s: Settings = Depends(get_settings)):
    """Fetch every feed and check every channel for new Shorts right now."""
    started = now()
    jobs.submit(jobs.rss_job, s)
    jobs.submit(jobs.shorts_job, s)
    return {"ok": True, "started": started}


@router.get("/admin/jobs")
def job_state(user=Depends(admin_user)):
    return {"jobs": jobs.job_status}


@router.post("/admin/jobs/{name}")
def run_job(
    name: Literal["rss", "shorts", "cleanup", "weights", "ytdlp_update"],
    user=Depends(admin_user),
    s: Settings = Depends(get_settings),
):
    fn = {
        "rss": jobs.rss_job,
        "shorts": jobs.shorts_job,
        "cleanup": jobs.cleanup_job,
        "weights": jobs.weights_job,
        "ytdlp_update": jobs.ytdlp_job,
    }[name]
    jobs.submit(fn, s)
    return {"ok": True}
