"""
WebSocket 推送服务
"""

from flask_socketio import emit
from extensions import socketio


def notify_all(event: str, data: dict):
    """向所有已连接的客户端广播"""
    socketio.emit(event, data, to='users')
    socketio.emit(event, data, to='admins')


def notify_admins(event: str, data: dict):
    """仅向管理员广播"""
    socketio.emit(event, data, to='admins')


def notify_user(user_id: int, event: str, data: dict):
    """向指定用户广播（跨设备）"""
    socketio.emit(event, data, to=f'user_{user_id}')


def notify_pool_update(pool_status: dict):
    """推送票池状态更新"""
    notify_all('pool_updated', pool_status)
