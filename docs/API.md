# HTTP API

All endpoints are defined in [app/api_auth.py](../app/api_auth.py), [app/api_feed.py](../app/api_feed.py),
[app/api_sources.py](../app/api_sources.py) and [app/main.py](../app/main.py). FastAPI's automatic docs pages
are switched off (`docs_url=None`); this page replaces them.

## Conventions

- **JSON in, JSON out.** Errors are `{"detail": "message"}` with a 4xx status. Validation errors are 422.
- **Auth:** the `sf_session` cookie (set by setup/login/register). Endpoints marked **user** return 401 without
  it; **admin** endpoints return 403 for non-admins.
- **CSRF:** every `POST`, `PUT`, `PATCH`, `DELETE` under `/api/` needs the header `X-CSRF-Token` equal to the
  `sf_csrf` cookie. `GET /api/state` sets that cookie and also returns the token as `csrf`.
- **Pagination:** list endpoints return `{"items": [...], "cursor": "..."}`. Pass `cursor` back to get the next
  page; `cursor: null` means the end. Cursors are opaque base64 JSON.
- **Item types:** `type` is `"item"` (a Feed post) or `"short"`.

Calling it from a shell (handy for debugging):

```bash
B=http://localhost:8080
curl -s -c jar -b jar $B/api/state > /dev/null
CSRF=$(awk '$6=="sf_csrf"{print $7}' jar)
curl -s -c jar -b jar -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
     -d '{"username":"demo","password":"demo-password"}' $B/api/login
curl -s -b jar "$B/api/feed?mode=latest&limit=2"
```

---

## Objects

**Item** (`item_json` in `api_feed.py`):

```json
{
  "type": "item", "id": 123,
  "source": {"id": 4, "title": "r/selfhosted", "kind": "reddit", "icon": null},
  "title": "…", "url": "https://…", "author": "/u/someone", "excerpt": "…", "image": "https://…",
  "published_at": 1760000000.0,
  "comments": 2, "likes": 1, "dislikes": 0,
  "my": 1,                 // this user's reaction: 1, -1 or 0
  "seen": false,
  "why": "Source weight 1.3x because you liked 1 of its posts",
  "explored": false,       // true when placed by exploration (For you)
  "mine": false,           // true for the caller's own user posts
  "attachments": []        // user posts: [{id, url, name, mime, kind, size}]
}
```

`GET /api/items/{id}` adds `content_html` (sanitized). Activity results add `acted_at`.

**Short** (`short_json`):

```json
{
  "type": "short", "id": 55, "video_id": "abcdefghijk", "source_id": 7,
  "title": "…", "channel": "…", "url": "https://www.youtube.com/shorts/…",
  "video": "/media/video/abcdefghijk",   // null unless status is "available"
  "thumb": "/media/thumb/abcdefghijk",   // null without thumbnail
  "status": "available", "published_at": …, "downloaded_at": …, "expired_at": null,
  "likes": 0, "dislikes": 0, "comments": 0, "my": 0, "seen": false, "why": "…", "explored": false
}
```

**User** (`user_public`): `id, username, is_admin, feed_mode, hide_seen, muted, theme, accent, layout`.

---

## Auth and account — `api_auth.py`

| Method & path | Auth | Body / params | Returns |
|---|---|---|---|
| `GET /api/state` | none | — | `{setup_needed, user \| null, csrf, version, ai}` (`ai`: an LLM server is configured); sets `sf_csrf` |
| `POST /api/setup` | none | `{username, password}` | `{user}` + session cookie. 403 once any user exists |
| `POST /api/login` | none | `{username, password}` | `{user}` + cookie. 401 wrong, 429 rate limited (`Retry-After`) |
| `POST /api/logout` | none | — | `{ok}`; deletes the session |
| `GET /api/invite/{token}` | none | — | `{ok}` or 404 if invalid/used/expired |
| `POST /api/register` | none | `{username, password, token}` | `{user}` + cookie. 404 bad invite, 409 name taken, 429 too many tries |
| `POST /api/account/password` | user | `{current, new}` | `{user}` + new cookie; all other sessions are logged out |
| `PATCH /api/me/prefs` | user | any of `feed_mode` (`latest`/`foryou`), `hide_seen`, `muted`, `theme` (`system`/`dark`/`black`/`light`), `accent` (`ember`/`ocean`/`forest`/`grape`/`rose`/`gold`), `layout` (`cards`/`compact`/`magazine`) | `{user}` |

## Feed, posts, activity — `api_feed.py`

| Method & path | Auth | Body / params | Returns |
|---|---|---|---|
| `GET /api/feed` | user | `mode=latest\|foryou`, `cursor`, `source` (id), `hide_seen=true`, `limit` (1–50, default 20) | `{items: [Item], cursor}`. Excludes disabled sources, sources with `rss_enabled=0`, and sources the user muted |
| `GET /api/items/{id}` | user | — | Item + `content_html` + `priority` (`high`/`medium`/`low`/null) |
| `POST /api/seen` | user | `{type, ids: [int] (≤200)}` | `{ok}` |
| `GET /api/me/activity` | user | `kind=liked\|disliked\|commented\|priority`, `q` (search in title, source, excerpt, author), `type=all\|item\|short`, `source` (id), `priority=any\|set\|high\|medium\|low\|none`, `sort=recent\|oldest\|priority\|popular`, `cursor`, `limit` | `{items: [Item \| Short], cursor, total, sources}`. Each entry has `acted_at` and `priority`. `sources` (first page only) lists `{id, title, count}` for the source filter. `popular` = likes + 2 × comments |
| `POST /api/me/priority` | user | `{type, id, level: high\|medium\|low\|none}` | `{priority}`. `none` removes it |
| `GET /api/feed` filter | user | `show` = `all` (default), `unread`, `liked`, `commented`, `disliked`; works with `mode`, `source` and `cursor`. `hide_seen=true` still means `unread` | same as above |
| `POST /api/posts` | user | `{title (1–300), text (≤10000), url (http/https or ""), attachments: [upload ids] (≤10)}` | the new Item. Creates the user's `kind='user'` source on first post. The first image attachment becomes `image`. 400 if an upload isn't yours or is already used |
| `POST /api/uploads?name=FILE` | user | raw file bytes as the body (not multipart) | `{id, url, name, mime, kind, size}`, `kind` = `image`/`video`/`audio`/`file`. 413 over `UPLOAD_MAX_MB`, 507 when the disk is low, 429 with 50 unposted uploads |
| `DELETE /api/uploads/{id}` | owner | — | `{ok}`. Only before the upload is attached to a post |
| `DELETE /api/posts/{id}` | author or admin | — | `{ok}`. 404 if the item is not a user post, 403 if not yours. Deletes its comments, reactions and seen rows too |

## Reels and Shorts

| Method & path | Auth | Body / params | Returns |
|---|---|---|---|
| `POST /api/reels/next` | user | `{exclude: [short ids already shown] (≤5000), n (1–30, default 6)}` | `{items: [Short], reset, remaining}`. Only `available` Shorts. When nothing is left and `exclude` was non-empty, it reshuffles everything and sets `reset: true` |
| `GET /api/shorts/past` | user | `cursor`, `limit` | `{items: [Short], cursor}` of `expired` Shorts, newest expiry first |
| `GET /api/shorts/{id}` | user | — | Short |

## Reactions and comments

| Method & path | Auth | Body / params | Returns |
|---|---|---|---|
| `POST /api/react` | user | `{type, id, value: 1 \| -1 \| 0}` (0 removes) | `{value, previous, likes, dislikes, source_id, weight, why}` |
| `GET /api/comments` | user | `type`, `id` | `{comments: [{id, user, user_id, body, created_at, can_delete}]}` (oldest first, max 500) |
| `POST /api/comments` | user | `{type, id, body (1–2000)}` | the new comment |
| `DELETE /api/comments/{id}` | author or admin | — | `{ok}` |

## Media

| Method & path | Auth | Notes |
|---|---|---|
| `GET /media/video/{video_id}` | user | MP4, supports `Range` (206 partial content), `ETag`, cached privately for a day. 404 when expired. Marks the file as in use for cleanup |
| `GET /media/thumb/{video_id}` | user | JPEG, cached privately for a week |
| `GET /media/demo/{name}` | user | Demo images |

## Sources and Discover — `api_sources.py`

| Method & path | Auth | Body / params | Returns |
|---|---|---|---|
| `GET /api/sources` | user | — | `{sources: [...]}` with status, counts, and the caller's `weight`, `share` (% of feed), `manual`, `likes`, `dislikes`, `why` |
| `POST /api/sources` | user | `{input, also_rss (YouTube: show videos in Feed), topics?}` | `{source, created}`. Starts a fetch in the background. 400 with a friendly message if the input can't be used |
| `PATCH /api/sources/{id}` | user | any of `enabled`, `rss_enabled`, `shorts_enabled` (YouTube only), `title`, `manual` (`boost`/`mute`/`none`) | `{source}`. `manual` is personal; the others affect everyone |
| `POST /api/sources/{id}/reset` | user | — | `{source}`. Ignores the caller's earlier reactions for this source |
| `POST /api/sources/{id}/refresh` | user | — | `{ok}`. Clears backoff, fetches in the background |
| `DELETE /api/sources/{id}` | admin | — | `{ok, archived}`. Keeps items with comments/reactions (then `archived: true`) |
| `GET /api/discover/starter` | user | — | `{items}` curated list; each entry has `added: true` if you already have it |
| `GET /api/discover/suggested` | user | — | `{items}` (max 12) not yet added, ranked by topic affinity, each with `score` and `reason` |
| `GET /api/discover/search` | user | `q`, `kind=youtube\|reddit` | `{items, error}` |

## Admin

| Method & path | Auth | Body / params | Returns |
|---|---|---|---|
| `GET /api/admin/status` | admin | — | versions, disk usage, job status, files in use, Short counts, totals, users, invites, effective settings |
| `GET /api/admin/settings` | admin | — | `{groups, fields, reddit_user_agent}`. Each field: `key, kind, group, label, help, min, max, choices, value, default, overridden, is_set`. Secrets (`llm_api_key`) are never returned, only `is_set` |
| `PATCH /api/admin/settings` | admin | `{values: {key: value \| null}}` | same as GET plus `changed` (keys) and `ai`. `null` removes the override (back to `.env`). 400 with a message on an invalid value; nothing is saved then |
| `POST /api/admin/invites` | admin | `{hours (default 72, max 720), note}` | `{url, expires_at}` |
| `DELETE /api/admin/invites/{id}` | admin | first 12 chars of the invite hash | `{ok}` (unused invites only) |
| `PATCH /api/admin/users/{id}` | admin | `{is_admin}` | `{ok}`. Can't change yourself |
| `DELETE /api/admin/users/{id}` | admin | — | `{ok}`. Comments stay as *[deleted user]*. Can't delete yourself |
| `POST /api/admin/refresh` | admin | — | `{ok, started}`. Runs the `rss` and `shorts` jobs now |
| `GET /api/admin/jobs` | admin | — | `{jobs}` (same structure as in status) |
| `POST /api/admin/jobs/{name}` | admin | `name` = `rss`, `shorts`, `cleanup`, `weights`, `ytdlp_update` | `{ok}` |

Job status entries look like
`{"running": false, "last_run": 1760000000.0, "took": 3.2, "ok": true, "error": null, "result": "12"}`.

## Ask AI — `api_ai.py`

| Method & path | Auth | Body / params | Returns |
|---|---|---|---|
| `POST /api/ai/ask` | user | `{type, id, mode: summary\|factcheck\|explain\|question, question (≤1000, required for mode=question)}` | **Plain text stream** (`text/plain`), the answer as it is generated. Headers `X-AI-Model` and `X-AI-Article` (`1` if the linked page was read). 503 not configured, 404 unknown item, 400 empty question, 502 when the LLM server fails before the first word; later failures are appended as `[AI error: …]` |
| `POST /api/admin/ai/test` | admin | — | `{ok, error, models}`: lists the server's models and checks `LLM_MODEL` is among them |

Reading the stream from JavaScript: `fetch()` then `res.body.getReader()` and a `TextDecoder` (see `openAsk()` in
`app.js`). From a shell: `curl -N -b jar -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' -d '{"type":"item","id":1,"mode":"summary"}' $B/api/ai/ask`.

## Other routes — `main.py`

| Path | Notes |
|---|---|
| `GET /healthz` | `{"status": "ok", "version": "x.y.z"}` after a trivial DB query. Used by the Docker healthcheck |
| `GET /` | `index.html` (`Cache-Control: no-cache`) |
| `GET /static/*` | Frontend files |
| `GET /sw.js` | Service worker, served from the root so it can control the whole site |
| `GET /manifest.webmanifest` | PWA manifest |
