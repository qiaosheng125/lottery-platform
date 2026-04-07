from functools import wraps
from flask import jsonify, request
from flask_login import current_user


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'error': '请先登录'}), 401
        if not current_user.is_admin:
            return jsonify({'success': False, 'error': '权限不足'}), 403
        return f(*args, **kwargs)
    return decorated


def login_required_json(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'error': '请先登录'}), 401
        if not current_user.is_active:
            return jsonify({'success': False, 'error': '账号已被禁用'}), 403
        return f(*args, **kwargs)
    return decorated


def can_receive_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.can_receive:
            return jsonify({'success': False, 'error': '接单功能已被暂停'}), 403
        return f(*args, **kwargs)
    return decorated


def mode_b_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if getattr(current_user, 'client_mode', None) != 'mode_b':
            return jsonify({'success': False, 'error': '仅 B 模式用户可使用此功能'}), 403
        return f(*args, **kwargs)
    return decorated


def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr
