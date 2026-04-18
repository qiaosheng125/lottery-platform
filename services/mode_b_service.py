"""
B模式批量下载服务

用户只选张数，服务器按截止时间升序自动分配票。
预查询 → 批量分配（行锁）→ TXT打包下载 → 确认完成
"""

from decimal import Decimal
from typing import List

from flask import current_app

from extensions import db
from models.ticket import LotteryTicket
from models.settings import SystemSettings
from services.ticket_pool import assign_tickets_batch, finalize_tickets_batch, get_mode_b_preview_available
from utils.time_utils import beijing_now


def preview_batch(requested_count: int, user_id: int = None) -> dict:
    """预查询当前票池总可用票数"""
    settings = SystemSettings.get()
    if not settings.mode_b_enabled or not settings.pool_enabled:
        return {
            'available': 0,
            'requested': requested_count,
            'sufficient': False,
        }
    blocked_lottery_types = []
    if user_id is not None:
        from models.user import User
        user = db.session.get(User, user_id)
        blocked_lottery_types = user.get_blocked_lottery_types() if user else []
    available = get_mode_b_preview_available(blocked_lottery_types=blocked_lottery_types)
    return {
        'available': available,
        'requested': requested_count,
        'sufficient': available >= requested_count,
    }


def download_batch(
    user_id: int,
    device_id: str,
    username: str,
    count: int,
) -> dict:
    """
    服务器自动按截止时间升序分配指定张数的票，每次只返回一个彩种的一个TXT文件。
    """
    settings = SystemSettings.get()
    if not settings.mode_b_enabled:
        return {'success': False, 'error': '模式B已被关闭'}
    if not settings.pool_enabled:
        return {'success': False, 'error': '票池已关闭'}

    # 获取用户的B模式处理中票数上限、每日上限和禁止彩种
    from models.user import User
    user = db.session.get(User, user_id)
    max_processing = user.max_processing_b_mode if user else None
    daily_limit = user.daily_ticket_limit if user else None
    blocked_lottery_types = user.get_blocked_lottery_types() if user else []

    # 在 assign_tickets_batch 的锁内进行并发安全的检查和分配
    tickets, adjustment_message = assign_tickets_batch(
        user_id=user_id,
        device_id=device_id,
        username=username,
        count=count,
        max_processing=max_processing,
        daily_limit=daily_limit,
        blocked_lottery_types=blocked_lottery_types,
    )

    if not tickets:
        if adjustment_message:
            return {'success': False, 'error': adjustment_message}

        if daily_limit is not None:
            from utils.time_utils import get_today_noon
            from services.ticket_pool import _count_today_completed

            business_start = get_today_noon()
            today_count = _count_today_completed(user_id, business_start)
            if today_count >= daily_limit:
                return {'success': False, 'error': '已达到今日处理上限'}

        if max_processing is not None:
            current_processing = LotteryTicket.query.filter_by(
                assigned_user_id=user_id,
                status='assigned',
            ).count()
            if current_processing >= max_processing:
                return {
                    'success': False,
                    'error': f'已达到处理中票数上限（{max_processing}张），请先完成当前票据'
                }

        return {'success': False, 'error': '当前票池无可用票'}

    now = beijing_now()
    now_str = now.strftime('%Y-%m%d-%H%M%S')

    # 所有票应该是同一个彩种（由 assign_tickets_batch 保证）
    lottery_type = tickets[0].lottery_type or '未知'
    lines = [t.raw_content for t in tickets]
    content = '\n'.join(lines)

    total_amount = sum(float(t.ticket_amount or 0) for t in tickets)
    ticket_ids = [t.id for t in tickets]

    # 倍数（取第一张票的倍数，若不一致标为混合）
    multipliers = list({t.multiplier for t in tickets if t.multiplier})
    mult_str = str(multipliers[0]) if len(multipliers) == 1 else '混合'

    # 最早截止时间，格式 HH.MM
    deadlines = [t.deadline_time for t in tickets if t.deadline_time]
    deadline_str = min(deadlines).strftime('%H.%M') if deadlines else '00.00'

    filename = f"{lottery_type}_{mult_str}倍_{len(tickets)}张_{int(total_amount)}元_{deadline_str}_{now_str}.txt"

    # 只返回一个文件
    result = {
        'success': True,
        'files': [{
            'filename': filename,
            'content': content,
            'ticket_ids': ticket_ids,
            'count': len(tickets),
            'amount': total_amount,
            'deadline_time': min(deadlines).isoformat() if deadlines else None,
        }],
        'ticket_ids': ticket_ids,
        'actual_count': len(tickets),
        'total_amount': total_amount,
    }

    # 如果有调整提示，添加到返回结果中
    if adjustment_message:
        result['adjustment_message'] = adjustment_message

    return result


def get_processing_batches(user_id: int, device_id: str = None) -> list:
    """
    查询当前用户处理中（assigned）的票，按"彩种+截止时间+分配时间（分钟级）"分组，
    恢复页面刷新后丢失的 bPendingBatches 列表。
    如果提供了 device_id，则只返回该设备的票。
    """
    query = LotteryTicket.query.filter_by(
        assigned_user_id=user_id,
        status='assigned',
    )
    # 如果传入了非空的 device_id，则只返回该设备的票
    # 如果 device_id 为 None 或空字符串，返回所有设备的票
    if device_id:
        query = query.filter_by(assigned_device_id=device_id)
        
    tickets = query.order_by(LotteryTicket.assigned_at, LotteryTicket.id).all()

    if not tickets:
        return []

    # 按 (device_id, lottery_type, deadline_time, assigned_at精确时间) 分组，还原每次下载批次
    from collections import defaultdict
    groups = defaultdict(list)
    for t in tickets:
        # 同一次 download_batch 的票 assigned_at 完全相同；不同批次即使同分钟也不能合并。
        assigned_key = t.assigned_at.isoformat() if t.assigned_at else '0000-00-00T00:00:00'
        lottery_key = t.lottery_type or '未知'
        deadline_key = t.deadline_time.strftime('%H%M') if t.deadline_time else '0000'
        device_key = t.assigned_device_id or ''
        key = f"{device_key}_{lottery_key}_{deadline_key}_{assigned_key}"
        groups[key].append(t)

    batches = []
    for key, group_tickets in groups.items():
        lottery_type = group_tickets[0].lottery_type or '未知'
        multipliers = list({t.multiplier for t in group_tickets if t.multiplier})
        mult_str = str(multipliers[0]) if len(multipliers) == 1 else '混合'
        total_amount = sum(float(t.ticket_amount or 0) for t in group_tickets)
        ticket_ids = [t.id for t in group_tickets]
        deadlines = [t.deadline_time for t in group_tickets if t.deadline_time]
        deadline_str = min(deadlines).strftime('%H.%M') if deadlines else '00.00'
        assigned_at = group_tickets[0].assigned_at
        downloaded_at = assigned_at.strftime('%H:%M:%S') if assigned_at else '--:--:--'

        # 还原文件名（尽量贴近原始格式）
        filename = (
            f"{lottery_type}_{mult_str}倍_{len(group_tickets)}张"
            f"_{int(total_amount)}元_{deadline_str}_（已接单）.txt"
        )

        batches.append({
            'filename': filename,
            'ticket_ids': ticket_ids,
            'count': len(group_tickets),
            'amount': total_amount,
            'downloaded_at': downloaded_at,
            'deadline_time': min(deadlines).isoformat() if deadlines else None,
        })

    return batches


def confirm_batch(ticket_ids: List[int], user_id: int, completed_count: int = None, device_id: str = None) -> dict:
    """确认收到，批量改为 completed"""
    ticket_ids = list(dict.fromkeys(ticket_ids))
    if completed_count is not None:
        try:
            completed_count = int(completed_count)
        except (TypeError, ValueError):
            return {'success': False, 'error': '已完成张数必须是整数', 'completed_count': 0, 'expired_count': 0}
        if completed_count < 0 or completed_count > len(ticket_ids):
            return {'success': False, 'error': '已完成张数超出当前批次范围', 'completed_count': 0, 'expired_count': 0}

    result = finalize_tickets_batch(ticket_ids, user_id, completed_count=completed_count, device_id=device_id)
    if result['completed_count'] == 0 and result['expired_count'] == 0:
        return {'success': False, 'error': '未找到可确认的票据，可能已完成或不属于当前用户或设备', 'completed_count': 0}
    return {'success': True, **result}
