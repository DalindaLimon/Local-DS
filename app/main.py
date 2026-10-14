"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__, api_ai, api_auth, api_feed, api_sources, jobs, retention, settings_store
from app.config import Settings, load_settings
from app.db import connect, init_db
from app.security import CSRF_COOKIE, CSRF_HEADER, LoginRateLimiter, csrf_ok

log = logging.getLogger("localds")
STATIC_DIR = Path(__file__).parent / "static"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

CSP = (
    "default-src 'self'; img-src 'self' https: data: blob:; media-src 'self' blob:; "
    "script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self'; "
    "manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def startup_maintenance(settings: Settings) -> None:
    """Reconcile disk vs. database, then run retention once."""
    conn = connect(settings.db_path)
    try:
        retention.reconcile(conn, settings)
        retention.cleanup(conn, settings)
    finally:
        conn.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    setup_logging(settings.log_level)
    settings.ensure_dirs()
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    try:
        settings_store.init(settings, conn)  # admin-page overrides on top of .env
    finally:
        conn.close()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("Local DS %s starting, data in %s", __version__, settings.data_dir)
        startup_maintenance(settings)
        sched = jobs.start_scheduler(settings) if settings.scheduler_enabled else None
        yield
        if sched:
            sched.shutdown(wait=False)
            jobs.scheduler = None

    app = FastAPI(title="Local DS", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.login_limiter = LoginRateLimiter()

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        path = request.url.path
        unsafe = request.method in UNSAFE_METHODS and path.startswith("/api/")
        if unsafe and not csrf_ok(request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER)):
            return JSONResponse({"detail": "CSRF check failed. Reload the page."}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not path.startswith("/media/"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.include_router(api_auth.router)
    app.include_router(api_feed.router)
    app.include_router(api_sources.router)
    app.include_router(api_ai.router)

    @app.get("/healthz")
    def healthz():
        conn = connect(settings.db_path)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return {"status": "ok", "version": __version__}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
        )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app
