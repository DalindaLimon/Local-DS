# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.5.1] - 2026-10-13

### Added
- **Seek bar in Reels:** drag (or tap) the progress line at the bottom of a Short to jump around in the video.
  It grows and shows the time while you drag, doesn't swipe to the next Short, and works with arrow keys.

## [0.5.0] - 2026-10-13

### Changed
- **Renamed to Local DS everywhere:** Docker image `localds:local`, container and compose service `localds`,
  compose project `localds`, install folder `/opt/localds`, backups `localds-*.tar.gz`, repo `local-ds`. The
  database file keeps its name (`/data/swipefeed.db`), so data carries over. To switch an existing install, stop
  the old container first (`docker compose -p swipefeed down`), then `docker compose up -d --build`. Installs made
  with `install.sh` in `/opt/swipefeed` can be moved with `mv /opt/swipefeed /opt/localds`.

### Added
- **Feed filters:** chips for *Unread*, *Liked*, *Commented* and *Disliked*, plus a *Sources* button that lists
  Reddit and YouTube sources (and blogs and people's posts) in separate sections. Replaces one chip per source.
  API: `GET /api/feed?show=liked|commented|disliked|unread`.
- **New logo:** Instagram-style purple-to-blue gradient icon (SVG, PNG and home-screen icons).
- **Attachments on posts:** add up to 10 photos, videos, audio or any other files to a post. They upload with a
  progress bar; photos show on the feed card and as a grid in the post, videos and audio get a player, other
  files download. Only logged-in users can see them; non-media files are always served as downloads.
  `UPLOAD_MAX_MB` (default 200) sets the size limit and is editable on the Admin page.
- **Discover suggestions learn from comments and dislikes too**, not just likes, and use the topics of the
  source a post came from. YouTube and Reddit get their own suggestion lists; the starter groups are ordered by
  the same interests.
- **Settings on the Admin page:** an admin can change almost every `.env` setting from the browser (Reddit
  username / User-Agent, feed and Shorts intervals, retention, encoding, personalization math, Ask AI server,
  model and key, base URL, cookies, log level). Saved values override `.env`, apply immediately without a
  restart, and can be reset to the `.env` value. The API key is write-only.

### Fixed
- `install.sh` restores the executable bit on its scripts after cloning/pulling (it is lost when files are
  uploaded through the GitHub web page).
- The service worker cached the old `app.js`/`app.css` after the 0.4.1 cache bump.
- **Discover:** the YouTube/Reddit switch did nothing unless a search was typed. It is now *All / YouTube /
  Reddit* and filters the search results, the suggestions and the starter list.

### Changed
- **Sharper Reddit images:** Reddit feeds only include 140 px or 640 px previews. Posts now show the full-size
  original from `i.redd.it` instead (feed cards and the reader view); existing posts are upgraded once on startup.
  GIFs and link previews (`external-preview.redd.it`) keep the preview, because no original exists or it is huge.

## [0.4.0] - 2026-10-13

### Added
- **Ask AI:** connect any OpenAI-compatible LLM server (`LLM_BASE_URL`, `LLM_MODEL`; Ollama, llama.cpp, LM Studio,
  vLLM, …). Every post and Short gets an Ask AI button with *Summarize*, *Fact-check*, *Explain* and free
  questions; answers stream in. When a feed only has an excerpt, the linked article is read too. Admin page has a
  connection test.
- **Your activity** now has search, filters (posts/Shorts, source, priority) and sorting (newest, oldest,
  priority, most liked & discussed).
- **Priority list:** flag any post or Short as High, Medium or Low priority from Your activity or the reader view;
  the *Priority list* tab shows them in order.
- Full documentation in `docs/` (user guide, install, remote access, operations, configuration, troubleshooting,
  architecture, database, API, personalization, feeds and Shorts, frontend, development, AI).

### Changed
- Subreddits are fetched several at a time (`r/a+b+c/.rss`, `REDDIT_BATCH_SIZE`, default 4) and split back into
  their sources, so a refresh makes about 4× fewer Reddit requests and hits the rate limit far less often.
- New `REDDIT_USERNAME` setting: the User-Agent becomes `linux:localds:<version> (by /u/NAME)`, the format Reddit asks for.

## [0.3.0] - 2026-10-13

### Added
- "Your activity" page (Account and the menu): every post and Short you liked, disliked or commented on.
- Appearance settings under Account, saved per user: theme (Auto, Dark, Black, Light), six colors and three
  feed layouts (Cards, Compact, Magazine).

### Changed
- The app is now called **Local DS** (short for doomscroll) in the interface, browser tab and installed app.
  The repository, Docker image and container are still named `swipefeed`.

## [0.2.0] - 2026-10-13

### Added
- Write your own posts (title, text, optional link) from the pencil button in the Feed. Authors and admins can
  delete them. Each user's posts form their own source, so likes and dislikes weight them like any other feed.
- Admins get a refresh button in the Feed header that fetches every source and checks for new Shorts right away,
  then reloads the feed.

### Changed
- Dislikes no longer hide the post or Short. They only lower that source's weight for you, so it shows up less
  over time. Use Mute to hide a source completely.

## [0.1.0] - 2026-10-13

### Added
- Feed tab: RSS/Atom, subreddits and YouTube channel videos with infinite scroll, Latest and For you modes,
  per-source and unread filters, seen tracking, pull to refresh, reader view and comments.
- Reels tab: locally downloaded YouTube Shorts in a full-screen vertical swipe feed with weighted shuffle,
  unseen-first ordering, endless reshuffle, mute memory and comment sheet.
- Likes/dislikes with per-user source weights (decay, clamping, exploration, boost/mute/reset, "why am I seeing this").
- Sources page with autodiscovery, Discover page with search, a curated starter list and "Suggested for you".
- Video retention that keeps every record, comment and reaction; Past Shorts list; startup reconciliation.
- First-run admin setup, invite links, admin page with disk usage, jobs and users.
- Docker image with ffmpeg, optional VAAPI encoding, daily yt-dlp updates; install, backup and restore scripts.
