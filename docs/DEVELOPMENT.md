# Development

Everything you need to change Local DS safely by hand: setting up, running, testing, the code conventions, and
step-by-step recipes for the most common kinds of change.

- [Set up](#set-up)
- [Run it](#run-it)
- [Checks (what CI runs)](#checks-what-ci-runs)
- [Tests](#tests)
- [Conventions](#conventions)
- [Recipes](#recipes)
- [Debugging tips](#debugging-tips)
- [Releasing](#releasing)
- [Maintaining it on your own](#maintaining-it-on-your-own)

---

## Set up

Requirements: **Python 3.12+**, **ffmpeg** (the Shorts pipeline tests use it), **Node.js** (only for
`node --check`), **shellcheck** (for the shell scripts), git.

```bash
git clone https://github.com/DalindaLimon/local-ds.git && cd local-ds
python3 -m venv .venv
source .venv/bin/activate              # fish: source .venv/bin/activate.fish ; Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt    # app deps + pytest, ruff, yt-dlp

# Debian/Ubuntu: sudo apt install ffmpeg shellcheck nodejs
# Arch/CachyOS:  sudo pacman -S ffmpeg shellcheck nodejs
# macOS:         brew install ffmpeg shellcheck node
```

On Windows, WSL2 is the easiest route (the app, scripts and Docker all expect Linux).

## Run it

```bash
export DATA_DIR=./data SCHEDULER_ENABLED=false   # fish: set -x DATA_DIR ./data; set -x SCHEDULER_ENABLED false
python -m app.seed --users                       # demo data; users demo/demo-password (admin), friend/friend-password
uvicorn --factory app.main:create_app --reload --host 0.0.0.0 --port 8080
```

Open http://localhost:8080. Python changes reload automatically; for frontend changes just reload the page (see
[FRONTEND.md](FRONTEND.md#pwa-and-the-service-worker) about the service worker cache).

- `SCHEDULER_ENABLED=false` keeps background jobs off so nothing hits the network unexpectedly. Run a job by hand
  from the Admin page or with `python -c "from app import jobs; from app.config import load_settings; jobs.rss_job(load_settings())"`.
- `python -m app.seed --remove` deletes the demo data; delete `./data` to start completely fresh.
- In Docker instead: `docker compose up -d --build` and `docker compose logs -f`.

## Checks (what CI runs)

Run these before every commit. CI ([.github/workflows/ci.yml](../.github/workflows/ci.yml)) runs exactly these,
plus a Docker build and smoke test:

```bash
ruff check . && ruff format --check .
pytest -q
shellcheck install.sh docker/entrypoint.sh scripts/*.sh
node --check app/static/app.js && node --check app/static/sw.js
```

`ruff format .` fixes formatting; `ruff check --fix .` fixes import order and simple lint issues. Ruff settings
are in `pyproject.toml` (line length 120; the formatter is the source of truth).

**UI check** at phone sizes (overflow, small tap targets, JS errors) and README screenshots:

```bash
pip install playwright && playwright install chromium
python scripts/screenshots.py http://localhost:8080 demo demo-password
```

## Tests

`pytest -q` runs everything in `tests/` in a few seconds. Network is never used: tests replace the functions that
would touch the internet.

| File | Covers |
|---|---|
| `test_auth.py` | setup, login, rate limiting, invites, CSRF, sessions |
| `test_urlsafe.py` | SSRF rules, redirects |
| `test_feeds.py` | input classification, parsing, sanitizing, fetching, backoff, Reddit batching, User-Agent |
| `test_personalization.py` | score/weight math, reactions, dislikes, For you, Reels order, exploration |
| `test_retention.py` | cleanup, reconcile, file locks, deletes that must keep data |
| `test_shorts_pipeline.py` | the download/convert pipeline with a fake yt-dlp and real ffmpeg |
| `test_comments.py` | comments |
| `test_posts.py` | user posts, activity, appearance prefs, migrations, admin refresh |
| `test_ai.py` | Ask AI (prompt, streaming, errors, article fetch, admin test), priority list, activity filters |

**Fixtures and helpers** in [tests/conftest.py](../tests/conftest.py):

- `settings` – a `Settings` with a temporary data folder and an initialized database.
- `conn` – a database connection for that settings.
- `app` – `create_app(settings)`.
- `client` – a `Client` (a `TestClient` that adds the CSRF header automatically).
- `make_user(conn, name, password="password123", admin=False)`, `login(app, name)` → logged-in `Client`.
- `make_source(conn, title, kind)`, `make_item(conn, source_id, title, age)`,
  `make_short(conn, settings, source_id, video_id, age_days, with_file, status)`.

**Mocking the network:** `monkeypatch.setattr(feeds, "safe_get", fake)` for feeds,
`shorts.list_channel_shorts` / `shorts.download_short` / `shorts.ytdlp_base` for YouTube,
`jobs.submit` to capture background jobs, `ai.stream_chat` (an async generator) / `ai.list_models` /
`ai.safe_get` for Ask AI. Set `feeds.reddit_throttle.gap = 0` in Reddit tests.

A typical API test:

```python
def test_something(app, conn):
    make_user(conn, "a")
    s = make_source(conn)
    i = make_item(conn, s, "hello")
    c = login(app, "a")
    r = c.post("/api/react", json={"type": "item", "id": i, "value": 1})
    assert r.status_code == 200 and r.json()["likes"] == 1
```

## Conventions

- **Keep it small:** one container, SQLite, no frontend build. New Python dependencies need a strong reason.
- **App factory:** never create a module-level `app`; use `create_app(settings)`.
- **Database:** connections are autocommit; wrap multi-statement writes in `with tx(conn):`. Times are epoch
  floats from `db.now()`. Use `INSERT OR IGNORE` for anything fetched from outside.
- **Settings:** add to `Settings` + `load_settings()` + `.env.example` + [CONFIGURATION.md](CONFIGURATION.md).
- **Network:** any user-supplied URL goes through `urlsafe.safe_get` / `validate_url`.
- **Frontend:** build DOM with `h()`; text as text; `innerHTML` only for sanitized `content_html` and icon SVGs;
  no inline scripts (CSP). Use CSS tokens for colors. Mobile rules in [FRONTEND.md](FRONTEND.md#mobile-rules).
- **Never auto-delete** comments, reactions or Short rows (see the full list in
  [ARCHITECTURE.md](ARCHITECTURE.md#rules-the-code-must-keep)).
- **Tests** for every behaviour change; a line in `CHANGELOG.md` for user-visible changes.
- **Commit messages:** short imperative subject ("Add OPML import"), the *why* in the body when not obvious.

## Recipes

### Recipe: add a setting

1. `app/config.py`: add a field with a default to `Settings`, and read it in `load_settings()` with `_int`,
   `_float`, `_bool` or `_str`.
2. Use it as `settings.my_value` (routes get settings via `s: Settings = Depends(get_settings)`).
3. Document it in `.env.example` and [CONFIGURATION.md](CONFIGURATION.md).
4. If the Admin page should show it, add it to the `settings` dict in `admin_status()` (`api_sources.py`).

### Recipe: add a database column

1. Add the column to the table's `CREATE TABLE` in `SCHEMA` (`app/db.py`).
2. Add `("table", "column", "TYPE NOT NULL DEFAULT …")` to `ADDED_COLUMNS` and bump `SCHEMA_VERSION`.
3. Write a test that drops the column, runs `init_db()` again and checks it's back (see
   `test_theme_prefs_and_migration`).
4. Update [DATABASE.md](DATABASE.md). Details: [DATABASE.md → Migrations](DATABASE.md#migrations).

A **new table** only needs `CREATE TABLE IF NOT EXISTS` in `SCHEMA`.

### Recipe: add an API endpoint

1. Pick the router: auth/account → `api_auth.py`; feed/items/Shorts/comments/media → `api_feed.py`;
   sources/discover/admin → `api_sources.py` (its routes are prefixed with `/api` by the router).
2. Write the handler:

   ```python
   class ThingBody(BaseModel):
       name: str = Field(min_length=1, max_length=100)


   @router.post("/api/things")
   def create_thing(body: ThingBody, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
       with tx(conn):
           cur = conn.execute(
               "INSERT INTO things(user_id, name, created_at) VALUES(?,?,?)", (user["id"], body.name, now())
           )
       return {"id": cur.lastrowid}
   ```

   Use `admin_user` instead of `current_user` for admin-only routes. Raise `HTTPException(status, "message")`
   for errors; the message is shown to the user as-is.
3. Plain `def` handlers run in a thread pool. If you call slow network code from an `async def`, wrap it in
   `await run_in_threadpool(fn, ...)`.
4. CSRF is automatic for unsafe methods under `/api/`.
5. Add tests and a row in [API.md](API.md).

### Recipe: add a screen to the frontend

1. Write `function viewThing(view) { … }` in `app.js` following the pattern in
   [FRONTEND.md](FRONTEND.md#routing-and-views) (call `setTabs`, build with `h()`, set `cleanupView`).
2. Add `[/^#\/thing$/, viewThing]` to `routes`.
3. Link to it: add a `link('#/thing', 'iconName', 'Label')` in the menu sheet, or an `<a href="#/thing">`.
4. Styles go in `app.css` using the tokens.
5. Bump the frontend version strings ([FRONTEND.md](FRONTEND.md#shipping-frontend-changes)) and check at 360 px.

### Recipe: add a new kind of source

1. `feeds.classify_input()`: recognise the input and return a new `SourceInput` kind.
2. `sources.add_source()`: create the `sources` row (`kind`, `title`, `feed_url` if it has an RSS/Atom feed).
3. If it has a normal feed, nothing else is needed: `refresh_all()` fetches any source with a `feed_url`.
   Otherwise write a fetch function and call it from `refresh_all()` (or a new job in `jobs.py`).
4. Frontend: add a label to `kindLabel` in `viewSources()`.
5. Tests with a mocked `safe_get`.

### Recipe: change the ranking

The math lives in `personalization.py` (`compute_score`, `weight_from_score`, `foryou_score`,
`weighted_shuffle`, `mix_exploration`); the queries that use it are `_foryou_order()` and `reels_order()` in
`api_feed.py`. Prefer adding a setting over hard-coding a constant. Update `tests/test_personalization.py` and
[PERSONALIZATION.md](PERSONALIZATION.md).

### Recipe: add a background job

1. Write `def my_task(conn, settings) -> result` somewhere sensible.
2. In `jobs.py`: `def my_job(settings): return _run("my_job", settings, module.my_task)` and add it to
   `start_scheduler()` with an interval or `CronTrigger`.
3. To make it runnable from the Admin page, add the name to the `Literal` and dict in `run_job()`
   (`api_sources.py`) and a `jobRow('my_job', 'Label')` in `viewAdmin()`.

## Debugging tips

- `LOG_LEVEL=DEBUG` logs every yt-dlp command line.
- Run a single test verbosely: `pytest -q tests/test_feeds.py -k batch -vv`.
- Inspect the dev database: `python -c "import sqlite3; c=sqlite3.connect('data/swipefeed.db'); print(c.execute('SELECT * FROM sources').fetchall())"`.
- Try the API from a shell: see [API.md → Conventions](API.md#conventions).
- Frontend: the browser console shows errors; `state` isn't global (ES module), so add a temporary
  `window.state = state` while debugging, and remove it afterwards.
- Reproduce Shorts problems directly: `python -m yt_dlp -J --flat-playlist "https://www.youtube.com/@channel/shorts"`.

## Releasing

1. Make sure all checks pass and `CHANGELOG.md` has the changes under `[Unreleased]`.
2. Bump `__version__` in `app/__init__.py`, rename `[Unreleased]` to `[x.y.z] - date` (add a new empty
   `[Unreleased]` above), and bump the frontend version strings in `index.html` and `sw.js` to match.
3. Commit, then tag and push:

   ```bash
   git tag v0.4.0 && git push origin main --tags
   ```

4. The **Docker image** workflow ([.github/workflows/docker.yml](../.github/workflows/docker.yml)) builds
   amd64 + arm64 images and pushes `ghcr.io/<user>/<repo>:0.4.0`, `:0.4`, `:latest`.
5. Servers update with `install.sh --update` (or `docker compose pull && docker compose up -d` when using `IMAGE`).

Version numbers follow semantic versioning: patch for fixes, minor for features, major for breaking changes
(e.g. needing manual steps on update).

## Maintaining it on your own

If you have to keep this running with no outside help, these are the things that actually need attention:

1. **YouTube breaks yt-dlp** a few times a year. The daily self-update almost always fixes it. If not, check the
   [yt-dlp issue tracker](https://github.com/yt-dlp/yt-dlp/issues), and as a stopgap rebuild the image
   (`docker compose build --pull --no-cache && docker compose up -d`).
2. **Reddit limits or blocks RSS.** See [TROUBLESHOOTING.md](TROUBLESHOOTING.md#feeds-and-reddit). The batching
   and backoff code is in `feeds.py` (`fetch_reddit_batch`, `_record_failure`).
3. **Dependencies age.** Every few months: bump the base image in `Dockerfile` (`python:3.12-slim-bookworm`), run
   `pip install -U -r requirements-dev.txt` in the venv, run the checks, rebuild. Upper bounds in
   `requirements.txt` (`<1`, `<4`, …) protect against breaking major releases; raise them deliberately and test.
4. **Disk fills up.** Lower `RETENTION_DAYS`; see [OPERATIONS.md](OPERATIONS.md#disk-space).
5. **Backups.** Keep the cron backup running and test a restore once in a while.

When changing code, read the module's docstring and the relevant docs page first, keep the rules in
[ARCHITECTURE.md](ARCHITECTURE.md#rules-the-code-must-keep), write a test that fails before your change, and run
all checks before committing.
