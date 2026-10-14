"""Configuration loaded from environment variables (see .env.example)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw.strip() if raw and raw.strip() else default


@dataclass
class Settings:
    data_dir: Path = Path("/data")
    secret_key: str = ""
    cookie_secure: str = "auto"  # auto | true | false
    session_days: int = 30

    # Shorts
    max_height: int = 720
    shorts_per_channel: int = 15
    retention_days: float = 7
    keep_thumbnails: bool = True
    min_free_disk_mb: int = 2048
    hwaccel: str = "auto"  # auto | vaapi | none
    ytdlp_auto_update: bool = True

    # RSS
    rss_retention_days: int = 0  # 0 = keep forever
    rss_interval_min: int = 20
    shorts_interval_min: int = 120
    allow_private_urls: bool = False
    reddit_user_agent: str = ""  # effective value: reddit_user_agent_custom or built from reddit_username
    reddit_username: str = ""
    reddit_user_agent_custom: str = ""
    reddit_batch_size: int = 4

    # User posts
    upload_max_mb: float = 200

    # Personalization
    like_base: float = 1.25
    dislike_factor: float = 0.8
    reaction_halflife_days: float = 30
    min_weight: float = 0.1
    max_weight: float = 5.0
    explore_percent: float = 10
    boost_multiplier: float = 2.0
    foryou_halflife_hours: float = 24
    foryou_window_days: int = 21

    # Ask AI (OpenAI-compatible LLM server)
    llm_base_url: str = ""  # e.g. http://192.168.1.50:11434/v1
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout: float = 180
    llm_max_context_chars: int = 12000
    llm_fetch_article: bool = True

    # Misc
    scheduler_enabled: bool = True
    log_level: str = "INFO"
    base_url: str = ""

    extra: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "swipefeed.db"  # old project name, kept so existing installs keep their data

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.videos_dir, self.thumbs_dir, self.tmp_dir, self.data_dir / "uploads"):
            d.mkdir(parents=True, exist_ok=True)


def reddit_user_agent(username: str = "") -> str:
    """Reddit's requested format: <platform>:<app id>:<version> (by /u/<username>)."""
    from app import __version__

    username = username.strip().removeprefix("/u/").removeprefix("u/")
    by = f"by /u/{username}" if username else "self-hosted RSS reader"
    return f"linux:localds:{__version__} ({by})"


def load_settings() -> Settings:

    s = Settings(
        data_dir=Path(_str("DATA_DIR", "/data")),
        secret_key=_str("SECRET_KEY", ""),
        cookie_secure=_str("COOKIE_SECURE", "auto").lower(),
        session_days=_int("SESSION_DAYS", 30),
        max_height=_int("MAX_HEIGHT", 720),
        shorts_per_channel=_int("SHORTS_PER_CHANNEL", 15),
        retention_days=_float("RETENTION_DAYS", 7),
        keep_thumbnails=_bool("KEEP_THUMBNAILS", True),
        min_free_disk_mb=_int("MIN_FREE_DISK_MB", 2048),
        hwaccel=_str("HWACCEL", "auto").lower(),
        ytdlp_auto_update=_bool("YTDLP_AUTO_UPDATE", True),
        rss_retention_days=_int("RSS_RETENTION_DAYS", 0),
        rss_interval_min=_int("RSS_INTERVAL_MIN", 20),
        shorts_interval_min=_int("SHORTS_INTERVAL_MIN", 120),
        allow_private_urls=_bool("ALLOW_PRIVATE_URLS", False),
        reddit_user_agent=_str("REDDIT_USER_AGENT", "") or reddit_user_agent(_str("REDDIT_USERNAME", "")),
        reddit_username=_str("REDDIT_USERNAME", ""),
        reddit_user_agent_custom=_str("REDDIT_USER_AGENT", ""),
        reddit_batch_size=max(1, min(_int("REDDIT_BATCH_SIZE", 4), 25)),
        upload_max_mb=_float("UPLOAD_MAX_MB", 200),
        like_base=_float("LIKE_BASE", 1.25),
        dislike_factor=_float("DISLIKE_FACTOR", 0.8),
        reaction_halflife_days=_float("REACTION_HALFLIFE_DAYS", 30),
        min_weight=_float("MIN_WEIGHT", 0.1),
        max_weight=_float("MAX_WEIGHT", 5.0),
        explore_percent=_float("EXPLORE_PERCENT", 10),
        boost_multiplier=_float("BOOST_MULTIPLIER", 2.0),
        foryou_halflife_hours=_float("FORYOU_HALFLIFE_HOURS", 24),
        foryou_window_days=_int("FORYOU_WINDOW_DAYS", 21),
        llm_base_url=_str("LLM_BASE_URL", ""),
        llm_model=_str("LLM_MODEL", ""),
        llm_api_key=_str("LLM_API_KEY", ""),
        llm_timeout=_float("LLM_TIMEOUT", 180),
        llm_max_context_chars=_int("LLM_MAX_CONTEXT_CHARS", 12000),
        llm_fetch_article=_bool("LLM_FETCH_ARTICLE", True),
        scheduler_enabled=_bool("SCHEDULER_ENABLED", True),
        log_level=_str("LOG_LEVEL", "INFO").upper(),
        base_url=_str("BASE_URL", ""),
    )
    if not s.secret_key or s.secret_key == "change-me":  # noqa: S105 - placeholder from .env.example
        # Persist a generated key in /data so sessions survive restarts.
        s.ensure_dirs()
        key_file = s.data_dir / ".secret_key"
        if key_file.exists():
            s.secret_key = key_file.read_text().strip()
        else:
            s.secret_key = secrets.token_urlsafe(48)
            key_file.write_text(s.secret_key)
            key_file.chmod(0o600)
    return s
