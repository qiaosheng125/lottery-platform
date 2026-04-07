"""
APScheduler 定时任务初始化
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = None


def _daily_reset_trigger(hour: int):
    return CronTrigger(hour=hour, minute=0, timezone='Asia/Shanghai')


def reschedule_daily_reset(app, hour: int):
    scheduler = get_scheduler()
    if scheduler is None:
        return
    scheduler.add_job(
        func=_run_with_context(app, 'tasks.daily_reset', 'daily_session_reset'),
        trigger=_daily_reset_trigger(hour),
        id='daily_reset',
        name='每日会话重置',
        replace_existing=True,
    )


def start_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone='Asia/Shanghai', daemon=True)

    # 超时票检测：每分钟
    scheduler.add_job(
        func=_run_with_context(app, 'tasks.expire_tickets', 'expire_overdue_tickets'),
        trigger=IntervalTrigger(minutes=1),
        id='expire_tickets',
        name='超时票检测',
        replace_existing=True,
    )

    # 3小时无活动会话清理：每15分钟
    scheduler.add_job(
        func=_run_with_context(app, 'tasks.clean_sessions', 'clean_inactive_sessions'),
        trigger=IntervalTrigger(minutes=15),
        id='clean_sessions',
        name='清理不活跃会话',
        replace_existing=True,
    )

    with app.app_context():
        from models.settings import SystemSettings

        reset_hour = SystemSettings.get().daily_reset_hour

    scheduler.add_job(
        func=_run_with_context(app, 'tasks.daily_reset', 'daily_session_reset'),
        trigger=_daily_reset_trigger(reset_hour),
        id='daily_reset',
        name='每日会话重置',
        replace_existing=True,
    )

    # DB 保活：每5分钟
    scheduler.add_job(
        func=_run_with_context(app, 'tasks.expire_tickets', 'db_keepalive'),
        trigger=IntervalTrigger(minutes=5),
        id='db_keepalive',
        name='数据库连接保活',
        replace_existing=True,
    )

    # 数据归档：每周一凌晨6点，归档30天前的数据
    scheduler.add_job(
        func=_run_with_context(app, 'tasks.archive', 'archive_old_tickets'),
        trigger=CronTrigger(day_of_week='mon', hour=6, minute=0, timezone='Asia/Shanghai'),
        id='archive_tickets',
        name='历史票据清理',
        replace_existing=True,
    )

    scheduler.add_job(
        func=_run_with_context(app, 'tasks.archive', 'archive_old_uploaded_txt_files'),
        trigger=CronTrigger(day_of_week='mon', hour=6, minute=10, timezone='Asia/Shanghai'),
        id='archive_uploaded_txt_files',
        name='原始TXT历史清理',
        replace_existing=True,
    )

    scheduler.add_job(
        func=_run_with_context(app, 'tasks.archive', 'purge_old_auxiliary_records'),
        trigger=CronTrigger(day_of_week='mon', hour=6, minute=20, timezone='Asia/Shanghai'),
        id='purge_old_auxiliary_records',
        name='辅助历史清理',
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info("APScheduler started with %d jobs", len(scheduler.get_jobs()))
    return scheduler


def _run_with_context(app, module_path: str, func_name: str):
    """返回一个在 app context 中执行指定函数的包装函数"""
    def wrapper():
        with app.app_context():
            import importlib
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
            func()
    return wrapper


def get_scheduler():
    return _scheduler
