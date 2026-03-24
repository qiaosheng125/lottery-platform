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
from services.ticket_pool import assign_tickets_batch, complete_tickets_batch, get_pool_total_pending
from utils.time_utils import beijing_now


def preview_batch(requested_count: int) -> dict:
    """预查询当前票池总可用票数"""
    available = get_pool_total_pending()
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
    device_name: str = None,
) -> dict:
    """
    服务器自动按截止时间升序分配指定张数的票，每次只返回一个彩种的一个TXT文件。
    """
    settings = SystemSettings.get()
    if not settings.mode_b_enabled:
        return {'success': False, 'error': '模式B已被关闭'}

    # 获取用户的B模式处理中票数上限和每日上限
    from models.user import User
    user = User.query.get(user_id)
    max_processing = user.max_processing_b_mode if user else None
    daily_limit = user.daily_ticket_limit if user else None

    # 在 assign_tickets_batch 的锁内进行并发安全的检查和分配
    tickets, adjustment_message = assign_tickets_batch(
        user_id=user_id,
        device_id=device_id,
        username=username,
        count=count,
        device_name=device_name,
        max_processing=max_processing,
        daily_limit=daily_limit,
    )

    if not tickets:
        # 如果是因为达到上限而返回空列表，返回友好的错误提示
        if max_processing is not None:
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
        }],
        'ticket_ids': ticket_ids,
        'actual_count': len(tickets),
        'total_amount': total_amount,
    }

    # 如果有调整提示，添加到返回结果中
    if adjustment_message:
        result['adjustment_message'] = adjustment_message

    return result


def confirm_batch(ticket_ids: List[int], user_id: int) -> dict:
    """确认收到，批量改为 completed"""
    count = complete_tickets_batch(ticket_ids, user_id)
    return {'success': True, 'completed_count': count}
