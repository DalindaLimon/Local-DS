"""Passwords, sessions, CSRF and login rate limiting."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

SESSION_COOKIE = "sf_session"
CSRF_COOKIE = "sf_csrf"
CSRF_HEADER = "x-csrf-token"

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD = 8
MAX_PASSWORD = 256

_ph = PasswordHasher()
# Pre-computed hash used to keep login timing similar for unknown usernames.
_DUMMY_HASH = _ph.hash("not-a-real-password-" + secrets.token_hex(8))


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw_hash: str | None, pw: str) -> bool:
    try:
        return _ph.verify(pw_hash or _DUMMY_HASH, pw) and pw_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(pw_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(pw_hash)
    except InvalidHashError:
        return False


def validate_credentials(username: str, password: str) -> str | None:
    """Return an error message or None."""
    if not USERNAME_RE.match(username or ""):
        return "Username must be 3-32 characters: letters, numbers, . _ -"
    if not password or len(password) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters"
    if len(password) > MAX_PASSWORD:
        return "Password is too long"
    return None


def token_hash(secret_key: str, token: str) -> str:
    return hmac.new(secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def create_session(conn: sqlite3.Connection, secret_key: str, user_id: int, days: int, user_agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    conn.execute(
        "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, user_agent) VALUES(?,?,?,?,?)",
        (token_hash(secret_key, token), user_id, now, now + days * 86400, user_agent[:200]),
    )
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    return token


def session_user(conn: sqlite3.Connection, secret_key: str, token: str | None) -> sqlite3.Row | None:
    if not token or len(token) > 128:
        return None
    row = conn.execute(
        """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.expires_at > ?""",
        (token_hash(secret_key, token), time.time()),
    ).fetchone()
    return row


def delete_session(conn: sqlite3.Connection, secret_key: str, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(secret_key, token),))


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def csrf_ok(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)


class LoginRateLimiter:
    """Sliding-window limiter: N failures per key within a window.

    Keys are tracked per IP and per username so a single attacker cannot spray
    passwords and a single account cannot be brute forced from many IPs quickly.
    """

    def __init__(self, max_failures: int = 5, window: float = 900, ip_max: int = 20) -> None:
        self.max_failures = max_failures
        self.ip_max = ip_max
        self.window = window
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def retry_after(self, ip: str, username: str) -> int:
        now = time.time()
        with self._lock:
            waits = []
            for key, limit in ((f"ip:{ip}", self.ip_max), (f"user:{username.lower()}", self.max_failures)):
                q = self._prune(key, now)
                if len(q) >= limit:
                    waits.append(int(self.window - (now - q[0])) + 1)
            return max(waits) if waits else 0

    def fail(self, ip: str, username: str) -> None:
        now = time.time()
        with self._lock:
            self._fails[f"ip:{ip}"].append(now)
            self._fails[f"user:{username.lower()}"].append(now)

    def success(self, ip: str, username: str) -> None:
        with self._lock:
            self._fails.pop(f"user:{username.lower()}", None)

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()
