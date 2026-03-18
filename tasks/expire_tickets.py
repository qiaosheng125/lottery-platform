"""
超时票检测任务 + DB保活
"""

import logging
from sqlalchemy import text
from extensions import db
from utils.time_utils import beijing_now

logger = logging.getLogger(__name__)


def _is_postgres():
    from flask import current_app
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    return 'postgresql' in uri or 'postgres' in uri


def expire_overdue_tickets():
    """将截止时间已过的 pending/assigned 票标记为 expired"""
    try:
        from flask import current_app
        from services.notify_service import notify_admins
        now = beijing_now()

        if _is_postgres():
            rows = db.session.execute(
                text("""
                    UPDATE lottery_tickets
                    SET status = 'expired'
                    WHERE status IN ('pending', 'assigned')
                      AND deadline_time < :now
                """),
                {'now': now}
            ).rowcount
        else:
            from models.ticket import LotteryTicket
            tickets = LotteryTicket.query.filter(
                LotteryTicket.status.in_(['pending', 'assigned']),
                LotteryTicket.deadline_time < now,
            ).all()
            rows = len(tickets)
            for t in tickets:
                t.status = 'expired'

        if rows:
            db.session.commit()
            try:
                notify_admins('tickets_expired', {'count': rows})
            except Exception:
                pass
            logger.info(f"Expired {rows} overdue tickets")
        else:
            db.session.commit()

    except Exception as e:
        db.session.rollback()
        logger.error(f"expire_overdue_tickets error: {e}")


def db_keepalive():
    """保持数据库连接活跃"""
    try:
        db.session.execute(text('SELECT 1'))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"db_keepalive error: {e}")
