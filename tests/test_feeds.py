import time

import httpx

from app import feeds
from app.feeds import classify_input, find_feed_links, parse_feed, prune_old_items
from app.urlsafe import FetchResult
from tests.conftest import make_item, make_source, make_user

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:media="http://search.yahoo.com/mrss/">
<channel>
  <title>Example Blog</title>
  <link>https://blog.example.com/</link>
  <image><url>https://blog.example.com/logo.png</url><title>x</title><link>https://blog.example.com/</link></image>
  <item>
    <title>Hello &amp; welcome</title>
    <link>https://blog.example.com/hello</link>
    <guid>post-1</guid>
    <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
    <media:thumbnail url="https://blog.example.com/thumb.jpg"/>
    <description>Short summary</description>
    <content:encoded><![CDATA[<p onclick="evil()">Full <b>text</b> here.</p><script>alert(1)</script>
      <a href="javascript:alert(1)">bad link</a> <a href="/rel">relative</a>
      <img src="https://blog.example.com/inline.jpg" onerror="evil()">
      <iframe src="https://evil.example.com"></iframe>]]></content:encoded>
  </item>
  <item>
    <title>No date</title>
    <link>https://blog.example.com/nodate</link>
    <description>&lt;p&gt;Body with &lt;img src="https://blog.example.com/a.png" width="600"&gt;&lt;/p&gt;</description>
  </item>
</channel>
</rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Site</title>
  <link href="https://atom.example.com/"/>
  <id>urn:x</id><updated>2024-02-01T00:00:00Z</updated>
  <entry>
    <title type="html">Atom &lt;em&gt;entry&lt;/em&gt;</title>
    <link href="https://atom.example.com/e1"/>
    <id>urn:e1</id>
    <updated>2024-02-01T00:00:00Z</updated>
    <content type="html">&lt;p&gt;Atom body&lt;/p&gt;</content>
    <author><name>Ann</name></author>
  </entry>
</feed>"""

REDDIT = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"
 xmlns:media="http://search.yahoo.com/mrss/"><title>selfhosted</title>
<entry><author><name>/u/someone</name></author><id>t3_abc</id>
<link href="https://www.reddit.com/r/selfhosted/comments/abc/x/"/>
<updated>2024-03-01T12:00:00+00:00</updated><title>My setup</title>
<media:thumbnail url="https://b.thumbs.redditmedia.com/t.jpg"/>
<content type="html">&lt;!-- SC_OFF --&gt;&lt;div class="md"&gt;&lt;p&gt;Look at this&lt;/p&gt;&lt;/div&gt;&lt;!-- SC_ON --&gt;
&amp;#32; submitted by &amp;#32; &lt;a href="https://www.reddit.com/user/someone"&gt; /u/someone &lt;/a&gt;
&lt;br/&gt; &lt;span&gt;&lt;a href="https://x"&gt;[link]&lt;/a&gt;&lt;/span&gt;</content></entry></feed>"""


def test_parse_rss_sanitizes_content():
    p = parse_feed(RSS, "https://blog.example.com/feed")
    assert p.is_feed and p.title == "Example Blog"
    assert p.icon_url == "https://blog.example.com/logo.png"
    e = p.entries[0]
    assert e.title == "Hello & welcome"
    assert e.guid == "post-1"
    assert e.image_url == "https://blog.example.com/thumb.jpg"
    assert e.published_at == 1704103200.0
    html = e.content_html
    for bad in ("<script", "onclick", "onerror", "javascript:", "<iframe", "evil"):
        assert bad not in html
    assert "<b>text</b>" in html
    assert 'href="https://blog.example.com/rel"' in html
    assert 'rel="noopener noreferrer nofollow"' in html
    assert "Full text here." in e.excerpt


def test_parse_rss_entry_without_date_and_image_from_body():
    p = parse_feed(RSS, "https://blog.example.com/feed")
    e = p.entries[1]
    assert abs(e.published_at - time.time()) < 60
    assert e.image_url == "https://blog.example.com/a.png"


def test_parse_atom():
    p = parse_feed(ATOM, "https://atom.example.com/feed")
    assert p.title == "Atom Site"
    e = p.entries[0]
    assert e.title == "Atom entry"
    assert e.author == "Ann"
    assert e.url == "https://atom.example.com/e1"
    assert "Atom body" in e.content_html


def test_parse_reddit_strips_footer():
    p = parse_feed(REDDIT, "https://www.reddit.com/r/selfhosted/.rss", reddit=True)
    e = p.entries[0]
    assert "submitted by" not in e.content_html
    assert "Look at this" in e.content_html
    assert e.image_url == "https://b.thumbs.redditmedia.com/t.jpg"


REDDIT_IMAGE = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"
 xmlns:media="http://search.yahoo.com/mrss/"><title>cachyos</title>
<entry><id>t3_def</id><link href="https://www.reddit.com/r/cachyos/comments/def/x/"/>
<updated>2024-03-01T12:00:00+00:00</updated><title>My desktop</title>
<media:thumbnail url="https://preview.redd.it/abc123.png?width=140&amp;height=78&amp;auto=webp&amp;s=ff"/>
<content type="html">&lt;a href="https://www.reddit.com/r/cachyos/comments/def/x/"&gt;
&lt;img src="https://preview.redd.it/abc123.png?width=640&amp;amp;crop=smart&amp;amp;s=ee" /&gt;&lt;/a&gt;
&lt;img src="https://preview.redd.it/anim.gif?width=640&amp;amp;s=dd" /&gt;
&lt;img src="https://external-preview.redd.it/ext.png?width=640&amp;amp;s=cc" /&gt;</content></entry></feed>"""


def test_parse_reddit_uses_full_size_images():
    e = parse_feed(REDDIT_IMAGE, "https://www.reddit.com/r/cachyos/.rss", reddit=True).entries[0]
    assert e.image_url == "https://i.redd.it/abc123.png"
    assert 'src="https://i.redd.it/abc123.png"' in e.content_html
    assert "preview.redd.it/anim.gif?width=640" in e.content_html  # GIF originals can be huge: keep the preview
    assert "external-preview.redd.it/ext.png" in e.content_html  # no original exists for these


def test_parse_non_reddit_keeps_preview_urls():
    e = parse_feed(REDDIT_IMAGE, "https://example.com/feed").entries[0]
    assert e.image_url.startswith("https://preview.redd.it/abc123.png?width=140")


def test_init_db_upgrades_existing_reddit_images(tmp_path):
    from app import db

    path = tmp_path / "t.db"
    db.init_db(path)
    conn = db.connect(path)
    conn.execute("INSERT INTO sources(kind,title,feed_url,status,created_at) VALUES('reddit','r/x','u','ok',0)")
    conn.execute(
        "INSERT INTO items(source_id,guid,title,image_url,content_html,published_at,fetched_at) VALUES(1,'g','t',?,?,0,0)",
        (
            "https://preview.redd.it/a1.jpg?width=640&s=x",
            '<img src="https://preview.redd.it/a1.jpg?width=640&amp;s=x">',
        ),
    )
    conn.execute("DELETE FROM kv WHERE key = 'reddit_full_images'")
    conn.close()
    db.init_db(path)
    conn = db.connect(path)
    row = conn.execute("SELECT image_url, content_html FROM items").fetchone()
    assert row["image_url"] == "https://i.redd.it/a1.jpg"
    assert row["content_html"] == '<img src="https://i.redd.it/a1.jpg">'


def test_parse_html_is_not_a_feed():
    p = parse_feed(b"<html><head><title>x</title></head><body>hi</body></html>", "https://x.example.com/")
    assert not p.is_feed or not p.entries


def test_autodiscovery_links():
    html = b"""<html><head>
      <link rel="alternate" type="application/rss+xml" href="/feed.xml">
      <link rel="alternate" type="application/atom+xml" href="https://cdn.example.com/atom">
      <link rel="stylesheet" href="/x.css"></head></html>"""
    assert find_feed_links(html, "https://site.example.com/blog/") == [
        "https://site.example.com/feed.xml",
        "https://cdn.example.com/atom",
    ]


def test_classify_input():
    assert classify_input("selfhosted").kind == "reddit"
    assert classify_input("r/homelab").value == "homelab"
    assert classify_input("https://www.reddit.com/r/Proxmox/top/").value == "Proxmox"
    yt = classify_input("@JeffGeerling")
    assert yt.kind == "youtube" and yt.value == "https://www.youtube.com/@JeffGeerling"
    assert classify_input("https://www.youtube.com/channel/UC" + "a" * 22 + "/videos").kind == "youtube"
    assert classify_input("https://youtube.com/@mkbhd/shorts").value == "https://www.youtube.com/@mkbhd"
    u = classify_input("blog.example.com")
    assert u.kind == "url" and u.value == "https://blog.example.com"
    assert feeds.reddit_feed_url("selfhosted") == "https://www.reddit.com/r/selfhosted/.rss"


def _result(status, content=b"", headers=None, url="https://www.reddit.com/r/x/.rss"):
    return FetchResult(status, url, httpx.Headers(headers or {}), content)


def test_fetch_source_stores_items_and_dedupes(conn, settings, monkeypatch):
    sid = make_source(conn, "blog")
    monkeypatch.setattr(feeds, "safe_get", lambda *a, **k: _result(200, RSS, {"etag": "abc"}))
    src = conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
    assert feeds.fetch_source(conn, src, settings) == 2
    src = conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
    assert src["etag"] == "abc" and src["status"] == "ok"
    assert feeds.fetch_source(conn, src, settings) == 0  # same guids


def test_reddit_429_backoff(conn, settings, monkeypatch):
    feeds.reddit_throttle.gap = 0
    cur = conn.execute(
        "INSERT INTO sources(kind,title,feed_url,status,created_at) VALUES('reddit','r/x',?,'new',?)",
        (feeds.reddit_feed_url("x"), time.time()),
    )
    monkeypatch.setattr(feeds, "safe_get", lambda *a, **k: _result(429, headers={"retry-after": "120"}))
    src = conn.execute("SELECT * FROM sources WHERE id=?", (cur.lastrowid,)).fetchone()
    assert feeds.fetch_source(conn, src, settings) == 0
    src = conn.execute("SELECT * FROM sources WHERE id=?", (cur.lastrowid,)).fetchone()
    assert src["status"] == "rate_limited"
    assert src["backoff_until"] > time.time() + 100
    assert "429" in src["last_error"]
    # while backing off, no request is made
    monkeypatch.setattr(feeds, "safe_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert feeds.fetch_source(conn, src, settings) == 0


def test_reddit_403_falls_back_to_old_reddit(conn, settings, monkeypatch):
    feeds.reddit_throttle.gap = 0
    cur = conn.execute(
        "INSERT INTO sources(kind,title,feed_url,status,created_at) VALUES('reddit','r/x',?,'new',?)",
        (feeds.reddit_feed_url("x"), time.time()),
    )
    calls = []

    def fake(url, **kw):
        calls.append(url)
        assert "User-Agent" in kw["headers"]
        return _result(403) if "www.reddit.com" in url else _result(200, REDDIT, url=url)

    monkeypatch.setattr(feeds, "safe_get", fake)
    src = conn.execute("SELECT * FROM sources WHERE id=?", (cur.lastrowid,)).fetchone()
    assert feeds.fetch_source(conn, src, settings) == 1
    assert any("old.reddit.com" in c for c in calls)


def test_optional_rss_retention_keeps_commented_items(conn):
    uid = make_user(conn, "a")
    sid = make_source(conn)
    old_plain = make_item(conn, sid, "old", age=40 * 86400)
    old_commented = make_item(conn, sid, "oldc", age=40 * 86400)
    new = make_item(conn, sid, "new")
    conn.execute(
        "INSERT INTO comments(user_id,item_type,item_id,body,created_at) VALUES(?,?,?,?,?)",
        (uid, "item", old_commented, "keep me", time.time()),
    )
    assert prune_old_items(conn, 30) == 1
    ids = {r[0] for r in conn.execute("SELECT id FROM items")}
    assert ids == {old_commented, new}
    assert old_plain not in ids


def _multi_feed(*subs: str) -> bytes:
    entries = "".join(
        f"""<entry>{"" if s == "homelab" else f'<category term="{s}" label="r/{s}"/>'}<id>t3_{s}{n}</id><title>{s} post {n}</title>
        <link href="https://www.reddit.com/r/{s}/comments/{n}/x/"/><updated>2026-10-01T10:00:00+00:00</updated>
        <content type="html">hi</content></entry>"""
        for s in subs
        for n in range(2)
    )
    return (
        f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>multi</title>{entries}</feed>'.encode()
    )


def _reddit_sources(conn, *names):
    ids = []
    for n in names:
        cur = conn.execute(
            "INSERT INTO sources(kind,title,feed_url,status,created_at) VALUES('reddit',?,?,'new',?)",
            (f"r/{n}", feeds.reddit_feed_url(n), time.time()),
        )
        ids.append(cur.lastrowid)
    return ids


def test_reddit_batch_one_request_split_by_subreddit(conn, settings, monkeypatch):
    feeds.reddit_throttle.gap = 0
    settings.reddit_batch_size = 3
    a, b, c = _reddit_sources(conn, "linux", "Selfhosted", "homelab", "gaming")[:3]
    calls = []

    def fake(url, **kw):
        calls.append(url)
        subs = url.split("/r/")[1].split("/")[0].lower().split("+")
        return _result(200, _multi_feed(*subs), url=url)

    monkeypatch.setattr(feeds, "safe_get", fake)
    assert feeds.refresh_all(conn, settings) == 8
    assert calls == [
        "https://www.reddit.com/r/linux+Selfhosted+homelab/.rss?limit=100",
        "https://www.reddit.com/r/gaming/.rss",  # a batch of one uses the normal path
    ]
    per_source = dict(conn.execute("SELECT source_id, COUNT(*) FROM items GROUP BY source_id").fetchall())
    # case-insensitive match, homelab entries matched by their link (no <category>), nothing cross-posted
    assert per_source[a] == per_source[b] == per_source[c] == 2
    assert {r["status"] for r in conn.execute("SELECT status FROM sources")} == {"ok"}


def test_reddit_batch_rate_limit_backs_off_every_source(conn, settings, monkeypatch):
    feeds.reddit_throttle.gap = 0
    ids = _reddit_sources(conn, "linux", "homelab")
    monkeypatch.setattr(feeds, "safe_get", lambda *a, **k: _result(429))
    assert feeds.refresh_all(conn, settings) == 0
    rows = conn.execute("SELECT status, backoff_until FROM sources WHERE id IN (?,?)", ids).fetchall()
    assert all(r["status"] == "rate_limited" and r["backoff_until"] > time.time() for r in rows)


def test_reddit_batch_falls_back_to_single_requests(conn, settings, monkeypatch):
    feeds.reddit_throttle.gap = 0
    _reddit_sources(conn, "linux", "gonesub")
    calls = []

    def fake(url, **kw):
        calls.append(url)
        if "+" in url:
            return _result(404, url=url)
        return _result(200, _multi_feed("linux"), url=url) if "linux" in url else _result(404, url=url)

    monkeypatch.setattr(feeds, "safe_get", fake)
    assert feeds.refresh_all(conn, settings) == 2
    status = dict(conn.execute("SELECT title, status FROM sources").fetchall())
    assert status == {"r/linux": "ok", "r/gonesub": "error"}


def test_reddit_user_agent():
    from app.config import reddit_user_agent

    assert reddit_user_agent("/u/someone").endswith("(by /u/someone)")
    assert reddit_user_agent("").startswith("linux:localds:")
