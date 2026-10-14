"""Feed, Reels, reactions, comments, seen-state and media routes."""

from __future__ import annotations

import base64
import html
import json
import os
import random
import re
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app import icons, uploads
from app import personalization as P
from app.config import Settings
from app.db import now, tx
from app.deps import current_user, get_db, get_settings
from app.locks import guard

router = APIRouter()

PAGE = 20
ItemType = Literal["item", "short"]
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


# --------------------------------------------------------------------------- helpers


def _enc(obj: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode().rstrip("=")


def _dec(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(cursor + pad))
        return data if isinstance(data, dict) else None
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(400, "Bad cursor") from None


def _reaction_stats(conn: sqlite3.Connection, user_id: int) -> dict[int, tuple[int, int]]:
    """source_id -> (likes, dislikes) counted after that source's reset."""
    rows = conn.execute(
        """SELECT r.source_id, SUM(r.value=1) AS likes, SUM(r.value=-1) AS dislikes
           FROM reactions r LEFT JOIN user_source_prefs p ON p.user_id=r.user_id AND p.source_id=r.source_id
           WHERE r.user_id=? AND r.source_id IS NOT NULL AND (p.reset_at IS NULL OR r.created_at >= p.reset_at)
           GROUP BY r.source_id""",
        (user_id,),
    ).fetchall()
    return {r["source_id"]: (r["likes"] or 0, r["dislikes"] or 0) for r in rows}


class Ctx:
    """Per-request personalization context for building 'why' lines."""

    def __init__(self, conn: sqlite3.Connection, user_id: int) -> None:
        self.conn = conn
        self.uid = user_id
        self.prefs = P.get_prefs(conn, user_id)
        self.stats = _reaction_stats(conn, user_id)

    def weight(self, source_id: int | None) -> float:
        p = self.prefs.get(source_id)
        return p["weight"] if p else 1.0

    def why(self, source_id: int | None, explored: bool = False) -> str:
        p = self.prefs.get(source_id)
        likes, dislikes = self.stats.get(source_id, (0, 0))
        return P.why_line(self.weight(source_id), likes, dislikes, p["manual"] if p else None, explored)


ITEM_SELECT = """
SELECT i.id, i.source_id, i.url, i.title, i.author, i.excerpt, i.image_url, i.published_at,
       s.title AS source_title, s.kind AS source_kind, s.icon_path AS source_icon_path,
       s.icon_checked_at AS source_icon_v, s.created_by AS source_owner,
       r.value AS my_reaction, sn.seen_at,
       (SELECT COUNT(*) FROM comments c WHERE c.item_type='item' AND c.item_id=i.id) AS comment_count,
       (SELECT COUNT(*) FROM reactions x WHERE x.item_type='item' AND x.item_id=i.id AND x.value=1) AS likes,
       (SELECT COUNT(*) FROM reactions x WHERE x.item_type='item' AND x.item_id=i.id AND x.value=-1) AS dislikes
FROM items i
JOIN sources s ON s.id = i.source_id
LEFT JOIN reactions r ON r.user_id = :uid AND r.item_type='item' AND r.item_id = i.id
LEFT JOIN seen sn ON sn.user_id = :uid AND sn.item_type='item' AND sn.item_id = i.id
"""

# Feed filter chips: unread, or what the user did with the post.
SHOW_FILTERS = {
    "all": "",
    "unread": " AND sn.seen_at IS NULL",
    "liked": " AND r.value = 1",
    "disliked": " AND r.value = -1",
    "commented": (
        " AND EXISTS (SELECT 1 FROM comments c WHERE c.item_type='item' AND c.item_id=i.id AND c.user_id=:uid)"
    ),
}
ShowFilter = Literal["all", "unread", "liked", "disliked", "commented"]

FEED_WHERE = """
WHERE s.enabled = 1 AND s.rss_enabled = 1
  AND s.id NOT IN (SELECT source_id FROM user_source_prefs WHERE user_id = :uid AND manual = 'mute')
"""


def item_json(row: sqlite3.Row, ctx: Ctx, explored: bool = False) -> dict:
    return {
        "type": "item",
        "id": row["id"],
        "source": {
            "id": row["source_id"],
            "title": row["source_title"],
            "kind": row["source_kind"],
            "icon": icons.icon_url(row, "source_id", "source_icon_path", "source_icon_v"),
        },
        "title": row["title"],
        "url": row["url"],
        "author": row["author"],
        "excerpt": row["excerpt"],
        "image": row["image_url"],
        "published_at": row["published_at"],
        "comments": row["comment_count"],
        "likes": row["likes"],
        "dislikes": row["dislikes"],
        "my": row["my_reaction"] or 0,
        "seen": row["seen_at"] is not None,
        "why": ctx.why(row["source_id"], explored),
        "explored": explored,
        "mine": row["source_kind"] == "user" and row["source_owner"] == ctx.uid,
        "attachments": _attachments(ctx.conn, row["id"]) if row["source_kind"] == "user" else [],
    }


def _attachments(conn: sqlite3.Connection, item_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM attachments WHERE item_id=? ORDER BY id", (item_id,)).fetchall()
    return [uploads.attachment_json(r) for r in rows]


# For-you ordering is cached per user/snapshot so infinite scroll stays stable.
_foryou_cache: OrderedDict[tuple, list[tuple[int, bool]]] = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_MAX = 32


def _foryou_order(
    conn: sqlite3.Connection, s: Settings, uid: int, snap: float, seed: int, source: int | None
) -> list[tuple[int, bool]]:
    key = (uid, snap, seed, source)
    with _cache_lock:
        if key in _foryou_cache:
            _foryou_cache.move_to_end(key)
            return _foryou_cache[key]
    params: dict = {"uid": uid, "since": snap - s.foryou_window_days * 86400}
    q = (
        "SELECT i.id, i.source_id, i.published_at FROM items i JOIN sources s ON s.id=i.source_id "
        "LEFT JOIN reactions r ON r.user_id=:uid AND r.item_type='item' AND r.item_id=i.id "
        + FEED_WHERE
        + " AND i.published_at >= :since"
    )
    if source:
        q += " AND i.source_id = :src"
        params["src"] = source
    q += " ORDER BY i.published_at DESC LIMIT 4000"
    rows = conn.execute(q, params).fetchall()
    weights = P.get_weights(conn, uid)
    scored = sorted(
        rows,
        key=lambda r: (
            -P.foryou_score(weights.get(r["source_id"], 1.0), snap - r["published_at"], s.foryou_halflife_hours),
            -r["id"],
        ),
    )
    rng = random.Random(seed)
    mixed = P.mix_exploration([r["id"] for r in scored], s.explore_percent, rng)
    with _cache_lock:
        _foryou_cache[key] = mixed
        while len(_foryou_cache) > _CACHE_MAX:
            _foryou_cache.popitem(last=False)
    return mixed


def invalidate_foryou(uid: int) -> None:
    with _cache_lock:
        for k in [k for k in _foryou_cache if k[0] == uid]:
            del _foryou_cache[k]


def invalidate_foryou_all() -> None:
    with _cache_lock:
        _foryou_cache.clear()


# --------------------------------------------------------------------------- feed


@router.get("/api/feed")
def feed(
    mode: Literal["latest", "foryou"] = "latest",
    cursor: str | None = None,
    source: int | None = None,
    hide_seen: bool = False,
    show: ShowFilter = "all",
    limit: int = Query(PAGE, ge=1, le=50),
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    uid = user["id"]
    ctx = Ctx(conn, uid)
    cur = _dec(cursor)
    if hide_seen and show == "all":
        show = "unread"  # older clients
    if mode == "latest":
        params: dict = {"uid": uid, "lim": limit + 1}
        q = ITEM_SELECT + FEED_WHERE
        if source:
            q += " AND i.source_id = :src"
            params["src"] = source
        q += SHOW_FILTERS[show]
        if cur:
            q += " AND (i.published_at < :cp OR (i.published_at = :cp AND i.id < :ci))"
            params["cp"], params["ci"] = float(cur.get("p", 0)), int(cur.get("i", 0))
        q += " ORDER BY i.published_at DESC, i.id DESC LIMIT :lim"
        rows = conn.execute(q, params).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = _enc({"p": rows[-1]["published_at"], "i": rows[-1]["id"]}) if more and rows else None
        return {"items": [item_json(r, ctx) for r in rows], "cursor": next_cursor}

    # For you
    snap = float(cur["t"]) if cur else round(now(), 3)
    seed = int(cur["sd"]) if cur else random.randrange(1 << 30)
    offset = int(cur.get("o", 0)) if cur else 0
    order = _foryou_order(conn, s, uid, snap, seed, source)
    out = []
    pos = offset
    while pos < len(order) and len(out) < limit:
        chunk = order[pos : pos + limit * 3]
        ids = [i for i, _ in chunk]
        marks = ",".join(str(int(i)) for i in ids) or "0"
        q = ITEM_SELECT + FEED_WHERE + f" AND i.id IN ({marks})" + SHOW_FILTERS[show]
        rows = {r["id"]: r for r in conn.execute(q, {"uid": uid}).fetchall()}
        for item_id, explored in chunk:
            pos += 1
            r = rows.get(item_id)
            if r is not None:
                out.append(item_json(r, ctx, explored))
                if len(out) >= limit:
                    break
    next_cursor = _enc({"t": snap, "sd": seed, "o": pos}) if pos < len(order) else None
    return {"items": out, "cursor": next_cursor}


@router.get("/api/items/{item_id}")
def item_detail(item_id: int, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute(ITEM_SELECT + " WHERE i.id = :id", {"uid": user["id"], "id": item_id}).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    content = conn.execute("SELECT content_html FROM items WHERE id=?", (item_id,)).fetchone()["content_html"]
    data = item_json(row, Ctx(conn, user["id"]))
    data["content_html"] = content or ""
    level = _priorities(conn, user["id"]).get(("item", item_id))
    data["priority"] = PRIORITY_NAMES.get(level) if level else None
    return data


class SeenBody(BaseModel):
    type: ItemType
    ids: list[int] = Field(max_length=200)


@router.post("/api/seen")
def mark_seen(body: SeenBody, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    t = now()
    with tx(conn):
        conn.executemany(
            "INSERT OR IGNORE INTO seen(user_id, item_type, item_id, seen_at) VALUES(?,?,?,?)",
            [(user["id"], body.type, i, t) for i in body.ids],
        )
    return {"ok": True}


# --------------------------------------------------------------------------- reels


SHORT_SELECT = """
SELECT sh.*, s.title AS source_title, s.icon_path AS source_icon_path, s.icon_checked_at AS source_icon_v,
       r.value AS my_reaction, sn.seen_at,
       (SELECT COUNT(*) FROM comments c WHERE c.item_type='short' AND c.item_id=sh.id) AS comment_count
FROM shorts sh
LEFT JOIN sources s ON s.id = sh.source_id
LEFT JOIN reactions r ON r.user_id = :uid AND r.item_type='short' AND r.item_id = sh.id
LEFT JOIN seen sn ON sn.user_id = :uid AND sn.item_type='short' AND sn.item_id = sh.id
"""


def short_json(row: sqlite3.Row, ctx: Ctx, explored: bool = False) -> dict:
    vid = row["video_id"]
    return {
        "type": "short",
        "id": row["id"],
        "video_id": vid,
        "source_id": row["source_id"],
        "title": row["title"],
        "channel": row["channel_name"] or row["source_title"] or "",
        "icon": icons.icon_url(row, "source_id", "source_icon_path", "source_icon_v") if row["source_id"] else None,
        "url": row["url"],
        "video": f"/media/video/{vid}" if row["status"] == "available" else None,
        "thumb": f"/media/thumb/{vid}" if row["thumb_path"] else None,
        "status": row["status"],
        "published_at": row["published_at"],
        "downloaded_at": row["downloaded_at"],
        "expired_at": row["expired_at"],
        "likes": row["like_count"],
        "dislikes": row["dislike_count"],
        "comments": row["comment_count"],
        "my": row["my_reaction"] or 0,
        "seen": row["seen_at"] is not None,
        "why": ctx.why(row["source_id"], explored),
        "explored": explored,
    }


class ReelsBody(BaseModel):
    exclude: list[int] = Field(default_factory=list, max_length=5000)
    n: int = Field(default=6, ge=1, le=30)


def reels_order(
    conn: sqlite3.Connection, s: Settings, uid: int, exclude: set[int], rng: random.Random | None = None
) -> list[tuple[sqlite3.Row, bool]]:
    """Unseen first (weighted shuffle + exploration), then seen ones."""
    rows = conn.execute(
        SHORT_SELECT
        + """ WHERE sh.status='available'
              AND (sh.source_id IS NULL OR sh.source_id NOT IN
                   (SELECT source_id FROM user_source_prefs WHERE user_id=:uid AND manual='mute'))
              AND (sh.source_id IS NULL OR sh.source_id IN (SELECT id FROM sources WHERE enabled=1))""",
        {"uid": uid},
    ).fetchall()
    rows = [r for r in rows if r["id"] not in exclude]
    weights = P.get_weights(conn, uid)
    rng = rng or random.Random()
    out: list[tuple[sqlite3.Row, bool]] = []
    for group in ([r for r in rows if r["seen_at"] is None], [r for r in rows if r["seen_at"] is not None]):
        ordered = P.weighted_shuffle(group, lambda r: weights.get(r["source_id"], 1.0), rng)
        out.extend(P.mix_exploration(ordered, s.explore_percent, rng, key=lambda r: r["id"]))
    return out


@router.post("/api/reels/next")
def reels_next(
    body: ReelsBody,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    ctx = Ctx(conn, user["id"])
    order = reels_order(conn, s, user["id"], set(body.exclude))
    reset = False
    if not order and body.exclude:
        # End reached: reshuffle everything instead of a dead end.
        order = reels_order(conn, s, user["id"], set())
        reset = True
    return {"items": [short_json(r, ctx, e) for r, e in order[: body.n]], "reset": reset, "remaining": len(order)}


@router.get("/api/shorts/past")
def past_shorts(
    cursor: str | None = None,
    limit: int = Query(PAGE, ge=1, le=50),
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    ctx = Ctx(conn, user["id"])
    params: dict = {"uid": user["id"], "lim": limit + 1}
    q = SHORT_SELECT + " WHERE sh.status='expired'"
    cur = _dec(cursor)
    if cur:
        q += " AND (COALESCE(sh.expired_at,0) < :ce OR (COALESCE(sh.expired_at,0) = :ce AND sh.id < :ci))"
        params["ce"], params["ci"] = float(cur["e"]), int(cur["i"])
    q += " ORDER BY COALESCE(sh.expired_at,0) DESC, sh.id DESC LIMIT :lim"
    rows = conn.execute(q, params).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    nxt = _enc({"e": rows[-1]["expired_at"] or 0, "i": rows[-1]["id"]}) if more and rows else None
    return {"items": [short_json(r, ctx) for r in rows], "cursor": nxt}


@router.get("/api/shorts/{short_id}")
def short_detail(short_id: int, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute(SHORT_SELECT + " WHERE sh.id = :id", {"uid": user["id"], "id": short_id}).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    return short_json(row, Ctx(conn, user["id"]))


# --------------------------------------------------------------------------- reactions


class ReactBody(BaseModel):
    type: ItemType
    id: int
    value: Literal[-1, 0, 1]


@router.post("/api/react")
def react(
    body: ReactBody,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    try:
        res = P.react(conn, user["id"], body.type, body.id, body.value, s)
    except LookupError:
        raise HTTPException(404, "Not found") from None
    invalidate_foryou(user["id"])
    ctx = Ctx(conn, user["id"])
    res["why"] = ctx.why(res["source_id"])
    return res


# --------------------------------------------------------------------------- activity

ACTIVITY_SQL = {
    "liked": "SELECT item_type, item_id, created_at AS t FROM reactions WHERE user_id=:uid AND value=1",
    "disliked": "SELECT item_type, item_id, created_at AS t FROM reactions WHERE user_id=:uid AND value=-1",
    "commented": """SELECT item_type, item_id, MAX(created_at) AS t FROM comments WHERE user_id=:uid
                    GROUP BY item_type, item_id""",
    "priority": "SELECT item_type, item_id, updated_at AS t FROM priorities WHERE user_id=:uid",
}
ACTIVITY_MAX = 5000
PRIORITY_NAMES = {1: "high", 2: "medium", 3: "low"}
PRIORITY_LEVELS = {v: k for k, v in PRIORITY_NAMES.items()}


def _priorities(conn: sqlite3.Connection, uid: int) -> dict[tuple[str, int], int]:
    rows = conn.execute("SELECT item_type, item_id, level FROM priorities WHERE user_id=?", (uid,)).fetchall()
    return {(r["item_type"], r["item_id"]): r["level"] for r in rows}


@router.get("/api/me/activity")
def my_activity(
    kind: Literal["liked", "disliked", "commented", "priority"] = "liked",
    q: str = Query("", max_length=200),
    source: int | None = None,
    type: Literal["all", "item", "short"] = "all",
    priority: Literal["any", "set", "high", "medium", "low", "none"] = "any",
    sort: Literal["recent", "oldest", "priority", "popular"] = "recent",
    cursor: str | None = None,
    limit: int = Query(PAGE, ge=1, le=50),
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Posts and Shorts this user liked, disliked, commented on, or put on their priority list.

    Filtering and sorting happen in Python: a user's activity is at most a few thousand rows.
    """
    uid = user["id"]
    cur = _dec(cursor)
    offset = int(cur.get("o", 0)) if cur else 0
    refs = conn.execute(
        f"SELECT * FROM ({ACTIVITY_SQL[kind]}) ORDER BY t DESC, item_id DESC LIMIT :lim",
        {"uid": uid, "lim": ACTIVITY_MAX},
    ).fetchall()
    if type != "all":
        refs = [r for r in refs if r["item_type"] == type]
    prios = _priorities(conn, uid)
    if priority == "set":
        refs = [r for r in refs if (r["item_type"], r["item_id"]) in prios]
    elif priority == "none":
        refs = [r for r in refs if (r["item_type"], r["item_id"]) not in prios]
    elif priority != "any":
        refs = [r for r in refs if prios.get((r["item_type"], r["item_id"])) == PRIORITY_LEVELS[priority]]

    ctx = Ctx(conn, uid)

    def fetch(sql: str, item_type: str) -> dict[int, sqlite3.Row]:
        ids = ",".join(str(int(r["item_id"])) for r in refs if r["item_type"] == item_type) or "0"
        return {r["id"]: r for r in conn.execute(sql + f" ({ids})", {"uid": uid}).fetchall()}

    rows = {
        "item": fetch(ITEM_SELECT + " WHERE i.id IN", "item"),
        "short": fetch(SHORT_SELECT + " WHERE sh.id IN", "short"),
    }
    entries = []
    facets: dict[int, dict] = {}
    needle = q.strip().lower()
    for r in refs:
        row = rows[r["item_type"]].get(r["item_id"])
        if row is None:
            continue  # the post was deleted by its author
        data = item_json(row, ctx) if r["item_type"] == "item" else short_json(row, ctx)
        src_id = data["source"]["id"] if r["item_type"] == "item" else data["source_id"]
        src_title = data["source"]["title"] if r["item_type"] == "item" else data["channel"]
        if (
            needle
            and needle
            not in " ".join(
                str(x or "") for x in (data["title"], src_title, data.get("excerpt"), data.get("author"))
            ).lower()
        ):
            continue
        if src_id is not None:
            f = facets.setdefault(src_id, {"id": src_id, "title": src_title, "count": 0})
            f["count"] += 1
        if source is not None and src_id != source:
            continue
        level = prios.get((r["item_type"], r["item_id"]))
        data["priority"] = PRIORITY_NAMES.get(level) if level else None
        data["acted_at"] = r["t"]
        entries.append((data, level or 9))
    if sort == "oldest":
        entries.reverse()
    elif sort == "priority":
        entries.sort(key=lambda e: e[1])  # stable: newest first within a level
    elif sort == "popular":
        entries.sort(key=lambda e: -(e[0]["likes"] + 2 * e[0]["comments"]))
    page = [d for d, _ in entries[offset : offset + limit]]
    return {
        "items": page,
        "cursor": _enc({"o": offset + limit}) if offset + limit < len(entries) else None,
        "total": len(entries),
        "sources": sorted(facets.values(), key=lambda f: (-f["count"], f["title"].lower())) if not cur else None,
    }


class PriorityBody(BaseModel):
    type: ItemType
    id: int
    level: Literal["high", "medium", "low", "none"]


@router.post("/api/me/priority")
def set_priority(body: PriorityBody, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Put a post or Short on your priority list (or take it off with level 'none')."""
    if not _item_exists(conn, body.type, body.id):
        raise HTTPException(404, "Not found")
    if body.level == "none":
        conn.execute(
            "DELETE FROM priorities WHERE user_id=? AND item_type=? AND item_id=?", (user["id"], body.type, body.id)
        )
    else:
        conn.execute(
            """INSERT INTO priorities(user_id, item_type, item_id, level, updated_at) VALUES(?,?,?,?,?)
               ON CONFLICT(user_id, item_type, item_id) DO UPDATE SET level=excluded.level,
               updated_at=excluded.updated_at""",
            (user["id"], body.type, body.id, PRIORITY_LEVELS[body.level], now()),
        )
    return {"priority": None if body.level == "none" else body.level}


# --------------------------------------------------------------------------- user posts


class PostBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(default="", max_length=10000)
    url: str = Field(default="", max_length=2048)
    attachments: list[int] = Field(default_factory=list, max_length=uploads.MAX_PER_POST)


def _user_source(conn: sqlite3.Connection, user: sqlite3.Row) -> int:
    """Each user's posts live in their own source (kind='user'), so they get per-user weights like any feed."""
    row = conn.execute("SELECT id FROM sources WHERE kind='user' AND created_by=?", (user["id"],)).fetchone()
    if row:
        conn.execute("UPDATE sources SET title=? WHERE id=?", (user["username"], row["id"]))
        return row["id"]
    cur = conn.execute(
        """INSERT INTO sources(kind, title, rss_enabled, shorts_enabled, status, created_by, created_at)
           VALUES('user', ?, 1, 0, 'ok', ?, ?)""",
        (user["username"], user["id"], now()),
    )
    return cur.lastrowid


def _text_html(text: str) -> str:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return "".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in paras)


@router.post("/api/posts")
def create_post(body: PostBody, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    title, text, url = body.title.strip(), body.text.strip(), body.url.strip()
    if not title:
        raise HTTPException(400, "Title is empty")
    if url:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise HTTPException(400, "Link must start with http:// or https://")
    ids = list(dict.fromkeys(body.attachments))
    files = [conn.execute("SELECT * FROM attachments WHERE id=?", (i,)).fetchone() for i in ids]
    if any(f is None or f["user_id"] != user["id"] or f["item_id"] is not None for f in files):
        raise HTTPException(400, "An attached file is missing. Remove it and add it again.")
    # The first photo becomes the card image in the feed.
    image = next((f"/media/upload/{f['token']}" for f in files if f["kind"] == "image"), None)
    t = now()
    with tx(conn):
        source_id = _user_source(conn, user)
        cur = conn.execute(
            """INSERT INTO items(source_id, guid, url, title, author, excerpt, content_html, image_url,
                                  published_at, fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (source_id, f"post:{user['id']}:{t}", url or None, title, user["username"],
             text[:300] or None, _text_html(text) or None, image, t, t),
        )  # fmt: skip
        for f in files:
            conn.execute("UPDATE attachments SET item_id=? WHERE id=?", (cur.lastrowid, f["id"]))
    invalidate_foryou_all()
    row = conn.execute(ITEM_SELECT + " WHERE i.id = :id", {"uid": user["id"], "id": cur.lastrowid}).fetchone()
    return item_json(row, Ctx(conn, user["id"]))


@router.delete("/api/posts/{item_id}")
def delete_post(
    item_id: int,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    """Authors (and admins) can delete a user post together with its comments and reactions."""
    row = conn.execute(
        "SELECT i.source_id, s.kind, s.created_by FROM items i JOIN sources s ON s.id=i.source_id WHERE i.id=?",
        (item_id,),
    ).fetchone()
    if not row or row["kind"] != "user":
        raise HTTPException(404, "Not found")
    if row["created_by"] != user["id"] and not user["is_admin"]:
        raise HTTPException(403, "You can only delete your own posts")
    with tx(conn):
        reacted = [
            r["user_id"]
            for r in conn.execute("SELECT user_id FROM reactions WHERE item_type='item' AND item_id=?", (item_id,))
        ]
        for table in ("comments", "reactions", "seen", "priorities"):
            conn.execute(f"DELETE FROM {table} WHERE item_type='item' AND item_id=?", (item_id,))
        uploads.delete_rows(conn, s, conn.execute("SELECT * FROM attachments WHERE item_id=?", (item_id,)).fetchall())
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))
        for uid in reacted:
            P.recompute_weight(conn, uid, row["source_id"], s)
    invalidate_foryou_all()
    return {"ok": True}


# --------------------------------------------------------------------------- uploads (post attachments)


@router.post("/api/uploads")
async def upload_file(
    request: Request,
    name: str = Query(min_length=1, max_length=255),
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    """Upload one file as the raw request body (no multipart, so no extra dependency). Attach it with POST /api/posts."""
    try:
        declared = int(request.headers.get("content-length", ""))
    except ValueError:
        declared = None
    pending = conn.execute(
        "SELECT COUNT(*) FROM attachments WHERE user_id=? AND item_id IS NULL", (user["id"],)
    ).fetchone()[0]
    if pending >= 50:
        raise HTTPException(429, "Too many files waiting to be posted. Post or remove some first.")
    try:
        row = await uploads.save(conn, s, user["id"], name, request.stream(), declared)
    except uploads.UploadError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    return uploads.attachment_json(row)


@router.delete("/api/uploads/{upload_id}")
def delete_upload(
    upload_id: int,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    """Remove a file from the post being written (only before it is posted)."""
    row = conn.execute("SELECT * FROM attachments WHERE id=?", (upload_id,)).fetchone()
    if not row or row["user_id"] != user["id"] or row["item_id"] is not None:
        raise HTTPException(404, "Not found")
    uploads.delete_rows(conn, s, [row])
    return {"ok": True}


# --------------------------------------------------------------------------- comments


class CommentBody(BaseModel):
    type: ItemType
    id: int
    body: str = Field(min_length=1, max_length=2000)


def _item_exists(conn: sqlite3.Connection, item_type: str, item_id: int) -> bool:
    table = P.ITEM_TABLES[item_type]
    return conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (item_id,)).fetchone() is not None


def comment_json(row: sqlite3.Row, user: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "user": row["username"] or "[deleted user]",
        "user_id": row["user_id"],
        "body": row["body"],
        "created_at": row["created_at"],
        "can_delete": bool(user["is_admin"]) or row["user_id"] == user["id"],
    }


@router.get("/api/comments")
def list_comments(
    type: ItemType,
    id: int,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    rows = conn.execute(
        """SELECT c.*, u.username FROM comments c LEFT JOIN users u ON u.id=c.user_id
           WHERE c.item_type=? AND c.item_id=? ORDER BY c.created_at, c.id LIMIT 500""",
        (type, id),
    ).fetchall()
    return {"comments": [comment_json(r, user) for r in rows]}


@router.post("/api/comments")
def add_comment(body: CommentBody, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    text = body.body.strip()
    if not text:
        raise HTTPException(400, "Comment is empty")
    if not _item_exists(conn, body.type, body.id):
        raise HTTPException(404, "Not found")
    cur = conn.execute(
        "INSERT INTO comments(user_id, item_type, item_id, body, created_at) VALUES(?,?,?,?,?)",
        (user["id"], body.type, body.id, text, now()),
    )
    row = conn.execute(
        "SELECT c.*, u.username FROM comments c LEFT JOIN users u ON u.id=c.user_id WHERE c.id=?", (cur.lastrowid,)
    ).fetchone()
    return comment_json(row, user)


@router.delete("/api/comments/{comment_id}")
def delete_comment(comment_id: int, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    if row["user_id"] != user["id"] and not user["is_admin"]:
        raise HTTPException(403, "You can only delete your own comments")
    conn.execute("DELETE FROM comments WHERE id=?", (comment_id,))
    return {"ok": True}


# --------------------------------------------------------------------------- media

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
CHUNK = 256 * 1024


def _iter_file(path: Path, start: int, length: int, video_id: str):
    with guard.streaming(video_id), open(path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            data = f.read(min(CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


@router.get("/media/video/{video_id}")
def video(
    video_id: str,
    request: Request,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    if not VIDEO_ID_RE.match(video_id):
        raise HTTPException(404)
    row = conn.execute("SELECT file_path, status FROM shorts WHERE video_id=?", (video_id,)).fetchone()
    if not row or row["status"] != "available" or not row["file_path"]:
        raise HTTPException(404, "Video is no longer available")
    path = s.videos_dir / Path(row["file_path"]).name
    try:
        size = os.path.getsize(path)
    except OSError:
        raise HTTPException(404, "Video file missing") from None
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": "video/mp4",
        "Cache-Control": "private, max-age=86400",
        "ETag": f'"{video_id}-{size}"',
    }
    rng = request.headers.get("range")
    if rng:
        m = _RANGE_RE.match(rng.strip())
        if not m or (m.group(1) == "" and m.group(2) == ""):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        if m.group(1) == "":
            length = min(int(m.group(2)), size)
            start = size - length
            end = size - 1
        else:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
            end = min(end, size - 1)
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        length = end - start + 1
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(length)
        return StreamingResponse(_iter_file(path, start, length, video_id), status_code=206, headers=headers)
    headers["Content-Length"] = str(size)
    return StreamingResponse(_iter_file(path, 0, size, video_id), status_code=200, headers=headers)


@router.get("/media/thumb/{video_id}")
def thumb(
    video_id: str,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    if not VIDEO_ID_RE.match(video_id):
        raise HTTPException(404)
    row = conn.execute("SELECT thumb_path FROM shorts WHERE video_id=?", (video_id,)).fetchone()
    if not row or not row["thumb_path"]:
        raise HTTPException(404)
    path = s.thumbs_dir / Path(row["thumb_path"]).name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=604800"})


@router.get("/media/upload/{token}")
def upload_media(
    token: str,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    if not uploads.TOKEN_RE.match(token):
        raise HTTPException(404)
    row = conn.execute("SELECT * FROM attachments WHERE token=?", (token,)).fetchone()
    path = uploads.file_path(s, row) if row else None
    if not path or not path.is_file():
        raise HTTPException(404)
    inline = row["kind"] in ("image", "video", "audio")
    headers = {
        "Cache-Control": "private, max-age=604800, immutable",
        # Uploaded files never run as a page on this origin, even if opened directly.
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    # FileResponse handles Range requests, so videos can seek.
    return FileResponse(
        path,
        media_type=row["mime"],
        filename=row["filename"],
        content_disposition_type="inline" if inline else "attachment",
        headers=headers,
    )


@router.get("/media/icon/{source_id}")
def source_icon(
    source_id: int,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    row = conn.execute("SELECT icon_path FROM sources WHERE id=?", (source_id,)).fetchone()
    path = icons.icons_dir(s) / Path(row["icon_path"]).name if row and row["icon_path"] else None
    if not path or not path.is_file():
        raise HTTPException(404)
    # The URL carries ?v=<check time>, so a changed picture gets a new URL and this can be cached long.
    headers = {"Cache-Control": "private, max-age=2592000", "Content-Security-Policy": "default-src 'none'; sandbox"}
    return FileResponse(path, headers=headers)


@router.get("/media/demo/{name}")
def demo_media(name: str, user=Depends(current_user), s: Settings = Depends(get_settings)):
    if not re.match(r"^[a-z0-9_-]{1,40}\.(jpg|png)$", name):
        raise HTTPException(404)
    path = s.data_dir / "demo" / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=604800"})
