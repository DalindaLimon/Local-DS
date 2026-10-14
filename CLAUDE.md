# CLAUDE.md

Context for Claude Code working in this repository.

## What this is

Local DS (short for doomscroll; Docker image/container/service `localds`, repo `local-ds`; only the database file
keeps its old name `swipefeed.db` so existing data loads): a private, self-hosted, mobile-first web app for two users (owner + one friend).

- **Feed tab**: Reddit-style infinite card list from RSS/Atom, subreddits and YouTube channel feeds.
- **Reels tab**: TikTok-style vertical swipe feed of YouTube Shorts downloaded locally with yt-dlp.
- Likes/dislikes/comments on everything; likes and dislikes set **per-user** source weights.
- User posts, Your activity (search, filters, sort, per-user priority list), per-user theme/color/layout.
- Ask AI: any OpenAI-compatible LLM server (`LLM_BASE_URL`, `LLM_MODEL`) summarizes/fact-checks/answers about an item.
- Video files expire after `RETENTION_DAYS`; records, comments and reactions are kept forever.

Target deployment: Docker on a small home server, e.g. inside an unprivileged Debian 12 LXC on Proxmox, ideally
with an Intel iGPU for VAAPI. Remote access through Tailscale (preferred) or a Cloudflare Tunnel; never
port-forwarded. Personal machine details live in `CLAUDE.local.md` (gitignored); keep them out of tracked files.

Version: 0.5.1 (`app/__init__.py`). Published to GitHub; images built to ghcr.io on `v*` tags.

## Stack and hard constraints

- Python 3.12+, FastAPI, SQLite (WAL), APScheduler in-process, single uvicorn worker.
- Frontend: plain ES module JavaScript + CSS in `app/static/`, **no npm, no build step**. PWA (manifest + service worker caching the shell only).
- One container, all state in `/data` (db, videos, thumbs, tmp, demo, `.secret_key`).
- yt-dlp + ffmpeg in the image; yt-dlp self-updates daily via pip into the app-owned venv.
- Keep dependencies minimal. New Python packages need a good reason.

## Layout

```
app/
  __init__.py        __version__
  config.py          Settings dataclass from env (load_settings); see .env.example
  settings_store.py  admin-page overrides (kv `settings_overrides`) applied live over .env values; SPECS list
  db.py              schema (SCHEMA), connect(), init_db() + ADDED_COLUMNS migrations, tx() (BEGIN IMMEDIATE), kv store
  security.py        argon2, sessions (hashed tokens), CSRF double-submit, LoginRateLimiter
  urlsafe.py         SSRF protection: validate_url(), safe_get() (re-validates every redirect, size cap)
  sanitize.py        allowlist HTML sanitizer for feed content (BeautifulSoup)
  feeds.py           classify_input(), parse_feed(), discover_feed(), fetch_source() with Reddit 429/403 backoff
  sources.py         add_source(): reddit / youtube (resolve via yt-dlp) / url (autodiscovery)
  uploads.py         post attachments: raw-body upload, /data/uploads, inline only for verified media types
  shorts.py          yt-dlp listing/downloading, transcode (remux, VAAPI, libx264), thumbnails, yt-dlp update
  retention.py       cleanup() (expire old video files), reconcile() (disk vs db, both directions), disk_usage()
  personalization.py score/weight math, react(), weighted_shuffle(), mix_exploration(), why_line()
  discovery.py       curated STARTER list, topic affinity, suggested(), search_reddit()
  ai.py              Ask AI: item_context(), article_text() (via safe_get), build_messages(), stream_chat()
  api_ai.py          POST /api/ai/ask (plain-text stream), POST /api/admin/ai/test
  locks.py           FileGuard: files being downloaded/streamed (+180 s grace) are never deleted
  jobs.py            APScheduler wiring + one-off background jobs (ThreadPoolExecutor)
  deps.py            FastAPI dependencies (get_db per request, current_user, admin_user)
  api_auth.py        /api/state, setup, login, logout, invites/register, password, prefs
  api_feed.py        /api/feed (latest + foryou), items, seen, reels, past shorts, react, comments, /media/*
  api_sources.py     /api/sources*, /api/discover/*, /api/admin/*
  main.py            create_app() factory, CSRF + security-header middleware, static routes, /healthz
  seed.py            demo data: python -m app.seed [--users] [--remove] [--no-videos]
  static/            index.html, app.css, app.js, sw.js, manifest.webmanifest, icons/
tests/               pytest suite (conftest has Client with auto CSRF, make_user/source/item/short, login)
scripts/             backup.sh, restore.sh, proxmox-create-lxc.sh (optional), screenshots.py, make_icons.py
docker/entrypoint.sh fixes /data ownership, joins /dev/dri render group, drops to uid 1000, runs uvicorn
install.sh           idempotent installer for a Debian 12 LXC (--update, --uninstall [--purge], --demo, --yes)
docs/              full docs: README (index) USER_GUIDE INSTALL REMOTE_ACCESS OPERATIONS AI CONFIGURATION
                   TROUBLESHOOTING ARCHITECTURE DATABASE API PERSONALIZATION FEEDS_AND_SHORTS FRONTEND DEVELOPMENT
```

## Commands

```bash
# dev setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt          # needs ffmpeg on PATH for the pipeline tests
export DATA_DIR=./data SCHEDULER_ENABLED=false
python -m app.seed --users                   # demo/demo-password (admin), friend/friend-password
uvicorn --factory app.main:create_app --reload --host 0.0.0.0 --port 8080

# checks (CI runs exactly these; run them before every commit)
ruff check . && ruff format --check .
pytest -q
shellcheck install.sh docker/entrypoint.sh scripts/*.sh
node --check app/static/app.js && node --check app/static/sw.js

# UI check at 360/390/430 px (overflow, small tap targets, JS errors) + README screenshots
pip install playwright && playwright install chromium
python scripts/screenshots.py http://localhost:8080 demo demo-password

# docker
docker compose up -d --build
docker compose exec -u 1000:1000 localds python -m app.seed --users   # always -u 1000:1000, never root
```

The app is created by a factory: always `uvicorn --factory app.main:create_app`. There is no module-level `app`.

## Invariants (do not break; tests cover most of them)

- **Never auto-delete comments, reactions, or Short rows.** Cleanup only deletes video (and preview) files,
  sets `status='expired'`, clears `file_path`. Thumbnails are kept unless `KEEP_THUMBNAILS=false`.
- **Never re-download a known video ID** (including expired). `INSERT OR IGNORE` on `shorts.video_id`.
- **No `available` row without a file**; `reconcile()` runs on startup and fixes both directions.
- Cleanup must skip files in `locks.guard` (downloading, streaming, recently streamed).
- Downloading ignores weights; weights only affect ordering.
- Weights are **per user**. Reactions are stored as rows and weights are always recomputable from them.
  Reset sets `reset_at` (older reactions ignored) instead of deleting anything.
- A dislike never hides anything: it only lowers that source's weight for that user (mute is the way to hide).
- User posts are items in a per-user `kind='user'` source; RSS retention never prunes them.
- Deleting a source keeps items that have comments/reactions (source archived as `status='removed'`).
- Every fetch of a user-supplied URL goes through `urlsafe.safe_get` / `validate_url`.
- Uploaded files are served from `/media/upload/` with `Content-Security-Policy: sandbox`; only media types in
  `uploads.INLINE` (images verified by magic bytes) are inline, everything else is a download.
- No personal data (names, emails, hostnames, IPs, hardware) in tracked files; it belongs in `.env`
  or `CLAUDE.local.md`. Examples use placeholders like `192.168.1.50` or `your-tailnet`.
- Frontend: user/feed text goes in with `textContent` (the `h()` helper does this). Only server-sanitized
  `content_html` uses `innerHTML`. Keep the strict CSP in `main.py` (no inline scripts).
- All unsafe `/api/*` requests need the `X-CSRF-Token` header matching the `sf_csrf` cookie.
- Ask AI answers are rendered as plain text (`textContent`). The LLM server URL comes from `.env` or the admin
  Settings page (admin-trusted) and is called directly with httpx; the linked *article* is user content and goes through `safe_get`.
- When code changes, update the matching page in `docs/` (and CHANGELOG). Note: `ruff format` also reformats
  Python code blocks inside Markdown, so keep those examples valid Python.
- Mobile rules: `100dvh`, safe-area insets, inputs >= 16px, tap targets >= 44px, no horizontal scroll.
  Reels: scroll-snap y mandatory, only current + next video get a `src`, muted autoplay, `playsinline`.

## Personalization math (keep README section 5 in sync if this changes)

```
score  = Σ (+1 like | −DISLIKE_FACTOR dislike) × 0.5^(age_days / REACTION_HALFLIFE_DAYS)   (after reset_at)
weight = clamp(LIKE_BASE^score, MIN_WEIGHT, MAX_WEIGHT); boost ×BOOST_MULTIPLIER; mute → MIN_WEIGHT + hidden
reels  = unseen first, weighted shuffle key = random()^(1/weight), then seen; reshuffle at the end
foryou = weight × 0.5^(age_hours / FORYOU_HALFLIFE_HOURS); order cached per (user, snapshot, seed, source)
explore: ~EXPLORE_PERCENT of slots are uniform random picks (mix_exploration)
```

Defaults: LIKE_BASE 1.25, DISLIKE_FACTOR 0.8, halflife 30 d, weights 0.1–5.0, explore 10 %.

## Conventions

- SQLite connections are autocommit (`isolation_level=None`); group writes with `with tx(conn):`.
- Times are Unix epoch floats (`db.now()`).
- Read settings from the shared `Settings` object at call time (never copy them into module globals): admin
  overrides change it live. New user-tunable settings go into `settings_store.SPECS` too.
- Ruff config in `pyproject.toml` (line length 120, formatter is the source of truth).
- Tests use `Settings(data_dir=tmp_path/...)` + `create_app(settings)`; mock network via monkeypatching
  `feeds.safe_get`, `shorts.list_channel_shorts`, `shorts.download_short`, or `shorts.ytdlp_base`.
- Bump the `?v=` query on app.css/app.js in `index.html` and `VERSION` in `sw.js` when shipping frontend changes,
  so installed PWAs pick them up.
- Update `CHANGELOG.md` for user-visible changes; bump `__version__` and tag `vX.Y.Z` for releases.
- Commit messages: short imperative subject, explain why in the body when not obvious.

## Status and known gaps

Verified in the build sandbox: 115 tests pass, ruff/shellcheck clean, UI checked in headless Chromium at
360/390/430 px and 1280 px (dark + light), download pipeline tested with a fake yt-dlp + real ffmpeg.

**Not yet verified (sandbox had no Docker Hub / internet access):**
- `docker build` and the container start (CI `docker-build` job does this on GitHub; check it first).
- Real YouTube, Reddit and RSS fetching end to end.
- VAAPI encoding on a real Intel iGPU (falls back to libx264 automatically).
- `install.sh` and `scripts/proxmox-create-lxc.sh` on a real Proxmox host.
- iOS Safari / installed PWA behaviour on a real phone.

Repository: https://github.com/DalindaLimon/local-ds (public). Image: `ghcr.io/dalindalimon/local-ds` on `v*` tags.
Run the app from this folder only; `.env`, `data/` and `CLAUDE.local.md` are gitignored and must never be committed.

## Ideas / possible next steps

- Reddit OAuth (app-only) as a fallback when anonymous RSS is blocked.
- Short preview clips (`shorts.preview_path` exists in the schema, unused so far).
- Per-user notification of new comments from the other user.
- Import/export of sources as OPML.
