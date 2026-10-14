import json
import os
import time

import httpx

from app import feeds, icons, shorts
from app.urlsafe import FetchResult
from tests.conftest import login, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _res(status, content=b""):
    return FetchResult(status, "https://x", httpx.Headers({}), content)


def _source(conn, kind, title, feed_url, **cols):
    keys = ["kind", "title", "feed_url", "status", "created_at", *cols]
    vals = [kind, title, feed_url, "ok", time.time(), *cols.values()]
    sql = f"INSERT INTO sources({','.join(keys)}) VALUES({','.join('?' * len(keys))})"
    return conn.execute(sql, vals).lastrowid


def test_subreddit_icon_is_downloaded_and_served_locally(app, conn, settings, monkeypatch):
    feeds.reddit_throttle.gap = 0
    sid = _source(conn, "reddit", "r/selfhosted", feeds.reddit_feed_url("selfhosted"))
    about = {"data": {"community_icon": "https://styles.redditmedia.com/x/icon.png?width=256&amp;s=abc"}}
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if url.endswith("/about.json"):
            return _res(200, json.dumps(about).encode())
        assert url == "https://styles.redditmedia.com/x/icon.png?width=256&s=abc"  # &amp; unescaped
        return _res(200, PNG)

    monkeypatch.setattr(icons, "safe_get", fake_get)
    res = icons.refresh(conn, settings)
    assert res["with_icon"] == 1
    assert (settings.data_dir / "icons" / f"{sid}.png").read_bytes() == PNG

    make_user(conn, "a")
    c = login(app, "a")
    src = next(s for s in c.get("/api/sources").json()["sources"] if s["id"] == sid)
    assert src["icon"].startswith(f"/media/icon/{sid}?v=")  # local URL, never Reddit's
    r = c.get(src["icon"])
    assert r.status_code == 200 and r.content == PNG and "sandbox" in r.headers["content-security-policy"]
    assert len(calls) == 2  # checked once, not again until it's due
    icons.refresh(conn, settings)
    assert len(calls) == 2


def test_blocked_reddit_keeps_letter_and_retries_later(conn, settings, monkeypatch):
    feeds.reddit_throttle.gap = 0
    sid = _source(conn, "reddit", "r/x", feeds.reddit_feed_url("x"))
    calls = []
    monkeypatch.setattr(icons, "safe_get", lambda url, **kw: calls.append(url) or _res(403))
    assert icons.refresh(conn, settings)["with_icon"] == 0
    assert len(calls) == 2  # www and old.reddit
    row = conn.execute("SELECT icon_path, icon_checked_at FROM sources WHERE id=?", (sid,)).fetchone()
    assert row["icon_path"] is None and row["icon_checked_at"]
    icons.refresh(conn, settings)
    assert len(calls) == 2  # not retried right away
    conn.execute("UPDATE sources SET icon_checked_at=? WHERE id=?", (time.time() - icons.RETRY_AFTER - 1, sid))
    icons.refresh(conn, settings)
    assert len(calls) == 4  # retried once due


def test_youtube_avatar_and_non_images_rejected(conn, settings, monkeypatch):
    yt = _source(conn, "youtube", "Chan", "https://www.youtube.com/feeds/videos.xml?channel_id=UC1",
                 channel_url="https://www.youtube.com/channel/UC1")  # fmt: skip
    monkeypatch.setattr(shorts, "resolve_channel", lambda url: {"avatar": "https://yt3.ggpht.com/a.jpg"})
    monkeypatch.setattr(icons, "safe_get", lambda url, **kw: _res(200, b"<html>not an image</html>"))
    assert icons.refresh(conn, settings)["with_icon"] == 0  # HTML is never stored as a picture
    assert conn.execute("SELECT icon_path FROM sources WHERE id=?", (yt,)).fetchone()[0] is None


def test_channel_avatar_picks_profile_picture_not_banner():
    info = {
        "thumbnails": [
            {"id": "banner_uncropped", "url": "https://yt3/banner", "width": 2560, "height": 424},
            {"id": "7", "url": "https://yt3/avatar-small", "width": 88, "height": 88},
            {"id": "avatar_uncropped", "url": "https://yt3/avatar-full"},
        ]
    }
    assert shorts.channel_avatar(info) == "https://yt3/avatar-full"
    del info["thumbnails"][2]
    assert shorts.channel_avatar(info) == "https://yt3/avatar-small"  # largest square one
    assert shorts.channel_avatar({}) is None
    google = {"thumbnails": [{"id": "avatar_uncropped", "url": "https://yt3.googleusercontent.com/AbC=s0"}]}
    assert shorts.channel_avatar(google) == "https://yt3.googleusercontent.com/AbC=s240"  # 14 KB instead of 580 KB
    google["thumbnails"][0]["url"] = "https://yt3.ggpht.com/AbC=s900-c-k-c0x00ffffff-no-rj"
    assert shorts.channel_avatar(google) == "https://yt3.ggpht.com/AbC=s240"


def test_reddit_feed_generic_logo_is_ignored():
    xml = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title>
    <icon>https://www.redditstatic.com/icon.png/</icon></feed>"""
    assert feeds.parse_feed(xml, "https://www.reddit.com/r/x/.rss", reddit=True).icon_url is None


def test_orphan_icons_are_removed(conn, settings):
    folder = settings.data_dir / "icons"
    folder.mkdir(exist_ok=True)
    stale = folder / "999.png"
    stale.write_bytes(PNG)
    old = time.time() - 7200
    os.utime(stale, (old, old))
    fresh = folder / "998.png"  # just downloaded by another run: kept for now
    fresh.write_bytes(PNG)
    assert icons.refresh(conn, settings)["orphans_removed"] == 1
    assert not stale.exists() and fresh.exists()
