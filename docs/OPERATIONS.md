# Operations

Day-to-day running of a Local DS server. Commands assume the install folder `/opt/localds`
(use wherever your `docker-compose.yml` is).

- [Where everything lives](#where-everything-lives)
- [Updating](#updating)
- [Backups](#backups)
- [Restore](#restore)
- [Logs and health](#logs-and-health)
- [The Admin page](#the-admin-page)
- [Common admin tasks from the shell](#common-admin-tasks-from-the-shell)
- [Looking inside the database](#looking-inside-the-database)
- [Disk space](#disk-space)

---

## Where everything lives

| Path (host) | Path (container) | Contents |
|---|---|---|
| `.env` | environment | All settings ([CONFIGURATION.md](CONFIGURATION.md)). Mode 600, never committed. **Back it up.** |
| `data/swipefeed.db` (+ `-wal`, `-shm`) | `/data/swipefeed.db` | The SQLite database: users, sources, posts, Shorts, reactions, comments, everything |
| `data/videos/<video_id>.mp4` | `/data/videos` | Downloaded Shorts (deleted after `RETENTION_DAYS`) |
| `data/thumbs/<video_id>.jpg` | `/data/thumbs` | Short thumbnails (kept unless `KEEP_THUMBNAILS=false`) |
| `data/tmp/` | `/data/tmp` | Downloads in progress |
| `data/demo/` | `/data/demo` | Demo images (only if you loaded demo data) |
| `data/.secret_key` | `/data/.secret_key` | Generated secret if `SECRET_KEY` is unset or `change-me` |

The data folder location is `DATA_PATH` in `.env` (default `./data`). Files are owned by uid 1000.

## Updating

```bash
bash /opt/localds/install.sh --update
```

This does `git pull` and rebuilds (or `docker compose pull` if `IMAGE` is set), then restarts. Data is untouched.
Database changes are applied automatically on start (see [DATABASE.md](DATABASE.md#migrations)).

Manually:

```bash
cd /opt/localds
git pull
docker compose up -d --build
```

yt-dlp updates itself inside the container every day and shortly after each start; you do not need to rebuild
for yt-dlp fixes. Phones pick up new frontend code on their next load.

**Before a big update, take a backup** (next section).

## Backups

Everything is in the data folder plus `.env`.

```bash
cd /opt/localds
bash scripts/backup.sh                         # -> backups/localds-YYYYmmdd-HHMMSS.tar.gz
bash scripts/backup.sh --no-videos --keep 14   # small backup without video files, keep the newest 14
bash scripts/backup.sh --dest /mnt/nas/localds # write somewhere else
```

The database is copied with SQLite's online backup API while the app keeps running, so the copy is consistent.
Video files expire anyway, so `--no-videos` backups are usually what you want.

Nightly via cron inside the CT:

```
0 4 * * * bash /opt/localds/scripts/backup.sh --no-videos --keep 14
```

Proxmox backups (vzdump) of the whole CT also work.

## Restore

```bash
bash scripts/restore.sh backups/localds-20261013-120000.tar.gz
```

It stops the app, moves the current data folder aside to `data.before-restore-<time>` (never deletes it),
unpacks the backup, and starts the app again. If the backup has no videos, startup reconciliation marks those
Shorts as expired; nothing else is lost.

## Logs and health

```bash
docker compose logs -f                 # follow logs
docker compose logs --since 1h | grep -i warn
curl -s localhost:8080/healthz         # {"status":"ok","version":"0.3.0"}
docker compose ps                      # shows (healthy) when the healthcheck passes
```

Useful log lines:

| Log text | Meaning |
|---|---|
| `Local DS x.y.z starting, data in /data` | Startup |
| `reconcile: {...}` | Files and database were out of sync and got fixed |
| `cleanup: expired N short video file(s)` | Retention deleted video files |
| `source N (title) fetch failed: ...` | A feed fetch failed; it backs off and retries |
| `combined Reddit fetch for a+b failed (...); fetching one by one` | A Reddit batch failed, fell back to single requests |
| `download of short ID failed: ...` | yt-dlp or ffmpeg failed; retried up to 3 times |
| `VAAPI encode failed (...); falling back to libx264` | GPU encode failed for one video; software was used |
| `yt-dlp updated A -> B` | Daily self-update found a new version |

Set `LOG_LEVEL=DEBUG` in `.env` for the yt-dlp command lines and more.

## The Admin page

**More → Admin** shows disk usage, versions, the result of each background job with a **Run** button, invite
links, and users. See [USER_GUIDE.md](USER_GUIDE.md#admin-page). The **refresh icon in the Feed header** (admins
only) fetches all feeds and Shorts at once.

## Common admin tasks from the shell

Always run Python inside the container as uid 1000 (`-u 1000:1000`).

**Reset a forgotten password:**

```bash
docker compose exec -u 1000:1000 localds python -c "
from app.config import load_settings; from app.db import connect; from app.security import hash_password
c = connect(load_settings().db_path)
c.execute('UPDATE users SET pw_hash=? WHERE username=?', (hash_password('new-password-here'), 'USERNAME'))
print('ok')"
```

**Make someone admin:**

```bash
docker compose exec -u 1000:1000 localds python -c "
from app.config import load_settings; from app.db import connect
connect(load_settings().db_path).execute(\"UPDATE users SET is_admin=1 WHERE username='USERNAME'\")"
```

**Log everyone out** (e.g. after a leaked cookie): delete all sessions with
`DELETE FROM sessions;` (see the next section), or change `SECRET_KEY` and restart (session and invite tokens are
signed with it).

**Run a job now:** use the Admin page, or e.g.
`docker compose exec -u 1000:1000 localds python -c "from app import jobs; from app.config import load_settings; jobs.rss_job(load_settings())"`.

**Force a yt-dlp update:** Admin → *Update yt-dlp*, or
`docker compose exec -u 1000:1000 localds python -m pip install -U "yt-dlp[default]"`.

## Looking inside the database

The image has Python's built-in `sqlite3` module (not the `sqlite3` CLI). A small helper:

```bash
docker compose exec -u 1000:1000 localds python -c "
import sqlite3, sys; c = sqlite3.connect('/data/swipefeed.db')
for row in c.execute(sys.argv[1]): print(row)" "SELECT id, kind, title, status, last_error FROM sources"
```

Or copy a backup to your PC and open it with [DB Browser for SQLite](https://sqlitebrowser.org/).
**Do not edit the live database with an external tool while the app runs** unless you know SQLite's locking;
use the helper above for small fixes.

Handy queries are in [DATABASE.md](DATABASE.md#handy-queries).

## Disk space

- Videos are the only thing that grows quickly. They are deleted after `RETENTION_DAYS`.
- Downloads stop when free space on `/data` drops below `MIN_FREE_DISK_MB` (default 2048); the Admin page says
  *Paused: free disk below …*.
- To free space now: lower `RETENTION_DAYS`, `docker compose up -d`, then Admin → *Cleanup + reconcile → Run*.
- Database size stays small (text only). `VACUUM` is rarely needed; if you want it, stop the app first.
