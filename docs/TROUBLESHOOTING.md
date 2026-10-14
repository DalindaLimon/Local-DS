# Troubleshooting

Start with the logs: `docker compose logs -f` (in the install folder) and the **Admin page**, which shows each
background job's last result and error. [OPERATIONS.md](OPERATIONS.md#logs-and-health) explains the log lines.

- [The app does not start](#the-app-does-not-start)
- [Can't reach it / login problems](#cant-reach-it--login-problems)
- [Feeds and Reddit](#feeds-and-reddit)
- [YouTube Shorts](#youtube-shorts)
- [Video playback on phones](#video-playback-on-phones)
- [The phone app shows old code](#the-phone-app-shows-old-code)
- [Ask AI](#ask-ai)
- [Database problems](#database-problems)

---

## The app does not start

**`failed to bind host port 0.0.0.0:8080: address already in use`**
Another program already uses that port (check with `ss -ltnp 'sport = :8080'`). Set `PORT=8081` (or any free
port) in `.env` and run `docker compose up -d`.

**Docker fails inside the LXC** — `install.sh` stops and prints the fix. Usually nesting/keyctl are off:
`pct set <CTID> -features nesting=1,keyctl=1 && pct reboot <CTID>`. On old Proxmox/ZFS combinations overlayfs may
fail; Proxmox VE 8 with ZFS 2.2+ supports it. As a last resort, `lxc.apparmor.profile: unconfined` in the CT
config fixes AppArmor-related start errors (it weakens isolation).

**`Permission denied` on `/data`** — the data folder must belong to uid 1000. The entrypoint fixes this on start
when the top folder has the wrong owner; if only some files are wrong (e.g. created by a command run as root),
run `chown -R 1000:1000 data` on the host. Always use `docker compose exec -u 1000:1000 …`.

**Container keeps restarting** — `docker compose logs` shows the Python traceback. A failed database migration or
an invalid `.env` value (e.g. text in a number setting) are the usual causes.

## Can't reach it / login problems

**"CSRF check failed. Reload the page."** — the `sf_csrf` cookie is set when the page loads; reload. Behind a
proxy that strips cookies or changes the host, check `BASE_URL` and the proxy config.

**Locked out after wrong passwords** — wait 15 minutes (5 failures per username, 20 per IP). To reset a password
see [OPERATIONS.md](OPERATIONS.md#common-admin-tasks-from-the-shell).

**Logged out all the time** — `SECRET_KEY` changes between restarts (set it in `.env`), or a Cloudflare Access
session that is too short, or `COOKIE_SECURE=true` while using plain HTTP.

**Invite link points to the wrong address** — set `BASE_URL`.

## Feeds and Reddit

**Reddit shows "Rate limited" or "Blocked"** — Reddit allows only a few anonymous RSS requests per minute per IP
and blocks some IPs entirely (often VPN/VPS ranges). What the app already does: descriptive User-Agent, ≥3 s
between Reddit requests, several subreddits per request (`REDDIT_BATCH_SIZE`), ETag caching for single fetches,
respects `Retry-After`, exponential backoff (up to 6 h for 429, 12 h for 403), and tries `old.reddit.com` when
`www` answers 403. What you can do:

1. Set `REDDIT_USERNAME` in `.env`.
2. Raise `RSS_INTERVAL_MIN` (e.g. 60) and avoid pressing the admin refresh button repeatedly.
3. Wait: a 429 clears by itself. The source card shows the next retry time; its *Refresh* button clears the
   backoff early.
4. A 403 on a home connection usually passes after some hours. On a VPS, Reddit may block the IP permanently.

Details in [FEEDS_AND_SHORTS.md](FEEDS_AND_SHORTS.md#reddit).

**A quiet subreddit gets no posts** — in a batch, 100 posts are shared between the subreddits, so a busy one can
crowd out a quiet one. Lower `REDDIT_BATCH_SIZE` (2, or 1 to turn batching off).

**"No RSS or Atom feed found at that address"** — the site has no `<link rel="alternate">` feed link. Find the
feed URL yourself (often `/feed`, `/rss`, `/atom.xml`, `/index.xml`) and paste it directly.

**"Requests to private or internal addresses are blocked"** — the feed is on your LAN. Set
`ALLOW_PRIVATE_URLS=true` if you really need it (see [CONFIGURATION.md](CONFIGURATION.md)).

**A source shows "Error" with an HTTP code** — the site is down or changed its feed URL. After two failures the
app waits 20 min, then doubles the wait up to 6 h. Delete and re-add the source if the URL changed.

## YouTube Shorts

**No Shorts appear** — Shorts runs every 2 hours (`SHORTS_INTERVAL_MIN`) and right after adding a channel. Check
the Admin page → *Fetch Shorts* result and *Shorts status*; press **Run**.

**yt-dlp errors after a YouTube change** — usually fixed by the next daily update. Force it: Admin →
*Update yt-dlp*, or `docker compose exec -u 1000:1000 localds python -m pip install -U "yt-dlp[default]"`.
Failed Shorts are retried up to 3 times within 3 days.

**"Sign in to confirm you're not a bot"** — YouTube wants cookies. Export cookies for youtube.com from a browser
logged into a throwaway account (a "cookies.txt" browser extension does this) to `data/cookies.txt`, then set
`YTDLP_EXTRA_ARGS=--cookies /data/cookies.txt` and `docker compose up -d`.

**"Paused: free disk below … MB"** — free space on `/data` is under `MIN_FREE_DISK_MB`. Free space or lower
`RETENTION_DAYS` (see [OPERATIONS.md](OPERATIONS.md#disk-space)).

**Encoding is slow / CPU is high** — enable the iGPU ([INSTALL.md](INSTALL.md#optional-igpu-hardware-encoding)).
Most Shorts only need a remux, which is cheap.

## Video playback on phones

- Shorts are always H.264/AAC MP4 with `faststart` and served with HTTP Range support, so iOS Safari can stream
  them.
- Autoplay only works muted: Reels start muted; tap the speaker for sound. Low Power Mode blocks autoplay; tap the
  video.
- The iPhone silent switch mutes web video sound on some iOS versions.
- A Short that expired while you were watching shows *"This Short just expired. It is in Past Shorts."*

## The phone app shows old code

The service worker caches the app shell (HTML, CSS, JS). New code only reaches phones if the version strings were
bumped (see [FRONTEND.md](FRONTEND.md#shipping-frontend-changes)). To force it on one device: close the app
completely and reopen it twice, or in a desktop browser open DevTools → Application → Service Workers →
*Unregister*, then reload.

## Ask AI

See the table in [AI.md → Troubleshooting](AI.md#troubleshooting). The Admin page's **Test connection** tells you
whether the server is reachable and the model exists.

## Database problems

**`database is locked`** — something else holds a write lock (e.g. you opened the live database in a GUI tool).
Close it. The app waits up to 30 s for locks.

**Rows `available` but the video file is missing (or the opposite)** — restart the app or run Admin →
*Cleanup + reconcile*; reconciliation fixes both directions.

**Corrupt database** — stop the app and restore the latest backup ([OPERATIONS.md](OPERATIONS.md#restore)).
