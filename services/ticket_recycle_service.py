from collections import defaultdict
from typing import Iterable

from flask import current_app
from sqlalchemy import func

from extensions import db
from models.audit import AuditLog
from models.file import UploadedFile
from models.ticket import LotteryTicket
from models.user import User

DEFAULT_RECYCLE_REASON = '管理员手动回收处理中票'
MAX_RECYCLE_LIST_LIMIT = 200


def _safe_text(value) -> str:
    return value.strip() if isinstance(value, str) else ''


def _status_label(status: str) -> str:
    return {
        'pending': '待分配',
        'assigned': '处理中',
        'completed': '已完成',
        'expired': '已过期',
        'revoked': '已撤回',
    }.get(status, status or '')


def _client_mode_label(mode: str) -> str:
    return {
        'mode_a': 'A模式',
        'mode_b': 'B模式',
    }.get(mode, mode or '')


def _ticket_item(ticket: LotteryTicket, user: User = None) -> dict:
    mode = user.client_mode if user else ''
    return {
        'id': ticket.id,
        'raw_content': ticket.raw_content or '',
        'status': ticket.status,
        'status_label': _status_label(ticket.status),
        'client_mode': mode,
        'client_mode_label': _client_mode_label(mode),
        'assigned_user_id': ticket.assigned_user_id,
        'assigned_username': ticket.assigned_username or '',
        'assigned_device_id': ticket.assigned_device_id or '',
        'download_filename': ticket.download_filename or '',
        'detail_period': ticket.detail_period or '',
        'lottery_type': ticket.lottery_type or '',
        'ticket_amount': float(ticket.ticket_amount or 0),
        'assigned_at': ticket.assigned_at.isoformat() if ticket.assigned_at else None,
    }


def _distinct_assigned_values(column, username: str = '', device_id: str = '', download_filename: str = '') -> list:
    rows_query = (
        db.session.query(column)
        .filter(
            LotteryTicket.status == 'assigned',
            column.isnot(None),
            func.trim(column) != '',
        )
    )
    if username:
        rows_query = rows_query.filter(LotteryTicket.assigned_username == username)
    if device_id:
        rows_query = rows_query.filter(LotteryTicket.assigned_device_id == device_id)
    if download_filename:
        rows_query = rows_query.filter(LotteryTicket.download_filename == download_filename)
    rows = rows_query.distinct().all()
    return sorted({(row[0] or '').strip() for row in rows if (row[0] or '').strip()})


def _filter_options(username: str = '', device_id: str = '', download_filename: str = '') -> dict:
    return {
        # Cascade filter options: each dimension is constrained by the other selected dimensions.
        'usernames': _distinct_assigned_values(
            LotteryTicket.assigned_username,
            device_id=device_id,
            download_filename=download_filename,
        ),
        'device_ids': _distinct_assigned_values(
            LotteryTicket.assigned_device_id,
            username=username,
            download_filename=download_filename,
        ),
        'download_filenames': _distinct_assigned_values(
            LotteryTicket.download_filename,
            username=username,
            device_id=device_id,
        ),
    }


def list_recyclable_assigned_tickets(username: str = '', device_id: str = '', download_filename: str = '') -> dict:
    username = _safe_text(username)
    device_id = _safe_text(device_id)
    download_filename = _safe_text(download_filename)

    query = (
        db.session.query(LotteryTicket, User)
        .outerjoin(User, LotteryTicket.assigned_user_id == User.id)
        .filter(LotteryTicket.status == 'assigned')
    )
    if username:
        query = query.filter(LotteryTicket.assigned_username == username)
    if device_id:
        query = query.filter(LotteryTicket.assigned_device_id == device_id)
    if download_filename:
        query = query.filter(LotteryTicket.download_filename == download_filename)

    total = query.count()
    rows = (
        query
        .order_by(LotteryTicket.assigned_at.desc(), LotteryTicket.id.desc())
        .limit(MAX_RECYCLE_LIST_LIMIT)
        .all()
    )
    return {
        'success': True,
        'items': [_ticket_item(ticket, user) for ticket, user in rows],
        'total': total,
        'limit': MAX_RECYCLE_LIST_LIMIT,
        'filter_options': _filter_options(
            username=username,
            device_id=device_id,
            download_filename=download_filename,
        ),
    }


def _push_recycled_tickets_to_redis(ticket_ids: Iterable[int]) -> None:
    from extensions import redis_client as rc

    ids = [str(ticket_id) for ticket_id in ticket_ids]
    if not ids or not rc:
        return
    try:
        rc.rpush('pool:pending', *ids)
    except Exception as exc:
        current_app.logger.warning('push recycled tickets to redis failed: %s', exc)


def _recycle_query(ticket_ids=None, username: str = '', device_id: str = '', download_filename: str = ''):
    query = LotteryTicket.query.filter(LotteryTicket.status == 'assigned')
    if ticket_ids is not None:
        query = query.filter(LotteryTicket.id.in_(ticket_ids))
    else:
        query = query.filter(
            LotteryTicket.assigned_username == username,
            LotteryTicket.assigned_device_id == device_id,
            LotteryTicket.download_filename == download_filename,
        )
    return query


def recycle_assigned_tickets(admin_user_id: int, ticket_ids=None, username: str = '',
                             device_id: str = '', download_filename: str = '',
                             reason: str = DEFAULT_RECYCLE_REASON) -> dict:
    reason = _safe_text(reason) or DEFAULT_RECYCLE_REASON
    if ticket_ids is not None:
        ticket_ids = list(dict.fromkeys(ticket_ids))
        if not ticket_ids:
            return {'success': False, 'error': '缺少要回收的票ID'}
        query = _recycle_query(ticket_ids=ticket_ids)
        recycle_scope = 'ticket_ids'
    else:
        username = _safe_text(username)
        device_id = _safe_text(device_id)
        download_filename = _safe_text(download_filename)
        if not username or not device_id or not download_filename:
            return {'success': False, 'error': '回收当前文件名处理中票必须提供用户名、设备ID、分配文件名'}
        query = _recycle_query(username=username, device_id=device_id, download_filename=download_filename)
        recycle_scope = 'download_filename'

    tickets = query.order_by(LotteryTicket.assigned_at, LotteryTicket.id).with_for_update().all()
    if not tickets:
        return {'success': False, 'error': '未找到可回收的处理中票'}

    recycled_ids = []
    original_details = []
    file_counts = defaultdict(int)
    total_amount = 0.0

    for ticket in tickets:
        recycled_ids.append(ticket.id)
        file_counts[ticket.source_file_id] += 1
        total_amount += float(ticket.ticket_amount or 0)
        original_details.append({
            'ticket_id': ticket.id,
            'assigned_user_id': ticket.assigned_user_id,
            'assigned_username': ticket.assigned_username,
            'assigned_device_id': ticket.assigned_device_id,
            'download_filename': ticket.download_filename,
            'assigned_at': ticket.assigned_at.isoformat() if ticket.assigned_at else None,
            'ticket_amount': float(ticket.ticket_amount or 0),
        })

        ticket.status = 'pending'
        ticket.assigned_user_id = None
        ticket.assigned_username = None
        ticket.assigned_device_id = None
        ticket.assigned_at = None
        ticket.locked_until = None
        ticket.download_filename = None
        ticket.completed_at = None
        ticket.version = (ticket.version or 0) + 1

    for file_id, count in file_counts.items():
        uploaded_file = db.session.get(UploadedFile, file_id)
        if not uploaded_file:
            continue
        uploaded_file.pending_count = (uploaded_file.pending_count or 0) + count
        uploaded_file.assigned_count = max((uploaded_file.assigned_count or 0) - count, 0)

    AuditLog.log(
        'ticket_recycle',
        user_id=admin_user_id,
        resource_type='ticket',
        resource_id=','.join(str(ticket_id) for ticket_id in recycled_ids[:20]),
        details={
            'reason': reason,
            'scope': recycle_scope,
            'recycled_count': len(recycled_ids),
            'recycled_amount': total_amount,
            'ticket_ids': recycled_ids,
            'original': original_details,
        },
        status_code=200,
    )
    db.session.commit()
    _push_recycled_tickets_to_redis(recycled_ids)

    return {
        'success': True,
        'message': f'已回收 {len(recycled_ids)} 张处理中票，已回到票池',
        'recycled_count': len(recycled_ids),
        'recycled_amount': total_amount,
        'ticket_ids': recycled_ids,
    }
