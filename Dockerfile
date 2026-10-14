# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ARG TARGETARCH
LABEL org.opencontainers.image.title="Local DS" \
      org.opencontainers.image.description="Self-hosted feed + YouTube Shorts reels for a few friends" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    DATA_DIR=/data

# ffmpeg for remux/encode + thumbnails. On amd64 also the Intel VAAPI driver (non-free build has
# the H.264 encoder) so an iGPU passed through as /dev/dri can encode. Everything works without it.
RUN set -eux; \
    sed -i 's/^Components: main$/Components: main non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources; \
    apt-get update; \
    apt-get install -y --no-install-recommends ffmpeg ca-certificates mesa-va-drivers; \
    if [ "${TARGETARCH:-amd64}" = "amd64" ]; then \
      apt-get install -y --no-install-recommends intel-media-va-driver-non-free i965-va-driver vainfo || true; \
    fi; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd --gid 1000 app; \
    useradd --uid 1000 --gid app --groups video --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY requirements.txt .
# The venv is owned by the app user so the daily yt-dlp self-update can run without root.
RUN python -m venv /opt/venv \
    && pip install -r requirements.txt "yt-dlp[default]" \
    && chown -R app:app /opt/venv

COPY app ./app
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh && mkdir -p /data && chown app:app /data

EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["serve"]
