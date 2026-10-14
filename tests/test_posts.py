import time

from app.feeds import prune_old_items
from tests.conftest import login, make_item, make_source, make_user


def test_post_shows_in_everyones_feed_and_is_weighted_per_author(app, conn):
    make_user(conn, "a")
    b = make_user(conn, "b")
    ca, cb = login(app, "a"), login(app, "b")
    r = ca.post("/api/posts", json={"title": "Hello", "text": "line <b>one</b>\nline two\n\npara", "url": ""})
    assert r.status_code == 200, r.text
    post = r.json()
    assert post["mine"] is True and post["source"]["kind"] == "user" and post["source"]["title"] == "a"
    feed_b = cb.get("/api/feed").json()["items"]
    assert [x["id"] for x in feed_b] == [post["id"]] and feed_b[0]["mine"] is False
    html = cb.get(f"/api/items/{post['id']}").json()["content_html"]
    assert html == "<p>line &lt;b&gt;one&lt;/b&gt;<br>line two</p><p>para</p>"
    # a second post reuses the author's source; disliking lowers that author's weight for b only
    second = ca.post("/api/posts", json={"title": "Again"}).json()
    assert second["source"]["id"] == post["source"]["id"]
    cb.post("/api/react", json={"type": "item", "id": second["id"], "value": -1})
    w = conn.execute(
        "SELECT weight FROM user_source_prefs WHERE user_id=? AND source_id=?", (b, post["source"]["id"])
    ).fetchone()["weight"]
    assert w < 1.0


def test_post_validation(app, conn):
    make_user(conn, "a")
    ca = login(app, "a")
    assert ca.post("/api/posts", json={"title": "   "}).status_code == 400
    assert ca.post("/api/posts", json={"title": "x", "url": "javascript:alert(1)"}).status_code == 400
    assert ca.post("/api/posts", json={"title": "x", "url": "https://example.com/a"}).json()["url"] == (
        "https://example.com/a"
    )


def test_delete_post_permissions(app, conn):
    make_user(conn, "admin", admin=True)
    make_user(conn, "a")
    make_user(conn, "b")
    ca, cb, cadm = login(app, "a"), login(app, "b"), login(app, "admin")
    p1 = ca.post("/api/posts", json={"title": "one"}).json()["id"]
    p2 = ca.post("/api/posts", json={"title": "two"}).json()["id"]
    cb.post("/api/comments", json={"type": "item", "id": p1, "body": "hi"})
    cb.post("/api/react", json={"type": "item", "id": p1, "value": 1})
    assert cb.delete(f"/api/posts/{p1}").status_code == 403
    assert ca.delete(f"/api/posts/{p1}").status_code == 200
    assert cadm.delete(f"/api/posts/{p2}").status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM reactions").fetchone()[0] == 0
    # feed items from real sources can't be deleted through this route
    s = make_source(conn)
    i = make_item(conn, s)
    assert cadm.delete(f"/api/posts/{i}").status_code == 404


def test_rss_retention_never_prunes_user_posts(app, conn):
    make_user(conn, "a")
    ca = login(app, "a")
    pid = ca.post("/api/posts", json={"title": "keep me"}).json()["id"]
    s = make_source(conn)
    old = make_item(conn, s, "old feed item")
    conn.execute("UPDATE items SET published_at=?", (time.time() - 400 * 86400,))
    assert prune_old_items(conn, 30) == 1
    ids = {r[0] for r in conn.execute("SELECT id FROM items")}
    assert ids == {pid} and old not in ids


def test_admin_refresh(app, conn, monkeypatch):
    from app import jobs

    calls = []
    monkeypatch.setattr(jobs, "submit", lambda fn, *a: calls.append(fn))
    make_user(conn, "admin", admin=True)
    make_user(conn, "a")
    assert login(app, "a").post("/api/admin/refresh").status_code == 403
    cadm = login(app, "admin")
    r = cadm.post("/api/admin/refresh")
    assert r.status_code == 200 and r.json()["started"] > 0
    assert calls == [jobs.rss_job, jobs.shorts_job]
    assert "jobs" in cadm.get("/api/admin/jobs").json()


def test_activity_lists_liked_disliked_and_commented(app, conn, settings):
    from tests.conftest import make_short

    make_user(conn, "a")
    make_user(conn, "b")
    s = make_source(conn)
    yt = make_source(conn, "yt", kind="youtube")
    i1, i2, i3 = make_item(conn, s, "one"), make_item(conn, s, "two"), make_item(conn, s, "three")
    sh = make_short(conn, settings, yt, "SHORTVID001")
    ca, cb = login(app, "a"), login(app, "b")
    ca.post("/api/react", json={"type": "item", "id": i1, "value": 1})
    ca.post("/api/react", json={"type": "short", "id": sh, "value": 1})
    ca.post("/api/react", json={"type": "item", "id": i2, "value": -1})
    ca.post("/api/comments", json={"type": "item", "id": i3, "body": "first"})
    ca.post("/api/comments", json={"type": "item", "id": i3, "body": "second"})
    cb.post("/api/react", json={"type": "item", "id": i3, "value": 1})

    def ids(c, kind, **params):
        d = c.get("/api/me/activity", params={"kind": kind, **params}).json()
        return [(x["type"], x["id"]) for x in d["items"]], d["cursor"]

    liked, _ = ids(ca, "liked")
    assert set(liked) == {("item", i1), ("short", sh)}
    assert ids(ca, "disliked")[0] == [("item", i2)]
    assert ids(ca, "commented")[0] == [("item", i3)]  # one entry per post, not per comment
    assert ids(cb, "liked")[0] == [("item", i3)]  # per user
    page1, cur = ids(ca, "liked", limit=1)
    page2, cur2 = ids(ca, "liked", limit=1, cursor=cur)
    assert len(page1) == len(page2) == 1 and page1 != page2 and cur2 is None


def test_theme_prefs_and_migration(app, conn, settings):
    from app.db import init_db

    make_user(conn, "a")
    ca = login(app, "a")
    u = ca.get("/api/state").json()["user"]
    assert (u["theme"], u["accent"], u["layout"]) == ("system", "ember", "cards")
    r = ca.patch("/api/me/prefs", json={"theme": "black", "accent": "ocean", "layout": "compact"})
    assert r.json()["user"]["layout"] == "compact"
    assert ca.patch("/api/me/prefs", json={"accent": "neon"}).status_code == 422
    # an old database without the new columns gets them added on startup
    conn.execute("ALTER TABLE users DROP COLUMN layout")
    init_db(settings.db_path)
    row = conn.execute("SELECT layout FROM users").fetchone()
    assert row["layout"] == "cards"
