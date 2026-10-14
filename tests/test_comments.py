from tests.conftest import login, make_item, make_source, make_user


def test_comment_lifecycle_and_permissions(app, conn):
    make_user(conn, "admin", admin=True)
    make_user(conn, "a")
    make_user(conn, "b")
    item = make_item(conn, make_source(conn))
    ca, cb, cadmin = login(app, "a"), login(app, "b"), login(app, "admin")

    payload = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
    r = ca.post("/api/comments", json={"type": "item", "id": item, "body": payload})
    assert r.status_code == 200
    cid = r.json()["id"]
    # stored verbatim as text; the frontend renders it with textContent (never innerHTML)
    listed = cb.get(f"/api/comments?type=item&id={item}").json()["comments"]
    assert listed[0]["body"] == payload and listed[0]["user"] == "a"
    assert listed[0]["can_delete"] is False
    assert ca.get(f"/api/comments?type=item&id={item}").json()["comments"][0]["can_delete"] is True

    assert cb.delete(f"/api/comments/{cid}").status_code == 403
    assert ca.delete(f"/api/comments/{cid}").status_code == 200
    cid2 = cb.post("/api/comments", json={"type": "item", "id": item, "body": "hello"}).json()["id"]
    assert cadmin.delete(f"/api/comments/{cid2}").status_code == 200  # admin can delete any


def test_comment_limits(app, conn):
    make_user(conn, "a")
    item = make_item(conn, make_source(conn))
    c = login(app, "a")
    assert c.post("/api/comments", json={"type": "item", "id": item, "body": ""}).status_code == 422
    assert c.post("/api/comments", json={"type": "item", "id": item, "body": "   "}).status_code == 400
    assert c.post("/api/comments", json={"type": "item", "id": item, "body": "x" * 2001}).status_code == 422
    assert c.post("/api/comments", json={"type": "item", "id": 99999, "body": "hi"}).status_code == 404
    assert c.post("/api/comments", json={"type": "nope", "id": item, "body": "hi"}).status_code == 422
    assert c.get("/api/feed").json()["items"][0]["comments"] == 0


def test_deleting_source_keeps_interacted_items(app, conn):
    make_user(conn, "admin", admin=True)
    src = make_source(conn)
    plain = make_item(conn, src, "plain")
    talked = make_item(conn, src, "talked")
    c = login(app, "admin")
    c.post("/api/comments", json={"type": "item", "id": talked, "body": "keep"})
    r = c.delete(f"/api/sources/{src}")
    assert r.json()["archived"] is True
    ids = {row[0] for row in conn.execute("SELECT id FROM items")}
    assert ids == {talked}
    assert plain not in ids
    assert conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 1
    assert all(s["id"] != src for s in c.get("/api/sources").json()["sources"])


def test_feed_filters_liked_commented_disliked_unread(app, conn):
    from tests.conftest import login, make_item, make_source, make_user

    make_user(conn, "a")
    make_user(conn, "b")
    c, other = login(app, "a"), login(app, "b")
    src = make_source(conn)
    liked, disliked, commented, seen, plain = (make_item(conn, src, f"P{n}", age=n) for n in range(5))
    c.post("/api/react", json={"type": "item", "id": liked, "value": 1})
    c.post("/api/react", json={"type": "item", "id": disliked, "value": -1})
    c.post("/api/comments", json={"type": "item", "id": commented, "body": "hi"})
    other.post("/api/comments", json={"type": "item", "id": plain, "body": "not mine"})
    c.post("/api/seen", json={"type": "item", "ids": [seen, liked]})

    def ids(show, mode="latest"):
        return {i["id"] for i in c.get(f"/api/feed?mode={mode}&show={show}").json()["items"]}

    for mode in ("latest", "foryou"):
        assert ids("liked", mode) == {liked}
        assert ids("disliked", mode) == {disliked}  # disliked posts are listed, never hidden
        assert ids("commented", mode) == {commented}
        assert ids("unread", mode) == {disliked, commented, plain}
        assert ids("all", mode) == {liked, disliked, commented, seen, plain}
    assert c.get("/api/feed?show=bogus").status_code == 422
    # the old hide_seen flag still works
    assert {i["id"] for i in c.get("/api/feed?hide_seen=true").json()["items"]} == {disliked, commented, plain}
