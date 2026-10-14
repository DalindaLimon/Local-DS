#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh.
#
#   scripts/restore.sh backups/localds-20261013-120000.tar.gz
#
# The current data folder is moved aside (data.before-restore-<time>), never deleted.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE="${1:-}"
[ -n "$ARCHIVE" ] && [ -f "$ARCHIVE" ] || { echo "Usage: $0 <backup.tar.gz>" >&2; exit 1; }
ARCHIVE="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"

tar -tzf "$ARCHIVE" | grep -qx './swipefeed.db' || { echo "Not a Local DS backup: $ARCHIVE" >&2; exit 1; }

env_get() { [ -f "$ROOT/.env" ] && grep -E "^$1=" "$ROOT/.env" | tail -n1 | cut -d= -f2- || true; }
DATA="$(env_get DATA_PATH)"
DATA="${DATA:-./data}"
case "$DATA" in /*) ;; *) DATA="$ROOT/${DATA#./}" ;; esac

if [ -t 0 ]; then
    read -r -p "Restore $ARCHIVE into $DATA? The app will restart. [y/N] " ans
    [[ "$ans" =~ ^[Yy] ]] || { echo "Aborted."; exit 1; }
fi

echo "==> Stopping the app"
(cd "$ROOT" && docker compose stop localds) || true

if [ -d "$DATA" ]; then
    SAVED="${DATA%/}.before-restore-$(date +%Y%m%d-%H%M%S)"
    mv "$DATA" "$SAVED"
    echo "    current data moved to $SAVED"
fi
mkdir -p "$DATA"
tar -C "$DATA" -xzf "$ARCHIVE"
chown -R 1000:1000 "$DATA" 2>/dev/null || true

echo "==> Starting the app"
(cd "$ROOT" && docker compose up -d)
echo "Done. Missing video files (e.g. from a --no-videos backup) are marked expired automatically on startup."
