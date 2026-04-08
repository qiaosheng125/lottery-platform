"""
管理员路由
"""

import os
import uuid
from datetime import datetime, timedelta
from urllib.parse import unquote

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
from utils.decorators import admin_required, get_client_ip, login_required_json
from utils.time_utils import beijing_now, get_business_date, get_business_window, get_today_noon

admin_bp = Blueprint('admin', __name__)


def _winning_terminal_at(ticket: LotteryTicket):
    return ticket.completed_at or ticket.deadline_time or ticket.assigned_at or ticket.admin_upload_time


def _winning_status_label(status: str) -> str:
    if status == 'expired':
        return '已过期未出票'
    if status == 'completed':
        return '已完成'
    if status == 'revoked':
        return '已撤回'
    return status or ''


def _get_winning_ticket_or_error(ticket_id_value):
    parsed_ticket_id = _parse_int_arg(ticket_id_value, minimum=1)
    if parsed_ticket_id is None:
        return None, (jsonify({'success': False, 'error': '票ID必须是大于 0 的整数'}), 400)

    ticket = db.session.get(LotteryTicket, parsed_ticket_id)
    if not ticket:
        return None, (jsonify({'success': False, 'error': '票据不存在'}), 404)
    if not ticket.is_winning:
        return None, (jsonify({'success': False, 'error': '该票未被系统判定为中奖，不能上传中奖图片'}), 400)
    return ticket, None


def _parse_int_arg(value, minimum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None and parsed < minimum:
        return None
    return parsed


def _parse_client_mode(value):
    if value not in {'mode_a', 'mode_b'}:
        return None
    return value


def _parse_bool_flag(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'true', '1'}:
            return True
        if normalized in {'false', '0'}:
            return False
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return None


def _database_display_info():
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if db_uri.startswith('sqlite:///'):
        raw_path = db_uri[len('sqlite:///'):]
        return {
            'engine': 'sqlite',
            'path': raw_path.replace('/', os.sep),
        }

    return {
        'engine': db_uri.split(':', 1)[0] if db_uri else 'unknown',
        'path': unquote(db_uri),
    }


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
    today_start = get_today_noon()
    today_end = today_start + timedelta(days=1)

    # 在线用户统计
    user_stats = []
    device_speed_stats = []  # 设备速度统计
    total_speed = 0.0  # 总速度（每分钟张数，只统计当前在线设备）

    # 计算最近1440分钟（24小时）的时间点（用于速度统计，时间窗口更长更稳定）
    SPEED_WINDOW_MINUTES = 1440
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

            if recent_tickets and len(recent_tickets) >= 1:  # 至少1张票才能计算速度
                # 筛选有效票（有分配和完成时间）
                valid_tickets = [t for t in recent_tickets if t.assigned_at and t.completed_at]

                if valid_tickets:
                    # 计算实际时间跨度：从最早分配到最晚完成
                    # 对于 B 模式，同一批次的 assigned_at 是相同的
                    # 如果只有一批次，速度会根据单张票的时间计算（如果 span 为 0 会有保护值）
                    sorted_by_assigned = sorted(valid_tickets, key=lambda t: t.assigned_at)
                    sorted_by_completed = sorted(valid_tickets, key=lambda t: t.completed_at)

                    earliest_assigned = sorted_by_assigned[0].assigned_at
                    latest_completed = sorted_by_completed[-1].completed_at

                    time_span_seconds = (latest_completed - earliest_assigned).total_seconds()
                    time_span_minutes = time_span_seconds / 60.0

                    # 统一保护值：如果时间跨度太短（<=0 或 <0.1分钟即6秒），使用0.1分钟避免速度过高
                    if time_span_minutes <= 0 or time_span_minutes < 0.1:
                        time_span_minutes = 0.1

                    # 速度 = 票数 / 时间跨度（分钟）
                    speed_per_minute = len(valid_tickets) / time_span_minutes
                    total_speed += speed_per_minute

                    device_name = valid_tickets[0].assigned_device_name or device_id
                    device_speed_stats.append({
                        'username': ou.username,
                        'device_id': device_id,
                        'device_name': device_name,
                        'speed_per_minute': round(speed_per_minute, 2),
                        'recent_count': len(valid_tickets),
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
@login_required_json
@login_required
@admin_required
def upload_files():
    files = request.files.getlist('files')
    if not files:
        return jsonify({'success': False, 'error': '请选择文件'}), 400

    results = []
    for f in files:
        if not f.filename:
            results.append({
                'success': False,
                'filename': '',
                'file_id': None,
                'message': '文件名为空',
            })
            continue
        try:
            result = process_uploaded_file(f, current_user.id)
        except Exception as exc:
            current_app.logger.exception("Admin upload failed for file %s", getattr(f, 'filename', ''))
            result = {
                'success': False,
                'filename': getattr(f, 'filename', '') or '',
                'file_id': None,
                'message': f'上传处理失败: {exc}',
            }
        results.append(result)

    any_success = any(result.get('success') for result in results)

    if any_success:
        try:
            from services.notify_service import notify_pool_update
            notify_pool_update(get_pool_status())
        except Exception:
            pass

    if not any_success:
        return jsonify({'success': False, 'results': results, 'error': '本次上传全部失败'}), 400

    return jsonify({'success': True, 'results': results})


@admin_bp.route('/files')
@login_required
@admin_required
def files_list():
    return render_template('admin/upload.html')


@admin_bp.route('/api/files')
@login_required_json
@login_required
@admin_required
def api_files_list():
    page = _parse_int_arg(request.args.get('page', 1), minimum=1)
    per_page = _parse_int_arg(request.args.get('per_page', 20), minimum=1)
    if page is None or per_page is None:
        return jsonify({'success': False, 'error': '分页参数必须是大于 0 的整数'}), 400
    status_filter = request.args.get('status', '')
    date_str = request.args.get('date', '').strip()

    q = UploadedFile.query.order_by(UploadedFile.uploaded_at.desc())
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'error': '日期格式无效，请使用 YYYY-MM-DD'}), 400
        start_at, end_at = get_business_window(selected_date)
        q = q.filter(
            UploadedFile.uploaded_at >= start_at,
            UploadedFile.uploaded_at < end_at,
        )

    # 日期选项（业务日）
    uploaded_rows = db.session.query(UploadedFile.uploaded_at).filter(
        UploadedFile.uploaded_at.isnot(None)
    ).all()
    date_options = sorted(
        {str(get_business_date(row[0])) for row in uploaded_rows if row[0]},
        reverse=True,
    )

    all_files = q.all()
    if status_filter:
        all_files = [uploaded_file for uploaded_file in all_files if uploaded_file.derived_status() == status_filter]

    total = len(all_files)
    pages = (total + per_page - 1) // per_page if total else 0
    if pages > 0:
        page = min(page, pages)
    else:
        page = 1
    start = (page - 1) * per_page
    items = all_files[start:start + per_page]

    return jsonify({
        'files': [f.to_dict() for f in items],
        'total': total,
        'pages': pages,
        'page': page,
        'date_options': date_options,
    })


@admin_bp.route('/api/files/<int:file_id>/detail')
@login_required_json
@login_required
@admin_required
def file_detail(file_id):
    uploaded_file = db.session.get(UploadedFile, file_id)
    if not uploaded_file:
        return jsonify({'success': False, 'error': '文件不存在'}), 404
    page = _parse_int_arg(request.args.get('page', 1), minimum=1)
    per_page = _parse_int_arg(request.args.get('per_page', 50), minimum=1)
    if page is None or per_page is None:
        return jsonify({'success': False, 'error': '分页参数必须是大于 0 的整数'}), 400

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
@login_required_json
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
    message = result.get('message') or ''
    if '不存在' in message:
        return jsonify(result), 404
    if not result['success']:
        return jsonify(result), 400
    return jsonify(result)


@admin_bp.route('/api/tickets/export')
@login_required
@admin_required
def export_tickets():
    """导出当日终态数据 CSV（completed + expired）"""
    import csv
    import io

    from models.ticket import LotteryTicket
    from models.file import UploadedFile as UF
    cutoff_start = get_today_noon()
    cutoff_end = cutoff_start + timedelta(days=1)

    all_tickets = LotteryTicket.query.filter(
        LotteryTicket.status.in_(['completed', 'expired']),
    ).order_by(LotteryTicket.id).all()
    tickets_q = [
        ticket for ticket in all_tickets
        if (terminal_at := _winning_terminal_at(ticket)) and cutoff_start <= terminal_at < cutoff_end
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['票ID', '行号', '原始内容', '彩种', '倍投', '截止时间', '期号',
                     '金额', '状态', '用户名', '设备ID', '设备名', '分配时间', '完成时间', '来源文件'])
    for t in tickets_q:
        f = db.session.get(UF, t.source_file_id)
        writer.writerow([
            t.id, t.line_number, t.raw_content, t.lottery_type, t.multiplier,
            t.deadline_time, t.detail_period, t.ticket_amount, t.status,
            t.assigned_username, t.assigned_device_id, t.assigned_device_name,
            t.assigned_at, t.completed_at, f.original_filename if f else '',
        ])

    output.seek(0)
    from flask import Response
    filename = f"tickets_{get_business_date()}.csv"
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
    from urllib.parse import quote

    date_str = request.args.get('date', '').strip()

    q = LotteryTicket.query
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'error': '日期格式无效，请使用 YYYY-MM-DD'}), 400
        start_at, end_at = get_business_window(selected_date)
        file_ids = db.session.query(UploadedFile.id).filter(
            UploadedFile.uploaded_at >= start_at,
            UploadedFile.uploaded_at < end_at,
        ).all()
        file_ids = [r[0] for r in file_ids]
        if not file_ids:
            wb = Workbook()
            ws = wb.active
            ws.append(['行号', '原始内容', '彩种', '倍投', '截止时间', '期号', '金额', '状态', '用户名', '设备ID', '设备名', '分配时间', '完成时间', '来源文件名'])
            buf = _io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            from flask import Response
            empty_filename = f"{date_str}_无数据投注内容详情.xlsx"
            empty_filename_encoded = quote(empty_filename, encoding='utf-8')
            return Response(buf.read(),
                            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            headers={'Content-Disposition': f"attachment; filename*=UTF-8''{empty_filename_encoded}"})
        q = q.filter(LotteryTicket.source_file_id.in_(file_ids))

    tickets = q.order_by(LotteryTicket.source_file_id, LotteryTicket.line_number).all()

    file_map = {f.id: f.original_filename for f in UploadedFile.query.all()}

    wb = Workbook()
    ws = wb.active
    ws.append(['行号', '原始内容', '彩种', '倍投', '截止时间', '期号', '金额', '状态', '用户名', '设备ID', '设备名', '分配时间', '完成时间', '来源文件名'])
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
            t.assigned_device_id or '',
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


@admin_bp.route('/api/lottery-types')
@login_required
@admin_required
def api_lottery_types():
    """返回固定的彩种列表"""
    return jsonify({'lottery_types': ['胜平负', '胜负', '比分', '上下盘', '总进球', '半全场']})


@admin_bp.route('/api/users', methods=['POST'])
@login_required
@admin_required
def api_create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    client_mode = _parse_client_mode(data.get('client_mode', 'mode_a'))
    if client_mode is None:
        return jsonify({'success': False, 'error': '客户端模式必须是 mode_a 或 mode_b'}), 400
    max_devices = _parse_int_arg(data.get('max_devices', 1), minimum=1)
    if max_devices is None:
        return jsonify({'success': False, 'error': '最大设备数必须是大于 0 的整数'}), 400

    # 验证 max_processing_b_mode
    max_processing_b_mode = data.get('max_processing_b_mode')
    if max_processing_b_mode is not None:
        try:
            max_processing_b_mode = int(max_processing_b_mode) if max_processing_b_mode else None
            if max_processing_b_mode is not None and (max_processing_b_mode < 1 or max_processing_b_mode > 10000):
                return jsonify({'success': False, 'error': 'B模式上限必须在1-10000之间'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'B模式上限必须是整数'}), 400

    # 验证 daily_ticket_limit
    daily_ticket_limit = data.get('daily_ticket_limit')
    if daily_ticket_limit is not None:
        try:
            daily_ticket_limit = int(daily_ticket_limit) if daily_ticket_limit else None
            if daily_ticket_limit is not None and (daily_ticket_limit < 1 or daily_ticket_limit > 100000):
                return jsonify({'success': False, 'error': '每日上限必须在1-100000之间'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': '每日上限必须是整数'}), 400

    # 验证 blocked_lottery_types
    blocked_lottery_types = data.get('blocked_lottery_types')
    if blocked_lottery_types is not None:
        if not isinstance(blocked_lottery_types, list):
            return jsonify({'success': False, 'error': '禁止彩种必须是数组'}), 400
        if not all(isinstance(t, str) for t in blocked_lottery_types):
            return jsonify({'success': False, 'error': '禁止彩种列表中的每项必须是字符串'}), 400

    if not username or not password:
        return jsonify({'success': False, 'error': '用户名和密码不能为空'}), 400
    if len(password) < 6:
        return jsonify({'success': False, 'error': '密码至少需要 6 位'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': '用户名已存在'}), 409

    user = User(username=username, client_mode=client_mode, max_devices=max_devices,
                max_processing_b_mode=max_processing_b_mode, daily_ticket_limit=daily_ticket_limit)
    user.set_password(password)
    if blocked_lottery_types is not None:
        user.set_blocked_lottery_types(blocked_lottery_types)
    db.session.add(user)
    db.session.commit()
    return jsonify({'success': True, 'user': user.to_dict()})


@admin_bp.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
def api_update_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        return jsonify({'success': False, 'error': '不允许在此接口修改管理员账号'}), 403
    data = request.get_json(silent=True) or {}
    was_active = user.is_active

    if 'client_mode' in data:
        parsed_client_mode = _parse_client_mode(data['client_mode'])
        if parsed_client_mode is None:
            return jsonify({'success': False, 'error': '客户端模式必须是 mode_a 或 mode_b'}), 400
        user.client_mode = parsed_client_mode
    if 'max_devices' in data:
        parsed_max_devices = _parse_int_arg(data['max_devices'], minimum=1)
        if parsed_max_devices is None:
            return jsonify({'success': False, 'error': '最大设备数必须是大于 0 的整数'}), 400
        user.max_devices = parsed_max_devices
    if 'max_processing_b_mode' in data:
        val = data['max_processing_b_mode']
        try:
            user.max_processing_b_mode = int(val) if val else None
            if user.max_processing_b_mode is not None and (user.max_processing_b_mode < 1 or user.max_processing_b_mode > 10000):
                return jsonify({'success': False, 'error': 'B模式上限必须在1-10000之间'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'B模式上限必须是整数'}), 400
    if 'daily_ticket_limit' in data:
        val = data['daily_ticket_limit']
        try:
            user.daily_ticket_limit = int(val) if val else None
            if user.daily_ticket_limit is not None and (user.daily_ticket_limit < 1 or user.daily_ticket_limit > 100000):
                return jsonify({'success': False, 'error': '每日上限必须在1-100000之间'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': '每日上限必须是整数'}), 400
    if 'is_active' in data:
        parsed_is_active = _parse_bool_flag(data['is_active'])
        if parsed_is_active is None:
            return jsonify({'success': False, 'error': 'is_active 必须是布尔值'}), 400
        user.is_active = parsed_is_active
    if 'can_receive' in data:
        parsed_can_receive = _parse_bool_flag(data['can_receive'])
        if parsed_can_receive is None:
            return jsonify({'success': False, 'error': 'can_receive 必须是布尔值'}), 400
        user.can_receive = parsed_can_receive
    if 'password' in data and data['password']:
        if len(data['password']) < 6:
            return jsonify({'success': False, 'error': '密码至少需要 6 位'}), 400
        user.set_password(data['password'])
    if 'blocked_lottery_types' in data:
        blocked_types = data['blocked_lottery_types']
        if blocked_types is not None and not isinstance(blocked_types, list):
            return jsonify({'success': False, 'error': '禁止彩种必须是数组'}), 400
        if isinstance(blocked_types, list) and not all(isinstance(t, str) for t in blocked_types):
            return jsonify({'success': False, 'error': '禁止彩种列表中的每项必须是字符串'}), 400
        user.set_blocked_lottery_types(blocked_types)

    db.session.commit()

    if was_active and not user.is_active:
        force_logout_user(user.id, '账号已被管理员禁用')
        AuditLog.log('force_logout', user_id=current_user.id,
                     resource_type='user', resource_id=user_id,
                     details={'reason': '账号已被管理员禁用'})
        db.session.commit()

    return jsonify({'success': True, 'user': user.to_dict()})


@admin_bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        return jsonify({'success': False, 'error': '不允许在此接口删除管理员账号'}), 403

    has_ticket_refs = LotteryTicket.query.filter(LotteryTicket.assigned_user_id == user_id).first() is not None
    has_uploaded_file_refs = UploadedFile.query.filter(UploadedFile.uploaded_by == user_id).first() is not None
    has_winning_refs = WinningRecord.query.filter(
        (WinningRecord.uploaded_by == user_id) |
        (WinningRecord.verified_by == user_id) |
        (WinningRecord.checked_by == user_id)
    ).first() is not None
    has_result_refs = ResultFile.query.filter(ResultFile.uploaded_by == user_id).first() is not None or MatchResult.query.filter(
        MatchResult.uploaded_by == user_id
    ).first() is not None
    has_audit_refs = AuditLog.query.filter(AuditLog.user_id == user_id).first() is not None

    if has_ticket_refs or has_uploaded_file_refs or has_winning_refs or has_result_refs or has_audit_refs:
        return jsonify({
            'success': False,
            'error': '该用户已有历史业务数据，不能直接删除，请改为禁用账号',
        }), 409

    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/api/users/<int:user_id>/force-logout', methods=['POST'])
@login_required
@admin_required
def api_force_logout(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        return jsonify({'success': False, 'error': '不允许在此接口强制下线管理员账号'}), 403
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
    data = request.get_json(silent=True) or {}
    parsed_can_receive = _parse_bool_flag(data.get('can_receive', True))
    if parsed_can_receive is None:
        return jsonify({'success': False, 'error': 'can_receive 必须是布尔值'}), 400
    user.can_receive = parsed_can_receive
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
    winning_tickets = LotteryTicket.query.filter(
        LotteryTicket.is_winning == True,
        LotteryTicket.status.in_(['completed', 'expired']),
    ).all()
    dates = sorted(
        {str(get_business_date(_winning_terminal_at(ticket))) for ticket in winning_tickets if _winning_terminal_at(ticket)},
        reverse=True,
    )
    return jsonify({
        'usernames': sorted({ticket.assigned_username for ticket in winning_tickets if ticket.assigned_username}),
        'dates': dates,
        'lottery_types': sorted({ticket.lottery_type for ticket in winning_tickets if ticket.lottery_type}),
        'current_business_date': str(get_business_date()),
    })


@admin_bp.route('/api/winning')
@login_required
@admin_required
def api_winning_list():
    """查询中奖票列表（从 LotteryTicket 查 is_winning=True）"""
    page = _parse_int_arg(request.args.get('page', 1), minimum=1)
    per_page = _parse_int_arg(request.args.get('per_page', 50), minimum=1)
    if page is None or per_page is None:
        return jsonify({'success': False, 'error': '分页参数必须是大于 0 的整数'}), 400
    username = request.args.get('username', '').strip()
    date_str = request.args.get('date', '').strip()
    lottery_type = request.args.get('lottery_type', '').strip()
    image_filter = request.args.get('image_filter', '').strip()  # 'uploaded' | 'missing'
    checked_status = request.args.get('checked_status', '').strip()  # 'all' | 'checked' | 'unchecked'

    from sqlalchemy import func

    terminal_expr = func.coalesce(
        LotteryTicket.completed_at,
        LotteryTicket.deadline_time,
        LotteryTicket.assigned_at,
        LotteryTicket.admin_upload_time,
    )
    q = LotteryTicket.query.filter(
        LotteryTicket.is_winning == True,
        LotteryTicket.status.in_(['completed', 'expired']),
    )
    if username:
        q = q.filter(LotteryTicket.assigned_username == username)
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'error': '日期格式无效，请使用 YYYY-MM-DD'}), 400
        start_at, end_at = get_business_window(selected_date)
        q = q.filter(
            terminal_expr >= start_at,
            terminal_expr < end_at,
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

    # 审核状态筛选（使用 EXISTS 子查询，避免丢失数据）
    if checked_status == 'checked':
        q = q.filter(
            db.exists().where(
                db.and_(
                    WinningRecord.ticket_id == LotteryTicket.id,
                    WinningRecord.is_checked == True
                )
            )
        )
    elif checked_status == 'unchecked':
        q = q.filter(
            ~db.exists().where(
                db.and_(
                    WinningRecord.ticket_id == LotteryTicket.id,
                    WinningRecord.is_checked == True
                )
            )
        )

    q = q.order_by(terminal_expr.desc(), LotteryTicket.id.desc())

    # 汇总（全量，不分页）
    all_items = q.all()
    summary_amount = sum(float(t.winning_amount or 0) for t in all_items)
    summary_gross  = sum(float(t.winning_gross  or 0) for t in all_items)
    summary_tax    = sum(float(t.winning_tax    or 0) for t in all_items)
    summary_missing = sum(1 for t in all_items if not t.winning_image_url)
    total = len(all_items)

    # 分页切片
    start = (page - 1) * per_page
    page_items = all_items[start:start + per_page]
    import math
    pages = math.ceil(total / per_page) if total else 1

    # 批量查询 WinningRecord，避免 N+1 查询问题
    ticket_ids = [t.id for t in page_items]
    winning_records_map = {
        wr.ticket_id: wr
        for wr in WinningRecord.query.filter(WinningRecord.ticket_id.in_(ticket_ids)).all()
    }

    records = []
    for t in page_items:
        winning_record = winning_records_map.get(t.id)
        terminal_at = _winning_terminal_at(t)
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
            'status': t.status,
            'status_label': _winning_status_label(t.status),
            'completed_at': (t.completed_at.isoformat() if t.completed_at else None),
            'terminal_at': (terminal_at.isoformat() if terminal_at else None),
            'terminal_label': '过期时间' if t.status == 'expired' else '完成时间',
            'is_checked': winning_record.is_checked if winning_record else False,
            'checked_at': winning_record.checked_at.isoformat() if (winning_record and winning_record.checked_at) else None,
            'checked_by_username': winning_record.checker.username if (winning_record and winning_record.checker) else None,
            'winning_record_id': winning_record.id if winning_record else None,
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
            'missing': summary_missing,
        },
    })


@admin_bp.route('/api/winning/export')
@login_required
@admin_required
def api_winning_export():
    """导出当前筛选条件下的所有中奖条目为 XLSX"""
    import io as _io
    from openpyxl import Workbook

    username     = request.args.get('username', '').strip()
    date_str     = request.args.get('date', '').strip()
    lottery_type = request.args.get('lottery_type', '').strip()
    image_filter = request.args.get('image_filter', '').strip()
    checked_status = request.args.get('checked_status', '').strip()

    from sqlalchemy import func

    terminal_expr = func.coalesce(
        LotteryTicket.completed_at,
        LotteryTicket.deadline_time,
        LotteryTicket.assigned_at,
        LotteryTicket.admin_upload_time,
    )
    q = LotteryTicket.query.filter(
        LotteryTicket.is_winning == True,
        LotteryTicket.status.in_(['completed', 'expired']),
    )
    if username:
        q = q.filter(LotteryTicket.assigned_username == username)
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'error': '日期格式无效，请使用 YYYY-MM-DD'}), 400
        start_at, end_at = get_business_window(selected_date)
        q = q.filter(
            terminal_expr >= start_at,
            terminal_expr < end_at,
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
    if checked_status == 'checked':
        q = q.filter(
            db.exists().where(
                db.and_(
                    WinningRecord.ticket_id == LotteryTicket.id,
                    WinningRecord.is_checked == True
                )
            )
        )
    elif checked_status == 'unchecked':
        q = q.filter(
            ~db.exists().where(
                db.and_(
                    WinningRecord.ticket_id == LotteryTicket.id,
                    WinningRecord.is_checked == True
                )
            )
        )
    items = q.order_by(terminal_expr.desc(), LotteryTicket.id.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.append(['票ID', '投注内容', '票面金额', '用户名', '设备名', '彩种', '期号',
               '状态', '税前金额', '税后金额', '税金', '图片状态', '终态时间'])
    for t in items:
        terminal_at = _winning_terminal_at(t)
        ws.append([
            t.id,
            t.raw_content or '',
            float(t.ticket_amount or 0),
            t.assigned_username or '',
            t.assigned_device_name or '',
            t.lottery_type or '',
            t.detail_period or '',
            _winning_status_label(t.status),
            float(t.winning_gross or 0),
            float(t.winning_amount or 0),
            float(t.winning_tax or 0),
            '已上传' if t.winning_image_url else '未上传',
            terminal_at.strftime('%Y-%m-%d %H:%M:%S') if terminal_at else '',
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
    ticket, error_response = _get_winning_ticket_or_error(ticket_id)
    if error_response:
        return error_response
    record = WinningRecord.query.filter_by(ticket_id=ticket.id).first()
    if record and record.is_checked:
        return jsonify({'success': False, 'error': '该中奖记录已被标记为已检查，无法更换图片'}), 403
    from services.oss_service import generate_presign_url, build_oss_key
    oss_key = build_oss_key(ticket.id)
    url, key = generate_presign_url(oss_key)
    if url.startswith('/api/winning/upload-local?'):
        url = f"{url}&ticket_id={ticket.id}"
    return jsonify({'success': True, 'url': url, 'oss_key': key})


@admin_bp.route('/api/winning/record', methods=['POST'])
@login_required
@admin_required
def admin_winning_record():
    """管理员更新中奖图片URL"""
    data = request.get_json(silent=True) or {}
    ticket_id = data.get('ticket_id')
    oss_key = data.get('oss_key', '')
    if not oss_key:
        return jsonify({'success': False, 'error': '缺少 oss_key'}), 400
    if not ticket_id:
        return jsonify({'success': False, 'error': '缺少ticket_id'}), 400
    ticket, error_response = _get_winning_ticket_or_error(ticket_id)
    if error_response:
        return error_response
    from services.oss_service import delete_stored_image, get_public_url
    image_url = get_public_url(oss_key) if oss_key else ''
    record = WinningRecord.query.filter_by(ticket_id=ticket.id).first()
    if record and record.is_checked:
        return jsonify({'success': False, 'error': '该中奖记录已被标记为已检查，无法更换图片'}), 403
    if record:
        if record.image_oss_key != (oss_key or None) or record.winning_image_url != image_url:
            delete_stored_image(record.image_oss_key, record.winning_image_url)
        record.winning_image_url = image_url
        record.image_oss_key = oss_key or None
        record.uploaded_by = current_user.id
        record.uploaded_at = beijing_now()
    else:
        record = WinningRecord(
            ticket_id=ticket.id,
            source_file_id=ticket.source_file_id,
            detail_period=ticket.detail_period,
            lottery_type=ticket.lottery_type,
            winning_image_url=image_url,
            image_oss_key=oss_key or None,
            uploaded_by=current_user.id,
        )
        db.session.add(record)
    ticket.winning_image_url = image_url
    ticket.is_winning = True
    db.session.commit()
    return jsonify({'success': True, 'image_url': image_url, 'record': record.to_dict()})


@admin_bp.route('/api/winning/<int:ticket_id>/upload-image', methods=['POST'])
@login_required
@admin_required
def admin_winning_upload_image(ticket_id):
    """直接上传中奖图片，自动压缩后存储（本地或OSS）"""
    ticket, error_response = _get_winning_ticket_or_error(ticket_id)
    if error_response:
        return error_response
    record = WinningRecord.query.filter_by(ticket_id=ticket_id).first()

    if record and record.is_checked:
        return jsonify({'success': False, 'error': '该中奖记录已被标记为已检查，无法更换图片'}), 403

    if 'image' not in request.files:
        return jsonify({'success': False, 'error': '请选择图片文件'}), 400

    file = request.files['image']
    if not file.filename:
        return jsonify({'success': False, 'error': '文件名为空'}), 400

    try:
        from utils.image_upload import prepare_uploaded_image

        compressed, save_ext = prepare_uploaded_image(file)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    from services.oss_service import _oss_configured, build_oss_key, delete_stored_image, get_public_url

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

    if record:
        if record.image_oss_key != (oss_key if _oss_configured() else None) or record.winning_image_url != image_url:
            delete_stored_image(record.image_oss_key, record.winning_image_url)
        record.winning_image_url = image_url
        record.image_oss_key = oss_key if _oss_configured() else None
        record.uploaded_by = current_user.id
        record.uploaded_at = beijing_now()
    else:
        record = WinningRecord(
            ticket_id=ticket.id,
            source_file_id=ticket.source_file_id,
            detail_period=ticket.detail_period,
            lottery_type=ticket.lottery_type,
            winning_image_url=image_url,
            image_oss_key=oss_key if _oss_configured() else None,
            uploaded_by=current_user.id,
        )
        db.session.add(record)
    ticket.winning_image_url = image_url
    ticket.is_winning = True
    db.session.commit()
    return jsonify({'success': True, 'image_url': image_url, 'record': record.to_dict()})


# ── Match results ─────────────────────────────────────────────────────

@admin_bp.route('/match-results/upload', methods=['POST'])
@login_required
@admin_required
def upload_match_result():
    """上传赛果文件，自动触发中奖计算"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '请选择文件'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'success': False, 'error': '文件名不能为空'}), 400
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
    else:
        from services.winning_calc_service import process_match_result
        process_match_result(match_result_id, app=current_app._get_current_object())

    return jsonify({'success': True, 'match_result_id': match_result_id, 'count': result['count']})


@admin_bp.route('/api/match-results')
@login_required
@admin_required
def api_match_results():
    date_str = request.args.get('date', '').strip()
    q = MatchResult.query.order_by(MatchResult.uploaded_at.desc())
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'error': '日期格式无效，请使用 YYYY-MM-DD'}), 400
        start_at, end_at = get_business_window(selected_date)
        q = q.filter(
            MatchResult.uploaded_at >= start_at,
            MatchResult.uploaded_at < end_at,
        )
    results = q.limit(100).all()
    # 附带日期列表供前端筛选
    uploaded_rows = db.session.query(MatchResult.uploaded_at).filter(
        MatchResult.uploaded_at.isnot(None)
    ).all()
    dates = sorted(
        {str(get_business_date(row[0])) for row in uploaded_rows if row[0]},
        reverse=True,
    )
    return jsonify({
        'results': [r.to_dict() for r in results],
        'dates': dates,
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
    match_result.calc_started_at = None
    match_result.calc_finished_at = None
    match_result.tickets_total = 0
    match_result.tickets_winning = 0
    match_result.total_winning_amount = 0
    db.session.commit()

    sched = get_scheduler()
    if sched:
        sched.add_job(
            func=process_match_result,
            args=[result_id],
            id=f'winning_recalc_{result_id}',
            replace_existing=True,
        )
    else:
        process_match_result(result_id, app=current_app._get_current_object())
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
    payload = settings.to_dict()
    payload['database_info'] = _database_display_info()
    return jsonify(payload)


@admin_bp.route('/api/settings', methods=['PUT'])
@login_required
@admin_required
def api_update_settings():
    data = request.get_json(silent=True) or {}
    settings = SystemSettings.get()

    for bool_field in ['registration_enabled', 'pool_enabled', 'mode_a_enabled', 'mode_b_enabled', 'announcement_enabled']:
        if bool_field in data:
            parsed_bool = _parse_bool_flag(data.get(bool_field))
            if parsed_bool is None:
                return jsonify({'success': False, 'error': f'{bool_field} 必须是布尔值'}), 400
            data[bool_field] = parsed_bool

    if 'session_lifetime_hours' in data:
        parsed_hours = _parse_int_arg(data.get('session_lifetime_hours'), minimum=1)
        if parsed_hours is None or parsed_hours > 24:
            return jsonify({'success': False, 'error': '无活动超时必须是 1 到 24 之间的整数'}), 400
        data['session_lifetime_hours'] = parsed_hours

    if 'daily_reset_hour' in data:
        parsed_reset_hour = _parse_int_arg(data.get('daily_reset_hour'), minimum=0)
        if parsed_reset_hour is None or parsed_reset_hour > 23:
            return jsonify({'success': False, 'error': '每日重置时间必须是 0 到 23 之间的整数'}), 400
        data['daily_reset_hour'] = parsed_reset_hour

    if 'mode_b_options' in data:
        mode_b_options = data.get('mode_b_options')
        if not isinstance(mode_b_options, list) or not mode_b_options:
            return jsonify({'success': False, 'error': 'B模式批量选项必须是非空整数数组'}), 400

        normalized_options = []
        seen = set()
        for value in mode_b_options:
            parsed_value = _parse_int_arg(value, minimum=1)
            if parsed_value is None:
                return jsonify({'success': False, 'error': 'B模式批量选项必须全部是大于 0 的整数'}), 400
            if parsed_value not in seen:
                seen.add(parsed_value)
                normalized_options.append(parsed_value)
        data['mode_b_options'] = normalized_options

    for field in ['registration_enabled', 'pool_enabled', 'mode_a_enabled', 'mode_b_enabled',
                  'mode_b_options', 'announcement', 'announcement_enabled',
                  'session_lifetime_hours', 'daily_reset_hour']:
        if field in data:
            setattr(settings, field, data[field])

    settings.updated_by = current_user.id
    db.session.commit()

    if 'daily_reset_hour' in data:
        try:
            from tasks.scheduler import reschedule_daily_reset

            reschedule_daily_reset(current_app._get_current_object(), settings.daily_reset_hour)
        except Exception:
            current_app.logger.warning('重排每日会话重置任务失败', exc_info=True)

    if data.get('announcement_enabled') and data.get('announcement'):
        notify_all('announcement', {'content': data['announcement']})

    if 'pool_enabled' in data:
        if data['pool_enabled']:
            notify_all('pool_enabled', {'message': '票池已开启'})
        else:
            notify_all('pool_disabled', {'message': '票池已关闭'})

    if 'mode_a_enabled' in data or 'mode_b_enabled' in data:
        try:
            from services.notify_service import notify_pool_update

            notify_pool_update(get_pool_status())
        except Exception:
            current_app.logger.warning('推送模式开关后的票池刷新事件失败', exc_info=True)

    return jsonify({'success': True, 'settings': settings.to_dict()})
