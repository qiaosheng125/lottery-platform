from datetime import timedelta
from urllib.parse import quote
import io as _io

from flask import Blueprint, Response, jsonify, request
from flask_login import current_user, login_required
from openpyxl import Workbook

from extensions import db
from models.settings import SystemSettings
from models.ticket import LotteryTicket
from services.ticket_pool import get_pool_status
from utils.decorators import login_required_json
from utils.time_utils import beijing_now, get_business_date, get_today_noon

user_bp = Blueprint('user', __name__)


@user_bp.route('/dashboard')
@login_required
def dashboard():
    from flask import render_template
    return render_template('client/dashboard.html')


@user_bp.route('/daily-stats')
@login_required
@login_required_json
def daily_stats():
    today = get_business_date()
    today_start = get_today_noon()
    today_end = today_start + timedelta(days=1)

    today_tickets = LotteryTicket.query.filter(
        LotteryTicket.assigned_user_id == current_user.id,
        LotteryTicket.status == 'completed',
        LotteryTicket.completed_at >= today_start,
        LotteryTicket.completed_at < today_end,
    ).all()

    ticket_count = len(today_tickets)
    total_amount = sum(float(t.ticket_amount or 0) for t in today_tickets)

    device_stats = {}
    for t in today_tickets:
        key = t.assigned_device_id or 'unknown'
        if key not in device_stats:
            device_stats[key] = {
                'device_id': t.assigned_device_id or '',
                'device_name': t.assigned_device_name or t.assigned_device_id or '未知设备',
                'count': 0,
                'amount': 0.0,
            }
        device_stats[key]['count'] += 1
        device_stats[key]['amount'] += float(t.ticket_amount or 0)
    device_stats_list = sorted(device_stats.values(), key=lambda x: x['count'], reverse=True)

    active = LotteryTicket.query.filter_by(
        assigned_user_id=current_user.id,
        status='assigned',
    ).count()

    pool = get_pool_status()
    settings = SystemSettings.get()
    pool_total_pending = pool['total_pending'] if current_user.can_receive else 0

    return jsonify({
        'success': True,
        'today': str(today),
        'ticket_count': ticket_count,
        'total_amount': total_amount,
        'active_count': active,
        'pool_total_pending': pool_total_pending,
        'mode_b_options': settings.mode_b_options or [50, 100, 200, 300, 400, 500],
        'device_stats': device_stats_list,
    })


@user_bp.route('/export-daily')
@login_required
def export_daily():
    """下载当日出票清单 XLSX（仅含已过截止时间的票）"""
    now = beijing_now()
    today_start = get_today_noon()
    today_end = today_start + timedelta(days=1)

    all_rows = LotteryTicket.query.filter(
        LotteryTicket.assigned_user_id == current_user.id,
        LotteryTicket.status == 'completed',
        LotteryTicket.completed_at >= today_start,
        LotteryTicket.completed_at < today_end,
    ).order_by(LotteryTicket.completed_at).all()

    rows = [r for r in all_rows if r.deadline_time and r.deadline_time <= now]
    pending_count = len(all_rows) - len(rows)

    if not rows:
        msg = '今日暂无可下载记录'
        if pending_count:
            msg += f'，有 {pending_count} 张票尚未到截止时间，截止后即可下载'
        return jsonify({'success': False, 'message': msg})

    ticket_count = len(rows)
    total_amount = sum(float(r.ticket_amount or 0) for r in rows)
    period_str = next((r.detail_period for r in rows if r.detail_period), '')

    wb = Workbook()
    ws = wb.active
    ws.append(['票ID', '原始内容', '彩种', '倍投', '截止时间', '期号', '金额', '状态', '用户名', '设备名', '分配时间', '完成时间'])
    status_map = {
        'pending': '待出票',
        'assigned': '出票中',
        'completed': '已完成',
        'revoked': '已撤回',
        'expired': '已过期',
    }
    for t in rows:
        ws.append([
            t.id,
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
        ])

    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"{today}_{period_str}_{ticket_count}张_{int(total_amount)}元.xlsx"
    filename_encoded = quote(filename, encoding='utf-8')
    resp_headers = {
        'Content-Disposition': f"attachment; filename*=UTF-8''{filename_encoded}",
        'Access-Control-Expose-Headers': 'X-Pending-Count',
        'X-Pending-Count': str(pending_count),
    }
    return Response(
        buf.read(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers=resp_headers,
    )


@user_bp.route('/change-password', methods=['POST'])
@login_required
@login_required_json
def change_password():
    data = request.get_json()
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')

    if not old_password or not new_password:
        return jsonify({'success': False, 'error': '请填写完整'}), 400

    if not current_user.check_password(old_password):
        return jsonify({'success': False, 'error': '旧密码错误'}), 400

    if len(new_password) < 6:
        return jsonify({'success': False, 'error': '新密码至少6位'}), 400

    current_user.set_password(new_password)
    db.session.commit()
    return jsonify({'success': True, 'message': '密码修改成功'})
