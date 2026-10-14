"""Video retention: expire old Short files, keep every record, reconcile disk vs. database."""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path

from app.config import Settings
from app.db import now
from app.locks import guard

log = logging.getLogger(__name__)


def _unlink(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def expire_short(conn: sqlite3.Connection, row: sqlite3.Row, settings: Settings) -> bool:
    """Delete a Short's video (and preview) file, keep the row, mark it expired."""
    vid = row["video_id"]
    if guard.busy(vid):
        log.info("cleanup: %s is in use, skipping", vid)
        return False
    if row["file_path"]:
        _unlink(settings.videos_dir / Path(row["file_path"]).name)
    if row["preview_path"]:
        _unlink(settings.videos_dir / Path(row["preview_path"]).name)
    thumb = row["thumb_path"]
    if thumb and not settings.keep_thumbnails:
        _unlink(settings.thumbs_dir / Path(thumb).name)
        thumb = None
    conn.execute(
        """UPDATE shorts SET status='expired', file_path=NULL, preview_path=NULL, thumb_path=?,
           expired_at=? WHERE id=?""",
        (thumb, now(), row["id"]),
    )
    return True


def cleanup(conn: sqlite3.Connection, settings: Settings) -> dict:
    """Expire video files older than RETENTION_DAYS. Never deletes rows, comments or reactions."""
    cutoff = now() - settings.retention_days * 86400
    rows = conn.execute(
        "SELECT * FROM shorts WHERE status='available' AND COALESCE(downloaded_at, created_at) < ?",
        (cutoff,),
    ).fetchall()
    expired = sum(1 for r in rows if expire_short(conn, r, settings))
    if not settings.keep_thumbnails:
        # Thumbnails of already-expired Shorts, e.g. if KEEP_THUMBNAILS was switched off later.
        for r in conn.execute("SELECT id, thumb_path FROM shorts WHERE status='expired' AND thumb_path IS NOT NULL"):
            _unlink(settings.thumbs_dir / Path(r["thumb_path"]).name)
            conn.execute("UPDATE shorts SET thumb_path=NULL WHERE id=?", (r["id"],))
    if expired:
        log.info("cleanup: expired %d short video file(s)", expired)
    return {"expired": expired}


def reconcile(conn: sqlite3.Connection, settings: Settings) -> dict:
    """Fix disk/database mismatches in both directions.

    * rows marked `available` whose file is missing -> `expired` (or `pending` re-download is NOT done,
      so a deleted video never comes back)
    * video files on disk without an `available` row -> deleted (orphans)
    * stale temporary download folders -> deleted
    """
    stats = {"rows_fixed": 0, "orphans_removed": 0, "tmp_removed": 0}
    rows = conn.execute("SELECT * FROM shorts WHERE status='available'").fetchall()
    for r in rows:
        fp = r["file_path"]
        if not fp or not (settings.videos_dir / Path(fp).name).is_file():
            thumb = r["thumb_path"] if settings.keep_thumbnails else None
            if r["thumb_path"] and not settings.keep_thumbnails:
                _unlink(settings.thumbs_dir / Path(r["thumb_path"]).name)
            conn.execute(
                "UPDATE shorts SET status='expired', file_path=NULL, preview_path=NULL, thumb_path=?, expired_at=? WHERE id=?",
                (thumb, now(), r["id"]),
            )
            stats["rows_fixed"] += 1

    known = {
        Path(r["file_path"]).name
        for r in conn.execute("SELECT file_path FROM shorts WHERE status='available' AND file_path IS NOT NULL")
    }
    known |= {
        Path(r["preview_path"]).name
        for r in conn.execute("SELECT preview_path FROM shorts WHERE status='available' AND preview_path IS NOT NULL")
    }
    if settings.videos_dir.exists():
        for f in settings.videos_dir.iterdir():
            if not f.is_file() or f.name in known:
                continue
            if guard.busy(f.stem):
                continue
            _unlink(f)
            stats["orphans_removed"] += 1

    known_thumbs = {
        Path(r["thumb_path"]).name for r in conn.execute("SELECT thumb_path FROM shorts WHERE thumb_path IS NOT NULL")
    }
    if settings.thumbs_dir.exists():
        for f in settings.thumbs_dir.iterdir():
            if f.is_file() and f.name not in known_thumbs and not guard.busy(f.stem):
                _unlink(f)
                stats["orphans_removed"] += 1

    if settings.tmp_dir.exists():
        for d in settings.tmp_dir.iterdir():
            if guard.busy(d.name):
                continue
            if time.time() - d.stat().st_mtime > 3600 or not guard.any_downloading():
                shutil.rmtree(d, ignore_errors=True) if d.is_dir() else _unlink(d)
                stats["tmp_removed"] += 1
    if any(stats.values()):
        log.info("reconcile: %s", stats)
    return stats


def disk_usage(settings: Settings) -> dict:
    def tree_size(p: Path) -> int:
        total = 0
        if not p.exists():
            return 0
        for root, _dirs, files in os.walk(p):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
        return total

    du = shutil.disk_usage(settings.data_dir)
    return {
        "data_bytes": tree_size(settings.data_dir),
        "videos_bytes": tree_size(settings.videos_dir),
        "thumbs_bytes": tree_size(settings.thumbs_dir),
        "disk_total": du.total,
        "disk_free": du.free,
        "min_free_bytes": settings.min_free_disk_mb * 1024 * 1024,
    }
