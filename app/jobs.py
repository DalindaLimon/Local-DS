"""Background jobs: scheduler wiring plus one-off jobs triggered from the UI."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import feeds, icons, personalization, retention, shorts, uploads
from app.config import Settings
from app.db import connect, kv_set

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="job")
_status_lock = threading.Lock()
job_status: dict[str, dict] = {}
scheduler: BackgroundScheduler | None = None


def _run(name: str, settings: Settings, fn: Callable, *args):
    t0 = time.time()
    with _status_lock:
        job_status[name] = {**job_status.get(name, {}), "running": True, "started": t0}
    status = {"ok": False, "error": None, "result": None}
    conn = connect(settings.db_path)
    try:
        result = fn(conn, settings, *args)
        status.update(ok=True, result=str(result)[:200])
        return result
    except Exception as exc:
        log.exception("job %s failed", name)
        status["error"] = str(exc)[:300]
        return None
    finally:
        with _status_lock:
            job_status[name] = {"running": False, "last_run": t0, "took": round(time.time() - t0, 1), **status}
        try:
            kv_set(conn, f"job:{name}", str(t0))
        except Exception:  # pragma: no cover - db closed or locked
            log.debug("could not store job time", exc_info=True)
        conn.close()


def rss_job(settings: Settings, source_id: int | None = None):
    return _run("rss", settings, feeds.refresh_all, source_id)


def shorts_job(settings: Settings, source_id: int | None = None):
    return _run("shorts", settings, shorts.fetch_all_shorts, source_id)


def cleanup_job(settings: Settings):
    def both(conn, s):
        rec = retention.reconcile(conn, s)
        cl = retention.cleanup(conn, s)
        up = uploads.cleanup(conn, s)
        return {**rec, **cl, **up}

    return _run("cleanup", settings, both)


def weights_job(settings: Settings):
    return _run("weights", settings, personalization.recompute_all)


def ytdlp_job(settings: Settings):
    return _run("ytdlp_update", settings, shorts.update_ytdlp)


def icons_job(settings: Settings, source_id: int | None = None):
    return _run("icons", settings, icons.refresh, source_id)


def submit(fn: Callable, *args) -> None:
    _executor.submit(fn, *args)


def start_scheduler(settings: Settings) -> BackgroundScheduler:
    sched = BackgroundScheduler(
        daemon=True, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 600}
    )
    sched.add_job(rss_job, "interval", minutes=settings.rss_interval_min, args=[settings], id="rss",
                  next_run_time=_soon(15))  # fmt: skip
    sched.add_job(shorts_job, "interval", minutes=settings.shorts_interval_min, args=[settings], id="shorts",
                  next_run_time=_soon(90))  # fmt: skip
    sched.add_job(cleanup_job, "interval", hours=1, args=[settings], id="cleanup")
    sched.add_job(weights_job, CronTrigger(hour=3, minute=30), args=[settings], id="weights")
    sched.add_job(ytdlp_job, "interval", hours=24, args=[settings], id="ytdlp_update", next_run_time=_soon(30))
    sched.add_job(icons_job, "interval", hours=6, args=[settings], id="icons", next_run_time=_soon(150))
    sched.start()
    log.info("scheduler started")
    global scheduler
    scheduler = sched
    return sched


def reschedule(settings: Settings) -> None:
    """Apply changed feed/Shorts intervals from the admin page to the running scheduler."""
    if scheduler is None:
        return
    scheduler.reschedule_job("rss", trigger="interval", minutes=settings.rss_interval_min)
    scheduler.reschedule_job("shorts", trigger="interval", minutes=settings.shorts_interval_min)


def _soon(seconds: int) -> datetime:
    return datetime.now() + timedelta(seconds=seconds)
