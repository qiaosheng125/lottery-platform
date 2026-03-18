"""
管理员路由
"""

import os
import uuid
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, send_file, current_app
from flask_login import login_required, current_user

from extensions import db
from models.user import User, UserSession
from models.file import UploadedFile
from models.ticket import LotteryTicket
from models.winning import WinningRecord
from models.result import MatchResult, ResultFile
from models.settings import SystemSettings
from models.audit import AuditLog
from services.file_parser import process_uploaded_file, revoke_file
from services.session_service import force_logout_user
from services.ticket_pool import get_pool_status
from services.notify_service import notify_admins, notify_all
from utils.decorators import admin_required, get_client_ip
from utils.time_utils import beijing_now, get_business_date

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    return render_template('admin/dashboard.html')


@admin_bp.route('/api/dashboard-data')
@login_required
@admin_required
def dashboard_data():
    """实时 Dashboard 数据接口"""
    pool = get_pool_status()

    from sqlalchemy import text, func
    from datetime import timedelta
    from models.user import UserSession
    cutoff = beijing_now() - timedelta(minutes=2)  # 2分钟内活跃视为在线

    # Get online users via ORM (SQLite compatible)
    active_sessions = UserSession.query.filter(UserSession.last_seen > cutoff).all()
    user_ids = list({s.user_id for s in active_sessions})

    from models.user import User as UserModel
    online_users_objs = UserModel.query.filter(
        UserModel.id.in_(user_ids), UserModel.is_admin == False
    ).all() if user_ids else []

    # 计算今日业务时间范围
    today = get_business_date()
    now = beijing_now()
    today_start = datetime.combine(today, datetime.min.time())
    if now.hour < 12:
        today_start = today_start - timedelta(days=1) + timedelta(hours=12)
        today_end = today_start + timedelta(days=1)
    else:
        today_start = today_start + timedelta(hours=12)
        today_end = today_start + timedelta(days=1)

    # 在线用户统计
    user_stats = []
    for ou in online_users_objs:
        # 用数据库过滤今日完成票
        today_tickets = LotteryTicket.query.filter(
            LotteryTicket.assigned_user_id == ou.id,
            LotteryTicket.status == 'completed',
            LotteryTicket.completed_at >= today_start,
            LotteryTicket.completed_at < today_end
        ).all()
        active_count = LotteryTicket.query.filter_by(assigned_user_id=ou.id, status='assigned').count()
        device_count = len({s.device_id for s in active_sessions if s.user_id == ou.id})

        user_stats.append({
            'id': ou.id,
            'username': ou.username,
            'client_mode': ou.client_mode,
            'can_receive': ou.can_receive,
            'device_count': device_count,
            'ticket_count': len(today_tickets),
            'total_amount': sum(float(t.ticket_amount or 0) for t in today_tickets),
            'active_count': active_count,
        })

    # 今日所有用户出票统计（包括不在线的）
    daily_stats_query = db.session.query(
        LotteryTicket.assigned_username,
        func.count(LotteryTicket.id).label('count'),
        func.sum(LotteryTicket.ticket_amount).label('amount')
    ).filter(
        LotteryTicket.status == 'completed',
        LotteryTicket.completed_at >= today_start,
        LotteryTicket.completed_at < today_end
    ).group_by(LotteryTicket.assigned_username).all()

    daily_all_users = [
        {
            'username': row.assigned_username,
            'count': row.count,
            'amount': float(row.amount or 0)
        }
        for row in daily_stats_query
    ]

    return jsonify({
        'pool': pool,
        'online_users': user_stats,
        'daily_all_users': daily_all_users,
    })


# ── File management ───────────────────────────────────────────────────

@admin_bp.route('/files/upload', methods=['POST'])
@login_required
@admin_required
def upload_files():
    files = request.files.getlist('files')
    if not files:
        return jsonify({'success': False, 'error': '请选择文件'}), 400

    results = []
    for f in files:
        if not f.filename:
            continue
        result = process_uploaded_file(f, current_user.id)
        results.append(result)

    # Push pool update
    try:
        from services.notify_service import notify_pool_update
        notify_pool_update(get_pool_status())
    except Exception:
        pass

    return jsonify({'success': True, 'results': results})


@admin_bp.route('/files')
@login_required
@admin_required
def files_list():
    return render_template('admin/upload.html')


@admin_bp.route('/api/files')
@login_required
@admin_required
def api_files_list():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    status_filter = request.args.get('status', '')

    q = UploadedFile.query.order_by(UploadedFile.uploaded_at.desc())
    if status_filter:
        q = q.filter_by(status=status_filter)

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'files': [f.to_dict() for f in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'page': page,
    })


@admin_bp.route('/api/files/<int:file_id>/detail')
@login_required
@admin_required
def file_detail(file_id):
    uploaded_file = UploadedFile.query.get_or_404(file_id)
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))

    tickets = LotteryTicket.query.filter_by(source_file_id=file_id)\
        .order_by(LotteryTicket.line_number)\
        .paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'file': uploaded_file.to_dict(),
        'tickets': [t.to_dict() for t in tickets.items],
        'total': tickets.total,
        'pages': tickets.pages,
    })


@admin_bp.route('/api/files/<int:file_id>/revoke', methods=['POST'])
@login_required
@admin_required
def api_revoke_file(file_id):
    result = revoke_file(file_id, current_user.id)
    if result['success']:
        notify_pool_update = get_pool_status
        try:
            from services.notify_service import notify_pool_update as _npu
            _npu(get_pool_status())
        except Exception:
            pass
    return jsonify(result)


@admin_bp.route('/api/tickets/export')
@login_required
@admin_required
def export_tickets():
    """导出当日所有数据 CSV"""
    import csv
    import io

    today = get_business_date()

    from sqlalchemy import text
    # Use ORM for cross-db compatibility
    from models.ticket import LotteryTicket
    from models.file import UploadedFile as UF
    from datetime import timedelta
    cutoff_start = datetime.combine(today, datetime.min.time()) + timedelta(hours=12)  # today noon
    cutoff_end = cutoff_start + timedelta(days=1)  # tomorrow noon

    tickets_q = LotteryTicket.query.filter(
        LotteryTicket.completed_at >= cutoff_start,
        LotteryTicket.completed_at < cutoff_end,
    ).order_by(LotteryTicket.id).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['票ID', '行号', '原始内容', '彩种', '倍投', '截止时间', '期号',
                     '金额', '状态', '用户名', '设备名', '分配时间', '完成时间', '来源文件'])
    for t in tickets_q:
        f = UF.query.get(t.source_file_id)
        writer.writerow([
            t.id, t.line_number, t.raw_content, t.lottery_type, t.multiplier,
            t.deadline_time, t.detail_period, t.ticket_amount, t.status,
            t.assigned_username, t.assigned_device_name,
            t.assigned_at, t.completed_at, f.original_filename if f else '',
        ])

    output.seek(0)
    from flask import Response
    filename = f"tickets_{today}.csv"
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


# ── User management ───────────────────────────────────────────────────

@admin_bp.route('/users')
@login_required
@admin_required
def users_page():
    return render_template('admin/users.html')


@admin_bp.route('/api/users')
@login_required
@admin_required
def api_users_list():
    users = User.query.filter_by(is_admin=False).order_by(User.created_at).all()
    return jsonify({'users': [u.to_dict() for u in users]})


@admin_bp.route('/api/users', methods=['POST'])
@login_required
@admin_required
def api_create_user():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    client_mode = data.get('client_mode', 'mode_a')
    max_devices = int(data.get('max_devices', 1))

    if not username or not password:
        return jsonify({'success': False, 'error': '用户名和密码不能为空'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': '用户名已存在'}), 409

    user = User(username=username, client_mode=client_mode, max_devices=max_devices)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({'success': True, 'user': user.to_dict()})


@admin_bp.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
def api_update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()

    if 'client_mode' in data:
        user.client_mode = data['client_mode']
    if 'max_devices' in data:
        user.max_devices = int(data['max_devices'])
    if 'is_active' in data:
        user.is_active = bool(data['is_active'])
    if 'can_receive' in data:
        user.can_receive = bool(data['can_receive'])
    if 'password' in data and data['password']:
        user.set_password(data['password'])

    db.session.commit()
    return jsonify({'success': True, 'user': user.to_dict()})


@admin_bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/api/users/<int:user_id>/force-logout', methods=['POST'])
@login_required
@admin_required
def api_force_logout(user_id):
    count = force_logout_user(user_id, '管理员强制下线')
    AuditLog.log('force_logout', user_id=current_user.id,
                 resource_type='user', resource_id=user_id)
    db.session.commit()
    return jsonify({'success': True, 'sessions_cleared': count})


@admin_bp.route('/api/users/<int:user_id>/can-receive', methods=['PUT'])
@login_required
@admin_required
def api_toggle_can_receive(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    user.can_receive = bool(data.get('can_receive', True))
    db.session.commit()
    return jsonify({'success': True, 'can_receive': user.can_receive})


# ── Winning management ────────────────────────────────────────────────

@admin_bp.route('/winning')
@login_required
@admin_required
def winning_page():
    return render_template('admin/winning.html')


@admin_bp.route('/api/winning/filter-options')
@login_required
@admin_required
def api_winning_filter_options():
    """获取中奖记录筛选下拉选项（用户名列表和期号列表）"""
    from sqlalchemy import distinct
    usernames = db.session.query(distinct(LotteryTicket.assigned_username))\
        .filter(LotteryTicket.assigned_username.isnot(None))\
        .order_by(LotteryTicket.assigned_username).all()
    periods = db.session.query(distinct(WinningRecord.detail_period))\
        .filter(WinningRecord.detail_period.isnot(None))\
        .order_by(WinningRecord.detail_period.desc()).all()
    return jsonify({
        'usernames': [u[0] for u in usernames if u[0]],
        'periods': [p[0] for p in periods if p[0]],
    })


@admin_bp.route('/api/winning')
@login_required
@admin_required
def api_winning_list():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    username = request.args.get('username', '').strip()
    date_str = request.args.get('date', '')
    period = request.args.get('period', '').strip()

    q = WinningRecord.query.order_by(WinningRecord.uploaded_at.desc())
    if username:
        q = q.join(LotteryTicket, WinningRecord.ticket_id == LotteryTicket.id)\
             .filter(LotteryTicket.assigned_username.ilike(f'%{username}%'))
    if period:
        q = q.filter(WinningRecord.detail_period == period)

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'records': [r.to_dict() for r in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
    })


@admin_bp.route('/api/winning/<int:record_id>/presign', methods=['POST'])
@login_required
@admin_required
def admin_winning_presign(record_id):
    record = WinningRecord.query.get_or_404(record_id)
    from services.oss_service import generate_presign_url, build_oss_key
    oss_key = build_oss_key(record.ticket_id)
    url, key = generate_presign_url(oss_key)
    return jsonify({'success': True, 'url': url, 'oss_key': key})


# ── Match results ─────────────────────────────────────────────────────

@admin_bp.route('/match-results/upload', methods=['POST'])
@login_required
@admin_required
def upload_match_result():
    """上传赛果文件，自动触发中奖计算"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '请选择文件'}), 400

    file = request.files['file']
    detail_period = (request.form.get('detail_period') or '').strip()
    if not detail_period:
        return jsonify({'success': False, 'error': '请输入期号'}), 400

    upload_folder = current_app.config['UPLOAD_FOLDER']
    stored = f"result_{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = os.path.join(upload_folder, stored)
    file.save(file_path)

    result_file = ResultFile(
        original_filename=file.filename,
        stored_filename=stored,
        uploaded_by=current_user.id,
    )
    db.session.add(result_file)
    db.session.flush()

    from services.result_parser import parse_result_file
    result = parse_result_file(file_path, detail_period, current_user.id, result_file.id)

    if not result['success']:
        result_file.status = 'error'
        result_file.parse_error = result.get('error')
        db.session.commit()
        return jsonify({'success': False, 'error': result.get('error')}), 400

    result_file.periods_count = result['count']
    db.session.commit()

    # Trigger async winning calculation
    match_result_id = result['match_result_id']
    from tasks.scheduler import get_scheduler
    sched = get_scheduler()
    if sched:
        from services.winning_calc_service import process_match_result
        sched.add_job(
            func=process_match_result,
            args=[match_result_id],
            id=f'winning_calc_{match_result_id}',
            replace_existing=True,
        )

    return jsonify({'success': True, 'match_result_id': match_result_id, 'count': result['count']})


@admin_bp.route('/api/match-results')
@login_required
@admin_required
def api_match_results():
    results = MatchResult.query.order_by(MatchResult.uploaded_at.desc()).limit(50).all()
    return jsonify({'results': [r.to_dict() for r in results]})


@admin_bp.route('/api/match-results/<int:result_id>/recalc', methods=['POST'])
@login_required
@admin_required
def api_recalc(result_id):
    from tasks.scheduler import get_scheduler
    from services.winning_calc_service import process_match_result
    match_result = MatchResult.query.get_or_404(result_id)
    match_result.calc_status = 'pending'
    db.session.commit()

    sched = get_scheduler()
    if sched:
        sched.add_job(
            func=process_match_result,
            args=[result_id],
            id=f'winning_recalc_{result_id}',
            replace_existing=True,
        )
    return jsonify({'success': True})


# ── Settings ──────────────────────────────────────────────────────────

@admin_bp.route('/settings')
@login_required
@admin_required
def settings_page():
    return render_template('admin/settings.html')


@admin_bp.route('/api/settings', methods=['GET'])
@login_required
@admin_required
def api_get_settings():
    settings = SystemSettings.get()
    return jsonify(settings.to_dict())


@admin_bp.route('/api/settings', methods=['PUT'])
@login_required
@admin_required
def api_update_settings():
    data = request.get_json()
    settings = SystemSettings.get()

    for field in ['registration_enabled', 'pool_enabled', 'mode_a_enabled', 'mode_b_enabled',
                  'mode_b_options', 'announcement', 'announcement_enabled',
                  'session_lifetime_hours', 'daily_reset_hour']:
        if field in data:
            setattr(settings, field, data[field])

    settings.updated_by = current_user.id
    db.session.commit()

    if data.get('announcement_enabled') and data.get('announcement'):
        notify_all('announcement', {'content': data['announcement']})

    if not data.get('pool_enabled', True):
        notify_all('pool_disabled', {'message': '票池已关闭'})

    return jsonify({'success': True, 'settings': settings.to_dict()})
