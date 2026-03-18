from flask_socketio import join_room, leave_room, emit
from flask_login import current_user
from extensions import socketio


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
    status = get_pool_status()
    emit('pool_updated', status)
