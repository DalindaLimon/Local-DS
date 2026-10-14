from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect, init_db
from app.locks import guard
from app.security import hash_password


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data", secret_key="test-secret", scheduler_enabled=False, log_level="WARNING")
    s.ensure_dirs()
    init_db(s.db_path)
    guard.reset()
    return s


@pytest.fixture
def conn(settings: Settings):
    c = connect(settings.db_path)
    yield c
    c.close()


@pytest.fixture
def app(settings: Settings):
    from app.main import create_app

    return create_app(settings)


class Client(TestClient):
    """TestClient that sends the CSRF header automatically."""

    def request(self, method, url, **kwargs):
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("x-csrf-token", self.cookies.get("sf_csrf") or "")
            kwargs["headers"] = headers
        return super().request(method, url, **kwargs)

    def prime(self) -> Client:
        self.get("/api/state")
        return self


@pytest.fixture
def client(app):
    with Client(app) as c:
        yield c.prime()


def make_user(conn, username: str, password: str = "password123", admin: bool = False) -> int:
    cur = conn.execute(
        "INSERT INTO users(username, pw_hash, is_admin, created_at) VALUES(?,?,?,?)",
        (username, hash_password(password), int(admin), time.time()),
    )
    return cur.lastrowid


def login(app, username: str, password: str = "password123") -> Client:
    c = Client(app)
    c.prime()
    r = c.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c


def make_source(conn, title: str = "Src", kind: str = "rss") -> int:
    cur = conn.execute(
        "INSERT INTO sources(kind, title, feed_url, rss_enabled, shorts_enabled, status, created_at)"
        " VALUES(?,?,?,1,1,'ok',?)",
        (kind, title, f"https://example.com/{title}.xml", time.time()),
    )
    return cur.lastrowid


def make_item(conn, source_id: int, title: str = "Post", age: float = 0) -> int:
    t = time.time() - age
    cur = conn.execute(
        "INSERT INTO items(source_id, guid, url, title, excerpt, content_html, published_at, fetched_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (source_id, f"{title}-{t}-{source_id}", "https://example.com/p", title, "x", "<p>x</p>", t, t),
    )
    return cur.lastrowid


def make_short(
    conn, settings: Settings, source_id: int, video_id: str, age_days: float = 0, with_file: bool = True,
    status: str = "available",
) -> int:  # fmt: skip
    t = time.time() - age_days * 86400
    file_path = thumb = None
    if with_file:
        (settings.videos_dir / f"{video_id}.mp4").write_bytes(b"\x00" * 2048)
        file_path = f"{video_id}.mp4"
    (settings.thumbs_dir / f"{video_id}.jpg").write_bytes(b"jpg")
    thumb = f"{video_id}.jpg"
    cur = conn.execute(
        """INSERT INTO shorts(video_id, source_id, title, channel_name, url, downloaded_at, file_path, thumb_path,
           status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (video_id, source_id, f"Short {video_id}", "Chan", f"https://www.youtube.com/shorts/{video_id}", t,
         file_path, thumb, status, t),
    )  # fmt: skip
    return cur.lastrowid
