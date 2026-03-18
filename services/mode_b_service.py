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
    服务器自动按截止时间升序分配指定张数的票，按彩种分组打包为多个TXT返回。
    """
    settings = SystemSettings.get()
    if not settings.mode_b_enabled:
        return {'success': False, 'error': '模式B已被关闭'}

    tickets = assign_tickets_batch(
        user_id=user_id,
        device_id=device_id,
        username=username,
        count=count,
        device_name=device_name,
    )

    if not tickets:
        return {'success': False, 'error': '当前票池无可用票'}

    now = beijing_now()
    now_str = now.strftime('%Y-%m%d-%H%M%S')

    # 按彩种分组
    from collections import defaultdict
    groups = defaultdict(list)
    for t in tickets:
        groups[t.lottery_type or '未知'].append(t)

    files = []
    all_ticket_ids = []
    total_count = 0
    total_amount = 0.0

    for lottery_type, group_tickets in groups.items():
        lines = [t.raw_content for t in group_tickets]
        content = '\n'.join(lines)

        group_amount = sum(float(t.ticket_amount or 0) for t in group_tickets)
        group_ids = [t.id for t in group_tickets]

        # 倍数（取第一张票的倍数，若不一致标为混合）
        multipliers = list({t.multiplier for t in group_tickets if t.multiplier})
        mult_str = str(multipliers[0]) if len(multipliers) == 1 else '混合'

        # 最早截止时间，格式 HH.MM
        deadlines = [t.deadline_time for t in group_tickets if t.deadline_time]
        deadline_str = min(deadlines).strftime('%H.%M') if deadlines else '00.00'

        filename = f"{lottery_type}_{mult_str}倍_{int(group_amount)}元_{deadline_str}_{now_str}.txt"

        files.append({
            'filename': filename,
            'content': content,
            'ticket_ids': group_ids,
            'count': len(group_tickets),
            'amount': group_amount,
        })

        all_ticket_ids.extend(group_ids)
        total_count += len(group_tickets)
        total_amount += group_amount

    return {
        'success': True,
        'files': files,
        'ticket_ids': all_ticket_ids,
        'actual_count': total_count,
        'total_amount': total_amount,
    }


def confirm_batch(ticket_ids: List[int], user_id: int) -> dict:
    """确认收到，批量改为 completed"""
    count = complete_tickets_batch(ticket_ids, user_id)
    return {'success': True, 'completed_count': count}
