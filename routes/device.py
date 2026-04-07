from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from extensions import db
from models.device import DeviceRegistry
from utils.time_utils import beijing_now

device_bp = Blueprint('device', __name__)


@device_bp.route('/register', methods=['POST'])
@login_required
def register_device():
    data = request.get_json(silent=True) or {}
    device_id = data.get('device_id', '')
    device_name = data.get('device_name', '')
    client_info = data.get('client_info', {})

    if not device_id:
        return jsonify({'success': False, 'error': '缺少设备ID'}), 400

    device = DeviceRegistry.query.filter_by(device_id=device_id).first()
    if device and device.user_id != current_user.id:
        return jsonify({
            'success': False,
            'error': '该设备ID已归属于其他用户',
        }), 409

    # 检查设备名重复（同一用户下）
    if device_name:
        duplicate = DeviceRegistry.query.filter(
            DeviceRegistry.user_id == current_user.id,
            DeviceRegistry.device_name == device_name,
            DeviceRegistry.device_id != device_id  # 排除自己
        ).first()
        if duplicate:
            return jsonify({
                'success': False,
                'error': f'设备名"{device_name}"已被使用，请重新命名',
                'duplicate': True
            }), 409

    if device:
        device.user_id = current_user.id
        device.client_info = client_info
        device.touch()
        if device_name:
            device.device_name = device_name
    else:
        device = DeviceRegistry(
            device_id=device_id,
            user_id=current_user.id,
            device_name=device_name or f'设备-{device_id[:8]}',
            client_info=client_info,
        )
        db.session.add(device)

    db.session.commit()
    return jsonify({'success': True, 'device': device.to_dict()})


@device_bp.route('/<device_id>/name', methods=['PUT'])
@login_required
def update_device_name(device_id):
    device = DeviceRegistry.query.filter_by(
        device_id=device_id, user_id=current_user.id
    ).first_or_404()

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': '设备名不能为空'}), 400

    # 检查设备名重复（同一用户下）
    duplicate = DeviceRegistry.query.filter(
        DeviceRegistry.user_id == current_user.id,
        DeviceRegistry.device_name == name,
        DeviceRegistry.device_id != device_id  # 排除自己
    ).first()
    if duplicate:
        return jsonify({
            'success': False,
            'error': f'设备名"{name}"已被使用，请重新命名'
        }), 409

    device.device_name = name
    db.session.commit()
    return jsonify({'success': True})
