"""YouTube Shorts: channel resolution, listing, downloading (yt-dlp + ffmpeg) and updates."""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from app.config import Settings
from app.db import kv_set, now
from app.locks import guard

log = logging.getLogger(__name__)

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_fetch_lock = threading.Lock()
YTDLP_TIMEOUT = 600


class ShortsError(Exception):
    pass


def ytdlp_base() -> list[str]:
    # YTDLP_EXTRA_ARGS lets you add e.g. "--cookies /data/cookies.txt" without code changes.
    extra = shlex.split(os.environ.get("YTDLP_EXTRA_ARGS", ""))
    return [sys.executable, "-m", "yt_dlp", "--no-warnings", "--ignore-config", "--no-progress", *extra]


def _run(cmd: list[str], timeout: int = YTDLP_TIMEOUT) -> subprocess.CompletedProcess:
    log.debug("run: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ShortsError(f"Timed out after {timeout}s: {cmd[0:4]}") from exc
    return proc


def _err_tail(proc: subprocess.CompletedProcess) -> str:
    lines = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else f"exit code {proc.returncode}")[:400]


# --------------------------------------------------------------------------- yt-dlp metadata


def resolve_channel(url: str) -> dict:
    """Return {channel_id, title, channel_url} for a YouTube channel URL or @handle URL."""
    target = url.rstrip("/")
    proc = _run([*ytdlp_base(), "-J", "--flat-playlist", "--playlist-end", "1", target + "/shorts"], timeout=90)
    if proc.returncode != 0:
        proc = _run([*ytdlp_base(), "-J", "--flat-playlist", "--playlist-end", "1", target], timeout=90)
    if proc.returncode != 0:
        raise ShortsError(f"Could not read that YouTube channel: {_err_tail(proc)}")
    info = json.loads(proc.stdout)
    channel_id = info.get("channel_id") or info.get("uploader_id") or info.get("id")
    if not channel_id or not str(channel_id).startswith("UC"):
        raise ShortsError("That URL does not look like a YouTube channel")
    title = info.get("channel") or info.get("uploader") or info.get("title") or channel_id
    title = re.sub(r"\s+-\s+(Shorts|Videos)$", "", title)
    return {
        "channel_id": channel_id,
        "title": title[:200],
        "channel_url": f"https://www.youtube.com/channel/{channel_id}",
        "description": (info.get("description") or "")[:2000],
        "tags": info.get("tags") or [],
        "avatar": channel_avatar(info),
    }


def channel_avatar(info: dict) -> str | None:
    """The channel's profile picture from yt-dlp's channel JSON (`thumbnails` also holds banners)."""
    thumbs = [t for t in info.get("thumbnails") or [] if str(t.get("url", "")).startswith("https://")]
    for t in thumbs:
        if t.get("id") == "avatar_uncropped":
            return _small_avatar(t["url"])
    avatars = [t for t in thumbs if "avatar" in str(t.get("id", ""))]
    square = [t for t in thumbs if t.get("width") and t.get("width") == t.get("height")]
    pick = avatars or square
    return _small_avatar(max(pick, key=lambda t: t.get("width") or 0)["url"]) if pick else None


def _small_avatar(url: str) -> str:
    """Google image URLs end in a size option (`=s0` is the original, often 500+ KB); 240 px is plenty."""
    if urlsplit(url).hostname in ("yt3.googleusercontent.com", "yt3.ggpht.com"):
        return re.sub(r"=s\d+[^/=]*$", "", url) + "=s240"
    return url


def list_channel_shorts(channel_url: str, limit: int) -> list[dict]:
    proc = _run(
        [*ytdlp_base(), "-J", "--flat-playlist", "--playlist-end", str(limit), channel_url.rstrip("/") + "/shorts"],
        timeout=120,
    )
    if proc.returncode != 0:
        raise ShortsError(_err_tail(proc))
    info = json.loads(proc.stdout)
    out = []
    for e in info.get("entries") or []:
        vid = e.get("id")
        if vid and VIDEO_ID_RE.match(vid):
            out.append({"id": vid, "title": e.get("title") or "", "url": f"https://www.youtube.com/shorts/{vid}"})
    return out


def search_channels(query: str, limit: int = 12) -> list[dict]:
    """Search YouTube with ytsearch and collapse results to unique channels."""
    proc = _run([*ytdlp_base(), "-J", "--flat-playlist", f"ytsearch{limit * 2}:{query}"], timeout=60)
    if proc.returncode != 0:
        raise ShortsError(_err_tail(proc))
    info = json.loads(proc.stdout)
    seen: dict[str, dict] = {}
    for e in info.get("entries") or []:
        cid = e.get("channel_id")
        if not cid or cid in seen:
            continue
        seen[cid] = {
            "kind": "youtube",
            "title": e.get("channel") or e.get("uploader") or cid,
            "input": f"https://www.youtube.com/channel/{cid}",
            "subtitle": f"Video: {e.get('title') or ''}"[:140],
        }
        if len(seen) >= limit:
            break
    return list(seen.values())


# --------------------------------------------------------------------------- download


def _probe(path: Path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    if proc.returncode != 0:
        raise ShortsError(f"ffprobe failed: {_err_tail(proc)}")
    data = json.loads(proc.stdout or "{}")
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    return {
        "vcodec": v.get("codec_name") if v else None,
        "acodec": a.get("codec_name") if a else None,
        "width": int(v.get("width") or 0) if v else 0,
        "height": int(v.get("height") or 0) if v else 0,
        "duration": float(data.get("format", {}).get("duration") or 0),
    }


def vaapi_device(settings: Settings) -> str | None:
    if settings.hwaccel == "none":
        return None
    dev = "/dev/dri/renderD128"
    if os.path.exists(dev) and os.access(dev, os.R_OK | os.W_OK):
        return dev
    if settings.hwaccel == "vaapi":
        log.warning("HWACCEL=vaapi but %s is not accessible; using software encoding", dev)
    return None


def transcode(src: Path, dst: Path, info: dict, settings: Settings) -> str:
    """Make an iOS-friendly MP4 (h264 + aac, faststart). Returns the method used."""
    short_side = min(info["width"], info["height"]) if info["width"] and info["height"] else 0
    needs_scale = short_side > settings.max_height
    copy_video = info["vcodec"] == "h264" and not needs_scale
    copy_audio = info["acodec"] in ("aac", None)
    audio = (
        ["-c:a", "copy"]
        if copy_audio and info["acodec"]
        else (["-c:a", "aac", "-b:a", "128k"] if info["acodec"] else ["-an"])
    )
    base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if copy_video:
        cmd = [
            *base,
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "copy",
            *audio,
            "-movflags",
            "+faststart",
            str(dst),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
        if proc.returncode == 0:
            return "remux"
        raise ShortsError(f"ffmpeg remux failed: {_err_tail(proc)}")

    h = settings.max_height
    # Scale so the short side is at most max_height, keep even dimensions.
    portrait = info["width"] <= info["height"]
    scale_expr = f"'min({h},iw)':-2" if portrait else f"-2:'min({h},ih)'"
    dev = vaapi_device(settings)
    if dev:
        vw = f"min({h},iw)" if info["width"] <= info["height"] else "-2"
        vh = "-2" if info["width"] <= info["height"] else f"min({h},ih)"
        cmd = [
            *base, "-vaapi_device", dev, "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", f"format=nv12,hwupload,scale_vaapi=w={vw}:h={vh}",
            "-c:v", "h264_vaapi", "-qp", "24", *audio, "-movflags", "+faststart", str(dst),
        ]  # fmt: skip
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=False)
        if proc.returncode == 0:
            return "vaapi"
        log.warning("VAAPI encode failed (%s); falling back to libx264", _err_tail(proc))
    cmd = [
        *base, "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-vf", f"scale={scale_expr}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-level", "4.0", *audio, "-movflags", "+faststart", str(dst),
    ]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, check=False)
    if proc.returncode != 0:
        raise ShortsError(f"ffmpeg encode failed: {_err_tail(proc)}")
    return "libx264"


def make_thumbnail(video: Path, dst: Path) -> bool:
    for ss in ("1", "0"):
        proc = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", ss, "-i", str(video),
             "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "5", str(dst)],
            capture_output=True, text=True, timeout=60, check=False,
        )  # fmt: skip
        if proc.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
            return True
    return False


def download_short(video_id: str, settings: Settings) -> dict:
    """Download one Short into tmp/, convert it and move it into videos/. Returns metadata."""
    if not VIDEO_ID_RE.match(video_id):
        raise ShortsError("bad video id")
    work = settings.tmp_dir / video_id
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        h = settings.max_height
        cmd = [
            *ytdlp_base(), "--no-playlist", "--write-info-json", "--no-write-playlist-metafiles",
            "-f", "bv*+ba/b", "-S", f"res:{h},vcodec:h264,acodec:aac,ext:mp4:m4a",
            "--merge-output-format", "mp4", "--max-filesize", "300M",
            "-o", str(work / "src.%(ext)s"), f"https://www.youtube.com/shorts/{video_id}",
        ]  # fmt: skip
        proc = _run(cmd)
        if proc.returncode != 0:
            raise ShortsError(_err_tail(proc))
        meta = {}
        info_file = work / "src.info.json"
        if info_file.exists():
            meta = json.loads(info_file.read_text())
        src = next((p for p in work.iterdir() if p.name.startswith("src.") and not p.name.endswith(".json")), None)
        if not src:
            raise ShortsError("yt-dlp produced no file")
        info = _probe(src)
        out = work / "out.mp4"
        method = transcode(src, out, info, settings)
        final_info = _probe(out)
        thumb_tmp = work / "thumb.jpg"
        has_thumb = make_thumbnail(out, thumb_tmp)

        video_path = settings.videos_dir / f"{video_id}.mp4"
        thumb_path = settings.thumbs_dir / f"{video_id}.jpg"
        os.replace(out, video_path)
        if has_thumb:
            os.replace(thumb_tmp, thumb_path)
        ts = meta.get("timestamp") or meta.get("release_timestamp")
        if not ts and meta.get("upload_date"):
            try:
                ts = time.mktime(time.strptime(meta["upload_date"], "%Y%m%d"))
            except ValueError:
                ts = None
        log.info("downloaded short %s via %s (%sx%s)", video_id, method, final_info["width"], final_info["height"])
        return {
            "title": (meta.get("title") or "")[:500],
            "channel_name": (meta.get("channel") or meta.get("uploader") or "")[:200],
            "channel_id": meta.get("channel_id"),
            "published_at": float(ts) if ts else None,
            "file_path": video_path.name,
            "thumb_path": thumb_path.name if has_thumb else None,
            "duration": final_info["duration"],
            "width": final_info["width"],
            "height": final_info["height"],
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def free_disk_mb(settings: Settings) -> float:
    return shutil.disk_usage(settings.data_dir).free / (1024 * 1024)


def fetch_all_shorts(conn: sqlite3.Connection, settings: Settings, source_id: int | None = None) -> dict:
    """List every enabled YouTube source's Shorts and download any new ones."""
    # A run for one newly added channel waits for a running full run instead of being dropped.
    if not _fetch_lock.acquire(blocking=source_id is not None):
        return {"skipped": "already running"}
    try:
        return _fetch_all(conn, settings, source_id)
    finally:
        _fetch_lock.release()


def _fetch_all(conn: sqlite3.Connection, settings: Settings, source_id: int | None) -> dict:
    stats = {"listed": 0, "new": 0, "downloaded": 0, "failed": 0, "low_disk": False}
    if free_disk_mb(settings) < settings.min_free_disk_mb:
        stats["low_disk"] = True
        kv_set(conn, "shorts_status", f"Paused: free disk below {settings.min_free_disk_mb} MB")
        log.warning("Shorts download skipped: low disk space")
        return stats
    q = "SELECT * FROM sources WHERE kind='youtube' AND enabled=1 AND shorts_enabled=1"
    args: tuple = ()
    if source_id is not None:
        q += " AND id=?"
        args = (source_id,)
    sources = conn.execute(q, args).fetchall()

    # 1. List channels. Downloading is independent of weights: every channel is fetched.
    for src in sources:
        try:
            entries = list_channel_shorts(src["channel_url"], settings.shorts_per_channel)
            stats["listed"] += len(entries)
            for e in entries:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO shorts(video_id, source_id, title, channel_name, channel_id, url,
                       status, created_at) VALUES(?,?,?,?,?,?,'pending',?)""",
                    (e["id"], src["id"], e["title"], src["title"], src["channel_id"], e["url"], now()),
                )
                stats["new"] += cur.rowcount
            conn.execute(
                "UPDATE sources SET status='ok', last_error=NULL, error_count=0 WHERE id=? AND kind='youtube'",
                (src["id"],),
            )
        except Exception as exc:
            log.warning("listing shorts for %s failed: %s", src["title"], exc)
            conn.execute(
                "UPDATE sources SET status='error', last_error=?, error_count=error_count+1 WHERE id=?",
                (f"Shorts: {exc}"[:500], src["id"]),
            )
        conn.execute("UPDATE sources SET last_fetched=? WHERE id=?", (now(), src["id"]))

    # 2. Download pending rows (new ones, plus earlier failures with attempts left).
    pending = conn.execute(
        """SELECT * FROM shorts WHERE status IN ('pending','failed') AND attempts < 3
           AND created_at > ? ORDER BY created_at""",
        (now() - 3 * 86400,),
    ).fetchall()
    for row in pending:
        if free_disk_mb(settings) < settings.min_free_disk_mb:
            stats["low_disk"] = True
            log.warning("Stopping Shorts downloads: low disk space")
            break
        vid = row["video_id"]
        try:
            with guard.downloading(vid):
                meta = download_short(vid, settings)
            conn.execute(
                """UPDATE shorts SET status='available', downloaded_at=?, file_path=?, thumb_path=?,
                   title=COALESCE(NULLIF(?, ''), title), channel_name=COALESCE(NULLIF(?, ''), channel_name),
                   channel_id=COALESCE(?, channel_id), published_at=?, duration=?, width=?, height=?,
                   attempts=attempts+1, error=NULL WHERE id=?""",
                (
                    now(), meta["file_path"], meta["thumb_path"], meta["title"], meta["channel_name"],
                    meta["channel_id"], meta["published_at"], meta["duration"], meta["width"], meta["height"],
                    row["id"],
                ),
            )  # fmt: skip
            stats["downloaded"] += 1
        except Exception as exc:
            stats["failed"] += 1
            log.warning("download of short %s failed: %s", vid, exc)
            conn.execute(
                "UPDATE shorts SET status='failed', attempts=attempts+1, error=? WHERE id=?",
                (str(exc)[:500], row["id"]),
            )
    kv_set(
        conn,
        "shorts_status",
        f"Last run {time.strftime('%Y-%m-%d %H:%M')}: {stats['downloaded']} downloaded, {stats['failed']} failed"
        + (" (paused: low disk)" if stats["low_disk"] else ""),
    )
    return stats


# --------------------------------------------------------------------------- yt-dlp updates


def ytdlp_version() -> str:
    proc = _run([sys.executable, "-m", "yt_dlp", "--version"], timeout=30)
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def update_ytdlp(conn: sqlite3.Connection, settings: Settings) -> str:
    before = ytdlp_version()
    if settings.ytdlp_auto_update:
        proc = _run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", "--disable-pip-version-check",
             "--quiet", "yt-dlp[default]"],
            timeout=300,
        )  # fmt: skip
        if proc.returncode != 0:
            log.warning("yt-dlp update failed: %s", _err_tail(proc))
    after = ytdlp_version()
    if after != before:
        log.info("yt-dlp updated %s -> %s", before, after)
    else:
        log.info("yt-dlp version %s", after)
    kv_set(conn, "ytdlp_version", after)
    kv_set(conn, "ytdlp_checked_at", str(now()))
    return after
