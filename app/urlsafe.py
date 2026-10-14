"""URL validation and SSRF-safe HTTP fetching for anything user-supplied."""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

log = logging.getLogger(__name__)

MAX_URL_LEN = 2048
BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet")


class UnsafeURLError(ValueError):
    """Raised when a URL is malformed or points somewhere we refuse to fetch."""


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv6Address) and ip.sixtofour is not None:
        ip = ip.sixtofour
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def normalize_url(raw: str) -> str:
    """Basic syntactic validation + normalization. Does not resolve DNS."""
    if not isinstance(raw, str):
        raise UnsafeURLError("URL must be a string")
    url = raw.strip()
    if not url:
        raise UnsafeURLError("URL is empty")
    if len(url) > MAX_URL_LEN:
        raise UnsafeURLError("URL is too long")
    if any(c in url for c in "\r\n\t\x00 "):
        raise UnsafeURLError("URL contains invalid characters")
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"}:
        raise UnsafeURLError("Only http and https URLs are allowed")
    if parts.username or parts.password:
        raise UnsafeURLError("URLs with credentials are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURLError("URL has no host")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("Invalid port") from exc
    netloc = host if ":" not in host else f"[{host}]"
    if port:
        netloc += f":{port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


def check_host(host: str, port: int | None = None, allow_private: bool = False) -> None:
    host = host.rstrip(".").lower()
    if allow_private:
        return
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        raise UnsafeURLError("Requests to local hosts are blocked")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _ip_is_public(literal):
            raise UnsafeURLError("Requests to private or internal addresses are blocked")
        return
    try:
        infos = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host {host}") from exc
    if not infos:
        raise UnsafeURLError(f"Could not resolve host {host}")
    for info in infos:
        addr = info[4][0]
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
        if not _ip_is_public(ip):
            raise UnsafeURLError("Requests to private or internal addresses are blocked")


def validate_url(raw: str, allow_private: bool = False) -> str:
    """Normalize and make sure the URL resolves only to public addresses."""
    url = normalize_url(raw)
    parts = urlsplit(url)
    check_host(parts.hostname or "", parts.port, allow_private)
    return url


@dataclass
class FetchResult:
    status: int
    url: str
    headers: httpx.Headers
    content: bytes

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()


def safe_get(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = 15.0,
    max_bytes: int = 8 * 1024 * 1024,
    max_redirects: int = 5,
    allow_private: bool = False,
    client: httpx.Client | None = None,
) -> FetchResult:
    """GET a URL, validating the target (and every redirect hop) against SSRF rules."""
    current = validate_url(url, allow_private)
    hdrs = {
        "User-Agent": "Mozilla/5.0 (compatible; Local DS RSS reader)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/html;q=0.8, */*;q=0.5",
    }
    if headers:
        hdrs.update(headers)
    own_client = client is None
    c = client or httpx.Client(timeout=timeout, follow_redirects=False)
    try:
        for _ in range(max_redirects + 1):
            with c.stream("GET", current, headers=hdrs) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                    nxt = urljoin(current, resp.headers["location"])
                    current = validate_url(nxt, allow_private)
                    continue
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise UnsafeURLError("Response is too large")
                return FetchResult(resp.status_code, str(resp.url), resp.headers, bytes(buf))
        raise UnsafeURLError("Too many redirects")
    finally:
        if own_client:
            c.close()
