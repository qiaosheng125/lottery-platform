"""
数据归档任务

将超过保留期的终态票据转存到归档表，再从主表删除，降低主表查询压力。
默认每周执行一次，归档 30 天前的数据。
"""

from datetime import timedelta

from flask import current_app

from extensions import db
from models.archive import ArchivedLotteryTicket
from models.ticket import LotteryTicket
from utils.time_utils import beijing_now


def _ticket_terminal_at(ticket: LotteryTicket):
    if ticket.status == 'completed':
        return ticket.completed_at
    return ticket.completed_at or ticket.deadline_time or ticket.assigned_at or ticket.admin_upload_time


def _build_archived_ticket(ticket: LotteryTicket, archived_at):
    return ArchivedLotteryTicket(
        original_ticket_id=ticket.id,
        source_file_id=ticket.source_file_id,
        line_number=ticket.line_number,
        raw_content=ticket.raw_content,
        lottery_type=ticket.lottery_type,
        multiplier=ticket.multiplier,
        deadline_time=ticket.deadline_time,
        detail_period=ticket.detail_period,
        ticket_amount=ticket.ticket_amount,
        status=ticket.status,
        assigned_user_id=ticket.assigned_user_id,
        assigned_username=ticket.assigned_username,
        assigned_device_id=ticket.assigned_device_id,
        assigned_device_name=ticket.assigned_device_name,
        admin_upload_time=ticket.admin_upload_time,
        assigned_at=ticket.assigned_at,
        completed_at=ticket.completed_at,
        terminal_at=_ticket_terminal_at(ticket),
        is_winning=ticket.is_winning,
        winning_gross=ticket.winning_gross,
        winning_amount=ticket.winning_amount,
        winning_tax=ticket.winning_tax,
        winning_image_url=ticket.winning_image_url,
        version=ticket.version,
        locked_until=ticket.locked_until,
        archived_at=archived_at,
    )


def archive_old_tickets(days_ago=30):
    """
    归档 N 天前的终态票据。

    流程：
    1. 找出超过保留期的 completed / revoked / expired 票
    2. 先写入 archived_lottery_tickets
    3. 确认归档记录写入成功后，再从 lottery_tickets 删除
    """
    cutoff_date = beijing_now() - timedelta(days=days_ago)
    archived_at = beijing_now()

    archived_ticket_ids = {
        row[0]
        for row in db.session.query(ArchivedLotteryTicket.original_ticket_id).all()
    }

    candidates = LotteryTicket.query.filter(
        LotteryTicket.status.in_(['completed', 'revoked', 'expired'])
    ).all()

    to_archive = [
        ticket
        for ticket in candidates
        if ticket.id not in archived_ticket_ids
        and _ticket_terminal_at(ticket) is not None
        and _ticket_terminal_at(ticket) < cutoff_date
    ]

    if not to_archive:
        current_app.logger.info('无需归档的数据（%s天前）', days_ago)
        return 0

    archived_rows = [_build_archived_ticket(ticket, archived_at) for ticket in to_archive]
    db.session.add_all(archived_rows)
    db.session.flush()

    persisted_ids = {
        row[0]
        for row in db.session.query(ArchivedLotteryTicket.original_ticket_id).filter(
            ArchivedLotteryTicket.original_ticket_id.in_([ticket.id for ticket in to_archive])
        ).all()
    }

    deleted_count = 0
    for ticket in to_archive:
        if ticket.id not in persisted_ids:
            raise RuntimeError(f'票据 {ticket.id} 归档写入失败，已中止删除')
        db.session.delete(ticket)
        deleted_count += 1

    db.session.commit()
    current_app.logger.info('已归档 %s 条数据（%s天前）', deleted_count, days_ago)
    return deleted_count


def vacuum_database():
    """
    SQLite: VACUUM 回收空间
    PostgreSQL: VACUUM ANALYZE 优化查询计划
    """
    try:
        db.session.execute(db.text('VACUUM'))
        db.session.commit()
        current_app.logger.info('数据库 VACUUM 完成')
    except Exception as e:
        current_app.logger.warning(f'VACUUM 失败: {e}')
