"""Profile pictures for sources: YouTube channel avatars, subreddit icons and feed logos.

Each picture is downloaded once into /data/icons/<source id>.<ext> and served from /media/icon/<id>, so phones
never contact Google or Reddit just to show a picture. A source without a picture keeps its coloured letter.

Reddit often refuses anonymous requests from servers (the same blocking that hits RSS sometimes), so a failed
lookup is simply retried a few days later. Pictures that worked are refreshed monthly in case they changed.
"""

from __future__ import annotations

import html
import json
import logging
import os
import sqlite3
from pathlib import Path

from app import feeds, shorts
from app.config import Settings
from app.db import now
from app.urlsafe import safe_get

log = logging.getLogger(__name__)

RETRY_AFTER = 3 * 86400  # lookup failed or no picture: try again after this
REFRESH_AFTER = 30 * 86400  # picture found: re-download after this
PER_RUN = 15  # sources per job run, to stay gentle with Reddit and YouTube
MAX_BYTES = 2 * 1024 * 1024
# Placeholders that are not the source's own picture.
GENERIC = ("redditstatic.com/icon.png", "redditstatic.com/avatars/", "/default_")
KINDS = ("reddit", "youtube", "rss")


def icons_dir(s: Settings) -> Path:
    return s.icons_dir


def icon_url(row: sqlite3.Row, id_key: str = "id", path_key: str = "icon_path", ver_key: str = "icon_checked_at"):
    """Browser URL for a source's cached picture, or None (the UI then shows a letter)."""
    if not row[path_key]:
        return None
    return f"/media/icon/{row[id_key]}?v={int(row[ver_key] or 0)}"


def sniff(data: bytes) -> str | None:
    """File extension if `data` really is a JPEG, PNG, GIF or WebP image."""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _usable(url: str | None) -> str | None:
    url = html.unescape(url or "").strip()
    if not url.startswith(("http://", "https://")) or any(g in url for g in GENERIC):
        return None
    return url


def reddit_icon(name: str, s: Settings) -> str | None:
    """The subreddit's own icon from /r/<name>/about.json, or None if Reddit refuses or has none."""
    headers = {"User-Agent": s.reddit_user_agent, "Accept": "application/json"}
    for host in feeds.REDDIT_HOSTS:
        feeds.reddit_throttle.wait()
        res = safe_get(f"https://{host}/r/{name}/about.json", headers=headers, max_bytes=MAX_BYTES)
        if res.status == 429:
            return None  # rate limited: don't hammer the second host too
        if res.status != 200:
            continue
        try:
            data = json.loads(res.content).get("data") or {}
        except (ValueError, AttributeError):
            continue
        return _usable(data.get("community_icon")) or _usable(data.get("icon_img"))
    return None


def lookup(row: sqlite3.Row, s: Settings) -> str | None:
    """Remote URL of a source's picture."""
    if row["kind"] == "reddit":
        name = feeds.subreddit_name(row["feed_url"])
        return reddit_icon(name, s) if name else None
    if row["kind"] == "youtube":
        if _usable(row["icon_url"]):
            return _usable(row["icon_url"])
        url = row["channel_url"] or row["site_url"]
        return shorts.resolve_channel(url).get("avatar") if url else None
    return _usable(row["icon_url"])  # rss: the feed's own <image>/<icon>


def download(s: Settings, source_id: int, url: str) -> str | None:
    """Fetch and store a picture; returns its file name, or None if it isn't a real image."""
    res = safe_get(url, max_bytes=MAX_BYTES, allow_private=s.allow_private_urls)
    if res.status != 200:
        return None
    ext = sniff(res.content)
    if not ext:
        return None
    folder = icons_dir(s)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{source_id}{ext}"
    tmp = folder / f".{name}.part"
    tmp.write_bytes(res.content)
    os.replace(tmp, folder / name)
    for old in folder.glob(f"{source_id}.*"):
        if old.name != name:
            old.unlink(missing_ok=True)
    return name


def refresh(conn: sqlite3.Connection, s: Settings, source_id: int | None = None, limit: int = PER_RUN) -> dict:
    """Look up and download pictures for sources that need one (or just `source_id`)."""
    t = now()
    marks = ",".join(f"'{k}'" for k in KINDS)
    if source_id is not None:
        rows = conn.execute(f"SELECT * FROM sources WHERE id=? AND kind IN ({marks})", (source_id,)).fetchall()
    else:
        rows = conn.execute(
            f"""SELECT * FROM sources WHERE kind IN ({marks}) AND status != 'removed'
                AND (icon_checked_at IS NULL
                     OR (icon_path IS NULL AND icon_checked_at < ?)
                     OR (icon_path IS NOT NULL AND icon_checked_at < ?))
                ORDER BY icon_checked_at IS NOT NULL, icon_checked_at LIMIT ?""",
            (t - RETRY_AFTER, t - REFRESH_AFTER, limit),
        ).fetchall()
    found = 0
    for row in rows:
        name = row["icon_path"]
        try:
            url = lookup(row, s)
            if url:
                name = download(s, row["id"], url) or name
                conn.execute("UPDATE sources SET icon_url=? WHERE id=?", (url, row["id"]))
        except Exception as exc:  # one bad source must not stop the others
            log.info("icon for source %s (%s) failed: %s", row["id"], row["title"], exc)
        if name and not (icons_dir(s) / name).is_file():
            name = None
        conn.execute("UPDATE sources SET icon_path=?, icon_checked_at=? WHERE id=?", (name, now(), row["id"]))
        found += bool(name)
    removed = _remove_orphans(conn, s)
    return {"checked": len(rows), "with_icon": found, "orphans_removed": removed}


def _remove_orphans(conn: sqlite3.Connection, s: Settings) -> int:
    folder = icons_dir(s)
    if not folder.is_dir():
        return 0
    keep = {r["icon_path"] for r in conn.execute("SELECT icon_path FROM sources WHERE icon_path IS NOT NULL")}
    removed = 0
    for p in folder.iterdir():
        # skip files younger than an hour: another run may have just downloaded it and not saved the row yet
        if p.is_file() and p.name not in keep and not p.name.startswith(".") and now() - p.stat().st_mtime > 3600:
            p.unlink(missing_ok=True)
            removed += 1
    return removed
