from flask_socketio import emit
from extensions import socketio


@socketio.on('admin_request_stats')
def on_admin_request_stats():
    from services.ticket_pool import get_pool_status
    status = get_pool_status()
    emit('pool_updated', status)
