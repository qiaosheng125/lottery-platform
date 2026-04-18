from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from extensions import db
from models.device import DeviceRegistry
from utils.decorators import login_required_json


device_bp = Blueprint('device', __name__)


@device_bp.route('/register', methods=['POST'])
@login_required_json
@login_required
def register_device():
    data = request.get_json(silent=True) or {}
    device_id = (data.get('device_id') or '').strip()
    client_info = data.get('client_info', {})

    if not device_id:
        return jsonify({'success': False, 'error': '请输入设备ID'}), 400
    if len(device_id) > 20 or not all(c.isalnum() or c in '-_' for c in device_id):
        return jsonify({'success': False, 'error': '设备ID只能包含字母、数字、连字符和下划线，且长度不能超过20'}), 400

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

    db.session.commit()
    return jsonify({'success': True, 'device': device.to_dict()})
