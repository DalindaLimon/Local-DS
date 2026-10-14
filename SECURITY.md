# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/DalindaLimon/local-ds/security/advisories/new) for this repository instead.
Include steps to reproduce and the version (shown in Admin and at `/healthz`). You should get a reply within a week.

## Deployment recommendations

Local DS is built for a handful of trusted people. Even so:

- **Do not expose it directly to the internet.** Reach it through [Tailscale](https://tailscale.com) (private
  network, nothing exposed) or a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
  with a Cloudflare Access policy that only allows your and your friend's email addresses.
- Use HTTPS (both options above give you that) and set `COOKIE_SECURE=true` once you only use HTTPS.
- Keep `SECRET_KEY` secret; `.env` is created with mode 600 and is ignored by git.
- Keep the image updated (`bash install.sh --update`); yt-dlp updates itself daily.
- Create the admin account right after the first start: until then, anyone who can reach the page can claim it.
- Never keep the demo accounts (`demo` / `friend`) on a real install; their passwords are public.
  `python -m app.seed --remove` deletes them (unless their password was changed).
- Leave `ALLOW_PRIVATE_URLS=false` unless you need LAN feeds: it is what blocks server-side request forgery
  against your other homelab services.

## What is in place

- Argon2 password hashing, httpOnly + SameSite session cookies, double-submit CSRF tokens
- Login and registration rate limiting, no public signup (single-use, expiring invites only)
- SSRF protection for every user-supplied URL, re-checked on every redirect, with response size limits
- Allowlist HTML sanitizer for feed content, strict Content-Security-Policy, all other text rendered as text
- Videos, thumbnails and post attachments are only served to logged-in users; uploaded files that are not
  photos/videos/audio are always downloads, never rendered, and all uploads are sandboxed by CSP
