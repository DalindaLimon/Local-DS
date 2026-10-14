import time

from app import uploads
from tests.conftest import login, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _up(c, name, data):
    return c.post(f"/api/uploads?name={name}", content=data, headers={"content-type": "application/octet-stream"})


def test_post_with_photo_video_and_file(app, conn, settings):
    make_user(conn, "a")
    make_user(conn, "b")
    ca, cb = login(app, "a"), login(app, "b")
    img = _up(ca, "cat.png", PNG).json()
    vid = _up(ca, "clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100).json()
    doc = _up(ca, "notes.pdf", b"%PDF-1.4 hello").json()
    assert (img["kind"], vid["kind"], doc["kind"]) == ("image", "video", "file")
    post = ca.post("/api/posts", json={"title": "Stuff", "attachments": [img["id"], vid["id"], doc["id"]]}).json()
    assert post["image"] == img["url"]  # first photo is the card image
    assert [a["name"] for a in post["attachments"]] == ["cat.png", "clip.mp4", "notes.pdf"]

    # the other user sees and can load them; photos/videos inline, other files as downloads
    feed = cb.get("/api/feed").json()["items"]
    assert feed[0]["attachments"][1]["url"] == vid["url"]
    r = cb.get(img["url"])
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"].startswith("inline")
    assert "sandbox" in r.headers["content-security-policy"]
    r = cb.get(doc["url"])
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment")
    r = cb.get(vid["url"], headers={"range": "bytes=0-9"})
    assert r.status_code == 206 and len(r.content) == 10

    # logged out: no access
    from tests.conftest import Client

    assert Client(app).get(img["url"]).status_code == 401

    # deleting the post deletes the files
    paths = list(uploads.uploads_dir(settings).iterdir())
    assert len(paths) == 3
    assert ca.delete(f"/api/posts/{post['id']}").status_code == 200
    assert list(uploads.uploads_dir(settings).iterdir()) == []
    assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0


def test_dangerous_files_are_never_inline(app, conn):
    make_user(conn, "a")
    c = login(app, "a")
    for name, data in [
        ("x.html", b"<script>alert(1)</script>"),
        ("x.svg", b"<svg onload=alert(1)>"),
        ("fake.png", b"<html><script>alert(1)</script>"),  # not really a PNG
        ("noext", b"hello"),
    ]:
        att = _up(c, name, data).json()
        assert att["kind"] == "file", name
        r = c.get(att["url"])
        assert r.headers["content-type"] == "application/octet-stream"
        assert r.headers["content-disposition"].startswith("attachment")


def test_upload_limits_and_ownership(app, conn, settings):
    make_user(conn, "a")
    make_user(conn, "b")
    ca, cb = login(app, "a"), login(app, "b")
    settings.upload_max_mb = 0.001  # ~1 KB
    assert _up(ca, "big.bin", b"x" * 5000).status_code == 413
    assert _up(ca, "empty.txt", b"").status_code == 400
    settings.upload_max_mb = 200
    att = _up(ca, "../../etc/passwd", b"x").json()
    assert att["name"] == "passwd"
    # b can't attach or remove a's upload
    assert cb.post("/api/posts", json={"title": "t", "attachments": [att["id"]]}).status_code == 400
    assert cb.delete(f"/api/uploads/{att['id']}").status_code == 404
    assert ca.delete(f"/api/uploads/{att['id']}").status_code == 200
    assert ca.post("/api/posts", json={"title": "t", "attachments": [att["id"]]}).status_code == 400
    assert ca.post("/api/posts", json={"title": "t", "attachments": list(range(11))}).status_code == 422


def test_cleanup_removes_unattached_uploads(app, conn, settings):
    make_user(conn, "a")
    c = login(app, "a")
    keep = _up(c, "keep.png", PNG).json()
    c.post("/api/posts", json={"title": "t", "attachments": [keep["id"]]})
    old = _up(c, "old.png", PNG).json()
    conn.execute("UPDATE attachments SET created_at=? WHERE id=?", (time.time() - 2 * 86400, old["id"]))
    res = uploads.cleanup(conn, settings)
    assert res["unattached_removed"] == 1
    assert [r["id"] for r in conn.execute("SELECT id FROM attachments")] == [keep["id"]]
    assert len(list(uploads.uploads_dir(settings).iterdir())) == 1
