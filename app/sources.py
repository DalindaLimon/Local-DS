"""Adding sources from user input (website, feed, subreddit, YouTube channel)."""

from __future__ import annotations

import sqlite3

from app import discovery, feeds, shorts
from app.config import Settings
from app.db import now, tx
from app.urlsafe import validate_url


class SourceError(ValueError):
    pass


def _exists(conn: sqlite3.Connection, feed_url: str | None = None, channel_id: str | None = None):
    if feed_url:
        row = conn.execute("SELECT * FROM sources WHERE feed_url=?", (feed_url,)).fetchone()
        if row:
            return row
    if channel_id:
        return conn.execute("SELECT * FROM sources WHERE channel_id=?", (channel_id,)).fetchone()
    return None


def add_source(
    conn: sqlite3.Connection,
    settings: Settings,
    raw: str,
    user_id: int,
    also_rss: bool = True,
    topics: list[str] | None = None,
) -> tuple[sqlite3.Row, bool]:
    """Create a source. Returns (row, created). Raises SourceError with a friendly message."""
    try:
        parsed_input = feeds.classify_input(raw)
    except ValueError as exc:
        raise SourceError(str(exc)) from exc

    t = now()
    if parsed_input.kind == "reddit":
        name = parsed_input.value
        feed_url = feeds.reddit_feed_url(name)
        existing = conn.execute(
            "SELECT * FROM sources WHERE kind='reddit' AND lower(feed_url)=lower(?)", (feed_url,)
        ).fetchone()
        if existing:
            return existing, False
        tps = topics or discovery.starter_topics_for("reddit", name) or discovery.guess_topics(name)
        with tx(conn):
            cur = conn.execute(
                """INSERT INTO sources(kind, title, feed_url, site_url, rss_enabled, shorts_enabled, topics,
                   status, created_by, created_at) VALUES('reddit', ?, ?, ?, 1, 0, ?, 'new', ?, ?)""",
                (f"r/{name}", feed_url, f"https://www.reddit.com/r/{name}/", ",".join(tps), user_id, t),
            )
        return conn.execute("SELECT * FROM sources WHERE id=?", (cur.lastrowid,)).fetchone(), True

    if parsed_input.kind == "youtube":
        validate_url(parsed_input.value, settings.allow_private_urls)
        try:
            ch = shorts.resolve_channel(parsed_input.value)
        except shorts.ShortsError as exc:
            raise SourceError(str(exc)) from exc
        existing = _exists(conn, channel_id=ch["channel_id"])
        if existing:
            return existing, False
        tps = (
            topics
            or discovery.starter_topics_for("youtube", parsed_input.value)
            or discovery.guess_topics(ch["title"], ch["description"], " ".join(ch["tags"][:20]))
        )
        with tx(conn):
            cur = conn.execute(
                """INSERT INTO sources(kind, title, feed_url, site_url, channel_id, channel_url, icon_url, rss_enabled,
                   shorts_enabled, topics, status, created_by, created_at)
                   VALUES('youtube', ?, ?, ?, ?, ?, ?, ?, 1, ?, 'new', ?, ?)""",
                (
                    ch["title"], feeds.youtube_feed_url(ch["channel_id"]), ch["channel_url"], ch["channel_id"],
                    ch["channel_url"], ch.get("avatar"), 1 if also_rss else 0, ",".join(tps), user_id, t,
                ),
            )  # fmt: skip
        return conn.execute("SELECT * FROM sources WHERE id=?", (cur.lastrowid,)).fetchone(), True

    # Plain URL: direct feed or a website with autodiscovery.
    try:
        url = validate_url(parsed_input.value, settings.allow_private_urls)
    except ValueError as exc:
        raise SourceError(str(exc)) from exc
    try:
        feed_url, parsed = feeds.discover_feed(url, settings)
    except Exception as exc:
        raise SourceError(f"Could not find a feed: {exc}") from exc
    existing = _exists(conn, feed_url=feed_url)
    if existing:
        return existing, False
    tps = topics or discovery.starter_topics_for("rss", raw.strip()) or discovery.guess_topics(parsed.title)
    with tx(conn):
        cur = conn.execute(
            """INSERT INTO sources(kind, title, feed_url, site_url, icon_url, rss_enabled, shorts_enabled, topics,
               status, created_by, created_at) VALUES('rss', ?, ?, ?, ?, 1, 0, ?, 'new', ?, ?)""",
            (parsed.title, feed_url, parsed.site_url or url, parsed.icon_url, ",".join(tps), user_id, t),
        )
        sid = cur.lastrowid
        for e in parsed.entries:
            conn.execute(
                """INSERT OR IGNORE INTO items(source_id, guid, url, title, author, excerpt, content_html, image_url,
                   published_at, fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (sid, e.guid, e.url, e.title, e.author, e.excerpt, e.content_html, e.image_url, e.published_at, t),
            )
        conn.execute("UPDATE sources SET status='ok', last_fetched=? WHERE id=?", (t, sid))
    return conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone(), True
