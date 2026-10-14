import time

from app import retention, shorts
from app.locks import guard
from tests.conftest import Client, login, make_short, make_source, make_user


def _row(conn, sid):
    return conn.execute("SELECT * FROM shorts WHERE id=?", (sid,)).fetchone()


def test_cleanup_removes_file_but_keeps_row_comments_reactions(conn, settings):
    uid = make_user(conn, "a")
    src = make_source(conn, "yt", kind="youtube")
    old = make_short(conn, settings, src, "OLDVIDEO001", age_days=10)
    fresh = make_short(conn, settings, src, "NEWVIDEO001", age_days=1)
    conn.execute(
        "INSERT INTO comments(user_id,item_type,item_id,body,created_at) VALUES(?, 'short', ?, 'nice', ?)",
        (uid, old, time.time()),
    )
    conn.execute(
        "INSERT INTO reactions(user_id,item_type,item_id,source_id,value,created_at) VALUES(?, 'short', ?, ?, 1, ?)",
        (uid, old, src, time.time()),
    )

    res = retention.cleanup(conn, settings)
    assert res["expired"] == 1
    assert not (settings.videos_dir / "OLDVIDEO001.mp4").exists()
    assert (settings.videos_dir / "NEWVIDEO001.mp4").exists()

    r = _row(conn, old)
    assert r is not None
    assert r["status"] == "expired"
    assert r["file_path"] is None
    assert r["expired_at"] is not None
    assert r["title"] == "Short OLDVIDEO001" and r["url"].endswith("OLDVIDEO001")
    assert r["thumb_path"] == "OLDVIDEO001.jpg"  # KEEP_THUMBNAILS default true
    assert (settings.thumbs_dir / "OLDVIDEO001.jpg").exists()
    assert conn.execute("SELECT COUNT(*) FROM comments WHERE item_id=?", (old,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM reactions WHERE item_id=?", (old,)).fetchone()[0] == 1
    assert _row(conn, fresh)["status"] == "available"


def test_cleanup_deletes_thumbnail_when_not_kept(conn, settings):
    settings.keep_thumbnails = False
    src = make_source(conn, "yt", kind="youtube")
    sid = make_short(conn, settings, src, "OLDVIDEO002", age_days=10)
    retention.cleanup(conn, settings)
    assert _row(conn, sid)["thumb_path"] is None
    assert not (settings.thumbs_dir / "OLDVIDEO002.jpg").exists()


def test_cleanup_skips_files_in_use(conn, settings):
    src = make_source(conn, "yt", kind="youtube")
    streaming = make_short(conn, settings, src, "STREAMING01", age_days=10)
    downloading = make_short(conn, settings, src, "DOWNLOADS01", age_days=10)
    with guard.streaming("STREAMING01"), guard.downloading("DOWNLOADS01"):
        retention.cleanup(conn, settings)
        assert _row(conn, streaming)["status"] == "available"
        assert _row(conn, downloading)["status"] == "available"
        assert (settings.videos_dir / "STREAMING01.mp4").exists()
    # recently streamed counts as busy (grace period), so it is still kept right after
    retention.cleanup(conn, settings)
    assert _row(conn, streaming)["status"] == "available"
    assert _row(conn, downloading)["status"] == "expired"
    guard.reset()
    retention.cleanup(conn, settings)
    assert _row(conn, streaming)["status"] == "expired"


def test_expired_shorts_leave_reels_and_appear_in_past(app, conn, settings):
    make_user(conn, "a")
    src = make_source(conn, "yt", kind="youtube")
    old = make_short(conn, settings, src, "OLDVIDEO003", age_days=10)
    fresh = make_short(conn, settings, src, "NEWVIDEO003", age_days=1)
    c = login(app, "a")
    ids = {x["id"] for x in c.post("/api/reels/next", json={"n": 20}).json()["items"]}
    assert ids == {old, fresh}

    retention.cleanup(conn, settings)
    reels = c.post("/api/reels/next", json={"n": 20}).json()["items"]
    assert {x["id"] for x in reels} == {fresh}
    past = c.get("/api/shorts/past").json()["items"]
    assert [x["id"] for x in past] == [old]
    assert past[0]["video"] is None and past[0]["thumb"] == "/media/thumb/OLDVIDEO003"
    assert c.get("/media/video/OLDVIDEO003").status_code == 404

    # comments and reactions on expired Shorts stay readable and writable
    assert c.post("/api/comments", json={"type": "short", "id": old, "body": "still here"}).status_code == 200
    assert len(c.get(f"/api/comments?type=short&id={old}").json()["comments"]) == 1
    r = c.post("/api/react", json={"type": "short", "id": old, "value": 1}).json()
    assert r["likes"] == 1 and r["weight"] > 1.0


def test_expired_shorts_not_redownloaded(conn, settings, monkeypatch):
    src_id = make_source(conn, "yt", kind="youtube")
    conn.execute(
        "UPDATE sources SET channel_url='https://www.youtube.com/channel/UCx', channel_id='UCx' WHERE id=?", (src_id,)
    )
    expired = make_short(conn, settings, src_id, "EXPIRED0001", age_days=10)
    retention.cleanup(conn, settings)
    assert _row(conn, expired)["status"] == "expired"

    monkeypatch.setattr(
        shorts, "list_channel_shorts",
        lambda url, limit: [
            {"id": "EXPIRED0001", "title": "old", "url": "u"},
            {"id": "BRANDNEW001", "title": "new", "url": "u"},
        ],
    )  # fmt: skip
    downloaded = []

    def fake_download(video_id, s):
        downloaded.append(video_id)
        (s.videos_dir / f"{video_id}.mp4").write_bytes(b"x")
        return {
            "title": "New one", "channel_name": "Chan", "channel_id": "UCx", "published_at": None,
            "file_path": f"{video_id}.mp4", "thumb_path": None, "duration": 5, "width": 720, "height": 1280,
        }  # fmt: skip

    monkeypatch.setattr(shorts, "download_short", fake_download)
    monkeypatch.setattr(shorts, "free_disk_mb", lambda s: 10**6)
    stats = shorts.fetch_all_shorts(conn, settings)
    assert downloaded == ["BRANDNEW001"]
    assert stats["downloaded"] == 1
    assert _row(conn, expired)["status"] == "expired"
    assert not (settings.videos_dir / "EXPIRED0001.mp4").exists()

    # second run downloads nothing
    downloaded.clear()
    shorts.fetch_all_shorts(conn, settings)
    assert downloaded == []


def test_low_disk_pauses_downloads(conn, settings, monkeypatch):
    src_id = make_source(conn, "yt", kind="youtube")
    conn.execute("UPDATE sources SET channel_url='https://www.youtube.com/channel/UCx' WHERE id=?", (src_id,))
    monkeypatch.setattr(shorts, "free_disk_mb", lambda s: 10)
    monkeypatch.setattr(shorts, "list_channel_shorts", lambda *a: (_ for _ in ()).throw(AssertionError("listed")))
    stats = shorts.fetch_all_shorts(conn, settings)
    assert stats["low_disk"] is True and stats["downloaded"] == 0


def test_reconcile_both_directions(conn, settings):
    src = make_source(conn, "yt", kind="youtube")
    # row says available but the file is gone
    missing = make_short(conn, settings, src, "MISSINGFILE", age_days=1)
    (settings.videos_dir / "MISSINGFILE.mp4").unlink()
    # file on disk with no row at all
    (settings.videos_dir / "ORPHANFILE1.mp4").write_bytes(b"x")
    # file on disk whose row is already expired
    exp = make_short(conn, settings, src, "EXPIREDROW1", age_days=1, status="expired")
    conn.execute("UPDATE shorts SET file_path=NULL WHERE id=?", (exp,))
    (settings.videos_dir / "EXPIREDROW1.mp4").write_bytes(b"x")
    # healthy
    ok = make_short(conn, settings, src, "HEALTHYFILE", age_days=1)
    # stale temp download
    (settings.tmp_dir / "STALEDOWNLD").mkdir()

    stats = retention.reconcile(conn, settings)
    assert stats["rows_fixed"] == 1
    assert _row(conn, missing)["status"] == "expired"
    assert _row(conn, missing)["file_path"] is None
    assert not (settings.videos_dir / "ORPHANFILE1.mp4").exists()
    assert not (settings.videos_dir / "EXPIREDROW1.mp4").exists()
    assert (settings.videos_dir / "HEALTHYFILE.mp4").exists()
    assert _row(conn, ok)["status"] == "available"
    assert not (settings.tmp_dir / "STALEDOWNLD").exists()
    # nothing in "available" without a file afterwards
    for r in conn.execute("SELECT file_path FROM shorts WHERE status='available'"):
        assert (settings.videos_dir / r["file_path"]).exists()


def test_reconcile_runs_on_startup(settings, conn):
    from fastapi.testclient import TestClient

    from app.main import create_app

    src = make_source(conn, "yt", kind="youtube")
    sid = make_short(conn, settings, src, "STARTUPMISS", age_days=1)
    (settings.videos_dir / "STARTUPMISS.mp4").unlink()
    old = make_short(conn, settings, src, "STARTUPOLD1", age_days=30)
    with TestClient(create_app(settings)):
        pass
    assert _row(conn, sid)["status"] == "expired"
    assert _row(conn, old)["status"] == "expired"


def test_range_requests(app, conn, settings):
    make_user(conn, "a")
    src = make_source(conn, "yt", kind="youtube")
    make_short(conn, settings, src, "RANGEVIDEO1", age_days=0)
    data = bytes(range(256)) * 8
    (settings.videos_dir / "RANGEVIDEO1.mp4").write_bytes(data)
    c = login(app, "a")
    r = c.get("/media/video/RANGEVIDEO1", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 0-99/{len(data)}"
    assert r.content == data[:100]
    r = c.get("/media/video/RANGEVIDEO1", headers={"Range": "bytes=-10"})
    assert r.status_code == 206 and r.content == data[-10:]
    r = c.get("/media/video/RANGEVIDEO1", headers={"Range": "bytes=100-"})
    assert r.content == data[100:]
    r = c.get("/media/video/RANGEVIDEO1", headers={"Range": f"bytes={len(data)}-"})
    assert r.status_code == 416
    r = c.get("/media/video/RANGEVIDEO1")
    assert r.status_code == 200 and r.headers["accept-ranges"] == "bytes" and r.content == data
    anon = Client(app)
    assert anon.get("/media/video/RANGEVIDEO1").status_code == 401
