import time

from app import discovery
from tests.conftest import login, make_item, make_user


def _source(conn, title, topics):
    return conn.execute(
        "INSERT INTO sources(kind,title,feed_url,topics,status,created_at) VALUES('rss',?,?,?,'ok',?)",
        (title, f"https://example.com/{title}.xml", topics, time.time()),
    ).lastrowid


def test_suggestions_follow_likes_comments_and_dislikes(app, conn):
    uid = make_user(conn, "a")
    c = login(app, "a")
    lab = make_item(conn, _source(conn, "LabNews", "homelab"), "Rack tour")
    food = make_item(conn, _source(conn, "FoodNews", "food"), "Pasta night")
    base = discovery.topic_affinity(conn, uid)

    c.post("/api/react", json={"type": "item", "id": food, "value": -1})
    c.post("/api/comments", json={"type": "item", "id": lab, "body": "nice"})
    aff = discovery.topic_affinity(conn, uid)
    assert aff["homelab"] > base["homelab"]  # a comment counts as interest
    assert aff["food"] < base["food"]  # a dislike pushes the topic down

    reddit = c.get("/api/discover/suggested?kind=reddit").json()["items"]
    youtube = c.get("/api/discover/suggested?kind=youtube").json()["items"]
    assert reddit and all(i["kind"] == "reddit" for i in reddit)
    assert youtube and all(i["kind"] == "youtube" for i in youtube)
    assert reddit[0]["topics"][0] == "homelab" or "homelab" in reddit[0]["topics"]
    assert "r/Cooking" not in [i["title"] for i in reddit[:5]]

    starter = c.get("/api/discover/starter").json()
    assert starter["affinity"]["homelab"] > starter["affinity"]["food"]
