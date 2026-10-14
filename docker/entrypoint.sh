#!/bin/sh
# Container entrypoint: fix /data ownership, give the app user access to /dev/dri, drop root.
set -eu

APP_USER=app

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data
    # Only chown when needed (a big /data with many files would be slow to walk every start).
    if [ "$(stat -c %u /data)" != "1000" ]; then
        echo "entrypoint: fixing ownership of /data"
        chown -R 1000:1000 /data
    fi
    # Join whatever group owns the GPU render node (its gid differs between hosts).
    for dev in /dev/dri/renderD*; do
        [ -e "$dev" ] || continue
        gid="$(stat -c %g "$dev")"
        if ! getent group "$gid" >/dev/null 2>&1; then
            groupadd --gid "$gid" "render$gid"
        fi
        usermod -aG "$(getent group "$gid" | cut -d: -f1)" "$APP_USER"
    done
    exec setpriv --reuid=1000 --regid=1000 --init-groups "$0" "$@"
fi

if [ "${1:-serve}" = "serve" ]; then
    exec uvicorn --factory app.main:create_app \
        --host 0.0.0.0 --port 8080 \
        --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10}" \
        --no-access-log --timeout-graceful-shutdown 10
fi
exec "$@"
