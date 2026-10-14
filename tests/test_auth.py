import time

from app.security import token_hash
from tests.conftest import Client, login, make_user


def test_first_run_setup_only_once(client, conn):
    r = client.get("/api/state")
    assert r.json()["setup_needed"] is True
    r = client.post("/api/setup", json={"username": "admin", "password": "supersecret1"})
    assert r.status_code == 200
    assert r.json()["user"]["is_admin"] is True
    assert client.get("/api/state").json()["setup_needed"] is False
    r = client.post("/api/setup", json={"username": "evil", "password": "supersecret1"})
    assert r.status_code == 403
    pw_hash = conn.execute("SELECT pw_hash FROM users WHERE username='admin'").fetchone()[0]
    assert pw_hash.startswith("$argon2")


def test_setup_validates_credentials(client):
    assert client.post("/api/setup", json={"username": "a", "password": "supersecret1"}).status_code == 400
    assert client.post("/api/setup", json={"username": "admin", "password": "short"}).status_code == 400


def test_session_cookie_is_httponly(client):
    r = client.post("/api/setup", json={"username": "admin", "password": "supersecret1"})
    cookie = r.headers["set-cookie"]
    assert "sf_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie or "samesite=lax" in cookie.lower()


def test_login_logout(app, conn):
    make_user(conn, "alice")
    c = Client(app).prime()
    assert c.get("/api/feed").status_code == 401
    assert c.post("/api/login", json={"username": "alice", "password": "wrong-password"}).status_code == 401
    assert c.post("/api/login", json={"username": "alice", "password": "password123"}).status_code == 200
    assert c.get("/api/feed").status_code == 200
    assert c.get("/api/state").json()["user"]["username"] == "alice"
    assert c.post("/api/logout").status_code == 200
    assert c.get("/api/feed").status_code == 401


def test_csrf_required(app, conn):
    make_user(conn, "alice")
    c = Client(app).prime()
    r = c.post("/api/login", json={"username": "alice", "password": "password123"}, headers={"x-csrf-token": "nope"})
    assert r.status_code == 403
    raw = Client(app)  # never primed: no CSRF cookie at all
    r = raw.post("/api/login", json={"username": "alice", "password": "password123"}, headers={"x-csrf-token": ""})
    assert r.status_code == 403


def test_login_rate_limited(app, conn):
    make_user(conn, "alice")
    c = Client(app).prime()
    for _ in range(5):
        assert c.post("/api/login", json={"username": "alice", "password": "bad-password"}).status_code == 401
    r = c.post("/api/login", json={"username": "alice", "password": "password123"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_no_public_signup_and_invites(app, conn):
    make_user(conn, "admin", admin=True)
    make_user(conn, "member")
    anon = Client(app).prime()
    r = anon.post("/api/register", json={"token": "x" * 32, "username": "bob", "password": "password123"})
    assert r.status_code == 404

    member = login(app, "member")
    assert member.post("/api/admin/invites", json={"hours": 1}).status_code == 403

    admin = login(app, "admin")
    r = admin.post("/api/admin/invites", json={"hours": 1})
    assert r.status_code == 200
    token = r.json()["url"].rsplit("/", 1)[1]

    friend = Client(app).prime()
    assert friend.get(f"/api/invite/{token}").status_code == 200
    r = friend.post("/api/register", json={"token": token, "username": "friend", "password": "password123"})
    assert r.status_code == 200
    assert r.json()["user"]["is_admin"] is False

    # single use
    other = Client(app).prime()
    r = other.post("/api/register", json={"token": token, "username": "friend2", "password": "password123"})
    assert r.status_code == 404


def test_expired_invite_rejected(app, conn, settings):
    make_user(conn, "admin", admin=True)
    conn.execute(
        "INSERT INTO invites(token_hash, created_by, created_at, expires_at) VALUES(?,?,?,?)",
        (token_hash(settings.secret_key, "expired-token-123"), 1, time.time() - 100, time.time() - 1),
    )
    c = Client(app).prime()
    r = c.post("/api/register", json={"token": "expired-token-123", "username": "late", "password": "password123"})
    assert r.status_code == 404


def test_admin_only_routes(app, conn):
    make_user(conn, "admin", admin=True)
    make_user(conn, "member")
    member = login(app, "member")
    assert member.get("/api/admin/status").status_code == 403
    assert member.delete("/api/admin/users/1").status_code == 403
    admin = login(app, "admin")
    assert admin.get("/api/admin/status").status_code == 200


def test_change_password_invalidates_sessions(app, conn):
    make_user(conn, "alice")
    a1 = login(app, "alice")
    a2 = login(app, "alice")
    r = a1.post("/api/account/password", json={"current": "password123", "new": "newpassword1"})
    assert r.status_code == 200
    assert a1.get("/api/feed").status_code == 200  # got a fresh session
    assert a2.get("/api/feed").status_code == 401  # other device logged out
    login(app, "alice", "newpassword1")


def test_healthz_and_security_headers(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "Content-Security-Policy" in r.headers
    assert r.headers["X-Frame-Options"] == "DENY"
