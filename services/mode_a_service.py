"""
A模式接单服务

包含接单、历史记录（Redis）、完成、停止逻辑。
Redis history key: history:{user_id}:{device_id}  → List，最近3张（LPUSH + LTRIM），TTL 3小时
"""

from typing import Optional, List

from flask import current_app

from extensions import db
from models.ticket import LotteryTicket
from models.settings import SystemSettings
from services.ticket_pool import assign_ticket_atomic, complete_ticket
from utils.time_utils import beijing_now

HISTORY_TTL = 3 * 3600  # 3 hours in seconds
MAX_HISTORY = 3


def _history_key(user_id: int, device_id: str) -> str:
    return f"history:{user_id}:{device_id}"


def _push_history(user_id: int, device_id: str, ticket_id: int):
    """将 ticket_id 推入用户历史记录（最多保留 MAX_HISTORY 条）"""
    from extensions import redis_client as rc
    if not rc:
        return
    key = _history_key(user_id, device_id)
    try:
        pipe = rc.pipeline()
        pipe.lpush(key, str(ticket_id))
        pipe.ltrim(key, 0, MAX_HISTORY - 1)
        pipe.expire(key, HISTORY_TTL)
        pipe.execute()
    except Exception as e:
        current_app.logger.warning(f"Redis history push error: {e}")


def _get_history(user_id: int, device_id: str) -> List[int]:
    """从 Redis 获取历史 ticket IDs（最近 MAX_HISTORY 条），无 Redis 时从数据库查询"""
    from extensions import redis_client as rc
    if rc:
        key = _history_key(user_id, device_id)
        try:
            items = rc.lrange(key, 0, MAX_HISTORY - 1)
            return [int(i) for i in items]
        except Exception:
            pass

    # DB fallback: query recently completed tickets for this device
    try:
        tickets = LotteryTicket.query.filter_by(
            assigned_user_id=user_id,
            assigned_device_id=device_id,
            status='completed',
        ).order_by(LotteryTicket.completed_at.desc()).limit(MAX_HISTORY).all()
        return [t.id for t in tickets]
    except Exception:
        return []


def get_next_ticket(user_id: int, device_id: str, username: str, device_name: str = None) -> dict:
    """
    A模式：获取下一张票。
    若当前有 assigned 票（来自当前设备），先完成再取下一张。
    """
    settings = SystemSettings.get()
    if not settings.mode_a_enabled:
        return {'success': False, 'error': '模式A已被关闭'}

    # Check if user already has an assigned ticket from this device
    current_ticket = LotteryTicket.query.filter_by(
        assigned_user_id=user_id,
        assigned_device_id=device_id,
        status='assigned',
    ).first()

    if current_ticket:
        # Complete the current ticket before assigning next
        complete_ticket(current_ticket.id, user_id)
        _push_history(user_id, device_id, current_ticket.id)

    # Assign next ticket
    ticket = assign_ticket_atomic(user_id, device_id, username, device_name)
    if not ticket:
        return {'success': False, 'error': '暂无可用票'}

    # Refresh history (new ticket not yet in history, but previous completed one is)
    return {
        'success': True,
        'ticket': ticket.to_dict(),
    }


def stop_receiving(user_id: int, device_id: str) -> dict:
    """A模式：停止接单（完成当前票）"""
    current_ticket = LotteryTicket.query.filter_by(
        assigned_user_id=user_id,
        assigned_device_id=device_id,
        status='assigned',
    ).first()

    if current_ticket:
        complete_ticket(current_ticket.id, user_id)
        _push_history(user_id, device_id, current_ticket.id)
        return {'success': True, 'message': '已停止接单，当前票已完成'}

    return {'success': True, 'message': '当前无进行中的票'}


def get_previous_ticket(user_id: int, device_id: str, offset: int = 0) -> dict:
    """
    A模式：查看历史票（不改变状态）。
    offset=0 → 上一张（最近一张完成的），offset=1 → 上上一张，最多2
    """
    history_ids = _get_history(user_id, device_id)
    if not history_ids or offset >= len(history_ids):
        return {'success': False, 'error': '无历史记录'}

    ticket_id = history_ids[offset]
    ticket = LotteryTicket.query.get(ticket_id)
    if not ticket:
        return {'success': False, 'error': '历史票不存在'}

    return {'success': True, 'ticket': ticket.to_dict()}


def get_current_ticket(user_id: int, device_id: str) -> Optional[LotteryTicket]:
    """返回当前分配给该设备的 assigned 票"""
    return LotteryTicket.query.filter_by(
        assigned_user_id=user_id,
        assigned_device_id=device_id,
        status='assigned',
    ).first()
