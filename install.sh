#!/usr/bin/env bash
# Local DS installer for a Debian 12 LXC (or VM). Idempotent: safe to run again.
#
#   curl -fsSL https://raw.githubusercontent.com/DalindaLimon/local-ds/main/install.sh | bash
#   ./install.sh [--yes] [--port 8080] [--retention 7] [--demo]
#   ./install.sh --update
#   ./install.sh --uninstall [--purge]
set -euo pipefail

# ----------------------------------------------------------------------------- settings
REPO="${REPO:-DalindaLimon/local-ds}"   # <owner>/<repo> on GitHub
BRANCH="${BRANCH:-main}"
APP_NAME="localds"
INSTALL_DIR="${INSTALL_DIR:-}"
MIN_FREE_GB=5
HEALTH_TIMEOUT=240

ASSUME_YES=0
MODE="install"
PURGE=0
DEMO=0
OPT_PORT=""
OPT_RETENTION=""

# ----------------------------------------------------------------------------- output
if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_BLUE=$'\033[34m'
else
    C_RESET=""; C_BOLD=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_BLUE=""
fi
step() { printf '%s==>%s %s%s%s\n' "$C_BLUE" "$C_RESET" "$C_BOLD" "$*" "$C_RESET"; }
ok()   { printf '  %s✔%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '  %s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()  { printf '%sError:%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Local DS installer

Usage: install.sh [options]

  (no option)        Install or repair: Docker, app files, .env, start the container
  --update           Pull the latest code (or image) and restart, keeping all data
  --uninstall        Stop and remove the container (keeps ${INSTALL_DIR:-/opt/$APP_NAME}/data)
  --purge            With --uninstall: also delete the data folder (asks for confirmation)
  --yes, -y          Non-interactive: accept defaults, never prompt
  --port N           Host port (default 8080)
  --retention N      Days to keep Short video files (default 7)
  --demo             Load demo posts and Shorts after starting
  --dir PATH         Install directory (default /opt/$APP_NAME, or this clone)
  -h, --help         Show this help

Environment: REPO=$REPO BRANCH=$BRANCH INSTALL_DIR=<path>
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        -y|--yes) ASSUME_YES=1 ;;
        --update) MODE="update" ;;
        --uninstall) MODE="uninstall" ;;
        --purge) PURGE=1 ;;
        --demo) DEMO=1 ;;
        --port) OPT_PORT="${2:-}"; shift ;;
        --retention) OPT_RETENTION="${2:-}"; shift ;;
        --dir) INSTALL_DIR="${2:-}"; shift ;;
        *) usage; die "Unknown option: $1" ;;
    esac
    shift
done

if [ -n "$OPT_PORT" ] && ! [[ "$OPT_PORT" =~ ^[0-9]{2,5}$ ]]; then die "--port must be a number"; fi
if [ -n "$OPT_RETENTION" ] && ! [[ "$OPT_RETENTION" =~ ^[0-9]+([.][0-9]+)?$ ]]; then die "--retention must be a number"; fi

# Interactive only when a terminal is available (works with curl | bash via /dev/tty).
INTERACTIVE=0
if [ "$ASSUME_YES" -eq 0 ] && { [ -t 0 ] || [ -r /dev/tty ]; } && [ -z "${CI:-}" ]; then
    if { true </dev/tty; } 2>/dev/null; then INTERACTIVE=1; fi
fi

ask() { # ask "Question" default -> echo answer
    local q="$1" def="$2" ans=""
    if [ "$INTERACTIVE" -eq 1 ]; then
        read -r -p "  $q [$def]: " ans </dev/tty || true
    fi
    printf '%s' "${ans:-$def}"
}

# ----------------------------------------------------------------------------- location
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
FROM_CLONE=0
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/docker-compose.yml" ] && [ -d "$SCRIPT_DIR/app" ]; then
    FROM_CLONE=1
    INSTALL_DIR="${INSTALL_DIR:-$SCRIPT_DIR}"
fi
INSTALL_DIR="${INSTALL_DIR:-/opt/$APP_NAME}"

# ----------------------------------------------------------------------------- helpers
in_lxc() {
    if command -v systemd-detect-virt >/dev/null 2>&1; then
        [ "$(systemd-detect-virt -c 2>/dev/null || true)" = "lxc" ] && return 0
    fi
    grep -qa 'container=lxc' /proc/1/environ 2>/dev/null
}

lxc_help() {
    cat >&2 <<'EOF'

  Docker cannot run inside this LXC container yet. On the Proxmox HOST run
  (replace 101 with this container's ID, shown in the Proxmox UI):

      pct set 101 -features nesting=1,keyctl=1
      pct reboot 101

  For an unprivileged container that is all you need. Then run this installer again.
  Alternatively in the UI: Container -> Options -> Features -> tick "keyctl" and "Nesting".

EOF
}

set_env() { # set_env KEY VALUE  (in $INSTALL_DIR/.env)
    local key="$1" val="$2" file="$INSTALL_DIR/.env"
    if grep -qE "^${key}=" "$file"; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$file"
    else
        printf '%s=%s\n' "$key" "$val" >>"$file"
    fi
}

get_env() { # get_env KEY -> value or empty
    local file="$INSTALL_DIR/.env"
    [ -f "$file" ] || return 0
    grep -E "^$1=" "$file" | tail -n1 | cut -d= -f2- || true
}

compose() { (cd "$INSTALL_DIR" && docker compose "$@"); }

host_ip() {
    local ip=""
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || true
    printf '%s' "${ip:-localhost}"
}

# ----------------------------------------------------------------------------- preflight
preflight() {
    step "Pre-flight checks"
    [ "$(id -u)" -eq 0 ] || die "Run as root (inside the LXC: just log in as root, or use sudo)."
    ok "running as root"

    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        if [ "${ID:-}" = "debian" ] && [ "${VERSION_ID:-}" = "12" ]; then
            ok "Debian 12 (bookworm)"
        elif [ "${ID:-}" = "debian" ] || [ "${ID_LIKE:-}" = "debian" ] || [ "${ID:-}" = "ubuntu" ]; then
            warn "Tested on Debian 12; found ${PRETTY_NAME:-unknown}. Continuing."
        else
            die "Unsupported OS: ${PRETTY_NAME:-unknown}. Use a Debian 12 LXC."
        fi
    fi

    if in_lxc; then ok "running in an LXC container"; fi

    local parent free_kb
    parent="$INSTALL_DIR"
    while [ ! -d "$parent" ]; do parent="$(dirname "$parent")"; done
    free_kb="$(df -Pk "$parent" | awk 'NR==2 {print $4}')"
    if [ "$free_kb" -lt $((MIN_FREE_GB * 1024 * 1024)) ]; then
        die "Only $((free_kb / 1024 / 1024)) GB free on $parent; need at least ${MIN_FREE_GB} GB (videos need space)."
    fi
    ok "$((free_kb / 1024 / 1024)) GB free on $parent"
}

install_packages() {
    local missing=()
    for p in curl ca-certificates git openssl gnupg; do
        dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        step "Installing base packages: ${missing[*]}"
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}" >/dev/null
    fi
    ok "base packages present"
}

install_docker() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        ok "Docker $(docker --version | awk '{print $3}' | tr -d ,) with compose plugin already installed"
    else
        step "Installing Docker Engine + compose plugin from Docker's apt repository"
        # shellcheck disable=SC1091
        . /etc/os-release
        local distro="${ID:-debian}"
        [ "$distro" = "ubuntu" ] || distro="debian"
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL "https://download.docker.com/linux/${distro}/gpg" -o /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc
        printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
            "$(dpkg --print-architecture)" "$distro" "${VERSION_CODENAME:-bookworm}" >/etc/apt/sources.list.d/docker.list
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
            docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
        systemctl enable --now docker >/dev/null 2>&1 || true
        ok "Docker installed"
    fi

    step "Checking that Docker can run containers here"
    if ! systemctl is-active --quiet docker 2>/dev/null; then
        systemctl start docker 2>/dev/null || true
        sleep 2
    fi
    local out=""
    if ! out="$(docker run --rm hello-world 2>&1)"; then
        printf '%s\n' "$out" | tail -n 5 >&2
        if in_lxc; then lxc_help; fi
        die "Docker is installed but cannot start containers."
    fi
    ok "Docker works"
}

fetch_code() {
    if [ "$FROM_CLONE" -eq 1 ] && [ "$INSTALL_DIR" = "$SCRIPT_DIR" ]; then
        ok "using this checkout: $INSTALL_DIR"
        return
    fi
    if [ -d "$INSTALL_DIR/.git" ]; then
        step "Updating code in $INSTALL_DIR"
        git -C "$INSTALL_DIR" pull --ff-only
    elif [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
        ok "code present in $INSTALL_DIR (not a git checkout, leaving as is)"
    else
        [ "$REPO" != "YOUR_GITHUB_USER/local-ds" ] || die "Set REPO=<owner>/<repo> (edit the top of install.sh or export REPO)."
        step "Cloning https://github.com/$REPO into $INSTALL_DIR"
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone --depth 1 --branch "$BRANCH" "https://github.com/$REPO.git" "$INSTALL_DIR"
    fi
    fix_modes
}

# Files uploaded through the GitHub web page lose their executable bit; restore it after every clone/pull.
fix_modes() {
    chmod +x "$INSTALL_DIR/install.sh" "$INSTALL_DIR"/scripts/*.sh "$INSTALL_DIR/docker/entrypoint.sh" 2>/dev/null || true
}

configure() {
    step "Configuring"
    local env="$INSTALL_DIR/.env"
    if [ ! -f "$env" ]; then
        cp "$INSTALL_DIR/.env.example" "$env"
        chmod 600 "$env"
        set_env SECRET_KEY "$(openssl rand -base64 48 | tr -d '\n/+=')"
        local port retention
        port="${OPT_PORT:-$(ask "Port to listen on" 8080)}"
        retention="${OPT_RETENTION:-$(ask "Days to keep Short videos" 7)}"
        [[ "$port" =~ ^[0-9]{2,5}$ ]] || die "Invalid port: $port"
        [[ "$retention" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "Invalid retention: $retention"
        set_env PORT "$port"
        set_env RETENTION_DAYS "$retention"
        ok "created .env with a random SECRET_KEY"
    else
        ok ".env exists, keeping it"
        [ -z "$OPT_PORT" ] || set_env PORT "$OPT_PORT"
        [ -z "$OPT_RETENTION" ] || set_env RETENTION_DAYS "$OPT_RETENTION"
    fi

    if [ -e /dev/dri/renderD128 ]; then
        set_env COMPOSE_FILE "docker-compose.yml:docker-compose.gpu.yml"
        [ "$(get_env HWACCEL)" = "none" ] || set_env HWACCEL auto
        ok "GPU found at /dev/dri/renderD128: hardware encoding enabled"
    else
        if grep -q '^COMPOSE_FILE=' "$env"; then sed -i '/^COMPOSE_FILE=/d' "$env"; fi
        [ "$(get_env HWACCEL)" != "vaapi" ] || set_env HWACCEL auto
        ok "no /dev/dri: using software encoding (see README to pass the iGPU through)"
    fi

    local data_path
    data_path="$(get_env DATA_PATH)"
    data_path="${data_path:-./data}"
    case "$data_path" in /*) ;; *) data_path="$INSTALL_DIR/${data_path#./}" ;; esac
    mkdir -p "$data_path"
    chown 1000:1000 "$data_path" 2>/dev/null || true
    ok "data folder: $data_path"
}

start() {
    local image
    image="$(get_env IMAGE)"
    if [ -n "$image" ]; then
        step "Pulling $image"
        compose pull
        compose up -d --no-build --remove-orphans
    else
        step "Building and starting the container (first build takes a few minutes)"
        compose up -d --build --remove-orphans
    fi
}

wait_healthy() {
    step "Waiting for the app to become healthy"
    local port i
    port="$(get_env PORT)"
    port="${port:-8080}"
    for ((i = 0; i < HEALTH_TIMEOUT; i += 3)); do
        if curl -fsS "http://127.0.0.1:${port}/healthz" >/dev/null 2>&1; then
            ok "healthy"
            return 0
        fi
        sleep 3
    done
    compose logs --tail 40 >&2 || true
    die "The app did not become healthy within ${HEALTH_TIMEOUT}s (logs above)."
}

summary() {
    local port ip
    port="$(get_env PORT)"
    port="${port:-8080}"
    ip="$(host_ip)"
    printf '\n%s%sLocal DS is running.%s\n\n' "$C_BOLD" "$C_GREEN" "$C_RESET"
    printf '  Open:          http://%s:%s\n' "$ip" "$port"
    printf '  First run:     the page asks you to create the admin account (one time only)\n'
    printf '  Install dir:   %s\n' "$INSTALL_DIR"
    printf '  Logs:          cd %s && docker compose logs -f\n' "$INSTALL_DIR"
    printf '  Update:        %s/install.sh --update\n' "$INSTALL_DIR"
    printf '  Backup:        %s/scripts/backup.sh\n\n' "$INSTALL_DIR"
    printf '  Share with a friend safely via Tailscale or a Cloudflare Tunnel (see README).\n\n'
}

# ----------------------------------------------------------------------------- modes
do_install() {
    preflight
    install_packages
    install_docker
    fetch_code
    configure
    start
    wait_healthy
    if [ "$DEMO" -eq 1 ]; then
        step "Loading demo data"
        compose exec -T -u 1000:1000 "$APP_NAME" python -m app.seed || warn "demo seed failed"
    fi
    summary
}

do_update() {
    [ -f "$INSTALL_DIR/docker-compose.yml" ] || die "No installation found in $INSTALL_DIR"
    [ "$(id -u)" -eq 0 ] || die "Run as root"
    if [ -d "$INSTALL_DIR/.git" ]; then
        step "Pulling latest code"
        git -C "$INSTALL_DIR" pull --ff-only
    fi
    fix_modes
    configure
    start
    wait_healthy
    docker image prune -f >/dev/null 2>&1 || true
    ok "updated; data in /data was not touched"
    summary
}

do_uninstall() {
    [ "$(id -u)" -eq 0 ] || die "Run as root"
    [ -f "$INSTALL_DIR/docker-compose.yml" ] || die "No installation found in $INSTALL_DIR"
    step "Stopping and removing the container"
    compose down --remove-orphans || true
    ok "container removed"
    local data_path
    data_path="$(get_env DATA_PATH)"
    data_path="${data_path:-./data}"
    case "$data_path" in /*) ;; *) data_path="$INSTALL_DIR/${data_path#./}" ;; esac
    if [ "$PURGE" -eq 1 ]; then
        if [ "$INTERACTIVE" -eq 1 ]; then
            local ans=""
            read -r -p "  Type DELETE to permanently remove $data_path (database, comments, videos): " ans </dev/tty || true
            [ "$ans" = "DELETE" ] || die "Aborted; data kept."
        elif [ "$ASSUME_YES" -ne 1 ]; then
            die "--purge needs a terminal to confirm, or --yes"
        fi
        rm -rf -- "$data_path"
        ok "deleted $data_path"
    else
        ok "kept your data in $data_path (use --purge to delete it)"
    fi
}

case "$MODE" in
    install) do_install ;;
    update) do_update ;;
    uninstall) do_uninstall ;;
esac
