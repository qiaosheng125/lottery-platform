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
    device_speed_stats = []  # 设备速度统计
    total_speed = 0.0  # 总速度（每分钟张数）

    # 计算最近30分钟的时间点（用于速度统计，时间窗口更长更稳定）
    SPEED_WINDOW_MINUTES = 30
    speed_window_start = beijing_now() - timedelta(minutes=SPEED_WINDOW_MINUTES)

    # 优化：一次性查询所有在线用户的最近完成票（避免N+1查询）
    online_user_ids = [ou.id for ou in online_users_objs]
    all_recent_tickets = LotteryTicket.query.filter(
        LotteryTicket.assigned_user_id.in_(online_user_ids),
        LotteryTicket.status == 'completed',
        LotteryTicket.completed_at >= speed_window_start
    ).all() if online_user_ids else []

    # 按 (user_id, device_id) 分组
    from collections import defaultdict
    tickets_by_device = defaultdict(list)
    for t in all_recent_tickets:
        key = (t.assigned_user_id, t.assigned_device_id)
        tickets_by_device[key].append(t)

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

        # 统计该用户每个设备的处理速度
        user_devices = {s.device_id for s in active_sessions if s.user_id == ou.id and s.device_id}
        for device_id in user_devices:
            # 从预加载的数据中获取该设备的最近完成票
            recent_tickets = tickets_by_device.get((ou.id, device_id), [])

            if recent_tickets and len(recent_tickets) >= 2:  # 至少2张票才能计算速度
                # 计算实际出票时间跨度（从第一张到最后一张的时间差）
                sorted_tickets = sorted(recent_tickets, key=lambda t: t.completed_at)
                first_time = sorted_tickets[0].completed_at
                last_time = sorted_tickets[-1].completed_at
                time_span_minutes = (last_time - first_time).total_seconds() / 60.0

                # 如果时间跨度太短（<1分钟），使用固定1分钟避免速度过高
                if time_span_minutes < 1.0:
                    time_span_minutes = 1.0

                # 计算速度：票数 / 实际出票时间跨度
                speed_per_minute = len(recent_tickets) / time_span_minutes
                total_speed += speed_per_minute

                device_name = recent_tickets[0].assigned_device_name or device_id
                device_speed_stats.append({
                    'username': ou.username,
                    'device_id': device_id,
                    'device_name': device_name,
                    'speed_per_minute': round(speed_per_minute, 2),
                    'recent_count': len(recent_tickets),
                    'time_span_minutes': round(time_span_minutes, 1),
                })

    # 计算预估完成时间
    estimated_minutes = None
    estimated_time_str = None
    if total_speed > 0.01 and pool['total_pending'] > 0:  # 至少每分钟0.01张
        estimated_minutes = pool['total_pending'] / total_speed
        # 添加上限保护（超过7天显示提示）
        if estimated_minutes > 10080:  # 7天 = 10080分钟
            estimated_time_str = "超过7天"
        else:
            hours = int(estimated_minutes // 60)
            minutes = int(estimated_minutes % 60)
            if hours > 0:
                estimated_time_str = f"{hours}小时{minutes}分钟"
            else:
                estimated_time_str = f"{minutes}分钟"

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
        'device_speed_stats': device_speed_stats,
        'total_speed': round(total_speed, 2),
        'estimated_time': estimated_time_str,
        'estimated_minutes': round(estimated_minutes, 1) if estimated_minutes else None,
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
    from sqlalchemy import func
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    status_filter = request.args.get('status', '')
    date_str = request.args.get('date', '').strip()

    q = UploadedFile.query.order_by(UploadedFile.uploaded_at.desc())
    if status_filter:
        q = q.filter_by(status=status_filter)
    if date_str:
        q = q.filter(
            func.date(func.datetime(UploadedFile.uploaded_at, '+8 hours')) == date_str
        )

    # 日期选项（北京时间）
    dates_raw = db.session.query(
        func.date(func.datetime(UploadedFile.uploaded_at, '+8 hours'))
    ).distinct().order_by(
        func.date(func.datetime(UploadedFile.uploaded_at, '+8 hours')).desc()
    ).all()
    date_options = [d[0] for d in dates_raw if d[0]]

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'files': [f.to_dict() for f in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'page': page,
        'date_options': date_options,
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

@admin_bp.route('/api/tickets/export-by-date')
@login_required
@admin_required
def export_tickets_by_date():
    """按上传日期导出该日所有票数据 XLSX"""
    import io as _io
    from openpyxl import Workbook
    from sqlalchemy import func
    from urllib.parse import quote

    date_str = request.args.get('date', '').strip()

    q = LotteryTicket.query
    if date_str:
        file_ids = db.session.query(UploadedFile.id).filter(
            func.date(func.datetime(UploadedFile.uploaded_at, '+8 hours')) == date_str
        ).all()
        file_ids = [r[0] for r in file_ids]
        if not file_ids:
            wb = Workbook()
            ws = wb.active
            ws.append(['行号', '原始内容', '彩种', '倍投', '截止时间', '期号', '金额', '状态', '用户名', '设备名', '分配时间', '完成时间', '来源文件名'])
            buf = _io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            from flask import Response
            return Response(buf.read(),
                            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            headers={'Content-Disposition': 'attachment; filename="empty.xlsx"'})
        q = q.filter(LotteryTicket.source_file_id.in_(file_ids))

    tickets = q.order_by(LotteryTicket.source_file_id, LotteryTicket.line_number).all()

    file_map = {f.id: f.original_filename for f in UploadedFile.query.all()}

    wb = Workbook()
    ws = wb.active
    ws.append(['行号', '原始内容', '彩种', '倍投', '截止时间', '期号', '金额', '状态', '用户名', '设备名', '分配时间', '完成时间', '来源文件名'])
    status_map = {'pending': '待出票', 'assigned': '出票中', 'completed': '已完成',
                  'revoked': '已撤回', 'expired': '已过期'}
    for t in tickets:
        ws.append([
            t.line_number,
            t.raw_content or '',
            t.lottery_type or '',
            f"{t.multiplier}倍" if t.multiplier else '',
            t.deadline_time.strftime('%Y-%m-%d %H:%M') if t.deadline_time else '',
            t.detail_period or '',
            float(t.ticket_amount or 0),
            status_map.get(t.status, t.status),
            t.assigned_username or '',
            t.assigned_device_name or '',
            t.assigned_at.strftime('%Y-%m-%d %H:%M:%S') if t.assigned_at else '',
            t.completed_at.strftime('%Y-%m-%d %H:%M:%S') if t.completed_at else '',
            file_map.get(t.source_file_id, ''),
        ])

    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    from flask import Response
    period_str = next((t.detail_period for t in tickets if t.detail_period), '未知期号')
    filename = f"{date_str or '全部'}_{period_str}投注内容详情.xlsx"
    filename_encoded = quote(filename, encoding='utf-8')
    return Response(
        buf.read(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{filename_encoded}"},
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
    from sqlalchemy import distinct, func
    usernames = db.session.query(distinct(LotteryTicket.assigned_username))\
        .filter(LotteryTicket.assigned_username.isnot(None),
                LotteryTicket.is_winning == True)\
        .order_by(LotteryTicket.assigned_username).all()
    dates_raw = db.session.query(
        func.date(func.datetime(LotteryTicket.completed_at, '+8 hours'))
    ).filter(
        LotteryTicket.is_winning == True,
        LotteryTicket.completed_at.isnot(None)
    ).distinct().order_by(
        func.date(func.datetime(LotteryTicket.completed_at, '+8 hours')).desc()
    ).all()
    types_raw = db.session.query(distinct(LotteryTicket.lottery_type))\
        .filter(LotteryTicket.is_winning == True,
                LotteryTicket.lottery_type.isnot(None))\
        .order_by(LotteryTicket.lottery_type).all()
    return jsonify({
        'usernames': [u[0] for u in usernames if u[0]],
        'dates': [d[0] for d in dates_raw if d[0]],
        'lottery_types': [t[0] for t in types_raw if t[0]],
    })


@admin_bp.route('/api/winning')
@login_required
@admin_required
def api_winning_list():
    """查询中奖票列表（从 LotteryTicket 查 is_winning=True）"""
    from sqlalchemy import func
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    username = request.args.get('username', '').strip()
    date_str = request.args.get('date', '').strip()
    lottery_type = request.args.get('lottery_type', '').strip()
    image_filter = request.args.get('image_filter', '').strip()  # 'uploaded' | 'missing'

    q = LotteryTicket.query.filter(LotteryTicket.is_winning == True)
    if username:
        q = q.filter(LotteryTicket.assigned_username == username)
    if date_str:
        q = q.filter(
            func.date(func.datetime(LotteryTicket.completed_at, '+8 hours')) == date_str
        )
    if lottery_type:
        q = q.filter(LotteryTicket.lottery_type == lottery_type)
    if image_filter == 'uploaded':
        q = q.filter(LotteryTicket.winning_image_url.isnot(None),
                     LotteryTicket.winning_image_url != '')
    elif image_filter == 'missing':
        q = q.filter(
            (LotteryTicket.winning_image_url == None) |
            (LotteryTicket.winning_image_url == '')
        )
    q = q.order_by(LotteryTicket.completed_at.desc())

    # 汇总（全量，不分页）
    all_items = q.all()
    summary_amount = sum(float(t.winning_amount or 0) for t in all_items)
    summary_gross  = sum(float(t.winning_gross  or 0) for t in all_items)
    summary_tax    = sum(float(t.winning_tax    or 0) for t in all_items)
    total = len(all_items)

    # 分页切片
    start = (page - 1) * per_page
    page_items = all_items[start:start + per_page]
    import math
    pages = math.ceil(total / per_page) if total else 1

    records = []
    for t in page_items:
        records.append({
            'ticket_id': t.id,
            'username': t.assigned_username or '-',
            'device_id': t.assigned_device_id or '-',
            'device_name': t.assigned_device_name or '-',
            'lottery_type': t.lottery_type,
            'detail_period': t.detail_period,
            'winning_gross': float(t.winning_gross) if t.winning_gross else 0,
            'winning_amount': float(t.winning_amount) if t.winning_amount else 0,
            'winning_tax': float(t.winning_tax) if t.winning_tax else 0,
            'winning_image_url': t.winning_image_url or '',
            'raw_content': t.raw_content or '',
            'ticket_amount': float(t.ticket_amount) if t.ticket_amount else 0,
            'completed_at': (t.completed_at.isoformat() if t.completed_at else None),
        })
    return jsonify({
        'records': records,
        'total': total,
        'pages': pages,
        'summary': {
            'amount': round(summary_amount, 2),
            'gross':  round(summary_gross,  2),
            'tax':    round(summary_tax,    2),
            'count':  total,
        },
    })


@admin_bp.route('/api/winning/export')
@login_required
@admin_required
def api_winning_export():
    """导出当前筛选条件下的所有中奖条目为 XLSX"""
    import io as _io
    from openpyxl import Workbook
    from sqlalchemy import func

    username     = request.args.get('username', '').strip()
    date_str     = request.args.get('date', '').strip()
    lottery_type = request.args.get('lottery_type', '').strip()
    image_filter = request.args.get('image_filter', '').strip()

    q = LotteryTicket.query.filter(LotteryTicket.is_winning == True)
    if username:
        q = q.filter(LotteryTicket.assigned_username == username)
    if date_str:
        q = q.filter(
            func.date(func.datetime(LotteryTicket.completed_at, '+8 hours')) == date_str
        )
    if lottery_type:
        q = q.filter(LotteryTicket.lottery_type == lottery_type)
    if image_filter == 'uploaded':
        q = q.filter(LotteryTicket.winning_image_url.isnot(None),
                     LotteryTicket.winning_image_url != '')
    elif image_filter == 'missing':
        q = q.filter(
            (LotteryTicket.winning_image_url == None) |
            (LotteryTicket.winning_image_url == '')
        )
    items = q.order_by(LotteryTicket.completed_at.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.append(['票ID', '投注内容', '票面金额', '用户名', '设备名', '彩种', '期号',
               '税前金额', '税后金额', '税金', '图片状态', '完成时间'])
    for t in items:
        ws.append([
            t.id,
            t.raw_content or '',
            float(t.ticket_amount or 0),
            t.assigned_username or '',
            t.assigned_device_name or '',
            t.lottery_type or '',
            t.detail_period or '',
            float(t.winning_gross or 0),
            float(t.winning_amount or 0),
            float(t.winning_tax or 0),
            '已上传' if t.winning_image_url else '未上传',
            t.completed_at.strftime('%Y-%m-%d %H:%M:%S') if t.completed_at else '',
        ])

    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    from flask import Response
    from urllib.parse import quote
    parts = ['中奖记录']
    if username:     parts.append(username)
    if date_str:     parts.append(date_str)
    if lottery_type: parts.append(lottery_type)
    if image_filter == 'uploaded':  parts.append('已上传')
    elif image_filter == 'missing': parts.append('未上传')
    from utils.time_utils import beijing_now
    parts.append(beijing_now().strftime('%Y%m%d_%H%M%S'))
    filename = '_'.join(parts) + '.xlsx'
    filename_encoded = quote(filename, encoding='utf-8')
    return Response(
        buf.read(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{filename_encoded}"},
    )


@admin_bp.route('/api/winning/<int:ticket_id>/presign', methods=['POST'])
@login_required
@admin_required
def admin_winning_presign(ticket_id):
    ticket = LotteryTicket.query.get_or_404(ticket_id)
    from services.oss_service import generate_presign_url, build_oss_key
    oss_key = build_oss_key(ticket.id)
    url, key = generate_presign_url(oss_key)
    return jsonify({'success': True, 'url': url, 'oss_key': key})


@admin_bp.route('/api/winning/record', methods=['POST'])
@login_required
@admin_required
def admin_winning_record():
    """管理员更新中奖图片URL"""
    data = request.get_json() or {}
    ticket_id = data.get('ticket_id')
    oss_key = data.get('oss_key', '')
    if not ticket_id:
        return jsonify({'success': False, 'error': '缺少ticket_id'}), 400
    ticket = LotteryTicket.query.get_or_404(int(ticket_id))
    from services.oss_service import get_public_url
    image_url = get_public_url(oss_key) if oss_key else ''
    ticket.winning_image_url = image_url
    db.session.commit()
    return jsonify({'success': True, 'image_url': image_url})


@admin_bp.route('/api/winning/<int:ticket_id>/upload-image', methods=['POST'])
@login_required
@admin_required
def admin_winning_upload_image(ticket_id):
    """直接上传中奖图片，自动压缩后存储（本地或OSS）"""
    ticket = LotteryTicket.query.get_or_404(ticket_id)

    if 'image' not in request.files:
        return jsonify({'success': False, 'error': '请选择图片文件'}), 400

    file = request.files['image']
    if not file.filename:
        return jsonify({'success': False, 'error': '文件名为空'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
    if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
        return jsonify({'success': False, 'error': '不支持的图片格式'}), 400

    # 压缩图片：最长边不超过 1200px，JPEG 质量 80
    import io as _io
    from PIL import Image as _Image
    try:
        img = _Image.open(file.stream)
        img = img.convert('RGB')  # 统一转 RGB（兼容 PNG/WEBP 透明通道）
        max_side = 1200
        if max(img.width, img.height) > max_side:
            img.thumbnail((max_side, max_side), _Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format='JPEG', quality=80, optimize=True)
        buf.seek(0)
        compressed = buf
        save_ext = 'jpg'
    except Exception as e:
        return jsonify({'success': False, 'error': f'图片处理失败: {e}'}), 400

    from services.oss_service import _oss_configured, build_oss_key, get_public_url

    if _oss_configured():
        from services.oss_service import _get_bucket
        oss_key = build_oss_key(ticket_id, save_ext)
        try:
            _get_bucket().put_object(oss_key, compressed.read())
            image_url = get_public_url(oss_key)
        except Exception as e:
            return jsonify({'success': False, 'error': f'OSS上传失败: {e}'}), 500
    else:
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        images_dir = os.path.join(upload_folder, 'images')
        os.makedirs(images_dir, exist_ok=True)
        filename = f"winning_{ticket_id}_{uuid.uuid4().hex[:8]}.{save_ext}"
        save_path = os.path.join(images_dir, filename)
        with open(save_path, 'wb') as f:
            f.write(compressed.read())
        image_url = f"/uploads/images/{filename}"

    ticket.winning_image_url = image_url
    db.session.commit()
    return jsonify({'success': True, 'image_url': image_url})


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
    from sqlalchemy import func
    date_str = request.args.get('date', '').strip()
    q = MatchResult.query.order_by(MatchResult.uploaded_at.desc())
    if date_str:
        q = q.filter(
            func.date(func.datetime(MatchResult.uploaded_at, '+8 hours')) == date_str
        )
    results = q.limit(100).all()
    # 附带日期列表供前端筛选
    dates_raw = db.session.query(
        func.date(func.datetime(MatchResult.uploaded_at, '+8 hours'))
    ).distinct().order_by(
        func.date(func.datetime(MatchResult.uploaded_at, '+8 hours')).desc()
    ).all()
    return jsonify({
        'results': [r.to_dict() for r in results],
        'dates': [d[0] for d in dates_raw if d[0]],
    })


@admin_bp.route('/api/match-results/<int:result_id>/detail')
@login_required
@admin_required
def api_match_result_detail(result_id):
    """查看某条赛果的详细内容（result_data）"""
    mr = MatchResult.query.get_or_404(result_id)
    return jsonify({'success': True, 'result_data': mr.result_data, 'detail_period': mr.detail_period})


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
