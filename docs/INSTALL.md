# Installation

Local DS runs as **one Docker container** with all state in one folder (`/data` inside the container,
`./data` next to `docker-compose.yml` on the host by default). Anything that can run Docker can run it.
The reference setup is an **unprivileged Debian 12 LXC on Proxmox**.

- [Requirements](#requirements)
- [Option A: Proxmox LXC with the installer](#option-a-proxmox-lxc-with-the-installer)
- [Option B: any Docker host, by hand](#option-b-any-docker-host-by-hand)
- [First run](#first-run)
- [Optional: iGPU hardware encoding](#optional-igpu-hardware-encoding)
- [What the container does on start](#what-the-container-does-on-start)

---

## Requirements

| Resource | Recommendation |
|---|---|
| CPU | 2 cores (transcoding is the only heavy work, and most Shorts only need a remux) |
| RAM | 2–4 GB (the container is capped at `MEM_LIMIT=2g`) |
| Disk | 16–32 GB. Video files are deleted after 7 days by default; a few hundred Shorts take 1–3 GB. |
| Software | Docker Engine with the compose plugin. The image contains Python, ffmpeg and yt-dlp. |
| Network | Outbound HTTPS to YouTube, Reddit and your feeds. **No inbound port needs to be opened.** |

## Option A: Proxmox LXC with the installer

### 1. Create the container

Docker inside an LXC needs two container features: **nesting** and **keyctl**.

**Helper script (on the Proxmox host shell):**

```bash
curl -fsSLO https://raw.githubusercontent.com/YOUR_GITHUB_USER/local-ds/main/scripts/proxmox-create-lxc.sh
bash proxmox-create-lxc.sh --gpu        # creates the CT, passes the iGPU through, runs install.sh inside
```

**By hand:**

1. Create a CT from the `debian-12-standard` template with *Unprivileged container* ticked.
2. On the Proxmox host, enable the features (replace `101` with your CT ID) and restart the CT:

   ```bash
   pct set 101 -features nesting=1,keyctl=1
   pct reboot 101
   ```

   (Or in the UI: *CT → Options → Features → Nesting + keyctl*.)

### 2. Run the installer

Inside the LXC, as root:

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB_USER/local-ds/main/install.sh | bash
```

The installer is **idempotent** (safe to run again). It:

1. checks you are root on Debian 12, that there is enough disk, and that Docker can start containers (if
   nesting/keyctl are off it prints the exact `pct set` command and stops);
2. installs Docker Engine and the compose plugin from Docker's apt repository if missing;
3. clones the repo to `/opt/localds` (override with `INSTALL_DIR=...` or `--dir`);
4. creates `.env` from `.env.example` with a random `SECRET_KEY`; it never overwrites an existing `.env` or data;
5. asks for the port and video retention days (skip with `--yes`);
6. enables hardware encoding if `/dev/dri/renderD128` exists;
7. builds and starts the container, waits for `/healthz`, and prints the URL.

| Flag | Meaning |
|---|---|
| `--yes`, `-y` | No questions, accept defaults |
| `--port N` | Host port (default 8080) |
| `--retention N` | Days to keep Short video files (default 7) |
| `--demo` | Load demo posts and Shorts after starting |
| `--dir PATH` | Install directory |
| `--update` | Pull the latest code (or image) and restart, keeping all data |
| `--uninstall` | Stop and remove the container; keeps the data folder |
| `--uninstall --purge` | Also delete the data folder (asks you to type `DELETE`) |

To install Docker yourself instead (Docker's official repository):

```bash
apt-get update && apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
docker run --rm hello-world
```

## Option B: any Docker host, by hand

```bash
git clone https://github.com/YOUR_GITHUB_USER/local-ds.git /opt/localds && cd /opt/localds
cp .env.example .env
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n/+=')|" .env
mkdir -p data && chown 1000:1000 data
docker compose up -d --build
docker compose logs -f          # wait for "Application startup complete"
```

If port 8080 is taken on that machine (another app already uses it), set `PORT=8081` (or any free port) in
`.env` and run `docker compose up -d` again. The app inside the container always listens on 8080; `PORT` only
changes the port on the host.

**Using the prebuilt image instead of building:** set `IMAGE=ghcr.io/YOUR_GITHUB_USER/local-ds:latest` in
`.env`, then `docker compose pull && docker compose up -d`. Images are multi-arch (amd64/arm64) and are built by
GitHub Actions for every `v*` tag.

## First run

1. Open `http://<host-ip>:<PORT>`. The first visit shows a one-time **setup page**: create the admin account.
2. You land on **Discover**: tap *Add* on a few starter sources, or go to **More → Sources** and paste your own.
3. Posts appear within a minute. Shorts take a few minutes (each channel's newest 15 are downloaded and converted).
4. Invite your friend: **More → Admin → Create invite link**.
5. Set up HTTPS access for phones: [REMOTE_ACCESS.md](REMOTE_ACCESS.md).

**Demo data** (posts, generated test videos, and the users `demo`/`demo-password` (admin) and
`friend`/`friend-password` if no users exist yet):

```bash
docker compose exec -u 1000:1000 localds python -m app.seed --users
docker compose exec -u 1000:1000 localds python -m app.seed --remove   # remove it again
```

Always run commands inside the container with `-u 1000:1000`. Files created as root inside `/data` would not be
writable by the app afterwards.

## Optional: iGPU hardware encoding

Most Shorts are already H.264 and only need a remux (no re-encoding), so this is a nice-to-have. With an Intel iGPU
(e.g. the UHD 730 in 11th-gen Core CPUs) the re-encodes use VAAPI instead of the CPU.

1. On the Proxmox host, check `ls -l /dev/dri` shows `renderD128`.
2. Find the `render` group ID inside the CT: `pct exec <CTID> -- getent group render` (e.g. `104`).
3. Pass the device through (Proxmox VE 8.1+), then reboot the CT:

   ```bash
   pct set <CTID> -dev0 /dev/dri/renderD128,gid=104
   pct reboot <CTID>
   ```

   Older Proxmox: add to `/etc/pve/lxc/<CTID>.conf`:

   ```
   lxc.cgroup2.devices.allow: c 226:128 rwm
   lxc.mount.entry: /dev/dri/renderD128 dev/dri/renderD128 none bind,optional,create=file
   ```

4. Re-run `bash install.sh` (or `--update`). It detects `/dev/dri/renderD128` and sets
   `COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml` and `HWACCEL=auto` in `.env`.
   `docker-compose.gpu.yml` simply maps `/dev/dri` into the container.
5. Check: Admin page → *Encoding* shows `/dev/dri/renderD128`, and
   `docker compose exec localds vainfo --display drm --device /dev/dri/renderD128` lists `VAEntrypointEncSlice`.

If VAAPI fails for a video, it falls back to software (libx264) automatically and logs a warning.

## What the container does on start

`docker/entrypoint.sh` runs as root only long enough to:

1. create `/data` and `chown` it to uid 1000 if it isn't already;
2. add the `app` user to whatever group owns `/dev/dri/renderD*` (the group ID differs between hosts);
3. drop to uid/gid 1000 and start `uvicorn --factory app.main:create_app` on port 8080, trusting
   `X-Forwarded-*` headers only from `FORWARDED_ALLOW_IPS`.

The app then creates/migrates the database, reconciles files against the database, runs one cleanup, and starts
the background jobs. See [ARCHITECTURE.md](ARCHITECTURE.md#startup-sequence) for details.
