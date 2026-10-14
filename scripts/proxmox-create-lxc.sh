#!/usr/bin/env bash
# OPTIONAL helper — run this on the Proxmox HOST (not inside a container).
# Creates an unprivileged Debian 12 LXC ready for Docker (nesting + keyctl), optionally passes
# the iGPU render node through, then runs install.sh inside it.
#
#   bash proxmox-create-lxc.sh [--ctid 120] [--hostname localds] [--storage local-lvm] [--disk 32]
#                              [--memory 3072] [--cores 2] [--bridge vmbr0] [--gpu] [--repo owner/repo]
#
# You can also create the container by hand; see README "LXC prerequisites".
set -euo pipefail

CTID=""
HOSTNAME_="localds"
STORAGE="local-lvm"
TEMPLATE_STORAGE="local"
DISK_GB=32
MEMORY=3072
SWAP=512
CORES=2
BRIDGE="vmbr0"
GPU=0
REPO="${REPO:-YOUR_GITHUB_USER/local-ds}"

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --ctid) CTID="$2"; shift ;;
        --hostname) HOSTNAME_="$2"; shift ;;
        --storage) STORAGE="$2"; shift ;;
        --template-storage) TEMPLATE_STORAGE="$2"; shift ;;
        --disk) DISK_GB="$2"; shift ;;
        --memory) MEMORY="$2"; shift ;;
        --cores) CORES="$2"; shift ;;
        --bridge) BRIDGE="$2"; shift ;;
        --gpu) GPU=1 ;;
        --repo) REPO="$2"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
    shift
done

command -v pct >/dev/null 2>&1 || { echo "This must run on a Proxmox VE host (pct not found)." >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "Run as root." >&2; exit 1; }
CTID="${CTID:-$(pvesh get /cluster/nextid)}"

echo "==> Finding the Debian 12 template"
pveam update >/dev/null
TEMPLATE="$(pveam available --section system | awk '/debian-12-standard/ {print $2}' | sort -V | tail -n1)"
[ -n "$TEMPLATE" ] || { echo "No debian-12-standard template available." >&2; exit 1; }
if ! pveam list "$TEMPLATE_STORAGE" | grep -q "$TEMPLATE"; then
    pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
fi

echo "==> Creating CT $CTID ($HOSTNAME_)"
pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
    --hostname "$HOSTNAME_" --unprivileged 1 --features nesting=1,keyctl=1 \
    --cores "$CORES" --memory "$MEMORY" --swap "$SWAP" \
    --rootfs "$STORAGE:$DISK_GB" --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp" \
    --onboot 1 --ostype debian
pct start "$CTID"

echo "==> Waiting for network"
for _ in $(seq 1 30); do
    if pct exec "$CTID" -- sh -c 'getent hosts deb.debian.org >/dev/null'; then break; fi
    sleep 2
done

if [ "$GPU" -eq 1 ]; then
    if [ -e /dev/dri/renderD128 ]; then
        echo "==> Passing /dev/dri/renderD128 through"
        RGID="$(pct exec "$CTID" -- getent group render | cut -d: -f3)"
        RGID="${RGID:-104}"
        pct set "$CTID" --dev0 "/dev/dri/renderD128,gid=$RGID"
        pct reboot "$CTID"
        sleep 8
    else
        echo "!! /dev/dri/renderD128 not found on the host; skipping GPU passthrough" >&2
    fi
fi

echo "==> Running install.sh inside the container"
pct exec "$CTID" -- bash -c "apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/../install.sh" ]; then
    pct push "$CTID" "$SCRIPT_DIR/../install.sh" /root/install.sh --perms 0755
    pct exec "$CTID" -- env REPO="$REPO" bash /root/install.sh --yes
else
    pct exec "$CTID" -- bash -c "curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh | REPO=$REPO bash -s -- --yes"
fi

IP="$(pct exec "$CTID" -- hostname -I | awk '{print $1}')"
echo
echo "Done. Local DS runs in CT $CTID: http://$IP:8080"
