"""
认证相关路由：登录、登出、心跳、公开注册关闭。
"""

from datetime import timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import db
from models.audit import AuditLog
from models.settings import SystemSettings
from models.user import User, UserSession
from services.session_service import create_session, delete_session
from utils.decorators import get_client_ip, login_required_json, parse_json_object
from utils.time_utils import beijing_now

auth_bp = Blueprint('auth', __name__)


def _normalize_device_id(raw_device_id):
    if raw_device_id is None:
        return ''
    if not isinstance(raw_device_id, str):
        return None
    return raw_device_id.strip()


def _validate_device_id(device_id):
    if not device_id:
        return None
    if len(device_id) > 20 or not all(c.isalnum() or c in '-_' for c in device_id):
        return 'invalid device_id'
    return None


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        redirect_target = url_for('admin.dashboard') if current_user.is_admin else url_for('user.dashboard')
        if request.method == 'POST' and request.is_json:
            return jsonify({
                'success': True,
                'redirect': redirect_target,
                'is_admin': current_user.is_admin,
                'client_mode': current_user.client_mode,
            })
        return redirect(url_for('index'))

    if request.method == 'POST':
        if request.is_json:
            data, data_error = parse_json_object()
            if data_error:
                return data_error
        else:
            data = request.form
        raw_username = data.get('username')
        if raw_username is None:
            username = ''
        elif isinstance(raw_username, str):
            username = raw_username.strip()
        else:
            if request.is_json:
                return jsonify({'success': False, 'error': 'invalid username type'}), 400
            flash('invalid username type', 'danger')
            return render_template('login.html')

        raw_password = data.get('password')
        password = '' if raw_password is None else raw_password
        if not isinstance(password, str):
            if request.is_json:
                return jsonify({'success': False, 'error': 'invalid password type'}), 400
            flash('invalid password type', 'danger')
            return render_template('login.html')
        device_id = _normalize_device_id(data.get('device_id'))
        if device_id is None:
            if request.is_json:
                return jsonify({'success': False, 'error': 'invalid device_id type'}), 400
            flash('invalid device_id type', 'danger')
            return render_template('login.html')
        device_error = _validate_device_id(device_id)
        if device_error:
            if request.is_json:
                return jsonify({'success': False, 'error': device_error}), 400
            flash(device_error, 'danger')
            return render_template('login.html')

        user = User.query.filter_by(username=username).first()

        if not user or not user.check_password(password):
            if request.is_json:
                return jsonify({'success': False, 'error': '用户名或密码错误'}), 401
            flash('用户名或密码错误', 'danger')
            return render_template('login.html')

        if not user.is_active:
            if request.is_json:
                return jsonify({'success': False, 'error': '账号已被禁用'}), 403
            flash('账号已被禁用', 'danger')
            return render_template('login.html')

        if not user.is_admin:
            settings = SystemSettings.get()
            cutoff = beijing_now() - timedelta(hours=settings.session_lifetime_hours)
            active_sessions = UserSession.query.filter_by(user_id=user.id).filter(
                UserSession.last_seen >= cutoff
            ).count()
            existing = None
            if device_id:
                existing = UserSession.query.filter_by(user_id=user.id, device_id=device_id).filter(
                    UserSession.last_seen >= cutoff
                ).first()
            if not existing and active_sessions >= user.max_devices:
                message = f'已超过最大设备数限制（{user.max_devices}台）'
                if request.is_json:
                    return jsonify({'success': False, 'error': message}), 403
                flash(message, 'danger')
                return render_template('login.html')

        if device_id:
            UserSession.query.filter_by(user_id=user.id, device_id=device_id).delete()
            db.session.commit()

        session_record = create_session(user, device_id=device_id, ip_address=get_client_ip())
        session['session_token'] = session_record.session_token

        login_user(user, remember=False)

        AuditLog.log('user_login', user_id=user.id, ip_address=get_client_ip(), device_id=device_id)
        db.session.commit()

        if request.is_json:
            return jsonify({
                'success': True,
                'redirect': url_for('admin.dashboard') if user.is_admin else url_for('user.dashboard'),
                'is_admin': user.is_admin,
                'client_mode': user.client_mode,
            })

        if user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('user.dashboard'))

    return render_template('login.html')


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    token = session.pop('session_token', None)
    if token:
        delete_session(token)
    AuditLog.log('user_logout', user_id=current_user.id, ip_address=get_client_ip())
    db.session.commit()
    logout_user()
    return redirect(url_for('auth.login'))


@auth_bp.route('/heartbeat', methods=['POST'])
@login_required_json
@login_required
def heartbeat():
    """心跳接口：刷新会话活跃时间。"""
    token = session.get('session_token')
    if token:
        session_record = UserSession.query.filter_by(session_token=token).first()
        if session_record:
            data, data_error = parse_json_object()
            if data_error:
                return data_error
            device_id = _normalize_device_id(data.get('device_id'))
            if device_id is None:
                return jsonify({'success': False, 'error': 'invalid device_id type'}), 400
            device_error = _validate_device_id(device_id)
            if device_error:
                return jsonify({'success': False, 'error': device_error}), 400
            if device_id:
                session_record.device_id = device_id
            now = beijing_now()
            session_record.last_seen = now
            settings = SystemSettings.get()
            session_record.expires_at = now + timedelta(hours=settings.session_lifetime_hours)
            db.session.commit()
    return jsonify({'success': True})


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    message = '公开注册已关闭，请联系管理员创建账号'
    if request.is_json:
        return jsonify({'success': False, 'error': message}), 403

    flash(message, 'warning')
    return redirect(url_for('auth.login'))
