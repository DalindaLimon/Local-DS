"""Turn untrusted feed HTML into a small, safe subset for the reader view."""

from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

ALLOWED_TAGS = {
    "p", "br", "a", "ul", "ol", "li", "blockquote", "pre", "code", "em", "strong",
    "b", "i", "h1", "h2", "h3", "h4", "h5", "h6", "img", "figure", "figcaption", "hr",
}  # fmt: skip
DROP_WITH_CONTENT = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "form",
    "noscript",
    "svg",
    "template",
    "head",
    "title",
}
HEADING_DOWN = {"h1": "h3", "h2": "h3"}

# Reddit feeds only carry signed 140/640 px previews. Images uploaded to Reddit have the full-size original at
# i.redd.it/<same name>. GIFs are skipped (the original can be huge); external-preview.redd.it has no original.
REDDIT_PREVIEW_RE = re.compile(r"https://preview\.redd\.it/([A-Za-z0-9_-]+\.(?:jpe?g|png|webp))(?:\?[^\"'\s<>]*)?")


def full_reddit_images(text: str | None) -> str | None:
    """Rewrite preview.redd.it image URLs (in a URL or an HTML string) to the full-size i.redd.it original."""
    return REDDIT_PREVIEW_RE.sub(r"https://i.redd.it/\1", text) if text else text


def _safe_href(value: str | None, base: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if base:
        value = urljoin(base, value)
    scheme = urlsplit(value).scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    return value


def _render(node, base: str | None, out: list[str]) -> None:
    for child in node.children:
        if isinstance(child, NavigableString):
            if child.__class__.__name__ in {"Comment", "Doctype", "CData", "ProcessingInstruction"}:
                continue
            out.append(html.escape(str(child), quote=False))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        if name in DROP_WITH_CONTENT:
            continue
        if name not in ALLOWED_TAGS:
            if name in {"div", "section", "article", "table", "tr", "td", "th", "tbody"}:
                inner: list[str] = []
                _render(child, base, inner)
                text = "".join(inner).strip()
                if text:
                    out.append(f"<p>{text}</p>" if name in {"div", "section", "article"} else text + " ")
            else:
                _render(child, base, out)
            continue
        name = HEADING_DOWN.get(name, name)
        if name == "img":
            src = _safe_href(child.get("src"), base)
            if src:
                alt = html.escape(child.get("alt", "")[:200])
                out.append(f'<img src="{html.escape(src)}" alt="{alt}" loading="lazy" referrerpolicy="no-referrer">')
            continue
        if name in {"br", "hr"}:
            out.append(f"<{name}>")
            continue
        if name == "a":
            href = _safe_href(child.get("href"), base)
            inner = []
            _render(child, base, inner)
            if href:
                out.append(
                    f'<a href="{html.escape(href)}" target="_blank" rel="noopener noreferrer nofollow">{"".join(inner)}</a>'
                )
            else:
                out.append("".join(inner))
            continue
        out.append(f"<{name}>")
        _render(child, base, out)
        out.append(f"</{name}>")


def clean_html(raw: str | None, base: str | None = None, max_len: int = 200_000) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw[:max_len], "html.parser")
    out: list[str] = []
    _render(soup, base, out)
    result = "".join(out)
    result = re.sub(r"(<p>\s*</p>)+", "", result)
    return result.strip()


def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(list(DROP_WITH_CONTENT)):
        t.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def first_image(raw: str | None, base: str | None = None) -> str | None:
    if not raw:
        return None
    soup = BeautifulSoup(raw, "html.parser")
    for img in soup.find_all("img"):
        src = _safe_href(img.get("src"), base)
        if not src:
            continue
        w = img.get("width")
        if w and str(w).isdigit() and int(w) < 40:
            continue  # tracking pixels
        return src
    return None


def excerpt(text: str, limit: int = 320) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "…"
