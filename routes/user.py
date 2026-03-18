from flask import Blueprint, jsonify, request, Response
from flask_login import login_required, current_user

from extensions import db
from models.ticket import LotteryTicket
from utils.decorators import login_required_json
from utils.time_utils import beijing_now, get_business_date

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
    from datetime import datetime, timedelta
    today = get_business_date()
    now = beijing_now()

    # 计算今日业务时间范围（12点分割线）
    today_start = datetime.combine(today, datetime.min.time())
    if now.hour < 12:
        today_start = today_start - timedelta(days=1) + timedelta(hours=12)
        today_end = today_start + timedelta(days=1)
    else:
        today_start = today_start + timedelta(hours=12)
        today_end = today_start + timedelta(days=1)

    # 用数据库过滤，不要 .all()
    today_tickets = LotteryTicket.query.filter(
        LotteryTicket.assigned_user_id == current_user.id,
        LotteryTicket.status == 'completed',
        LotteryTicket.completed_at >= today_start,
        LotteryTicket.completed_at < today_end
    ).all()

    ticket_count = len(today_tickets)
    total_amount = sum(float(t.ticket_amount or 0) for t in today_tickets)

    # Active count
    active = LotteryTicket.query.filter_by(
        assigned_user_id=current_user.id, status='assigned'
    ).count()

    # Pool status
    from services.ticket_pool import get_pool_status
    from models.settings import SystemSettings
    pool = get_pool_status()
    settings = SystemSettings.get()

    return jsonify({
        'success': True,
        'today': str(today),
        'ticket_count': ticket_count,
        'total_amount': total_amount,
        'active_count': active,
        'pool_total_pending': pool['total_pending'],
        'mode_b_options': settings.mode_b_options or [50, 100, 200, 300, 400, 500],
    })


@user_bp.route('/export-daily')
@login_required
@login_required_json
def export_daily():
    """下载当日出票清单（需截止时间已过）"""
    today = get_business_date()
    now = beijing_now()

    completed = LotteryTicket.query.filter_by(
        assigned_user_id=current_user.id, status='completed'
    ).all()

    # Filter: business date matches AND deadline has passed
    rows = [
        t for t in completed
        if t.completed_at and get_business_date(t.completed_at) == today
        and t.deadline_time and t.deadline_time < now
    ]

    if not rows:
        return jsonify({'success': False, 'error': '暂无可下载的数据'}), 404

    lines = [r.raw_content for r in rows]
    content = '\n'.join(lines)

    filename = f"出票清单_{current_user.username}_{today}.txt"
    return Response(
        content.encode('utf-8'),
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
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
