"""Admin-editable settings.

`.env` gives the base values. The admin page can override most of them; overrides are stored as JSON in the
kv table (`settings_overrides`) and applied over the base values at startup and immediately on save, on the one
shared Settings object. Removing an override goes back to the `.env` (or built-in default) value.

Not editable here (they need a restart or are infrastructure): DATA_DIR, SECRET_KEY, SCHEDULER_ENABLED.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.config import Settings, reddit_user_agent
from app.db import kv_get, kv_set

KV_KEY = "settings_overrides"


@dataclass(frozen=True)
class Spec:
    key: str
    kind: str  # int | float | bool | str | choice | url | secret
    group: str
    label: str
    help: str = ""
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = ()


GROUPS = {
    "reddit": "Reddit & feeds",
    "shorts": "Shorts & storage",
    "personalization": "Personalization",
    "ai": "Ask AI",
    "general": "General",
}

SPECS = [
    Spec("reddit_username", "str", "reddit", "Reddit username",
         "Your Reddit username (without /u/). Reddit asks clients to name a contact in the User-Agent; "
         "it makes blocking less likely. No login or password is used."),
    Spec("reddit_user_agent_custom", "str", "reddit", "Custom User-Agent",
         "Advanced. Leave empty to build one from the username."),
    Spec("reddit_batch_size", "int", "reddit", "Subreddits per request",
         "Subreddits fetched together in one request (fewer requests, less rate limiting).", 1, 25),
    Spec("rss_interval_min", "int", "reddit", "Feed refresh interval (minutes)", "", 5, 1440),
    Spec("rss_retention_days", "int", "reddit", "Keep feed posts (days)",
         "0 = forever. Posts with comments or reactions and your own posts are always kept.", 0, 3650),
    Spec("allow_private_urls", "bool", "reddit", "Allow private / LAN feed URLs",
         "Lets sources point at addresses inside your network. Off is safer."),
    Spec("shorts_interval_min", "int", "shorts", "Shorts check interval (minutes)", "", 15, 1440),
    Spec("shorts_per_channel", "int", "shorts", "Shorts per channel", "Newest Shorts checked per channel.", 1, 100),
    Spec("max_height", "choice", "shorts", "Max video height", "", choices=("360", "480", "720", "1080")),
    Spec("retention_days", "float", "shorts", "Keep video files (days)",
         "Comments, reactions and the Short itself are kept forever; only the file expires.", 0.5, 365),
    Spec("keep_thumbnails", "bool", "shorts", "Keep thumbnails of expired Shorts"),
    Spec("min_free_disk_mb", "int", "shorts", "Minimum free disk (MB)",
         "Downloads pause below this.", 0, 1_000_000),
    Spec("hwaccel", "choice", "shorts", "Hardware encoding", "auto uses VAAPI when /dev/dri is available.",
         choices=("auto", "vaapi", "none")),
    Spec("ytdlp_auto_update", "bool", "shorts", "Update yt-dlp daily"),
    Spec("like_base", "float", "personalization", "Like strength",
         "weight = this ^ score. Higher = likes matter more.", 1.01, 3),
    Spec("dislike_factor", "float", "personalization", "Dislike factor", "A dislike counts as -this.", 0, 5),
    Spec("reaction_halflife_days", "float", "personalization", "Reaction half-life (days)", "", 1, 3650),
    Spec("min_weight", "float", "personalization", "Min source weight", "", 0.01, 1),
    Spec("max_weight", "float", "personalization", "Max source weight", "", 1, 100),
    Spec("boost_multiplier", "float", "personalization", "Boost multiplier", "", 1, 10),
    Spec("explore_percent", "float", "personalization", "Exploration (%)",
         "Share of random picks so new things still show up.", 0, 50),
    Spec("foryou_halflife_hours", "float", "personalization", "For you: freshness half-life (hours)", "", 1, 720),
    Spec("foryou_window_days", "int", "personalization", "For you: look back (days)", "", 1, 365),
    Spec("llm_base_url", "url", "ai", "LLM server URL",
         "OpenAI-compatible base URL, e.g. http://192.168.1.50:11434/v1 (Ollama, llama.cpp, LM Studio, vLLM)."),
    Spec("llm_model", "str", "ai", "Model"),
    Spec("llm_api_key", "secret", "ai", "API key", "Only if your server needs one. Never shown again."),
    Spec("llm_timeout", "float", "ai", "Timeout (seconds)", "", 5, 1800),
    Spec("llm_max_context_chars", "int", "ai", "Max context (characters)", "", 1000, 200_000),
    Spec("llm_fetch_article", "bool", "ai", "Read the linked article"),
    Spec("upload_max_mb", "float", "general", "Max file size for posts (MB)",
         "Per photo/video/file attached to a post. Behind a Cloudflare Tunnel keep it under 100.", 1, 4096),
    Spec("base_url", "url", "general", "Public base URL",
         "Used in invite links, e.g. https://ds.your-tailnet.ts.net. Empty = the address you opened."),
    Spec("session_days", "int", "general", "Stay logged in (days)", "Applies to new logins.", 1, 365),
    Spec("cookie_secure", "choice", "general", "Secure cookies", "auto = only over HTTPS.",
         choices=("auto", "true", "false")),
    Spec("log_level", "choice", "general", "Log level", "", choices=("DEBUG", "INFO", "WARNING", "ERROR")),
]  # fmt: skip
SPEC_BY_KEY = {sp.key: sp for sp in SPECS}


def _base(s: Settings) -> dict[str, Any]:
    """The .env/default values, captured once before any override is applied."""
    if "env" not in s.extra:
        s.extra["env"] = {sp.key: getattr(s, sp.key) for sp in SPECS}
    return s.extra["env"]


def load_overrides(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        data = json.loads(kv_get(conn, KV_KEY) or "{}")
    except ValueError:
        return {}
    return {k: v for k, v in data.items() if k in SPEC_BY_KEY} if isinstance(data, dict) else {}


def validate(key: str, value: Any) -> Any:
    sp = SPEC_BY_KEY.get(key)
    if sp is None:
        raise ValueError(f"Unknown setting: {key}")
    if sp.kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{sp.label}: expected on/off")
        return value
    if sp.kind in ("int", "float"):
        if isinstance(value, bool):
            raise ValueError(f"{sp.label}: expected a number")
        try:
            num = int(value) if sp.kind == "int" else float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{sp.label}: expected a number") from None
        if sp.kind == "int" and isinstance(value, float) and not value.is_integer():
            raise ValueError(f"{sp.label}: expected a whole number")
        if (sp.min is not None and num < sp.min) or (sp.max is not None and num > sp.max):
            raise ValueError(f"{sp.label}: must be between {sp.min:g} and {sp.max:g}")
        return num
    if not isinstance(value, str | int | float) or isinstance(value, bool):
        raise ValueError(f"{sp.label}: expected text")
    text = str(value).strip()
    if len(text) > 300:
        raise ValueError(f"{sp.label}: too long")
    if sp.kind == "choice":
        if text not in sp.choices:
            raise ValueError(f"{sp.label}: choose one of {', '.join(sp.choices)}")
        return int(text) if key == "max_height" else text
    if sp.kind == "url" and text:
        parts = urlsplit(text)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"{sp.label}: must start with http:// or https://")
        text = text.rstrip("/")
    if key == "reddit_username":
        text = text.removeprefix("/u/").removeprefix("u/")
        if text and not all(c.isalnum() or c in "-_" for c in text):
            raise ValueError("Reddit username: letters, digits, - and _ only")
    return text


def apply(s: Settings, overrides: dict[str, Any]) -> None:
    base = _base(s)
    for sp in SPECS:
        setattr(s, sp.key, overrides.get(sp.key, base[sp.key]))
    s.reddit_user_agent = s.reddit_user_agent_custom or reddit_user_agent(s.reddit_username)
    logging.getLogger().setLevel(getattr(logging, s.log_level, logging.INFO))


def init(s: Settings, conn: sqlite3.Connection) -> None:
    """Apply stored overrides at startup. Bad stored values are skipped, never fatal."""
    clean = {}
    for key, value in load_overrides(conn).items():
        try:
            clean[key] = validate(key, value)
        except ValueError:
            logging.getLogger(__name__).warning("ignoring invalid stored setting %s", key)
    apply(s, clean)


def update(s: Settings, conn: sqlite3.Connection, changes: dict[str, Any]) -> list[str]:
    """Validate and save `changes` ({key: value, or None to go back to .env}). Returns the changed keys."""
    overrides = load_overrides(conn)
    for key, value in changes.items():
        if value is None:
            if key not in SPEC_BY_KEY:
                raise ValueError(f"Unknown setting: {key}")
            overrides.pop(key, None)
        else:
            overrides[key] = validate(key, value)
    base = _base(s)
    lo = overrides.get("min_weight", base["min_weight"])
    hi = overrides.get("max_weight", base["max_weight"])
    if lo >= hi:
        raise ValueError("Min source weight must be lower than max source weight")
    before = {sp.key: getattr(s, sp.key) for sp in SPECS}
    kv_set(conn, KV_KEY, json.dumps(overrides))
    apply(s, overrides)
    return [k for k, v in before.items() if getattr(s, k) != v]


def describe(s: Settings, conn: sqlite3.Connection) -> dict:
    base = _base(s)
    overrides = load_overrides(conn)
    fields = []
    for sp in SPECS:
        secret = sp.kind == "secret"
        value = getattr(s, sp.key)
        fields.append(
            {
                "key": sp.key,
                "kind": sp.kind,
                "group": sp.group,
                "label": sp.label,
                "help": sp.help,
                "min": sp.min,
                "max": sp.max,
                "choices": list(sp.choices),
                "value": ("" if secret else str(value) if sp.kind == "choice" else value),
                "is_set": bool(value) if secret else None,
                "default": (bool(base[sp.key]) if secret else base[sp.key]),
                "overridden": sp.key in overrides,
            }
        )
    return {"groups": GROUPS, "fields": fields, "reddit_user_agent": s.reddit_user_agent}
