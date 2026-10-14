"""Files attached to user posts: photos, videos, audio and any other file type.

Files live in /data/uploads/<token><ext> and are only served to logged-in users. Uploads are kept forever with
their post (RETENTION_DAYS is for Shorts only). Deleting the post deletes its files; uploads that never got
attached to a post are removed by the hourly cleanup after a day.

Only known media types are served inline, and images only when their bytes really are that image format.
Everything else is served as a download (`application/octet-stream` + `Content-Disposition: attachment`), so an
uploaded .html or .svg can never run as a page on this origin.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
import sqlite3
import unicodedata
from collections.abc import AsyncIterator
from pathlib import Path

from app.config import Settings
from app.db import now

log = logging.getLogger(__name__)

MAX_PER_POST = 10
ORPHAN_AGE = 24 * 3600
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_EXT_RE = re.compile(r"^\.[a-z0-9]{1,10}$")

# extension -> (mime, kind) for files that may be shown inline
INLINE = {
    ".jpg": ("image/jpeg", "image"),
    ".jpeg": ("image/jpeg", "image"),
    ".png": ("image/png", "image"),
    ".gif": ("image/gif", "image"),
    ".webp": ("image/webp", "image"),
    ".avif": ("image/avif", "image"),
    ".mp4": ("video/mp4", "video"),
    ".m4v": ("video/mp4", "video"),
    ".mov": ("video/quicktime", "video"),
    ".webm": ("video/webm", "video"),
    ".mp3": ("audio/mpeg", "audio"),
    ".m4a": ("audio/mp4", "audio"),
    ".aac": ("audio/aac", "audio"),
    ".ogg": ("audio/ogg", "audio"),
    ".opus": ("audio/ogg", "audio"),
    ".wav": ("audio/wav", "audio"),
    ".flac": ("audio/flac", "audio"),
}


class UploadError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def uploads_dir(s: Settings) -> Path:
    return s.data_dir / "uploads"


def clean_filename(name: str) -> str:
    name = unicodedata.normalize("NFC", name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"|?*').strip(" .")
    return name[:200] or "file"


def _ext(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    return ext if _EXT_RE.match(ext) else ""


def _image_matches(path: Path, ext: str) -> bool:
    with open(path, "rb") as f:
        head = f.read(16)
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".gif":
        return head[:6] in (b"GIF87a", b"GIF89a")
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext == ".avif":
        return head[4:8] == b"ftyp" and head[8:12] in (b"avif", b"avis")
    return False


def classify(path: Path, ext: str) -> tuple[str, str]:
    """(mime, kind) for a stored file."""
    mime, kind = INLINE.get(ext, ("application/octet-stream", "file"))
    if kind == "image" and not _image_matches(path, ext):
        return "application/octet-stream", "file"
    return mime, kind


def attachment_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "url": f"/media/upload/{row['token']}",
        "name": row["filename"],
        "mime": row["mime"],
        "kind": row["kind"],
        "size": row["size"],
    }


async def save(
    conn: sqlite3.Connection,
    s: Settings,
    user_id: int,
    filename: str,
    chunks: AsyncIterator[bytes],
    declared_size: int | None,
) -> sqlite3.Row:
    """Stream an upload to disk (size-capped), then record it as an unattached attachment."""
    max_bytes = int(s.upload_max_mb * 1024 * 1024)
    if declared_size is not None and declared_size > max_bytes:
        raise UploadError(f"File is larger than {s.upload_max_mb:g} MB", 413)
    folder = uploads_dir(s)
    folder.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(folder).free
    if free - (declared_size or 0) < s.min_free_disk_mb * 1024 * 1024:
        raise UploadError("The server is low on disk space", 507)
    name = clean_filename(filename)
    ext = _ext(name)
    token = secrets.token_urlsafe(18)
    final = folder / f"{token}{ext}"
    tmp = s.tmp_dir / f"upload-{token}.part"
    size = 0
    try:
        with open(tmp, "wb") as f:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise UploadError(f"File is larger than {s.upload_max_mb:g} MB", 413)
                f.write(chunk)
        if size == 0:
            raise UploadError("File is empty")
        os.replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)
    mime, kind = classify(final, ext)
    cur = conn.execute(
        """INSERT INTO attachments(token, user_id, filename, ext, mime, kind, size, created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (token, user_id, name, ext, mime, kind, size, now()),
    )
    return conn.execute("SELECT * FROM attachments WHERE id=?", (cur.lastrowid,)).fetchone()


def file_path(s: Settings, row: sqlite3.Row) -> Path:
    return uploads_dir(s) / f"{row['token']}{row['ext']}"


def delete_rows(conn: sqlite3.Connection, s: Settings, rows: list[sqlite3.Row]) -> None:
    for r in rows:
        file_path(s, r).unlink(missing_ok=True)
        conn.execute("DELETE FROM attachments WHERE id=?", (r["id"],))


def cleanup(conn: sqlite3.Connection, s: Settings) -> dict:
    """Remove uploads never attached to a post (after a day) and files on disk with no row."""
    old = conn.execute(
        "SELECT * FROM attachments WHERE item_id IS NULL AND created_at < ?", (now() - ORPHAN_AGE,)
    ).fetchall()
    delete_rows(conn, s, old)
    known = {f"{r['token']}{r['ext']}" for r in conn.execute("SELECT token, ext FROM attachments")}
    stray = 0
    folder = uploads_dir(s)
    if folder.is_dir():
        for p in folder.iterdir():
            if p.is_file() and p.name not in known and now() - p.stat().st_mtime > 3600:
                p.unlink(missing_ok=True)
                stray += 1
    if old or stray:
        log.info("uploads: removed %d unattached upload(s), %d stray file(s)", len(old), stray)
    return {"unattached_removed": len(old), "stray_removed": stray}
