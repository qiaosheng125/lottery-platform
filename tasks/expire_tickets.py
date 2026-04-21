"""Ticket expiration tasks and lightweight DB keepalive."""

import logging

from sqlalchemy import case, func, text

from extensions import db
from models.file import UploadedFile
from utils.time_utils import beijing_now

logger = logging.getLogger(__name__)


def _is_postgres():
    from flask import current_app

    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    return 'postgresql' in uri or 'postgres' in uri


def _sync_uploaded_file_counters(source_file_ids):
    if not source_file_ids:
        return

    from models.ticket import LotteryTicket

    aggregated = {
        row.source_file_id: {
            'pending_count': row.pending_count or 0,
            'assigned_count': row.assigned_count or 0,
            'completed_count': row.completed_count or 0,
        }
        for row in db.session.query(
            LotteryTicket.source_file_id,
            func.sum(case((LotteryTicket.status == 'pending', 1), else_=0)).label('pending_count'),
            func.sum(case((LotteryTicket.status == 'assigned', 1), else_=0)).label('assigned_count'),
            func.sum(case((LotteryTicket.status == 'completed', 1), else_=0)).label('completed_count'),
        ).filter(
            LotteryTicket.source_file_id.in_(source_file_ids)
        ).group_by(LotteryTicket.source_file_id).all()
    }

    for file_id in source_file_ids:
        uploaded_file = db.session.get(UploadedFile, file_id)
        if not uploaded_file:
            continue
        counts = aggregated.get(file_id, {})
        uploaded_file.pending_count = counts.get('pending_count', 0)
        uploaded_file.assigned_count = counts.get('assigned_count', 0)
        uploaded_file.completed_count = counts.get('completed_count', 0)


def expire_overdue_tickets():
    """Mark overdue pending tickets as expired and sync file counters."""
    try:
        from services.notify_service import notify_admins
        from services.notify_service import notify_pool_update
        from services.ticket_pool import get_pool_status
        from extensions import redis_client

        now = beijing_now()
        affected_file_ids = []
        expired_pending_ticket_ids = []

        if _is_postgres():
            affected_file_ids = [
                row[0]
                for row in db.session.execute(
                    text("""
                        SELECT DISTINCT source_file_id
                        FROM lottery_tickets
                        WHERE status = 'pending'
                          AND deadline_time <= :now
                          AND source_file_id IS NOT NULL
                    """),
                    {'now': now},
                ).fetchall()
            ]
            expired_pending_ticket_ids = [
                row[0]
                for row in db.session.execute(
                    text("""
                        SELECT id
                        FROM lottery_tickets
                        WHERE status = 'pending'
                          AND deadline_time <= :now
                    """),
                    {'now': now},
                ).fetchall()
            ]
            rows = db.session.execute(
                text("""
                    UPDATE lottery_tickets
                    SET status = 'expired',
                        version = version + 1
                    WHERE status = 'pending'
                      AND deadline_time <= :now
                """),
                {'now': now},
            ).rowcount
        else:
            from models.ticket import LotteryTicket

            tickets = LotteryTicket.query.filter(
                LotteryTicket.status == 'pending',
                LotteryTicket.deadline_time <= now,
            ).all()
            rows = len(tickets)
            for ticket in tickets:
                if ticket.source_file_id is not None:
                    affected_file_ids.append(ticket.source_file_id)
                expired_pending_ticket_ids.append(ticket.id)
                ticket.status = 'expired'
                ticket.version += 1

        _sync_uploaded_file_counters(sorted(set(affected_file_ids)))
        db.session.commit()

        if expired_pending_ticket_ids and redis_client:
            try:
                pipe = redis_client.pipeline()
                for ticket_id in expired_pending_ticket_ids:
                    pipe.lrem('pool:pending', 0, str(ticket_id))
                pipe.execute()
            except Exception as redis_error:
                logger.warning("expire_overdue_tickets Redis cleanup error: %s", redis_error)

        if rows:
            try:
                notify_admins('tickets_expired', {'count': rows})
            except Exception:
                pass
            try:
                notify_pool_update(get_pool_status())
            except Exception:
                pass
            logger.info("Expired %s overdue tickets", rows)
    except Exception as e:
        db.session.rollback()
        logger.error("expire_overdue_tickets error: %s", e)


def db_keepalive():
    """Keep the database connection warm."""
    try:
        db.session.execute(text('SELECT 1'))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning("db_keepalive error: %s", e)
