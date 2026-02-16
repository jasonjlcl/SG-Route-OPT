from __future__ import annotations

import threading
import time
from datetime import datetime

from app.services.jobs import create_job, enqueue_job
from app.utils.db import SessionLocal
from app.utils.settings import get_settings

_thread: threading.Thread | None = None
_stop = threading.Event()


def _scheduler_loop() -> None:
    last_daily_key = ""
    last_weekly_key = ""
    while not _stop.is_set():
        now = datetime.utcnow()

        daily_key = now.strftime("%Y-%m-%d")
        if now.hour == 2 and daily_key != last_daily_key:
            db = SessionLocal()
            try:
                job = create_job(db, job_type="ML_MONITOR", payload={"trigger": "daily"})
                enqueue_job(job)
                last_daily_key = daily_key
            finally:
                db.close()

        weekly_key = now.strftime("%Y-%W")
        if now.weekday() == 0 and now.hour == 3 and weekly_key != last_weekly_key:
            db = SessionLocal()
            try:
                job = create_job(db, job_type="ML_RETRAIN_IF_NEEDED", payload={"trigger": "weekly"})
                enqueue_job(job)
                last_weekly_key = weekly_key
            finally:
                db.close()

        _stop.wait(timeout=60)


def start_scheduler() -> None:
    global _thread
    settings = get_settings()
    if settings.app_env in {"test", "prod", "production"}:
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()
