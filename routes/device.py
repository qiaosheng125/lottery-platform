from datetime import timedelta

from flask import Blueprint, jsonify, session
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.audit import AuditLog
from models.device import DeviceRegistry
from models.settings import SystemSettings
from models.ticket import LotteryTicket
from models.user import UserSession
from utils.decorators import get_client_ip, login_required_json, parse_json_object
from utils.time_utils import beijing_now


device_bp = Blueprint('device', __name__)


def _normalize_device_id(raw_device_id):
    if raw_device_id is None:
        return ''
    if not isinstance(raw_device_id, str):
        return None
    return raw_device_id.strip()


def _validate_device_id(device_id):
    if not device_id:
        return '请输入设备ID'
    if len(device_id) > 20 or not all(c.isalnum() or c in '-_' for c in device_id):
        return '设备ID只能包含字母、数字、连字符和下划线，且长度不能超过20'
    return None


@device_bp.route('/register', methods=['POST'])
@login_required_json
@login_required
def register_device():
    data, data_error = parse_json_object()
    if data_error:
        return data_error

    device_id = _normalize_device_id(data.get('device_id'))
    if device_id is None:
        return jsonify({'success': False, 'error': 'invalid device_id type'}), 400
    client_info = data.get('client_info', {})
    if not isinstance(client_info, dict):
        return jsonify({'success': False, 'error': 'invalid client_info type'}), 400

    validation_error = _validate_device_id(device_id)
    if validation_error:
        return jsonify({'success': False, 'error': validation_error}), 400

    device = DeviceRegistry.query.filter_by(device_id=device_id).first()
    if device and device.user_id != current_user.id:
        return jsonify({'success': False, 'error': '该设备ID已被其他用户占用'}), 409

    if device:
        device.user_id = current_user.id
        device.client_info = client_info
        device.touch()
    else:
        device = DeviceRegistry(
            device_id=device_id,
            user_id=current_user.id,
            client_info=client_info,
        )
        db.session.add(device)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'success': False, 'error': '设备ID已被占用，请换一个'}), 409
    return jsonify({'success': True, 'device': device.to_dict()})


@device_bp.route('/update', methods=['POST'])
@login_required_json
@login_required
def update_device_id():
    data, data_error = parse_json_object()
    if data_error:
        return data_error

    token = session.get('session_token')
    if not token:
        return jsonify({'success': False, 'error': 'session invalid'}), 401

    session_record = UserSession.query.filter_by(
        session_token=token,
        user_id=current_user.id,
    ).first()
    if not session_record:
        return jsonify({'success': False, 'error': 'session invalid'}), 401

    current_device_id = _normalize_device_id(data.get('current_device_id'))
    if current_device_id is None:
        return jsonify({'success': False, 'error': 'invalid current_device_id type'}), 400

    new_device_id = _normalize_device_id(data.get('new_device_id'))
    if new_device_id is None:
        return jsonify({'success': False, 'error': 'invalid new_device_id type'}), 400

    validation_error = _validate_device_id(new_device_id)
    if validation_error:
        return jsonify({'success': False, 'error': validation_error}), 400

    bound_device_id = (session_record.device_id or '').strip()
    old_device_id = bound_device_id or current_device_id
    if bound_device_id and current_device_id and current_device_id != bound_device_id:
        return jsonify({'success': False, 'error': 'current_device_id mismatch with active session'}), 403

    client_info = data.get('client_info', {})
    if not isinstance(client_info, dict):
        return jsonify({'success': False, 'error': 'invalid client_info type'}), 400

    target_device = DeviceRegistry.query.filter_by(device_id=new_device_id).first()
    if target_device and target_device.user_id != current_user.id:
        return jsonify({'success': False, 'error': '该设备ID已被其他用户占用'}), 409

    if old_device_id and old_device_id != new_device_id:
        assigned_count = LotteryTicket.query.filter_by(
            assigned_user_id=current_user.id,
            assigned_device_id=old_device_id,
            status='assigned',
        ).count()
        if assigned_count:
            return jsonify({'success': False, 'error': '当前设备还有处理中的票，请先完成或停止接单后再修改设备ID'}), 409

    try:
        cutoff = beijing_now() - timedelta(hours=SystemSettings.get().session_lifetime_hours)
    except Exception:
        cutoff = beijing_now() - timedelta(hours=3)

    active_conflict = UserSession.query.filter(
        UserSession.user_id == current_user.id,
        UserSession.device_id == new_device_id,
        UserSession.session_token != token,
        UserSession.last_seen >= cutoff,
    ).first()
    if active_conflict:
        return jsonify({'success': False, 'error': '该设备ID正在当前账号的其他会话中使用'}), 409

    old_device = None
    if old_device_id:
        old_device = DeviceRegistry.query.filter_by(
            device_id=old_device_id,
            user_id=current_user.id,
        ).first()

    if target_device:
        target_device.client_info = client_info
        target_device.touch()
        if old_device and old_device.id != target_device.id:
            db.session.delete(old_device)
        device = target_device
    elif old_device:
        old_device.device_id = new_device_id
        old_device.client_info = client_info
        old_device.touch()
        device = old_device
    else:
        device = DeviceRegistry(
            device_id=new_device_id,
            user_id=current_user.id,
            client_info=client_info,
        )
        db.session.add(device)

    session_record.device_id = new_device_id
    session_record.last_seen = beijing_now()
    AuditLog.log(
        'device_id_update',
        user_id=current_user.id,
        ip_address=get_client_ip(),
        device_id=new_device_id,
        details={'old_device_id': old_device_id, 'new_device_id': new_device_id},
    )

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'success': False, 'error': '设备ID已被占用，请换一个'}), 409

    return jsonify({'success': True, 'device': device.to_dict()})
