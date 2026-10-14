# Configuration reference

All settings are environment variables, normally set in `.env` next to `docker-compose.yml`
([.env.example](../.env.example) is the commented template). After changing `.env`, apply it with:

```bash
docker compose up -d
```

Settings are read once at startup by `load_settings()` in [app/config.py](../app/config.py) into a `Settings`
dataclass. Empty values fall back to the default. Booleans accept `1/true/yes/on` (anything else is false).

**Admin page overrides.** Most settings can also be changed under **More → Admin → Settings**. Those values are
stored in the database (kv key `settings_overrides`), take priority over `.env`, and apply immediately without a
restart ([app/settings_store.py](../app/settings_store.py)). *Reset* on a setting removes the override. Only
`DATA_DIR`, `SECRET_KEY`, `SCHEDULER_ENABLED` and the container variables (`PORT`, `BIND_ADDRESS`, `DATA_PATH`,
`MEM_LIMIT`, `IMAGE`, `FORWARDED_ALLOW_IPS`) are `.env`-only. If a `.env` change seems to have no effect, check
whether the setting was overridden on the admin page.

---

## Server and container

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | generated | Key for signing session and invite tokens (HMAC-SHA256). If empty or `change-me`, a random key is generated once and stored in `/data/.secret_key`. **Changing it logs everyone out and invalidates open invites.** |
| `PORT` | `8080` | Port on the **host**. The app inside the container always listens on 8080. |
| `BIND_ADDRESS` | `0.0.0.0` | Host address to bind. `127.0.0.1` = only reachable from the host itself (e.g. through Tailscale serve or cloudflared). |
| `DATA_PATH` | `./data` | Host folder mounted at `/data`. Back this up. |
| `DATA_DIR` | `/data` | Data folder **inside** the process. Set by the image; change only for local development (`./data`). |
| `BASE_URL` | empty | Public URL, e.g. `https://ds.example.com`. Used to build invite links. Empty = taken from the request. |
| `COOKIE_SECURE` | `auto` | `auto`: secure cookies when the request is HTTPS. `true`: always (use once you only use HTTPS). `false`: never. |
| `SESSION_DAYS` | `30` | How long a login lasts. |
| `FORWARDED_ALLOW_IPS` | private ranges + Tailscale | Proxies whose `X-Forwarded-For` / `-Proto` headers are trusted (comma separated, CIDR allowed). Read by the entrypoint and passed to uvicorn. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `MEM_LIMIT` | `2g` | Container memory limit (compose). |
| `IMAGE` | empty | Empty = build locally. `ghcr.io/<user>/local-ds:latest` = use the published image. |
| `COMPOSE_FILE` | unset | Set by `install.sh` to `docker-compose.yml:docker-compose.gpu.yml` when an iGPU is present. |
| `SCHEDULER_ENABLED` | `true` | Run background jobs. Set `false` in development and tests. |

## Shorts (Reels)

| Variable | Default | Meaning |
|---|---|---|
| `SHORTS_INTERVAL_MIN` | `120` | Minutes between Shorts runs (list every channel, download new ones). |
| `SHORTS_PER_CHANNEL` | `15` | Newest Shorts checked per channel per run. |
| `MAX_HEIGHT` | `720` | Maximum length of the **short side** in pixels (720 → 720×1280 for vertical video). Larger videos are scaled down. |
| `RETENTION_DAYS` | `7` | Video files are deleted this many days after download. Rows, comments and reactions stay forever. Decimals allowed. |
| `KEEP_THUMBNAILS` | `true` | Keep thumbnails of expired Shorts for *Past Shorts*. |
| `MIN_FREE_DISK_MB` | `2048` | Downloads pause when free space on `/data` drops below this. |
| `HWACCEL` | `auto` | `auto`: use VAAPI if `/dev/dri/renderD128` is usable. `vaapi`: same, but log a warning if it isn't. `none`: always software (libx264). |
| `YTDLP_AUTO_UPDATE` | `true` | `pip install -U yt-dlp` daily and shortly after start. |
| `YTDLP_EXTRA_ARGS` | empty | Extra arguments for every yt-dlp call, e.g. `--cookies /data/cookies.txt`. Read at call time. |

## Feeds (RSS, Reddit, YouTube video entries)

| Variable | Default | Meaning |
|---|---|---|
| `RSS_INTERVAL_MIN` | `20` | Minutes between feed refreshes. Raise it if Reddit rate-limits you. |
| `RSS_RETENTION_DAYS` | `0` | `0` = keep posts forever. Otherwise delete posts older than N days, **except** posts with comments or reactions and user posts. |
| `ALLOW_PRIVATE_URLS` | `false` | Allow feeds on private/LAN addresses. Turning this on disables SSRF protection for them; only do it if you need LAN feeds. |
| `REDDIT_USERNAME` | empty | Your Reddit username (without `/u/`). The User-Agent becomes `linux:localds:<version> (by /u/NAME)`, the format Reddit asks for. Reddit rate-limits generic User-Agents harder. |
| `REDDIT_USER_AGENT` | built from `REDDIT_USERNAME` | Full User-Agent override for Reddit requests. |
| `REDDIT_BATCH_SIZE` | `4` | Subreddits fetched in one request (`r/a+b+c/.rss?limit=100`, 100 posts shared and split back per subreddit). `1` = one request per subreddit. Clamped to 1–25. Lower it if a quiet subreddit gets crowded out by a busy one. |

## User posts

| Variable | Default | Meaning |
|---|---|---|
| `UPLOAD_MAX_MB` | `200` | Max size of one file attached to a post. Behind a Cloudflare Tunnel keep it under 100 (Cloudflare's request limit on the free plan). |

## Personalization

See [PERSONALIZATION.md](PERSONALIZATION.md) for the formulas and examples.

| Variable | Default | Meaning |
|---|---|---|
| `LIKE_BASE` | `1.25` | Weight = `LIKE_BASE ^ score`. Higher = each like matters more. |
| `DISLIKE_FACTOR` | `0.8` | A dislike counts as `−0.8` (a bit weaker than a like). |
| `REACTION_HALFLIFE_DAYS` | `30` | A reaction counts half after this many days, a quarter after twice that, … |
| `MIN_WEIGHT` / `MAX_WEIGHT` | `0.1` / `5.0` | Weight limits. Mute sets `MIN_WEIGHT` and hides the source. |
| `BOOST_MULTIPLIER` | `2.0` | Boost multiplies the weight by this (still capped at `MAX_WEIGHT`). |
| `EXPLORE_PERCENT` | `10` | Share of slots filled with random picks regardless of weight. `0` turns exploration off. |
| `FORYOU_HALFLIFE_HOURS` | `24` | In *For you*, a post's score halves every N hours of age. |
| `FORYOU_WINDOW_DAYS` | `21` | *For you* only considers posts from the last N days (max 4000 posts). |

## Ask AI (LLM server)

See [AI.md](AI.md). Ask AI is off until both `LLM_BASE_URL` and `LLM_MODEL` are set.

| Variable | Default | Meaning |
|---|---|---|
| `LLM_BASE_URL` | empty | OpenAI-compatible base URL, e.g. `http://192.168.1.50:11434/v1` (Ollama). Called directly, so LAN addresses work |
| `LLM_MODEL` | empty | Model name on that server, e.g. `llama3.1:8b` |
| `LLM_API_KEY` | empty | Bearer token, only if the server needs one |
| `LLM_TIMEOUT` | `180` | Seconds to wait for the first token and between tokens |
| `LLM_MAX_CONTEXT_CHARS` | `12000` | Max characters of post + linked article text sent to the model |
| `LLM_FETCH_ARTICLE` | `true` | When the feed text is short, fetch the linked page (through the SSRF filter) for more context |

## Remote access helpers (not read by the app)

| Variable | Used by | Meaning |
|---|---|---|
| `CLOUDFLARE_TUNNEL_TOKEN` | `docker-compose.override.yml` | Token for the `cloudflared` container ([REMOTE_ACCESS.md](REMOTE_ACCESS.md)). |

## Adding a new setting

See the recipe in [DEVELOPMENT.md](DEVELOPMENT.md#recipe-add-a-setting).
