import socket

import httpx
import pytest

from app.urlsafe import UnsafeURLError, normalize_url, safe_get, validate_url

BLOCKED = [
    "http://127.0.0.1/feed",
    "http://localhost:8080/",
    "http://foo.localhost/",
    "http://printer.local/",
    "http://10.0.0.5/rss",
    "http://172.16.3.4/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://[fd00::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://0.0.0.0/",
    "http://2130706433/",  # 127.0.0.1 in decimal
    "http://100.64.0.1/",  # CGNAT / Tailscale range
]


@pytest.mark.parametrize("url", BLOCKED)
def test_private_targets_blocked(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url)


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)", "gopher://x", "http://user:pw@example.com/"],
)
def test_bad_schemes_and_credentials(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url)


def test_garbage_rejected():
    for bad in ["", "   ", "http://", "http://exa mple.com", "http://example.com/\r\nHost: x", "x" * 3000]:
        with pytest.raises(UnsafeURLError):
            normalize_url(bad)


def test_public_ip_allowed():
    assert validate_url("https://1.1.1.1/feed") == "https://1.1.1.1/feed"
    assert normalize_url("example.com/rss") == "https://example.com/rss"


def test_hostname_resolving_to_private_blocked(monkeypatch):
    def fake_getaddrinfo(host, port, *a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURLError):
        validate_url("https://evil.example.com/feed")


def test_mixed_resolution_blocked(monkeypatch):
    def fake_getaddrinfo(host, port, *a, **kw):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURLError):
        validate_url("https://rebind.example.com/")


def test_allow_private_override():
    assert validate_url("http://192.168.1.5/rss", allow_private=True).startswith("http://192.168.1.5")


def test_redirect_to_private_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(UnsafeURLError):
        safe_get("https://1.1.1.1/start", client=client)


def test_redirect_followed_and_size_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "/final"})
        return httpx.Response(200, content=b"x" * 5000)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = safe_get("https://1.1.1.1/start", client=client)
    assert res.status == 200 and res.url.endswith("/final")
    with pytest.raises(UnsafeURLError):
        safe_get("https://1.1.1.1/start", client=client, max_bytes=100)


def test_add_source_api_blocks_ssrf(app, conn):
    from tests.conftest import login, make_user

    make_user(conn, "alice")
    c = login(app, "alice")
    r = c.post("/api/sources", json={"input": "http://127.0.0.1:8080/feed.xml"})
    assert r.status_code == 400
    assert "blocked" in r.json()["detail"].lower()
