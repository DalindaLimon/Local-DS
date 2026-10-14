"""'Ask AI' about a post or Short using an OpenAI-compatible LLM server (Ollama, llama.cpp, LM Studio, vLLM, ...).

The server is configured by the admin in .env (LLM_BASE_URL, LLM_MODEL, LLM_API_KEY). It is usually on the LAN,
so it is called directly with httpx rather than through urlsafe.safe_get (which only allows public addresses).
The *article* a post links to is user-supplied content, so fetching it does go through safe_get.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from app.config import Settings
from app.sanitize import html_to_text
from app.urlsafe import safe_get

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You help the user understand a post from their personal news feed.
Rules:
- Be accurate. Never invent facts, numbers, quotes, names or sources. If you are not sure, say so plainly.
- Keep two things apart: what the post claims, and what is well established. Say which is which.
- You cannot browse the web. Your knowledge has a cutoff date, so recent events may be unknown to you; say so when
  it matters instead of guessing.
- If the provided text is only an excerpt, say that your answer is limited by it.
- Answer in the language of the user's question. Be concise. Use plain text; use "- " for lists. No markdown
  headings, tables or bold."""

MODES = {
    "summary": "Summarize this post in a few short bullet points, then one line on why it might matter.",
    "factcheck": (
        "Fact-check this post. List its main claims. For each one say: consistent with well-established "
        "knowledge, disputed/uncertain, or likely false, and explain briefly why. Point out missing context, "
        "loaded wording or signs of clickbait. End with what the reader should verify elsewhere and where."
    ),
    "explain": "Explain the background and context someone needs to understand this post. Keep it simple.",
}

ARTICLE_SKIP_HOSTS = ("reddit.com", "redd.it", "youtube.com", "youtu.be")
STRIP_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "iframe"]


class AIError(Exception):
    pass


def configured(s: Settings) -> bool:
    return bool(s.llm_base_url and s.llm_model)


def _endpoint(s: Settings, path: str) -> str:
    return s.llm_base_url.rstrip("/") + path


def _headers(s: Settings) -> dict:
    h = {"Content-Type": "application/json"}
    if s.llm_api_key:
        h["Authorization"] = f"Bearer {s.llm_api_key}"
    return h


# --------------------------------------------------------------------------- context


def article_text(url: str, s: Settings, limit: int) -> str:
    """Readable text of a linked web page, or '' if it can't be fetched. Goes through safe_get (SSRF rules)."""
    host = (urlsplit(url).hostname or "").lower()
    if not host or any(host == h or host.endswith("." + h) for h in ARTICLE_SKIP_HOSTS):
        return ""
    try:
        res = safe_get(url, timeout=10, max_bytes=3 * 1024 * 1024, allow_private=s.allow_private_urls)
    except Exception as exc:
        log.info("ask ai: could not fetch %s: %s", url, exc)
        return ""
    if res.status >= 400 or "html" not in res.content_type:
        return ""
    soup = BeautifulSoup(res.content, "html.parser")
    for tag in soup(STRIP_TAGS):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    paras = [p.get_text(" ", strip=True) for p in main.find_all(["p", "li", "h2", "h3", "blockquote"])]
    text = "\n".join(p for p in paras if len(p) > 30) or main.get_text(" ", strip=True)
    return text[:limit]


def item_context(conn: sqlite3.Connection, s: Settings, item_type: str, item_id: int) -> dict | None:
    """Everything the model gets to see about one post or Short."""
    if item_type == "item":
        row = conn.execute(
            """SELECT i.title, i.url, i.author, i.excerpt, i.content_html, i.published_at,
                      s.title AS source, s.kind AS kind
               FROM items i JOIN sources s ON s.id=i.source_id WHERE i.id=?""",
            (item_id,),
        ).fetchone()
        if not row:
            return None
        text = html_to_text(row["content_html"]) or row["excerpt"] or ""
        return {
            "kind": "user post" if row["kind"] == "user" else f"{row['kind']} post",
            "title": row["title"],
            "source": row["source"],
            "author": row["author"],
            "url": row["url"],
            "published": row["published_at"],
            "text": text,
        }
    row = conn.execute("SELECT title, channel_name, url, published_at FROM shorts WHERE id=?", (item_id,)).fetchone()
    if not row:
        return None
    return {
        "kind": "YouTube Short (only the title is available, not the video content)",
        "title": row["title"],
        "source": row["channel_name"],
        "author": None,
        "url": row["url"],
        "published": row["published_at"],
        "text": "",
    }


def build_messages(ctx: dict, mode: str, question: str, s: Settings, article: str = "") -> list[dict]:
    limit = s.llm_max_context_chars
    text = (ctx.get("text") or "")[:limit]
    lines = [
        f"Type: {ctx['kind']}",
        f"Title: {ctx['title']}",
        f"Source: {ctx['source']}",
    ]
    if ctx.get("author"):
        lines.append(f"Author: {ctx['author']}")
    if ctx.get("published"):
        lines.append("Published: " + time.strftime("%Y-%m-%d", time.gmtime(ctx["published"])))
    if ctx.get("url"):
        lines.append(f"Link: {ctx['url']}")
    lines.append(f"Today: {time.strftime('%Y-%m-%d')}")
    if text:
        lines += ["", "Post text (may be an excerpt):", text]
    if article:
        lines += ["", "Text of the linked page:", article[: max(0, limit - len(text))]]
    if not text and not article:
        lines += ["", "(No text is available beyond the title.)"]
    task = MODES.get(mode) or question.strip()
    if mode in MODES and question.strip():
        task += "\nAlso answer this: " + question.strip()
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines) + "\n\nTask: " + task},
    ]


# --------------------------------------------------------------------------- LLM calls


def parse_sse_line(line: str) -> str | None:
    """Text delta from one 'data: {...}' line of an OpenAI-style stream. None for [DONE]/keepalives."""
    line = line.strip()
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return None
    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return None
    choices = obj.get("choices") or []
    if not choices:
        return None
    delta = choices[0].get("delta") or choices[0].get("message") or {}
    return delta.get("content") or None


async def stream_chat(s: Settings, messages: list[dict]) -> AsyncIterator[str]:
    """Yield the answer text as it is generated."""
    payload = {"model": s.llm_model, "messages": messages, "stream": True, "temperature": 0.2}
    timeout = httpx.Timeout(s.llm_timeout, connect=10)
    try:
        async with (
            httpx.AsyncClient(timeout=timeout) as client,
            client.stream("POST", _endpoint(s, "/chat/completions"), json=payload, headers=_headers(s)) as res,
        ):
            if res.status_code >= 400:
                body = (await res.aread()).decode(errors="replace")[:300]
                raise AIError(f"LLM server answered HTTP {res.status_code}: {body}")
            async for line in res.aiter_lines():
                chunk = parse_sse_line(line)
                if chunk:
                    yield chunk
    except httpx.TimeoutException as exc:
        raise AIError(f"The LLM server did not answer within {s.llm_timeout:.0f} s") from exc
    except httpx.HTTPError as exc:
        raise AIError(f"Could not reach the LLM server: {exc.__class__.__name__}: {exc}") from exc


def list_models(s: Settings) -> list[str]:
    """Model ids the server offers (GET /models). Used by the admin connection test."""
    try:
        res = httpx.get(_endpoint(s, "/models"), headers=_headers(s), timeout=10)
    except httpx.HTTPError as exc:
        raise AIError(f"Could not reach the LLM server: {exc.__class__.__name__}: {exc}") from exc
    if res.status_code >= 400:
        raise AIError(f"LLM server answered HTTP {res.status_code}: {res.text[:300]}")
    try:
        return [m.get("id", "") for m in res.json().get("data", []) if m.get("id")]
    except (ValueError, AttributeError) as exc:
        raise AIError("The LLM server's /models answer is not OpenAI-compatible JSON") from exc
