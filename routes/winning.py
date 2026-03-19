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
    """用户中奖记录（从 LotteryTicket.is_winning=True 查询，按业务日期分类）"""
    tickets = LotteryTicket.query.filter(
        LotteryTicket.assigned_user_id == current_user.id,
        LotteryTicket.is_winning == True,
    ).order_by(LotteryTicket.completed_at.desc()).limit(200).all()

    grouped = {}
    for t in tickets:
        bdate = str(get_business_date(t.completed_at)) if t.completed_at else 'unknown'
        if bdate not in grouped:
            grouped[bdate] = []
        grouped[bdate].append({
            'ticket_id': t.id,
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

    return jsonify({'success': True, 'grouped': grouped})


@winning_bp.route('/upload-image/<int:ticket_id>', methods=['POST'])
@login_required
@login_required_json
def upload_winning_image(ticket_id):
    """用户上传自己中奖票的图片"""
    import os, uuid, io as _io
    from flask import current_app
    from PIL import Image as _Image

    ticket = LotteryTicket.query.get_or_404(ticket_id)
    if ticket.assigned_user_id != current_user.id:
        return jsonify({'success': False, 'error': '权限不足'}), 403

    if 'image' not in request.files:
        return jsonify({'success': False, 'error': '请选择图片'}), 400

    file = request.files['image']
    ext = (file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg')
    if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
        return jsonify({'success': False, 'error': '不支持的图片格式'}), 400

    # 压缩：最长边 1200px，JPEG 质量 80
    try:
        img = _Image.open(file.stream).convert('RGB')
        if max(img.width, img.height) > 1200:
            img.thumbnail((1200, 1200), _Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format='JPEG', quality=80, optimize=True)
        buf.seek(0)
    except Exception as e:
        return jsonify({'success': False, 'error': f'图片处理失败: {e}'}), 400

    from services.oss_service import _oss_configured, build_oss_key, get_public_url
    if _oss_configured():
        from services.oss_service import _get_bucket
        oss_key = build_oss_key(ticket_id, 'jpg')
        try:
            _get_bucket().put_object(oss_key, buf.read())
            image_url = get_public_url(oss_key)
        except Exception as e:
            return jsonify({'success': False, 'error': f'OSS上传失败: {e}'}), 500
    else:
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        images_dir = os.path.join(upload_folder, 'images')
        os.makedirs(images_dir, exist_ok=True)
        filename = f"winning_{ticket_id}_{uuid.uuid4().hex[:8]}.jpg"
        with open(os.path.join(images_dir, filename), 'wb') as f:
            f.write(buf.read())
        image_url = f"/uploads/images/{filename}"

    ticket.winning_image_url = image_url
    db.session.commit()
    return jsonify({'success': True, 'image_url': image_url})
