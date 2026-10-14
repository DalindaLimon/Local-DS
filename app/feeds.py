"""RSS/Atom handling: input classification, autodiscovery, fetching and parsing."""

from __future__ import annotations

import calendar
import hashlib
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import feedparser
from bs4 import BeautifulSoup

from app.config import Settings
from app.db import now, tx
from app.sanitize import clean_html, excerpt, first_image, full_reddit_images, html_to_text
from app.urlsafe import UnsafeURLError, safe_get, validate_url

log = logging.getLogger(__name__)

SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_]{1,20}$")
YT_HANDLE_RE = re.compile(r"^@[A-Za-z0-9._-]{2,100}$")
YT_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json", "application/xml", "text/xml")
REDDIT_HOSTS = ("www.reddit.com", "old.reddit.com")
# Posts per combined request (Reddit caps RSS at 100), shared by the subreddits in one batch.
REDDIT_BATCH_LIMIT = 100


# --------------------------------------------------------------------------- input


@dataclass
class SourceInput:
    kind: str  # reddit | youtube | url
    value: str  # subreddit name, youtube URL, or URL


def classify_input(raw: str) -> SourceInput:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Paste a URL, a subreddit name or a YouTube channel")
    if len(text) > 2048:
        raise ValueError("Input is too long")

    m = re.match(r"^/?r/([A-Za-z0-9_]{2,21})/?$", text)
    if m:
        return SourceInput("reddit", m.group(1))
    if SUBREDDIT_RE.match(text):
        return SourceInput("reddit", text)
    if YT_HANDLE_RE.match(text):
        return SourceInput("youtube", f"https://www.youtube.com/{text}")
    if YT_CHANNEL_ID_RE.match(text):
        return SourceInput("youtube", f"https://www.youtube.com/channel/{text}")

    url = text if "://" in text else "https://" + text
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path
    if host.endswith("reddit.com") or host == "redd.it":
        m = re.match(r"^/r/([A-Za-z0-9_]{2,21})", path)
        if m:
            return SourceInput("reddit", m.group(1))
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        m = re.match(r"^/(@[A-Za-z0-9._-]+|channel/UC[A-Za-z0-9_-]{22}|c/[^/]+|user/[^/]+)", path)
        if m:
            return SourceInput("youtube", f"https://www.youtube.com/{m.group(1)}")
        if path.startswith("/feeds/videos.xml"):
            m = re.search(r"channel_id=(UC[A-Za-z0-9_-]{22})", parts.query)
            if m:
                return SourceInput("youtube", f"https://www.youtube.com/channel/{m.group(1)}")
    return SourceInput("url", url)


def reddit_feed_url(name: str, host: str = "www.reddit.com") -> str:
    return f"https://{host}/r/{name}/.rss"


def youtube_feed_url(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


# --------------------------------------------------------------------------- parsing


@dataclass
class ParsedEntry:
    guid: str
    title: str
    url: str | None
    author: str | None
    published_at: float
    content_html: str
    excerpt: str
    image_url: str | None
    category: str | None = None  # first <category term>; the subreddit name in Reddit feeds


@dataclass
class ParsedFeed:
    title: str
    site_url: str | None
    icon_url: str | None
    entries: list[ParsedEntry] = field(default_factory=list)
    is_feed: bool = True


def _entry_time(entry) -> float:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t:
            try:
                ts = float(calendar.timegm(t))
            except (TypeError, ValueError, OverflowError):
                continue
            return min(ts, time.time())
    return time.time()


def _entry_image(entry, content: str, base: str | None) -> str | None:
    for key in ("media_thumbnail", "media_content"):
        for m in entry.get(key) or []:
            url = m.get("url")
            medium = m.get("medium", "")
            mtype = m.get("type", "")
            is_image = key == "media_thumbnail" or medium == "image" or mtype.startswith("image/")
            if url and is_image and url.startswith(("http://", "https://")):
                return url
    for enc in entry.get("enclosures") or []:
        if (enc.get("type") or "").startswith("image/") and (enc.get("href") or "").startswith("http"):
            return enc["href"]
    return first_image(content, base)


def _strip_reddit_footer(raw: str) -> str:
    idx = raw.find("submitted by")
    if idx > 0:
        raw = raw[:idx]
        raw = re.sub(r"(&#32;|\s)+$", "", raw)
    return raw


def parse_feed(content: bytes, base_url: str | None = None, reddit: bool = False) -> ParsedFeed:
    parsed = feedparser.parse(content)
    feed = parsed.get("feed", {})
    is_feed = bool(parsed.get("version")) or bool(parsed.get("entries"))
    title = html_to_text(feed.get("title", "")) or (urlsplit(base_url).hostname if base_url else "Feed")
    site_url = feed.get("link")
    icon = None
    image = {} if reddit else (feed.get("image") or {})  # Reddit only sends its generic logo; see app/icons.py
    if isinstance(image, dict) and str(image.get("href", "")).startswith("http"):
        icon = image["href"]
    elif not reddit and str(feed.get("icon", "")).startswith("http"):
        icon = feed["icon"]
    entries: list[ParsedEntry] = []
    for e in parsed.get("entries", [])[:200]:
        raw_content = ""
        if e.get("content"):
            raw_content = e["content"][0].get("value", "")
        if not raw_content:
            raw_content = e.get("summary", "") or e.get("media_description", "") or ""
        if reddit:
            raw_content = full_reddit_images(_strip_reddit_footer(raw_content))
        link = e.get("link")
        if link and not str(link).startswith(("http://", "https://")):
            link = urljoin(base_url or "", link) if base_url else None
        entry_title = html_to_text(e.get("title", "")) or "(untitled)"
        guid = (
            e.get("id")
            or link
            or hashlib.sha1(f"{entry_title}{e.get('published', '')}".encode(), usedforsecurity=False).hexdigest()
        )
        text = html_to_text(raw_content)
        image = _entry_image(e, raw_content, link or base_url)
        entries.append(
            ParsedEntry(
                guid=str(guid)[:500],
                title=entry_title[:500],
                url=link,
                author=html_to_text(e.get("author", ""))[:200] or None,
                published_at=_entry_time(e),
                content_html=clean_html(raw_content, link or base_url),
                excerpt=excerpt(text),
                image_url=full_reddit_images(image) if reddit else image,
                category=str((e.get("tags") or [{}])[0].get("term") or "")[:100] or None,
            )
        )
    return ParsedFeed(title=title[:200], site_url=site_url, icon_url=icon, entries=entries, is_feed=is_feed)


def find_feed_links(html_bytes: bytes, base_url: str) -> list[str]:
    soup = BeautifulSoup(html_bytes[:2_000_000], "html.parser")
    links = []
    for link in soup.find_all("link"):
        rel = link.get("rel") or []
        rel = [r.lower() for r in (rel if isinstance(rel, list) else [rel])]
        ltype = (link.get("type") or "").lower()
        href = link.get("href")
        if "alternate" in rel and href and any(t in ltype for t in ("rss", "atom", "feed+json", "xml")):
            links.append(urljoin(base_url, href))
    return links


# --------------------------------------------------------------------------- fetching


class RedditThrottle:
    """Keep at least `gap` seconds between requests to reddit.com."""

    def __init__(self, gap: float = 3.0) -> None:
        self.gap = gap
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delta = time.time() - self._last
            if delta < self.gap:
                time.sleep(self.gap - delta)
            self._last = time.time()


reddit_throttle = RedditThrottle()


class FetchError(Exception):
    def __init__(self, message: str, status: str = "error", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def discover_feed(url: str, settings: Settings) -> tuple[str, ParsedFeed]:
    """Return (feed_url, parsed feed) for a website or direct feed URL."""
    res = safe_get(url, allow_private=settings.allow_private_urls)
    if res.status >= 400:
        raise FetchError(f"{url} returned HTTP {res.status}")
    parsed = parse_feed(res.content, res.url)
    if parsed.is_feed and "html" not in res.content_type:
        return res.url, parsed
    for candidate in find_feed_links(res.content, res.url):
        try:
            validate_url(candidate, settings.allow_private_urls)
            res2 = safe_get(candidate, allow_private=settings.allow_private_urls)
        except Exception as exc:  # try the next candidate
            log.info("feed candidate %s failed: %s", candidate, exc)
            continue
        if res2.status < 400:
            p2 = parse_feed(res2.content, res2.url)
            if p2.is_feed:
                if not p2.site_url:
                    p2.site_url = res.url
                return res2.url, p2
    if parsed.is_feed and parsed.entries:  # a feed served with an HTML content type
        return res.url, parsed
    raise FetchError("No RSS or Atom feed found at that address")


def _fetch_reddit(name_or_url: str, settings: Settings, etag: str | None, modified: str | None, limit: int = 0):
    """Try www.reddit.com then old.reddit.com. Returns (FetchResult, used_url).

    `name_or_url` is a feed URL, a subreddit name or several names joined with '+'.
    """
    m = re.search(r"/r/([A-Za-z0-9_+]+)", name_or_url)
    name = m.group(1) if m else name_or_url
    headers = {"User-Agent": settings.reddit_user_agent}
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified
    last = None
    for host in REDDIT_HOSTS:
        url = reddit_feed_url(name, host) + (f"?limit={limit}" if limit else "")
        reddit_throttle.wait()
        res = safe_get(url, headers=headers, allow_private=settings.allow_private_urls)
        if res.status == 429:
            ra = res.headers.get("retry-after")
            retry = float(ra) if ra and ra.isdigit() else None
            raise FetchError("Reddit rate limit (429). Backing off.", "rate_limited", retry)
        if res.status == 403:
            last = res
            continue
        return res, url
    raise FetchError(
        f"Reddit refused the request (HTTP {last.status if last else 403}). It often blocks server IPs; "
        "it will be retried later.",
        "blocked",
    )


def _store_entries(
    conn: sqlite3.Connection, source: sqlite3.Row, entries: list[ParsedEntry], t0: float,
    etag: str | None = None, modified: str | None = None, icon: str | None = None, site: str | None = None,
) -> int:  # fmt: skip
    new = 0
    with tx(conn):
        for e in entries:
            cur = conn.execute(
                """INSERT OR IGNORE INTO items(source_id, guid, url, title, author, excerpt, content_html,
                   image_url, published_at, fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    source["id"], e.guid, e.url, e.title, e.author, e.excerpt, e.content_html,
                    e.image_url, e.published_at, t0,
                ),
            )  # fmt: skip
            new += cur.rowcount
        conn.execute(
            """UPDATE sources SET last_fetched=?, status='ok', last_error=NULL, error_count=0,
               backoff_until=NULL, etag=?, last_modified=?,
               icon_url=COALESCE(icon_url, ?), site_url=COALESCE(site_url, ?) WHERE id=?""",
            (t0, etag, modified, icon, site, source["id"]),
        )
    if new:
        log.info("source %s (%s): %d new items", source["id"], source["title"], new)
    return new


def _record_failure(conn: sqlite3.Connection, source: sqlite3.Row, exc: Exception, t0: float) -> None:
    status = getattr(exc, "status", "error")
    count = (source["error_count"] or 0) + 1
    retry_after = getattr(exc, "retry_after", None)
    if status == "rate_limited":
        delay = max(retry_after or 0, min(6 * 3600, 600 * 2 ** (count - 1)))
    elif status == "blocked":
        delay = min(12 * 3600, 1800 * 2 ** (count - 1))
    elif count >= 2:
        delay = min(6 * 3600, 1200 * 2 ** (count - 2))
    else:
        delay = 0
    msg = str(exc) or exc.__class__.__name__
    if not isinstance(exc, (FetchError, UnsafeURLError)):
        msg = f"{exc.__class__.__name__}: {msg}"
    conn.execute(
        "UPDATE sources SET last_fetched=?, status=?, last_error=?, error_count=?, backoff_until=? WHERE id=?",
        (t0, status, msg[:500], count, (t0 + delay) if delay else None, source["id"]),
    )
    log.warning("source %s (%s) fetch failed: %s", source["id"], source["title"], msg)


def fetch_source(conn: sqlite3.Connection, source: sqlite3.Row, settings: Settings) -> int:
    """Fetch one source's RSS feed and store new items. Returns count of new items."""
    t0 = now()
    if source["backoff_until"] and source["backoff_until"] > t0:
        return 0
    try:
        if source["kind"] == "reddit":
            res, used = _fetch_reddit(source["feed_url"], settings, source["etag"], source["last_modified"])
        else:
            headers = {}
            if source["etag"]:
                headers["If-None-Match"] = source["etag"]
            if source["last_modified"]:
                headers["If-Modified-Since"] = source["last_modified"]
            res = safe_get(source["feed_url"], headers=headers, allow_private=settings.allow_private_urls)
            used = source["feed_url"]
        if res.status == 304:
            conn.execute(
                "UPDATE sources SET last_fetched=?, status='ok', last_error=NULL, error_count=0, backoff_until=NULL WHERE id=?",
                (t0, source["id"]),
            )
            return 0
        if res.status == 429:
            raise FetchError("Rate limited (429)", "rate_limited")
        if res.status >= 400:
            raise FetchError(f"HTTP {res.status}")
        parsed = parse_feed(res.content, used, reddit=source["kind"] == "reddit")
        if not parsed.is_feed:
            raise FetchError("Response is not a valid RSS/Atom feed")
        return _store_entries(
            conn, source, parsed.entries, t0, res.headers.get("etag"), res.headers.get("last-modified"),
            parsed.icon_url, parsed.site_url,
        )  # fmt: skip
    except Exception as exc:
        _record_failure(conn, source, exc, t0)
        return 0


def subreddit_name(feed_url: str | None) -> str | None:
    m = re.search(r"/r/([A-Za-z0-9_]+)", feed_url or "")
    return m.group(1) if m else None


def fetch_reddit_batch(conn: sqlite3.Connection, sources: list[sqlite3.Row], settings: Settings) -> int:
    """Fetch several subreddits with one request (r/a+b+c/.rss) and split the posts by subreddit.

    Anonymous Reddit RSS allows only a few requests per minute, so this cuts the request count by the batch
    size. If the combined request fails for any reason other than a rate limit or a block (e.g. one of the
    subreddits was banned), each subreddit is fetched on its own instead.
    """
    t0 = now()
    by_name = {subreddit_name(s["feed_url"]).lower(): s for s in sources if subreddit_name(s["feed_url"])}
    if len(by_name) < 2:
        return sum(fetch_source(conn, s, settings) for s in sources)
    combined = "+".join(subreddit_name(s["feed_url"]) for s in by_name.values())
    try:
        res, used = _fetch_reddit(combined, settings, None, None, limit=REDDIT_BATCH_LIMIT)
        if res.status >= 400:
            raise FetchError(f"HTTP {res.status}")
        parsed = parse_feed(res.content, used, reddit=True)
        if not parsed.is_feed:
            raise FetchError("Response is not a valid RSS/Atom feed")
    except FetchError as exc:
        if exc.status in ("rate_limited", "blocked"):
            for s in by_name.values():
                _record_failure(conn, s, exc, t0)
            return 0
        log.info("combined Reddit fetch for %s failed (%s); fetching one by one", combined, exc)
        return sum(fetch_source(conn, s, settings) for s in by_name.values())
    except Exception as exc:
        log.info("combined Reddit fetch for %s failed (%s); fetching one by one", combined, exc)
        return sum(fetch_source(conn, s, settings) for s in by_name.values())
    groups: dict[str, list[ParsedEntry]] = {name: [] for name in by_name}
    for e in parsed.entries:
        # <category term="name"> names the subreddit; the post link (/r/name/comments/...) is the fallback.
        name = (e.category or "").lower()
        if name not in groups:
            name = (subreddit_name(e.url) or "").lower()
        if name in groups:
            groups[name].append(e)
    return sum(_store_entries(conn, by_name[name], entries, t0) for name, entries in groups.items())


def refresh_all(conn: sqlite3.Connection, settings: Settings, source_id: int | None = None) -> int:
    q = "SELECT * FROM sources WHERE enabled=1 AND rss_enabled=1 AND feed_url IS NOT NULL AND kind != 'demo'"
    args: tuple = ()
    if source_id is not None:
        q += " AND id=?"
        args = (source_id,)
    total = 0
    reddit: list[sqlite3.Row] = []
    t0 = now()
    for src in conn.execute(q + " ORDER BY id", args).fetchall():
        if src["kind"] == "reddit" and source_id is None and settings.reddit_batch_size > 1:
            if not (src["backoff_until"] and src["backoff_until"] > t0):
                reddit.append(src)
            continue
        total += fetch_source(conn, src, settings)
    size = settings.reddit_batch_size
    for i in range(0, len(reddit), size):
        total += fetch_reddit_batch(conn, reddit[i : i + size], settings)
    if settings.rss_retention_days > 0:
        prune_old_items(conn, settings.rss_retention_days)
    return total


def prune_old_items(conn: sqlite3.Connection, days: int) -> int:
    """Optional RSS retention. Items with comments or reactions, and user posts, are always kept."""
    cutoff = now() - days * 86400
    cur = conn.execute(
        """DELETE FROM items WHERE published_at < ?
           AND NOT EXISTS (SELECT 1 FROM comments c WHERE c.item_type='item' AND c.item_id=items.id)
           AND NOT EXISTS (SELECT 1 FROM reactions r WHERE r.item_type='item' AND r.item_id=items.id)
           AND source_id NOT IN (SELECT id FROM sources WHERE kind='user')""",
        (cutoff,),
    )
    return cur.rowcount
