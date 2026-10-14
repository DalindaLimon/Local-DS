#!/usr/bin/env bash
# Back up Local DS's /data folder to a timestamped .tar.gz.
#
#   scripts/backup.sh                 # full backup into ./backups
#   scripts/backup.sh --no-videos     # skip Short video files (they expire anyway; much smaller)
#   scripts/backup.sh --dest /mnt/nas/localds
#
# The database is copied with SQLite's online backup API while the app keeps running,
# so the backup is consistent without stopping anything.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/backups"
NO_VIDEOS=0
KEEP=0

usage() {
    sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
    echo "Options: --no-videos  --dest DIR  --keep N (delete older backups, keep the newest N)"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --no-videos) NO_VIDEOS=1 ;;
        --dest) DEST="${2:?--dest needs a path}"; shift ;;
        --keep) KEEP="${2:?--keep needs a number}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
    shift
done

env_get() { [ -f "$ROOT/.env" ] && grep -E "^$1=" "$ROOT/.env" | tail -n1 | cut -d= -f2- || true; }
DATA="$(env_get DATA_PATH)"
DATA="${DATA:-./data}"
case "$DATA" in /*) ;; *) DATA="$ROOT/${DATA#./}" ;; esac
[ -d "$DATA" ] || { echo "Data folder not found: $DATA" >&2; exit 1; }

mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$DEST/localds-$STAMP.tar.gz"
SNAP=".backup-$STAMP.db"

cleanup() { rm -f "$DATA/$SNAP"; }
trap cleanup EXIT

echo "==> Snapshotting the database"
if (cd "$ROOT" && docker compose ps --status running --services 2>/dev/null | grep -qx localds); then
    (cd "$ROOT" && docker compose exec -T localds python -c \
        "import sqlite3; s=sqlite3.connect('/data/swipefeed.db'); d=sqlite3.connect('/data/$SNAP'); s.backup(d); d.close(); s.close()")
elif command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DATA/swipefeed.db" ".backup '$DATA/$SNAP'"
else
    python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d)" \
        "$DATA/swipefeed.db" "$DATA/$SNAP"
fi

echo "==> Writing $OUT"
excludes=(--exclude=./swipefeed.db --exclude=./swipefeed.db-wal --exclude=./swipefeed.db-shm --exclude=./tmp)
if [ "$NO_VIDEOS" -eq 1 ]; then excludes+=(--exclude=./videos); fi
tar -C "$DATA" -czf "$OUT" "${excludes[@]}" \
    --transform "s|^\./$SNAP\$|./swipefeed.db|" .
chmod 600 "$OUT"
echo "    $(du -h "$OUT" | cut -f1)  $OUT"

if [ "$KEEP" -gt 0 ]; then
    shopt -s nullglob
    all=("$DEST"/localds-*.tar.gz)  # names are timestamped, so name order is age order
    mapfile -t old < <(printf '%s\n' "${all[@]}" | sort -r | tail -n +"$((KEEP + 1))")
    for f in "${old[@]}"; do rm -f -- "$f"; echo "    removed old backup $f"; done
fi
echo "Done."
