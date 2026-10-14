# User guide

This page describes every screen of Local DS from a user's point of view. For how things work underneath, follow
the links to the technical pages.

The app has three tabs at the bottom: **Feed**, **Reels** and **More**. *More* opens a menu with
**Your activity**, **Sources**, **Discover**, **Past Shorts**, **Account** and (for admins) **Admin**.

---

## Accounts

- **First run:** the very first visit shows a setup page where you create the admin account. It works only once.
- **Inviting someone:** there is no public signup. An admin creates a single-use invite link under
  **More → Admin → Invite a friend**. Links expire after 3 days by default. The friend opens the link, picks a
  username and password, and is logged in.
- **Usernames:** 3–32 characters, letters, numbers, `.`, `_`, `-`. **Passwords:** at least 8 characters.
- **Logging in:** after 5 wrong passwords for one username (or 20 from one IP address) you must wait 15 minutes.
- **Sessions** last 30 days (`SESSION_DAYS`). Changing your password logs out your other devices.
- **Admins vs members:** admins can delete sources, see the Admin page, create invites, promote/remove users, and
  delete anyone's posts or comments. Everything else is the same for both.

## Feed

A Reddit-style list of cards. Each card shows the source, age, title, a short excerpt and an image if the post has
one. Tap a card to open the **reader view** with the full text, a link to the original, reactions and comments.

**Header controls**

| Control | What it does |
|---|---|
| **Latest / For you** | *Latest* is newest first. *For you* ranks posts by how much you like their source and how recent they are (see [PERSONALIZATION.md](PERSONALIZATION.md)). Your choice is remembered. |
| **Eye icon** | Hide posts you have already seen ("Unread" mode). A card counts as seen once you scroll past it. |
| **Refresh icon** (admins only) | Fetches every source and checks every YouTube channel for new Shorts right now, waits for the feed fetch to finish, then reloads the list and tells you how many new posts arrived. |
| **Chips** | *All* resets every filter. *Unread* hides posts you've seen (same as the eye icon). *Liked*, *Commented* and *Disliked* show only posts you liked, commented on or disliked. *Sources* opens a list with Reddit and YouTube (and blogs, people's posts) in separate sections; pick one to show only that source. Past Shorts is in the More menu and on the Reels screen. |
| **Pull down** at the top | Reloads the list from the server (does not fetch sources; use the admin refresh for that). |

**On each card**

| Button | What it does |
|---|---|
| ♥ Like | Raises that source's weight **for you**. Tap again to undo. |
| 👎 Dislike | Lowers that source's weight for you. The post stays where it is; you'll see that source less over time. A message offers *Undo*. To hide a source completely, use *Mute* on the Sources page. |
| 💬 Comments | Opens the comment sheet. Comments are shared between users. |
| ✨ Ask AI | Only when an LLM server is connected ([AI.md](AI.md)). See [Ask AI](#ask-ai) below. |
| 🗑 Delete | Only on user posts you wrote (admins see it on all user posts). Deletes the post with its comments and reactions. |
| ↗ Open original | Opens the original web page in a new tab. |

In *For you* mode each card also shows a grey **"why" line**, e.g. *"Source weight 1.6x because you liked 3 of its
posts"*, or *"Exploring: a random pick…"* for the ~10 % of random picks.

## Ask AI

If the admin connected an LLM server ([AI.md](AI.md)), every post and Short has a ✨ button (on feed cards, in the
reader view, *Ask* in Reels, and in Past Shorts and Your activity). It opens a sheet with:

- **Summarize** – a few bullet points.
- **Fact-check** – the post's main claims, each rated as well established, uncertain, or likely false, with what
  to verify elsewhere.
- **Explain** – the background you need.
- A box for **your own question**.

The answer appears word by word; **Stop** cancels it. The line above the answer shows the model and whether the
linked article was read. The AI can be wrong and can't browse the web, so treat it as a starting point and check
important facts at the source.

## Writing posts

Tap the round **pencil button** at the bottom right of the Feed. A post has a **title** (required), **text**
(optional, line breaks are kept, blank lines start new paragraphs) and a **link** (optional, must start with
`http://` or `https://`). Posts appear immediately in everyone's feed.

**Attachments:** tap *Add photos, videos or files* to attach up to 10 files of any type (photos, videos, audio,
PDFs, archives, …). They upload right away with a progress bar; *Post* waits until all are done. In the feed the
first photo (or else the first video) is shown on the card. In the post, photos show as a grid, videos and audio
get a player, and other files are download links. The size limit per file is set by the admin (default 200 MB).
Files are only visible to logged-in users and are deleted together with the post.

Each person's posts form their own source named after their username, so the other person's likes and dislikes
on your posts change how often they see your posts, exactly like any other source. Old posts are never cleaned up
automatically.

## Reels

A full-screen vertical feed of YouTube Shorts that were downloaded to the server. Swipe up for the next video.

- Videos start **muted** (browsers only allow muted autoplay). Tap the speaker button to turn sound on; the choice
  is remembered.
- Tap the video to pause or play.
- **Seek:** drag the thin line at the bottom of the video (or tap a spot on it) to jump forward or back. It grows
  and shows the time while you drag. On desktop, focus it and use the arrow keys (5 s steps).
- Side buttons: **Like**, **Nope** (dislike, also skips to the next video), **Chat** (comments), **Sound**, and
  **YouTube** (open the original).
- Order: Shorts you haven't seen come first, shuffled with a bias towards sources you like; then ones you have seen.
  When you reach the end it reshuffles instead of stopping.
- Keyboard (desktop): `↓`/`j` next, `↑`/`k` previous, `m` mute, `space` pause.

## Past Shorts

Video files are deleted after `RETENTION_DAYS` (7 by default) to save disk space. The Short itself is kept forever
with its title, channel, thumbnail, comments and reactions, and moves to **Past Shorts** (menu, or
the clock icon in Reels). From there you can still react, comment and open it on YouTube.

## Your activity

**More → Your activity** (also linked from Account) keeps every post and Short you **liked**, **disliked** or
**commented on**, plus your **Priority list**. Only you see your activity. A post you commented on several times
appears once.

**Filters and sorting** (your choices are remembered on the device):

| Control | Options |
|---|---|
| Search | Matches title, source/channel, excerpt and author |
| Type | Posts and Shorts / Posts only / Shorts only |
| Source | All sources, or one (the list shows how many entries each has) |
| Priority | Any / Has a priority / High / Medium / Low / No priority |
| Sort | Newest first / Oldest first / By priority / Most liked & discussed |

**Priority list:** tap the 🚩 flag on any entry here (or *Priority* in the reader view) and pick **High**,
**Medium** or **Low**; *Remove priority* takes it off. The **Priority list** tab shows everything you flagged,
sorted High → Medium → Low (newest first within each level). Priorities are personal and never deleted
automatically.

## Appearance

**More → Account → Appearance.** These settings are saved with your account, so they follow you to other devices.

| Setting | Options |
|---|---|
| Theme | **Auto** (follows your phone's light/dark setting), **Dark**, **Black** (pure black, good for OLED screens), **Light** |
| Color | Ember (orange, default), Ocean, Forest, Grape, Rose, Gold. Changes buttons, highlights and the pencil button. |
| Feed layout | **Cards** (big cards with image), **Compact** (dense list, small thumbnail on the right), **Magazine** (edge to edge, large image above the title) |

## Sources

**More → Sources** lists every source. Sources are **shared** by all users; weights, boost, mute and reset are
**personal**.

To add one, paste any of these into the box at the top:

| You paste | What happens |
|---|---|
| `selfhosted`, `r/selfhosted`, `https://reddit.com/r/selfhosted` | The subreddit's RSS feed |
| `https://some-blog.com` | The page is fetched and its RSS/Atom feed is found automatically |
| `https://site.com/feed.xml` | Used directly |
| `@JeffGeerling`, `https://youtube.com/@JeffGeerling`, `…/channel/UC…` | Shorts are downloaded for Reels; regular videos also appear in the Feed unless you untick the box |

Each source card shows:

- **Status badge:** OK, Pending (just added), Rate limited, Blocked, Error, or Disabled.
- Last fetch time, number of posts / Shorts on disk.
- **Share bar:** roughly how much of *your* feed this source takes, and its weight for you.
- The *why* line explaining the weight, and the last error if any (with the next retry time).
- Buttons: **Boost** (×2 weight), **Mute** (hide it for you), **Reset** (forget your past reactions for this
  source), **Refresh** (fetch now and clear any backoff), **Show/Hide videos in Feed** (YouTube), the
  enable/disable toggle (affects everyone), and **Delete** (admins). Deleting keeps posts that have comments or
  reactions; the source is then archived instead of removed.

Your own and your friend's posts appear here as sources of type *Posts*.

## Discover

- **All / YouTube / Reddit** switch: filters the whole page (search results, suggestions and the starter list).
  *All* searches YouTube and Reddit at the same time.
- **Search** YouTube channels or subreddits by keyword, then tap *Add*.
- **Suggested for you:** ranked by the topics of sources you already keep and the posts and Shorts you like,
  comment on (counts as interest) and dislike (pushes that topic down). Separate suggestions for YouTube and
  Reddit. Everything is computed on your server; nothing is sent anywhere.
- **Starter list:** topic groups are ordered the same way, best match first.
- **Starter list:** a curated list grouped by topic (tech, homelab, science, …).

## Admin page

**More → Admin** (admins only):

- **Storage:** disk used by `/data`, videos and thumbnails, and free space. Downloads pause when free space drops
  below `MIN_FREE_DISK_MB`.
- **Versions and encoding:** app version, yt-dlp version, whether the iGPU is used for encoding.
- **Jobs:** last run time and result of *Refresh feeds*, *Fetch Shorts*, *Cleanup + reconcile*, *Recompute
  weights* and *Update yt-dlp*, each with a **Run** button.
- **Ask AI:** the connected LLM server and model, with a **Test connection** button.
- **Settings:** change almost every `.env` setting from the browser, grouped into *Reddit & feeds* (including
  your Reddit username for the User-Agent), *Shorts & storage*, *Personalization*, *Ask AI* and *General*.
  Saved values override `.env` and apply immediately, no restart. **Reset** goes back to the `.env` value.
  The data folder, secret key and scheduler on/off can only be set in `.env`.
- **Invite a friend:** create, share or revoke invite links.
- **Users:** promote/demote admins, delete users (their comments stay, shown as *[deleted user]*).

## Installing on your phone

The app can be installed like a native app (no app store). It needs HTTPS, so set up
[REMOTE_ACCESS.md](REMOTE_ACCESS.md) first.

- **iPhone:** open it in Safari → Share → *Add to Home Screen*.
- **Android:** open it in Chrome → menu → *Install app*.
