# Remote access (phones, a friend, HTTPS)

Local DS is meant for a few trusted people. **Never port-forward it to the internet.** Use one of these:

| | Tailscale | Cloudflare Tunnel |
|---|---|---|
| Cost | Free | Free, but you need a domain (about $10/year if you don't have one) |
| Who can reach it | Only devices in your tailnet (your friend installs Tailscale) | Anyone with the URL, gated by Cloudflare Access email login |
| Video traffic | Directly between devices | Goes through Cloudflare (see the note at the end) |
| HTTPS | Yes, real certificate via `tailscale serve` | Yes, Cloudflare's certificate |
| Recommended for | Default choice | Friends who won't install an app |

You can run both at the same time.

HTTPS matters: the phone's "Add to Home Screen" install, the service worker, and secure cookies all require it.

---

## Tailscale

### 1. Give the LXC a TUN device

Tailscale inside an unprivileged LXC needs `/dev/net/tun`. On the Proxmox host add to
`/etc/pve/lxc/<CTID>.conf`:

```
lxc.cgroup2.devices.allow: c 10:200 rwm
lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file
```

then `pct reboot <CTID>`.

### 2. Install and serve

Inside the CT:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up
tailscale serve --bg 8080        # use your PORT if you changed it
```

In the Tailscale admin console: *DNS → enable MagicDNS and HTTPS certificates*. The app is now at
`https://<ct-name>.<tailnet>.ts.net`.

### 3. Share with your friend

*Machines → … → Share* the machine with them. They install Tailscale and only see this one device.

### 4. Tell the app its URL

In `.env`:

```
BASE_URL=https://<ct-name>.<tailnet>.ts.net
COOKIE_SECURE=true
BIND_ADDRESS=127.0.0.1      # optional: only reachable through tailscale serve
```

Then `docker compose up -d`.

---

## Cloudflare Tunnel

A small `cloudflared` container makes an **outbound** connection to Cloudflare; nothing is opened on your router.

### 1. Put a domain on Cloudflare

Add the site in the Cloudflare dashboard, pick the Free plan, and change the nameservers at your registrar to the
two Cloudflare shows. Wait until the site shows **Active**.

(No domain? `cloudflared tunnel --url http://localhost:8080` gives you a temporary random `*.trycloudflare.com`
address for testing. It changes on every restart and cannot have a login gate, so don't use it for real.)

### 2. Create the tunnel

*Zero Trust → Networks → Tunnels → Create a tunnel* → *Cloudflared* → name it (e.g. `localds`). On the install
screen choose *Docker* and copy only the **token** (the long string after `--token`).

### 3. Add a public hostname

In the tunnel → *Public Hostname → Add*:

- Subdomain `ds`, your domain → `ds.example.com`
- Service type **HTTP**, URL **`localds:8080`**

Use port **8080** here even if you changed `PORT`. The tunnel container talks to the app over the Docker network,
where the app always listens on 8080.

### 4. Run cloudflared next to the app

Create `docker-compose.override.yml` next to `docker-compose.yml` (compose picks it up automatically):

```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on: [localds]
```

If you use `COMPOSE_FILE` in `.env` (the iGPU setup does), append `:docker-compose.override.yml` to it, because an
explicit `COMPOSE_FILE` disables the automatic override.

Add to `.env`:

```
CLOUDFLARE_TUNNEL_TOKEN=<the token>
BASE_URL=https://ds.example.com
COOKIE_SECURE=true
BIND_ADDRESS=127.0.0.1
```

`BIND_ADDRESS=127.0.0.1` makes the tunnel the only way in from other machines.

```bash
docker compose up -d
```

### 5. Put a login gate in front (strongly recommended)

*Zero Trust → Access → Applications → Add → Self-hosted*:

- Domain: `ds.example.com`
- Policy: *Allow*, include *Emails*: yours and your friend's
- Login method: *One-time PIN* (a code by email; no extra accounts)
- Session duration: about a month, so the installed app doesn't keep asking

Bots and scanners then never reach the app's own login page.

### Known issue: home-screen install behind Cloudflare Access

Browsers fetch the web app manifest **without cookies** by default, so Access may answer it with a login redirect
and the "Add to Home Screen" install fails or uses the wrong name/icon. Fix: in `app/static/index.html` change

```html
<link rel="manifest" href="/manifest.webmanifest">
```

to

```html
<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">
```

(and bump the version strings as described in [FRONTEND.md](FRONTEND.md#shipping-frontend-changes)).

### Note on video and Cloudflare's terms

Cloudflare's free plan discourages serving large amounts of video through its network. Two people watching Shorts
is small, but it is a grey area. Tailscale avoids the question.

---

## Why `BASE_URL`, `COOKIE_SECURE` and `FORWARDED_ALLOW_IPS` matter

- **`BASE_URL`** is used to build invite links. Without it, the link uses whatever host the admin's browser used.
- **`COOKIE_SECURE=true`** marks session cookies as HTTPS-only. `auto` (the default) does this when the request
  arrives over HTTPS, which uvicorn learns from the proxy's `X-Forwarded-Proto` header.
- **`FORWARDED_ALLOW_IPS`** lists the proxies whose `X-Forwarded-For`/`-Proto` headers are trusted. The default
  covers localhost, private networks (Docker's network included) and Tailscale's `100.64.0.0/10`. The login rate
  limiter uses the client IP from these headers, so only trust your own proxies.
