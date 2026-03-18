from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from extensions import db
from models.ticket import LotteryTicket
from models.winning import WinningRecord
from utils.decorators import login_required_json
from utils.time_utils import beijing_now, get_business_date
from sqlalchemy import text

winning_bp = Blueprint('winning', __name__)


@winning_bp.route('/presign')
@login_required
@login_required_json
def presign():
    ticket_id = request.args.get('ticket_id')
    if not ticket_id:
        return jsonify({'success': False, 'error': '缺少票ID'}), 400

    ticket = LotteryTicket.query.get_or_404(int(ticket_id))

    # Only the assigned user can upload
    if ticket.assigned_user_id != current_user.id and not current_user.is_admin:
        return jsonify({'success': False, 'error': '权限不足'}), 403

    try:
        from services.oss_service import generate_presign_url, build_oss_key
        oss_key = build_oss_key(ticket.id)
        url, key = generate_presign_url(oss_key)
        return jsonify({'success': True, 'url': url, 'oss_key': key})
    except Exception as e:
        return jsonify({'success': False, 'error': f'OSS错误: {str(e)}'}), 500


@winning_bp.route('/record', methods=['POST'])
@login_required
@login_required_json
def record_winning():
    data = request.get_json()
    ticket_id = data.get('ticket_id')
    oss_key = data.get('oss_key')
    winning_amount = data.get('winning_amount')

    if not ticket_id or not oss_key:
        return jsonify({'success': False, 'error': '参数不完整'}), 400

    ticket = LotteryTicket.query.get_or_404(int(ticket_id))

    if ticket.assigned_user_id != current_user.id and not current_user.is_admin:
        return jsonify({'success': False, 'error': '权限不足'}), 403

    from services.oss_service import get_public_url, delete_object

    # Delete old image if exists
    if ticket.winning_image_url and hasattr(ticket, '_oss_key'):
        existing = WinningRecord.query.filter_by(ticket_id=ticket_id).first()
        if existing and existing.image_oss_key:
            delete_object(existing.image_oss_key)

    image_url = get_public_url(oss_key)

    # Update or create winning record
    record = WinningRecord.query.filter_by(ticket_id=ticket_id).first()
    if record:
        old_key = record.image_oss_key
        if old_key and old_key != oss_key:
            delete_object(old_key)
        record.winning_image_url = image_url
        record.image_oss_key = oss_key
        record.winning_amount = winning_amount
        record.uploaded_by = current_user.id
        record.uploaded_at = beijing_now()
    else:
        record = WinningRecord(
            ticket_id=ticket_id,
            source_file_id=ticket.source_file_id,
            detail_period=ticket.detail_period,
            lottery_type=ticket.lottery_type,
            winning_amount=winning_amount,
            winning_image_url=image_url,
            image_oss_key=oss_key,
            uploaded_by=current_user.id,
        )
        db.session.add(record)

    # Update ticket
    ticket.winning_image_url = image_url
    ticket.is_winning = True

    db.session.commit()
    return jsonify({'success': True, 'record': record.to_dict()})


@winning_bp.route('/my')
@login_required
@login_required_json
def my_winning():
    """用户中奖记录（按业务日期分类）"""
    from models.winning import WinningRecord

    records = WinningRecord.query.join(
        LotteryTicket, WinningRecord.ticket_id == LotteryTicket.id
    ).filter(
        LotteryTicket.assigned_user_id == current_user.id
    ).order_by(LotteryTicket.completed_at.desc()).limit(200).all()

    grouped = {}
    for rec in records:
        ticket = rec.ticket
        bdate = str(get_business_date(ticket.completed_at)) if ticket and ticket.completed_at else 'unknown'
        if bdate not in grouped:
            grouped[bdate] = []
        grouped[bdate].append({
            'id': rec.id,
            'ticket_id': rec.ticket_id,
            'detail_period': rec.detail_period,
            'lottery_type': rec.lottery_type,
            'winning_amount': float(rec.winning_amount) if rec.winning_amount else None,
            'winning_image_url': rec.winning_image_url,
            'raw_content': ticket.raw_content if ticket else '',
            'ticket_amount': float(ticket.ticket_amount) if ticket and ticket.ticket_amount else None,
            'completed_at': ticket.completed_at.isoformat() if ticket and ticket.completed_at else None,
        })

    return jsonify({'success': True, 'grouped': grouped})
