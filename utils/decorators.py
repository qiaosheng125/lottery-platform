from functools import wraps

import ipaddress

from flask import current_app, jsonify, request
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
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'error': '请先登录'}), 401
        if not current_user.is_active:
            return jsonify({'success': False, 'error': '账号已被禁用'}), 403
        if not current_user.can_receive:
            return jsonify({'success': False, 'error': '当前账号已停止接单'}), 403
        return f(*args, **kwargs)

    return decorated

def mode_b_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if getattr(current_user, 'client_mode', None) != 'mode_b':
            return jsonify({'success': False, 'error': '仅 B 模式用户可访问'}), 403
        return f(*args, **kwargs)

    return decorated


def mode_a_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if getattr(current_user, 'client_mode', None) != 'mode_a':
            return jsonify({'success': False, 'error': '仅 A 模式用户可访问'}), 403
        return f(*args, **kwargs)

    return decorated


def get_client_ip():
    remote_addr = (request.remote_addr or '').strip() or None
    forwarded_for = (request.headers.get('X-Forwarded-For') or '').strip()
    if not forwarded_for:
        return remote_addr

    trusted_proxy_ips = current_app.config.get('TRUSTED_PROXY_IPS', '')
    if isinstance(trusted_proxy_ips, str):
        trusted_proxy_set = {ip.strip() for ip in trusted_proxy_ips.split(',') if ip.strip()}
    elif isinstance(trusted_proxy_ips, (list, tuple, set)):
        trusted_proxy_set = {str(ip).strip() for ip in trusted_proxy_ips if str(ip).strip()}
    else:
        trusted_proxy_set = set()

    if not remote_addr or remote_addr not in trusted_proxy_set:
        return remote_addr

    client_ip = forwarded_for.split(',')[0].strip()
    if not client_ip:
        return remote_addr

    try:
        ipaddress.ip_address(client_ip)
    except ValueError:
        return remote_addr
    return client_ip


def parse_json_object(error_message: str = 'JSON 请求体必须是对象'):
    """Return (data, error_response)."""
    data = request.get_json(silent=True)
    if data is None:
        raw_body = request.get_data(cache=True)
        if request.is_json and raw_body and raw_body.strip():
            return None, (jsonify({'success': False, 'error': error_message}), 400)
        return {}, None
    if not isinstance(data, dict):
        return None, (jsonify({'success': False, 'error': error_message}), 400)
    return data, None
