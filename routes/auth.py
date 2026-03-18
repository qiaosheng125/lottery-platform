"""
认证路由：登录、注册、登出
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db
from models.user import User, UserSession
from models.settings import SystemSettings
from models.audit import AuditLog
from services.session_service import create_session, delete_session
from utils.decorators import get_client_ip

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        username = (data.get('username') or '').strip()
        password = data.get('password') or ''
        device_id = data.get('device_id') or ''

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

        # Check device limit (non-admin only)
        if not user.is_admin and device_id:
            active_sessions = UserSession.query.filter_by(user_id=user.id).count()
            # Check if this device already has a session
            existing = UserSession.query.filter_by(user_id=user.id, device_id=device_id).first()
            if not existing and active_sessions >= user.max_devices:
                msg = f'已超过最大设备数限制（{user.max_devices}台）'
                if request.is_json:
                    return jsonify({'success': False, 'error': msg}), 403
                flash(msg, 'danger')
                return render_template('login.html')

        # Remove existing session for this device (re-login)
        if device_id:
            UserSession.query.filter_by(user_id=user.id, device_id=device_id).delete()
            db.session.commit()

        # Create session record
        sess = create_session(user, device_id=device_id, ip_address=get_client_ip())
        session['session_token'] = sess.session_token

        login_user(user, remember=False)

        AuditLog.log('user_login', user_id=user.id, ip_address=get_client_ip(), device_id=device_id)
        db.session.commit()

        if request.is_json:
            return jsonify({
                'success': True,
                'redirect': url_for('admin.dashboard') if user.is_admin else url_for('user.dashboard'),
                'is_admin': user.is_admin,
            })

        if user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('user.dashboard'))

    return render_template('login.html')


@auth_bp.route('/logout', methods=['POST', 'GET'])
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
@login_required
def heartbeat():
    """心跳接口：更新会话 last_seen"""
    token = session.get('session_token')
    if token:
        sess = UserSession.query.filter_by(session_token=token).first()
        if sess:
            from utils.time_utils import beijing_now
            sess.last_seen = beijing_now()
            db.session.commit()
    return jsonify({'success': True})


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    settings = SystemSettings.get()
    if not settings.registration_enabled:
        if request.is_json:
            return jsonify({'success': False, 'error': '注册已关闭'}), 403
        flash('注册已关闭', 'danger')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        username = (data.get('username') or '').strip()
        password = data.get('password') or ''

        if not username or not password:
            if request.is_json:
                return jsonify({'success': False, 'error': '用户名和密码不能为空'}), 400
            flash('用户名和密码不能为空', 'danger')
            return render_template('register.html')

        if len(username) < 2 or len(username) > 32:
            if request.is_json:
                return jsonify({'success': False, 'error': '用户名长度需在2-32字符之间'}), 400
            flash('用户名长度需在2-32字符之间', 'danger')
            return render_template('register.html')

        if User.query.filter_by(username=username).first():
            if request.is_json:
                return jsonify({'success': False, 'error': '用户名已存在'}), 409
            flash('用户名已存在', 'danger')
            return render_template('register.html')

        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        if request.is_json:
            return jsonify({'success': True, 'message': '注册成功，请登录'})
        flash('注册成功，请登录', 'success')
        return redirect(url_for('auth.login'))

    return render_template('register.html')
