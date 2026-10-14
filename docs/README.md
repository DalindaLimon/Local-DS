# Local DS documentation

These docs are written for a person maintaining Local DS on their own: someone who knows a bit of Python, HTML and
the command line, but has never seen this code before. If you only read one technical page, read
[ARCHITECTURE.md](ARCHITECTURE.md) first; it explains how every other piece fits in.

## Where to start

| You are… | Start with |
|---|---|
| Using the app | [USER_GUIDE.md](USER_GUIDE.md) |
| Installing or running a server | [INSTALL.md](INSTALL.md) → [REMOTE_ACCESS.md](REMOTE_ACCESS.md) → [OPERATIONS.md](OPERATIONS.md) |
| Fixing a problem | [TROUBLESHOOTING.md](TROUBLESHOOTING.md), then [OPERATIONS.md](OPERATIONS.md) for logs and the database |
| Changing the code | [ARCHITECTURE.md](ARCHITECTURE.md) → [DEVELOPMENT.md](DEVELOPMENT.md) → the topic page you need |

## All pages

| Page | Contents |
|---|---|
| [USER_GUIDE.md](USER_GUIDE.md) | Every screen: Feed, Reels, posts, activity, appearance, sources, Discover, admin |
| [INSTALL.md](INSTALL.md) | Proxmox LXC prerequisites, `install.sh`, manual Docker install, first run, iGPU encoding |
| [REMOTE_ACCESS.md](REMOTE_ACCESS.md) | Tailscale and Cloudflare Tunnel setups, HTTPS, login gate |
| [OPERATIONS.md](OPERATIONS.md) | Updating, backups, restore, logs, admin page, password reset, database inspection |
| [AI.md](AI.md) | Connecting an LLM server, what Ask AI sends, accuracy, troubleshooting |
| [CONFIGURATION.md](CONFIGURATION.md) | Every environment variable, grouped, with defaults and effects |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Symptoms → causes → fixes |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Process model, startup, request flow, modules, background jobs, security layers |
| [DATABASE.md](DATABASE.md) | Every table and column, data rules, migrations, handy SQL |
| [API.md](API.md) | Every HTTP route with parameters, responses and permissions |
| [PERSONALIZATION.md](PERSONALIZATION.md) | Source weights, decay, For you ranking, Reels shuffle, exploration, "why" lines |
| [FEEDS_AND_SHORTS.md](FEEDS_AND_SHORTS.md) | RSS/Reddit/YouTube fetching, backoff, Shorts download and transcoding, retention |
| [FRONTEND.md](FRONTEND.md) | `app.js` sections, the `h()` helper, routing, views, CSS tokens, themes, layouts, PWA |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Dev setup, tests, lint, conventions, step-by-step recipes, releasing |

## Glossary

| Term | Meaning |
|---|---|
| **Source** | Something content comes from: an RSS/Atom feed, a subreddit, a YouTube channel, or a user's own posts. Sources are shared by all users. |
| **Item** | One post in the Feed (a row in the `items` table): an RSS entry, a Reddit post, a YouTube video entry, or a user post. |
| **Short** | One YouTube Short (a row in `shorts`). Its video file lives in `/data/videos` until it expires. |
| **Reaction** | A like (+1) or dislike (−1) by one user on one item or Short. |
| **Weight** | A per-user, per-source multiplier (0.1×–5×) computed from that user's reactions. It changes ordering only. |
| **Boost / Mute** | Manual per-user overrides on a source: boost multiplies the weight, mute hides the source. |
| **Reset** | Makes a source ignore your reactions made before now (nothing is deleted). |
| **For you** | Feed mode that ranks by weight × recency. **Latest** is purely chronological. |
| **Exploration** | About 10 % of slots are random picks regardless of weight, so you don't end up in a bubble. |
| **Retention** | Video files of Shorts are deleted after `RETENTION_DAYS`; their rows stay as "expired" (Past Shorts). |
| **Reconcile** | Startup check that makes the database and the files on disk agree. |
| **Priority list** | Your own High/Medium/Low ranking of posts and Shorts, under *Your activity*. Personal, never shared. |
| **Ask AI** | Sends one post or Short to your LLM server for a summary, fact-check, explanation or answer. |
| **PWA** | Progressive Web App: the site installed on a phone's home screen, with a service worker caching the app shell. |
| **`/data`** | The one folder (a Docker volume) that holds all state: database, videos, thumbnails, secret key. |
