from app import settings_store
from app.config import Settings
from app.db import connect
from tests.conftest import login, make_user


def _field(d, key):
    return next(f for f in d["fields"] if f["key"] == key)


def test_settings_admin_only(app, conn):
    make_user(conn, "admin", admin=True)
    make_user(conn, "friend")
    friend = login(app, "friend")
    assert friend.get("/api/admin/settings").status_code == 403
    assert friend.patch("/api/admin/settings", json={"values": {"llm_model": "x"}}).status_code == 403
    assert login(app, "admin").get("/api/admin/settings").status_code == 200


def test_patch_applies_live_and_persists(app, conn, settings):
    make_user(conn, "admin", admin=True)
    c = login(app, "admin")
    r = c.patch(
        "/api/admin/settings",
        json={
            "values": {
                "reddit_username": "/u/someone",
                "retention_days": 3,
                "llm_base_url": "http://10.0.0.5:11434/v1/",
            }
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d["changed"]) >= {"reddit_username", "retention_days", "llm_base_url"}
    assert settings.reddit_username == "someone"
    assert settings.reddit_user_agent.endswith("(by /u/someone)")
    assert d["reddit_user_agent"] == settings.reddit_user_agent
    assert settings.retention_days == 3
    assert settings.llm_base_url == "http://10.0.0.5:11434/v1"
    assert _field(d, "retention_days")["overridden"] is True
    assert _field(d, "retention_days")["default"] == 7

    # A fresh Settings (like after a restart) picks the overrides up from the database.
    fresh = Settings(data_dir=settings.data_dir, secret_key="x")
    db = connect(fresh.db_path)
    settings_store.init(fresh, db)
    db.close()
    assert fresh.retention_days == 3 and fresh.reddit_username == "someone"

    # null goes back to the .env/default value
    d = c.patch("/api/admin/settings", json={"values": {"retention_days": None}}).json()
    assert settings.retention_days == 7
    assert _field(d, "retention_days")["overridden"] is False


def test_patch_validation(app, conn, settings):
    make_user(conn, "admin", admin=True)
    c = login(app, "admin")
    bad = [
        {"retention_days": 0},
        {"reddit_batch_size": 99},
        {"hwaccel": "cuda"},
        {"llm_base_url": "ftp://x"},
        {"keep_thumbnails": "yes"},
        {"reddit_username": "bad name!"},
        {"data_dir": "/tmp"},
        {"secret_key": "x"},
        {"min_weight": 1, "max_weight": 1},
        {"shorts_per_channel": 2.5},
    ]
    for values in bad:
        r = c.patch("/api/admin/settings", json={"values": values})
        assert r.status_code == 400, values
    assert settings.retention_days == 7  # nothing was applied
    assert settings.hwaccel == "auto"


def test_secret_never_returned(app, conn, settings):
    make_user(conn, "admin", admin=True)
    c = login(app, "admin")
    d = c.patch("/api/admin/settings", json={"values": {"llm_api_key": "sk-test-123"}}).json()
    assert "sk-test-123" not in str(d)
    assert _field(d, "llm_api_key")["is_set"] is True
    assert settings.llm_api_key == "sk-test-123"


def test_ai_flag_follows_settings(app, conn, settings):
    make_user(conn, "admin", admin=True)
    c = login(app, "admin")
    assert c.get("/api/state").json()["ai"] is False
    d = c.patch(
        "/api/admin/settings", json={"values": {"llm_base_url": "http://10.0.0.5:11434/v1", "llm_model": "m"}}
    ).json()
    assert d["ai"] is True
    assert c.get("/api/state").json()["ai"] is True


def test_bad_stored_value_is_ignored(settings, conn):
    conn.execute(
        "INSERT INTO kv(key, value) VALUES('settings_overrides', ?)", ('{"retention_days": -5, "max_height": "720"}',)
    )
    s = Settings(data_dir=settings.data_dir, secret_key="x")
    settings_store.init(s, conn)
    assert s.retention_days == 7
    assert s.max_height == 720
