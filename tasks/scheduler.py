"""
APScheduler initialization with cross-worker job locks.
"""

import hashlib
import logging
from contextlib import contextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

logger = logging.getLogger(__name__)

_scheduler = None


def _daily_reset_trigger(hour: int):
    return CronTrigger(hour=hour, minute=0, timezone='Asia/Shanghai')


def _job_lock_key(job_id: str) -> int:
    digest = hashlib.blake2b(job_id.encode('utf-8'), digest_size=8).digest()
    key = int.from_bytes(digest, byteorder='big', signed=False)
    if key >= (1 << 63):
        key -= (1 << 64)
    return key


@contextmanager
def _job_execution_lock(job_id: str):
    """
    In PostgreSQL, hold a transaction-scoped advisory lock for this job run.
    This prevents the same job from running concurrently across gunicorn workers.
    """
    from extensions import db

    bind = db.session.get_bind()
    dialect_name = (getattr(getattr(bind, 'dialect', None), 'name', '') or '').lower()
    if dialect_name != 'postgresql':
        yield True
        return

    conn = db.engine.connect()
    tx = conn.begin()
    try:
        acquired = bool(conn.execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {'lock_key': _job_lock_key(job_id)},
        ).scalar())
        yield acquired
    finally:
        try:
            tx.rollback()
        except Exception:
            pass
        conn.close()


def _run_with_context(app, module_path: str, func_name: str, job_id: str):
    """Return a callable that executes the target function in app context."""

    def wrapper():
        with app.app_context():
            with _job_execution_lock(job_id) as acquired:
                if not acquired:
                    logger.info("Skip scheduler job %s: lock held by another worker", job_id)
                    return

                import importlib

                module = importlib.import_module(module_path)
                func = getattr(module, func_name)
                func()

    return wrapper


def reschedule_daily_reset(app, hour: int):
    scheduler = get_scheduler()
    if scheduler is None:
        return
    scheduler.add_job(
        func=_run_with_context(app, 'tasks.daily_reset', 'daily_session_reset', job_id='daily_reset'),
        trigger=_daily_reset_trigger(hour),
        id='daily_reset',
        name='daily_session_reset',
        replace_existing=True,
    )


def start_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone='Asia/Shanghai', daemon=True)

    scheduler.add_job(
        func=_run_with_context(app, 'tasks.expire_tickets', 'expire_overdue_tickets', job_id='expire_tickets'),
        trigger=IntervalTrigger(minutes=1),
        id='expire_tickets',
        name='expire_overdue_tickets',
        replace_existing=True,
    )

    scheduler.add_job(
        func=_run_with_context(app, 'tasks.clean_sessions', 'clean_inactive_sessions', job_id='clean_sessions'),
        trigger=IntervalTrigger(minutes=15),
        id='clean_sessions',
        name='clean_inactive_sessions',
        replace_existing=True,
    )

    with app.app_context():
        from models.settings import SystemSettings

        reset_hour = SystemSettings.get().daily_reset_hour

    scheduler.add_job(
        func=_run_with_context(app, 'tasks.daily_reset', 'daily_session_reset', job_id='daily_reset'),
        trigger=_daily_reset_trigger(reset_hour),
        id='daily_reset',
        name='daily_session_reset',
        replace_existing=True,
    )

    scheduler.add_job(
        func=_run_with_context(app, 'tasks.expire_tickets', 'db_keepalive', job_id='db_keepalive'),
        trigger=IntervalTrigger(minutes=5),
        id='db_keepalive',
        name='db_keepalive',
        replace_existing=True,
    )

    scheduler.add_job(
        func=_run_with_context(app, 'tasks.archive', 'archive_old_tickets', job_id='archive_tickets'),
        trigger=CronTrigger(day_of_week='mon', hour=6, minute=0, timezone='Asia/Shanghai'),
        id='archive_tickets',
        name='archive_old_tickets',
        replace_existing=True,
    )

    scheduler.add_job(
        func=_run_with_context(
            app,
            'tasks.archive',
            'archive_old_uploaded_txt_files',
            job_id='archive_uploaded_txt_files',
        ),
        trigger=CronTrigger(day_of_week='mon', hour=6, minute=10, timezone='Asia/Shanghai'),
        id='archive_uploaded_txt_files',
        name='archive_old_uploaded_txt_files',
        replace_existing=True,
    )

    scheduler.add_job(
        func=_run_with_context(
            app,
            'tasks.archive',
            'purge_old_auxiliary_records',
            job_id='purge_old_auxiliary_records',
        ),
        trigger=CronTrigger(day_of_week='mon', hour=6, minute=20, timezone='Asia/Shanghai'),
        id='purge_old_auxiliary_records',
        name='purge_old_auxiliary_records',
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info("APScheduler started with %d jobs", len(scheduler.get_jobs()))
    return scheduler


def get_scheduler():
    return _scheduler
