from flask_socketio import join_room, leave_room, emit
from flask_login import current_user
from extensions import socketio
MODE_B_POOL_RESERVE = 20


def _trim_status_for_mode_b(status: dict) -> dict:
    available_total = max(0, int(status.get('total_pending') or 0) - MODE_B_POOL_RESERVE)
    trimmed_by_type = []
    remaining = available_total
    for item in status.get('by_type') or []:
        if remaining <= 0:
            break
        raw_count = int(item.get('count') or 0)
        if raw_count <= 0:
            continue
        visible_count = min(raw_count, remaining)
        trimmed_by_type.append({**item, 'count': visible_count})
        remaining -= visible_count
    return {
        **status,
        'total_pending': available_total,
        'by_type': trimmed_by_type,
    }


@socketio.on('connect')
def on_connect():
    if current_user.is_authenticated:
        join_room('users')
        join_room(f'user_{current_user.id}')
        if current_user.is_admin:
            join_room('admins')
        emit('connected', {'message': '连接成功'})


@socketio.on('disconnect')
def on_disconnect():
    if current_user.is_authenticated:
        leave_room('users')
        leave_room(f'user_{current_user.id}')
        if current_user.is_admin:
            leave_room('admins')


@socketio.on('request_pool_status')
def on_request_pool_status():
    from services.ticket_pool import get_pool_status
    blocked_types = current_user.get_blocked_lottery_types() if current_user.is_authenticated else []
    status = get_pool_status(blocked_types)
    if getattr(current_user, 'client_mode', None) == 'mode_b':
        status = _trim_status_for_mode_b(status)
    emit('pool_updated', status)
