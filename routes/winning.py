from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from extensions import db
from models.ticket import LotteryTicket
from models.winning import WinningRecord
from utils.decorators import login_required_json
from utils.time_utils import beijing_now, get_business_date, get_business_window

winning_bp = Blueprint('winning', __name__)


def _get_winning_ticket_or_error(ticket_id_value):
    try:
        ticket_id = int(ticket_id_value)
    except (TypeError, ValueError):
        return None, (jsonify({'success': False, 'error': '票ID必须是整数'}), 400)

    ticket = db.session.get(LotteryTicket, ticket_id)
    if not ticket:
        return None, (jsonify({'success': False, 'error': '票据不存在'}), 404)
    if not ticket.is_winning:
        return None, (jsonify({'success': False, 'error': '该票未被系统判定为中奖，不能上传中奖图片'}), 400)
    return ticket, None


@winning_bp.route('/presign')
@login_required_json
@login_required
def presign():
    ticket_id = request.args.get('ticket_id')
    if not ticket_id:
        return jsonify({'success': False, 'error': '缺少票ID'}), 400

    ticket, error_response = _get_winning_ticket_or_error(ticket_id)
    if error_response:
        return error_response
    if ticket.assigned_user_id != current_user.id and not current_user.is_admin:
        return jsonify({'success': False, 'error': '权限不足'}), 403

    record = WinningRecord.query.filter_by(ticket_id=ticket.id).first()
    if record and record.is_checked:
        return jsonify({'success': False, 'error': '该中奖记录已被管理员标记为已检查，无法更换图片'}), 403

    try:
        from services.oss_service import build_oss_key, generate_presign_url

        oss_key = build_oss_key(ticket.id)
        url, key = generate_presign_url(oss_key)
        if url.startswith('/api/winning/upload-local?'):
            url = f"{url}&ticket_id={ticket.id}"
        return jsonify({'success': True, 'url': url, 'oss_key': key})
    except Exception as e:
        return jsonify({'success': False, 'error': f'OSS错误: {e}'}), 500


@winning_bp.route('/upload-local', methods=['POST'])
@login_required_json
@login_required
def upload_local():
    import os

    from flask import current_app

    key = (request.args.get('key') or '').strip()
    ticket_id = (request.args.get('ticket_id') or '').strip()
    if not key:
        return jsonify({'success': False, 'error': '缺少 key'}), 400
    if not ticket_id:
        return jsonify({'success': False, 'error': '缺少票ID'}), 400
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '请选择图片'}), 400

    ticket, error_response = _get_winning_ticket_or_error(ticket_id)
    if error_response:
        return error_response
    if ticket.assigned_user_id != current_user.id and not current_user.is_admin:
        return jsonify({'success': False, 'error': '权限不足'}), 403

    record = WinningRecord.query.filter_by(ticket_id=ticket.id).first()
    if record and record.is_checked:
        return jsonify({'success': False, 'error': '该中奖记录已被管理员标记为已检查，无法更换图片'}), 403

    from services.oss_service import build_oss_key

    expected_key = build_oss_key(ticket.id).replace('/', '_')
    if key != expected_key:
        return jsonify({'success': False, 'error': '上传 key 与票据不匹配'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'success': False, 'error': '文件名不能为空'}), 400

    try:
        from utils.image_upload import prepare_uploaded_image

        image_stream, save_ext = prepare_uploaded_image(file)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    images_dir = os.path.join(upload_folder, 'images')
    os.makedirs(images_dir, exist_ok=True)

    normalized_key = key.replace('/', '_')
    root, _ = os.path.splitext(normalized_key)
    filename = f"{root}.{save_ext}"
    path = os.path.join(images_dir, filename)
    with open(path, 'wb') as f:
        f.write(image_stream.read())

    return jsonify({'success': True, 'oss_key': filename, 'image_url': f"/uploads/images/{filename}"})


@winning_bp.route('/record', methods=['POST'])
@login_required_json
@login_required
def record_winning():
    data = request.get_json(silent=True) or {}
    ticket_id = data.get('ticket_id')
    oss_key = data.get('oss_key')
    winning_amount = data.get('winning_amount')

    if not ticket_id or not oss_key:
        return jsonify({'success': False, 'error': '参数不完整'}), 400

    ticket, error_response = _get_winning_ticket_or_error(ticket_id)
    if error_response:
        return error_response
    if ticket.assigned_user_id != current_user.id and not current_user.is_admin:
        return jsonify({'success': False, 'error': '权限不足'}), 403

    from services.oss_service import delete_stored_image, get_public_url

    image_url = get_public_url(oss_key)

    record = WinningRecord.query.filter_by(ticket_id=ticket.id).first()
    if record:
        if record.is_checked:
            return jsonify({'success': False, 'error': '该中奖记录已被管理员标记为已检查，无法更换图片'}), 403
        old_key = record.image_oss_key
        old_url = record.winning_image_url
        if old_key != oss_key or old_url != image_url:
            delete_stored_image(old_key, old_url)
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

    ticket.winning_image_url = image_url
    ticket.is_winning = True

    db.session.commit()
    return jsonify({'success': True, 'record': record.to_dict()})


@winning_bp.route('/my')
@login_required_json
@login_required
def my_winning():
    """Return the current user's winning tickets from the last 4 business days."""
    from datetime import datetime, timedelta

    date_str = request.args.get('date', '').strip()
    lottery_type = request.args.get('lottery_type', '').strip()

    today = get_business_date()
    four_days_ago = today - timedelta(days=3)
    start_time, _ = get_business_window(four_days_ago)
    _, end_time = get_business_window(today)

    q = LotteryTicket.query.filter(
        LotteryTicket.assigned_user_id == current_user.id,
        LotteryTicket.is_winning == True,
        LotteryTicket.completed_at >= start_time,
        LotteryTicket.completed_at < end_time,
    )

    if date_str:
        try:
            filter_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'error': '日期格式无效，请使用 YYYY-MM-DD'}), 400
        filter_start, filter_end = get_business_window(filter_date)
        q = q.filter(
            LotteryTicket.completed_at >= filter_start,
            LotteryTicket.completed_at < filter_end,
        )

    if lottery_type:
        q = q.filter(LotteryTicket.lottery_type == lottery_type)

    tickets = q.order_by(LotteryTicket.completed_at.desc()).all()

    grouped = {}
    for t in tickets:
        business_date = str(get_business_date(t.completed_at)) if t.completed_at else 'unknown'
        grouped.setdefault(business_date, []).append({
            'ticket_id': t.id,
            'business_date': business_date,
            'detail_period': t.detail_period,
            'lottery_type': t.lottery_type,
            'raw_content': t.raw_content or '',
            'ticket_amount': float(t.ticket_amount) if t.ticket_amount else None,
            'winning_gross': float(t.winning_gross) if t.winning_gross else 0,
            'winning_amount': float(t.winning_amount) if t.winning_amount else 0,
            'winning_tax': float(t.winning_tax) if t.winning_tax else 0,
            'winning_image_url': t.winning_image_url,
            'completed_at': t.completed_at.isoformat() if t.completed_at else None,
            'assigned_device_id': t.assigned_device_id or '',
            'assigned_device_name': t.assigned_device_name or '',
        })

    date_options = sorted(
        {str(get_business_date(t.completed_at)) for t in tickets if t.completed_at},
        reverse=True,
    )
    type_options = sorted({t.lottery_type for t in tickets if t.lottery_type})

    return jsonify({
        'success': True,
        'grouped': grouped,
        'filter_options': {
            'dates': date_options,
            'lottery_types': type_options,
        },
    })


@winning_bp.route('/admin/mark-checked/<int:record_id>', methods=['POST'])
@login_required_json
@login_required
def mark_checked(record_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': '权限不足'}), 403

    rows_updated = db.session.query(WinningRecord).filter(
        WinningRecord.id == record_id,
        WinningRecord.is_checked == False,
    ).update({
        'is_checked': True,
        'checked_at': beijing_now(),
        'checked_by': current_user.id,
    }, synchronize_session=False)

    db.session.commit()

    if rows_updated == 0:
        record = WinningRecord.query.get(record_id)
        if not record:
            return jsonify({'success': False, 'error': '记录不存在'}), 404
        return jsonify({'success': False, 'error': '该记录已经标记为已检查'}), 400

    record = WinningRecord.query.get(record_id)
    return jsonify({'success': True, 'record': record.to_dict()})


@winning_bp.route('/upload-image/<int:ticket_id>', methods=['POST'])
@login_required_json
@login_required
def upload_winning_image(ticket_id):
    """Upload a winning image and keep LotteryTicket / WinningRecord in sync."""
    import os
    import uuid

    from flask import current_app

    ticket, error_response = _get_winning_ticket_or_error(ticket_id)
    if error_response:
        return error_response
    if ticket.assigned_user_id != current_user.id:
        return jsonify({'success': False, 'error': '权限不足'}), 403

    record = WinningRecord.query.filter_by(ticket_id=ticket_id).first()
    if record and record.is_checked:
        return jsonify({'success': False, 'error': '该中奖记录已被管理员标记为已检查，无法更换图片'}), 403

    if 'image' not in request.files:
        return jsonify({'success': False, 'error': '请选择图片'}), 400

    file = request.files['image']
    if not file.filename:
        return jsonify({'success': False, 'error': '文件名不能为空'}), 400

    try:
        from utils.image_upload import prepare_uploaded_image

        image_stream, save_ext = prepare_uploaded_image(file)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    from services.oss_service import _oss_configured, build_oss_key, delete_stored_image, get_public_url

    image_oss_key = None
    if _oss_configured():
        from services.oss_service import _get_bucket

        image_oss_key = build_oss_key(ticket_id, save_ext)
        try:
            _get_bucket().put_object(image_oss_key, image_stream.read())
            image_url = get_public_url(image_oss_key)
        except Exception as e:
            return jsonify({'success': False, 'error': f'OSS上传失败: {e}'}), 500
    else:
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        images_dir = os.path.join(upload_folder, 'images')
        os.makedirs(images_dir, exist_ok=True)
        filename = f"winning_{ticket_id}_{uuid.uuid4().hex[:8]}.{save_ext}"
        with open(os.path.join(images_dir, filename), 'wb') as f:
            f.write(image_stream.read())
        image_url = f"/uploads/images/{filename}"

    if record:
        if record.image_oss_key != image_oss_key or record.winning_image_url != image_url:
            delete_stored_image(record.image_oss_key, record.winning_image_url)
        record.winning_image_url = image_url
        record.image_oss_key = image_oss_key
        record.uploaded_by = current_user.id
        record.uploaded_at = beijing_now()
    else:
        record = WinningRecord(
            ticket_id=ticket_id,
            source_file_id=ticket.source_file_id,
            detail_period=ticket.detail_period,
            lottery_type=ticket.lottery_type,
            winning_image_url=image_url,
            image_oss_key=image_oss_key,
            uploaded_by=current_user.id,
        )
        db.session.add(record)

    ticket.winning_image_url = image_url
    ticket.is_winning = True
    db.session.commit()
    return jsonify({'success': True, 'image_url': image_url, 'record': record.to_dict()})
