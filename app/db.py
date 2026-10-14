"""SQLite access: schema, migrations and connection helpers."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash     TEXT NOT NULL,
    is_admin    INTEGER NOT NULL DEFAULT 0,
    feed_mode   TEXT NOT NULL DEFAULT 'latest',
    hide_seen   INTEGER NOT NULL DEFAULT 0,
    muted       INTEGER NOT NULL DEFAULT 1,
    theme       TEXT NOT NULL DEFAULT 'system',   -- system | dark | black | light
    accent      TEXT NOT NULL DEFAULT 'ember',
    layout      TEXT NOT NULL DEFAULT 'cards',    -- cards | compact | magazine
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    user_agent  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS invites (
    token_hash  TEXT PRIMARY KEY,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    used_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    used_at     REAL,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,              -- rss | reddit | youtube | demo
    title         TEXT NOT NULL,
    feed_url      TEXT,                       -- RSS/Atom URL (rss, reddit, youtube when rss_enabled)
    site_url      TEXT,
    icon_url      TEXT,
    channel_id    TEXT,                       -- youtube
    channel_url   TEXT,                       -- youtube
    rss_enabled   INTEGER NOT NULL DEFAULT 1, -- show posts in the Feed tab
    shorts_enabled INTEGER NOT NULL DEFAULT 0,-- download Shorts (youtube)
    enabled       INTEGER NOT NULL DEFAULT 1,
    topics        TEXT NOT NULL DEFAULT '',   -- comma separated
    status        TEXT NOT NULL DEFAULT 'new',
    last_fetched  REAL,
    last_error    TEXT,
    error_count   INTEGER NOT NULL DEFAULT 0,
    backoff_until REAL,
    etag          TEXT,
    last_modified TEXT,
    created_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at    REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_feed ON sources(feed_url) WHERE feed_url IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_channel ON sources(channel_id) WHERE channel_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY,
    source_id     INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    guid          TEXT NOT NULL,
    url           TEXT,
    title         TEXT NOT NULL,
    author        TEXT,
    excerpt       TEXT,
    content_html  TEXT,
    image_url     TEXT,
    published_at  REAL NOT NULL,
    fetched_at    REAL NOT NULL,
    UNIQUE(source_id, guid)
);
CREATE INDEX IF NOT EXISTS idx_items_pub ON items(published_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_items_source_pub ON items(source_id, published_at DESC);

CREATE TABLE IF NOT EXISTS shorts (
    id            INTEGER PRIMARY KEY,
    video_id      TEXT NOT NULL UNIQUE,
    source_id     INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    title         TEXT NOT NULL DEFAULT '',
    channel_name  TEXT NOT NULL DEFAULT '',
    channel_id    TEXT,
    url           TEXT NOT NULL,
    published_at  REAL,
    downloaded_at REAL,
    expired_at    REAL,
    file_path     TEXT,
    thumb_path    TEXT,
    preview_path  TEXT,
    duration      REAL,
    width         INTEGER,
    height        INTEGER,
    status        TEXT NOT NULL DEFAULT 'pending', -- pending|available|expired|failed
    attempts      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    like_count    INTEGER NOT NULL DEFAULT 0,
    dislike_count INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shorts_status ON shorts(status, downloaded_at);

CREATE TABLE IF NOT EXISTS reactions (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_type   TEXT NOT NULL,            -- item | short
    item_id     INTEGER NOT NULL,
    source_id   INTEGER,
    value       INTEGER NOT NULL,         -- +1 / -1
    created_at  REAL NOT NULL,
    PRIMARY KEY (user_id, item_type, item_id)
);
CREATE INDEX IF NOT EXISTS idx_reactions_user_source ON reactions(user_id, source_id);

CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    item_type   TEXT NOT NULL,
    item_id     INTEGER NOT NULL,
    body        TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_item ON comments(item_type, item_id, created_at);

CREATE TABLE IF NOT EXISTS attachments (
    id          INTEGER PRIMARY KEY,
    token       TEXT NOT NULL UNIQUE,      -- random file name, used in /media/upload/<token>
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    item_id     INTEGER REFERENCES items(id) ON DELETE CASCADE,  -- NULL until the post is created
    filename    TEXT NOT NULL,             -- original name, shown and used for downloads
    ext         TEXT NOT NULL,
    mime        TEXT NOT NULL,
    kind        TEXT NOT NULL,             -- image | video | audio | file
    size        INTEGER NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attachments_item ON attachments(item_id);

CREATE TABLE IF NOT EXISTS seen (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_type   TEXT NOT NULL,
    item_id     INTEGER NOT NULL,
    seen_at     REAL NOT NULL,
    PRIMARY KEY (user_id, item_type, item_id)
);

CREATE TABLE IF NOT EXISTS user_source_prefs (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id   INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    weight      REAL NOT NULL DEFAULT 1.0,
    score       REAL NOT NULL DEFAULT 0.0,
    manual      TEXT,                     -- NULL | boost | mute
    reset_at    REAL,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (user_id, source_id)
);

-- A user's own priority list: level 1 high, 2 medium, 3 low. Rows exist only while a priority is set.
CREATE TABLE IF NOT EXISTS priorities (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_type   TEXT NOT NULL,            -- item | short
    item_id     INTEGER NOT NULL,
    level       INTEGER NOT NULL,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (user_id, item_type, item_id)
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        kv_set(conn, "schema_version", str(SCHEMA_VERSION))
    finally:
        conn.close()


# Columns added after the first release: (table, column, definition).
ADDED_COLUMNS = [
    ("users", "theme", "TEXT NOT NULL DEFAULT 'system'"),
    ("users", "accent", "TEXT NOT NULL DEFAULT 'ember'"),
    ("users", "layout", "TEXT NOT NULL DEFAULT 'cards'"),
    ("sources", "icon_path", "TEXT"),  # cached picture in /data/icons (app/icons.py)
    ("sources", "icon_checked_at", "REAL"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, definition in ADDED_COLUMNS:
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    if kv_get(conn, "reddit_full_images") is None:
        _upgrade_reddit_images(conn)
        kv_set(conn, "reddit_full_images", "1")


def _upgrade_reddit_images(conn: sqlite3.Connection) -> None:
    """One-off: point items fetched by older versions at full-size Reddit images instead of 140/640 px previews."""
    from app.sanitize import full_reddit_images

    rows = conn.execute(
        "SELECT id, image_url, content_html FROM items WHERE image_url LIKE '%preview.redd.it%' "
        "OR content_html LIKE '%preview.redd.it%'"
    ).fetchall()
    with tx(conn):
        for r in rows:
            conn.execute(
                "UPDATE items SET image_url = ?, content_html = ? WHERE id = ?",
                (full_reddit_images(r["image_url"]), full_reddit_images(r["content_html"]), r["id"]),
            )


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit write transaction (connections run in autocommit mode)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def kv_get(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def now() -> float:
    return time.time()
