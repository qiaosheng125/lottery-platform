from typing import List, Optional

from flask import current_app

from models.settings import SystemSettings
from models.ticket import LotteryTicket
from services.ticket_pool import assign_ticket_atomic, finalize_ticket

HISTORY_TTL = 3 * 3600
MAX_HISTORY = 3


def _history_key(user_id: int, device_id: str) -> str:
    return f"history:{user_id}:{device_id}"


def _push_history(user_id: int, device_id: str, ticket_id: int):
    """Push the completed ticket into the short device history."""
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
    """Fetch recent ticket IDs from Redis, or fall back to the database."""
    from extensions import redis_client as rc

    if rc:
        key = _history_key(user_id, device_id)
        try:
            items = rc.lrange(key, 0, MAX_HISTORY - 1)
            return [int(i) for i in items]
        except Exception:
            pass

    try:
        tickets = LotteryTicket.query.filter_by(
            assigned_user_id=user_id,
            assigned_device_id=device_id,
            status='completed',
        ).order_by(LotteryTicket.completed_at.desc()).limit(MAX_HISTORY).all()
        return [t.id for t in tickets]
    except Exception:
        return []


def _parse_requested_ticket_id(complete_current_ticket_id) -> Optional[int]:
    if complete_current_ticket_id in (None, ''):
        return None
    try:
        return int(complete_current_ticket_id)
    except (TypeError, ValueError):
        return None


def _normalize_ticket_action(action: Optional[str]) -> str:
    return 'expired' if action == 'expired' else 'completed'


def _get_latest_assigned_ticket(user_id: int, device_id: str) -> Optional[LotteryTicket]:
    return LotteryTicket.query.filter_by(
        assigned_user_id=user_id,
        assigned_device_id=device_id,
        status='assigned',
    ).order_by(
        LotteryTicket.assigned_at.desc(),
        LotteryTicket.id.desc(),
    ).first()


def get_next_ticket(
    user_id: int,
    device_id: str,
    username: str,
    device_name: str = None,
    complete_current_ticket_id: int = None,
    complete_current_ticket_action: str = 'completed',
) -> dict:
    """
    Get the next ticket for mode A.

    The currently assigned ticket is only completed when the client explicitly
    confirms the exact current ticket ID. This avoids duplicate/retried requests
    from accidentally completing a newer ticket.
    """
    settings = SystemSettings.get()
    if not settings.mode_a_enabled:
        return {'success': False, 'error': '模式A已被关闭'}

    from models.user import User

    user = User.query.get(user_id)
    daily_limit = user.daily_ticket_limit if user else None
    blocked_lottery_types = user.get_blocked_lottery_types() if user else []

    current_ticket = _get_latest_assigned_ticket(user_id, device_id)

    if current_ticket:
        requested_ticket_id = _parse_requested_ticket_id(complete_current_ticket_id)
        if requested_ticket_id != current_ticket.id:
            return {
                'success': True,
                'ticket': current_ticket.to_dict(),
                'completed_current': False,
            }

        completed = finalize_ticket(
            current_ticket.id,
            user_id,
            final_status=_normalize_ticket_action(complete_current_ticket_action),
        )
        if not completed:
            return {'success': False, 'error': '当前票状态已变化，请刷新后重试'}
        if _normalize_ticket_action(complete_current_ticket_action) != 'expired':
            _push_history(user_id, device_id, current_ticket.id)

    ticket = assign_ticket_atomic(
        user_id,
        device_id,
        username,
        device_name,
        daily_limit=daily_limit,
        blocked_lottery_types=blocked_lottery_types,
    )
    if not ticket:
        return {'success': False, 'error': '暂无可用票'}

    return {
        'success': True,
        'ticket': ticket.to_dict(),
        'completed_current': current_ticket is not None,
    }


def stop_receiving(user_id: int, device_id: str, current_ticket_action: str = 'completed') -> dict:
    """Stop mode A and complete the current assigned ticket for this device."""
    current_ticket = _get_latest_assigned_ticket(user_id, device_id)

    if current_ticket:
        final_status = _normalize_ticket_action(current_ticket_action)
        finalized = finalize_ticket(current_ticket.id, user_id, final_status=final_status)
        if not finalized:
            return {'success': False, 'error': '当前票状态已变化，请刷新后重试'}
        if final_status != 'expired':
            _push_history(user_id, device_id, current_ticket.id)
        if final_status == 'expired':
            return {'success': True, 'message': '已停止接单，当前票已标记为已过期'}
        return {'success': True, 'message': '已停止接单，当前票已完成'}

    return {'success': True, 'message': '当前无进行中的票'}


def get_previous_ticket(user_id: int, device_id: str, offset: int = 0) -> dict:
    """Return a recent completed ticket without mutating state."""
    history_ids = _get_history(user_id, device_id)
    if not history_ids or offset >= len(history_ids):
        return {'success': False, 'error': '无历史记录'}

    ticket_id = history_ids[offset]
    ticket = LotteryTicket.query.get(ticket_id)
    if not ticket:
        return {'success': False, 'error': '历史票不存在'}

    return {'success': True, 'ticket': ticket.to_dict()}


def get_current_ticket(user_id: int, device_id: str) -> Optional[LotteryTicket]:
    """Return the currently assigned ticket for the given device."""
    return _get_latest_assigned_ticket(user_id, device_id)
