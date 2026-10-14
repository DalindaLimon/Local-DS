import math
import random
import time

import pytest

from app import personalization as P
from tests.conftest import login, make_item, make_short, make_source, make_user


def weight(conn, uid, sid):
    row = conn.execute("SELECT weight FROM user_source_prefs WHERE user_id=? AND source_id=?", (uid, sid)).fetchone()
    return row["weight"] if row else 1.0


def test_like_raises_dislike_lowers_for_that_user_only(conn, settings):
    a, b = make_user(conn, "a"), make_user(conn, "b")
    s1, s2 = make_source(conn, "s1"), make_source(conn, "s2")
    i1, i2 = make_item(conn, s1), make_item(conn, s2)

    P.react(conn, a, "item", i1, 1, settings)
    assert weight(conn, a, s1) == pytest.approx(1.25)
    assert weight(conn, b, s1) == 1.0  # friend's feed is untouched

    P.react(conn, a, "item", i2, -1, settings)
    assert weight(conn, a, s2) == pytest.approx(1.25**-settings.dislike_factor)
    assert weight(conn, a, s2) < 1.0
    assert weight(conn, b, s2) == 1.0
    # dislike is a bit weaker than a like
    assert (1 / weight(conn, a, s2)) < weight(conn, a, s1)


def test_switch_and_remove_reaction_recompute(conn, settings):
    a = make_user(conn, "a")
    s = make_source(conn)
    i = make_item(conn, s)
    P.react(conn, a, "item", i, 1, settings)
    assert weight(conn, a, s) > 1
    res = P.react(conn, a, "item", i, -1, settings)  # switch
    assert res["previous"] == 1 and res["likes"] == 0 and res["dislikes"] == 1
    assert weight(conn, a, s) == pytest.approx(1.25**-0.8)
    P.react(conn, a, "item", i, 0, settings)  # remove
    assert weight(conn, a, s) == pytest.approx(1.0)
    assert conn.execute("SELECT COUNT(*) FROM reactions").fetchone()[0] == 0


def test_short_reaction_counts_and_weight(conn, settings):
    a, b = make_user(conn, "a"), make_user(conn, "b")
    s = make_source(conn, "yt", kind="youtube")
    sh = make_short(conn, settings, s, "AAAAAAAAAAA")
    P.react(conn, a, "short", sh, 1, settings)
    P.react(conn, b, "short", sh, -1, settings)
    row = conn.execute("SELECT like_count, dislike_count FROM shorts WHERE id=?", (sh,)).fetchone()
    assert (row["like_count"], row["dislike_count"]) == (1, 1)
    assert weight(conn, a, s) > 1 > weight(conn, b, s)


def test_weights_clamped(conn, settings):
    a = make_user(conn, "a")
    good, bad = make_source(conn, "good"), make_source(conn, "bad")
    for n in range(40):
        P.react(conn, a, "item", make_item(conn, good, f"g{n}"), 1, settings)
        P.react(conn, a, "item", make_item(conn, bad, f"b{n}"), -1, settings)
    assert weight(conn, a, good) == settings.max_weight
    assert weight(conn, a, bad) == settings.min_weight
    assert P.weight_from_score(1e9, settings) == settings.max_weight
    assert P.weight_from_score(-1e9, settings) == settings.min_weight


def test_decay_moves_weight_back_to_one(conn, settings):
    a = make_user(conn, "a")
    s = make_source(conn)
    for n in range(4):
        P.react(conn, a, "item", make_item(conn, s, f"p{n}"), 1, settings)
    fresh = weight(conn, a, s)
    assert fresh == pytest.approx(1.25**4)
    # age every reaction by two half-lives -> score / 4
    conn.execute("UPDATE reactions SET created_at = created_at - ?", (2 * settings.reaction_halflife_days * 86400,))
    P.recompute_all(conn, settings)
    decayed = weight(conn, a, s)
    assert decayed == pytest.approx(1.25**1, rel=1e-3)
    assert 1.0 < decayed < fresh
    conn.execute("UPDATE reactions SET created_at = created_at - ?", (3650 * 86400,))
    P.recompute_all(conn, settings)
    assert weight(conn, a, s) == pytest.approx(1.0, abs=1e-6)


def test_compute_score_math():
    now = time.time()
    hl = 30
    reactions = [(1, now), (1, now - hl * 86400), (-1, now)]
    assert P.compute_score(reactions, now, hl, 0.8) == pytest.approx(1 + 0.5 - 0.8)
    assert P.compute_score(reactions, now, hl, 0.8, reset_at=now - 1) == pytest.approx(1 - 0.8)


def test_reset_and_manual_controls(conn, settings):
    a = make_user(conn, "a")
    s = make_source(conn)
    P.react(conn, a, "item", make_item(conn, s), 1, settings)
    assert weight(conn, a, s) > 1
    P.reset_source(conn, a, s, settings)
    assert weight(conn, a, s) == pytest.approx(1.0)
    assert conn.execute("SELECT COUNT(*) FROM reactions").fetchone()[0] == 1  # history is kept
    assert P.set_manual(conn, a, s, "boost", settings) == pytest.approx(settings.boost_multiplier)
    assert P.set_manual(conn, a, s, "mute", settings) == settings.min_weight
    assert s in P.muted_sources(conn, a)
    assert P.set_manual(conn, a, s, None, settings) == pytest.approx(1.0)


def test_weighted_shuffle_favours_heavy_sources_but_light_ones_still_appear():
    items = [("heavy", i) for i in range(10)] + [("light", i) for i in range(10)]
    weights = {"heavy": 4.0, "light": 0.5}
    rng = random.Random(1)
    heavy_top = light_top = 0
    light_first = 0
    for _ in range(3000):
        order = P.weighted_shuffle(items, lambda it: weights[it[0]], rng)
        top = order[:5]
        heavy_top += sum(1 for it in top if it[0] == "heavy")
        light_top += sum(1 for it in top if it[0] == "light")
        light_first += order[0][0] == "light"
    assert heavy_top > 4 * light_top
    assert light_top > 0  # low-weight sources still show up
    assert light_first > 0
    # equal weights -> roughly fair
    eq = sum(P.weighted_shuffle(items, lambda it: 1.0, rng)[0][0] == "heavy" for _ in range(4000))
    assert 0.44 < eq / 4000 < 0.56


def test_mix_exploration_keeps_every_item_once():
    ordered = list(range(200))
    rng = random.Random(3)
    mixed = P.mix_exploration(ordered, 10, rng)
    assert sorted(i for i, _ in mixed) == ordered
    explored = sum(1 for _, e in mixed if e)
    assert 5 <= explored <= 40
    assert all(not e for _, e in P.mix_exploration(ordered, 0, rng))


def test_disliked_items_stay_in_feed_and_lower_source_weight(app, conn, settings):
    a, b = make_user(conn, "a"), make_user(conn, "b")
    s = make_source(conn)
    i1, i2 = make_item(conn, s, "one"), make_item(conn, s, "two", age=60)
    ca, cb = login(app, "a"), login(app, "b")
    r = ca.post("/api/react", json={"type": "item", "id": i1, "value": -1})
    assert r.status_code == 200 and r.json()["weight"] < 1.0
    a_items = ca.get("/api/feed").json()["items"]
    assert [x["id"] for x in a_items] == [i1, i2]
    assert a_items[0]["my"] == -1
    assert [x["id"] for x in cb.get("/api/feed").json()["items"]] == [i1, i2]
    # the weight drop is per user
    assert weight(conn, a, s) < 1.0
    assert weight(conn, b, s) == 1.0


def test_disliked_short_stays_in_reels(app, conn, settings):
    make_user(conn, "a")
    s = make_source(conn, "yt", kind="youtube")
    sh = make_short(conn, settings, s, "DISLIKED001")
    other = make_short(conn, settings, s, "OTHERVID001")
    ca = login(app, "a")
    ca.post("/api/react", json={"type": "short", "id": sh, "value": -1})
    assert {x["id"] for x in ca.post("/api/reels/next", json={"n": 10}).json()["items"]} == {sh, other}


def test_reels_unseen_first_and_reshuffle(app, conn, settings):
    make_user(conn, "a")
    s = make_source(conn, "yt", kind="youtube")
    ids = [make_short(conn, settings, s, f"VIDEOID{n:04d}") for n in range(6)]
    c = login(app, "a")
    c.post("/api/seen", json={"type": "short", "ids": ids[:3]})
    order = [x["id"] for x in c.post("/api/reels/next", json={"n": 6}).json()["items"]]
    assert set(order[:3]) == set(ids[3:])  # unseen first
    assert set(order[3:]) == set(ids[:3])
    r = c.post("/api/reels/next", json={"n": 6, "exclude": ids}).json()
    assert r["reset"] is True and len(r["items"]) == 6  # endless: reshuffled instead of a dead end


def test_foryou_prefers_liked_source_and_cursor_is_stable(app, conn, settings):
    settings.explore_percent = 0
    make_user(conn, "a")
    liked, other = make_source(conn, "liked"), make_source(conn, "other")
    for n in range(30):
        make_item(conn, liked, f"L{n}", age=n * 600 + 300)
        make_item(conn, other, f"O{n}", age=n * 600)
    c = login(app, "a")
    first_liked = conn.execute("SELECT id FROM items WHERE source_id=? LIMIT 1", (liked,)).fetchone()[0]
    c.post("/api/react", json={"type": "item", "id": first_liked, "value": 1})
    for n in range(3):
        iid = conn.execute("SELECT id FROM items WHERE source_id=? LIMIT 1 OFFSET ?", (liked, n + 1)).fetchone()[0]
        c.post("/api/react", json={"type": "item", "id": iid, "value": 1})

    seen_ids, cursor, pages = [], None, 0
    while True:
        url = "/api/feed?mode=foryou&limit=7" + (f"&cursor={cursor}" if cursor else "")
        d = c.get(url).json()
        seen_ids += [x["id"] for x in d["items"]]
        cursor = d["cursor"]
        pages += 1
        if not cursor:
            break
    assert len(seen_ids) == len(set(seen_ids)) == 60  # no duplicates, nothing skipped
    top = seen_ids[:10]
    liked_ids = {r[0] for r in conn.execute("SELECT id FROM items WHERE source_id=?", (liked,))}
    assert sum(1 for i in top if i in liked_ids) >= 7
    latest = [x["id"] for x in c.get("/api/feed?mode=latest&limit=50").json()["items"]]
    times = [conn.execute("SELECT published_at FROM items WHERE id=?", (i,)).fetchone()[0] for i in latest]
    assert times == sorted(times, reverse=True)


def test_latest_cursor_pagination(app, conn):
    make_user(conn, "a")
    s = make_source(conn)
    for n in range(45):
        make_item(conn, s, f"P{n}", age=n * 10)
    c = login(app, "a")
    ids, cursor = [], None
    while True:
        d = c.get("/api/feed?limit=20" + (f"&cursor={cursor}" if cursor else "")).json()
        ids += [x["id"] for x in d["items"]]
        cursor = d["cursor"]
        if not cursor:
            break
    assert len(ids) == len(set(ids)) == 45


def test_muted_source_hidden(app, conn, settings):
    make_user(conn, "a")
    s1, s2 = make_source(conn, "s1"), make_source(conn, "s2")
    make_item(conn, s1)
    keep = make_item(conn, s2)
    c = login(app, "a")
    r = c.patch(f"/api/sources/{s1}", json={"manual": "mute"})
    assert r.status_code == 200 and r.json()["source"]["manual"] == "mute"
    assert [x["id"] for x in c.get("/api/feed").json()["items"]] == [keep]


def test_sources_page_share_and_why(app, conn, settings):
    make_user(conn, "a")
    s1, s2 = make_source(conn, "s1"), make_source(conn, "s2")
    c = login(app, "a")
    for n in range(3):
        c.post("/api/react", json={"type": "item", "id": make_item(conn, s1, f"x{n}"), "value": 1})
    src = {x["id"]: x for x in c.get("/api/sources").json()["sources"]}
    assert src[s1]["share"] > src[s2]["share"]
    assert math.isclose(src[s1]["share"] + src[s2]["share"], 100, abs_tol=0.2)
    assert "liked 3" in src[s1]["why"]
    item = c.get("/api/feed?mode=foryou").json()["items"][0]
    assert "why" in item
