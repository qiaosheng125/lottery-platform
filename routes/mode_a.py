from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from services.mode_a_service import get_next_ticket, stop_receiving, get_previous_ticket, get_current_ticket
from utils.decorators import login_required_json, can_receive_required

mode_a_bp = Blueprint('mode_a', __name__)


def _get_device_info():
    data = request.get_json(silent=True) or {}
    device_id = data.get('device_id') or request.args.get('device_id', '')
    device_name = data.get('device_name') or request.args.get('device_name', '')
    return device_id, device_name


@mode_a_bp.route('/next', methods=['POST'])
@login_required
@login_required_json
@can_receive_required
def next_ticket():
    device_id, device_name = _get_device_info()
    if not device_id:
        return jsonify({'success': False, 'error': '缺少设备ID'}), 400

    result = get_next_ticket(
        user_id=current_user.id,
        device_id=device_id,
        username=current_user.username,
        device_name=device_name,
    )
    return jsonify(result)


@mode_a_bp.route('/current', methods=['GET'])
@login_required
@login_required_json
def current_ticket():
    """返回当前 assigned 票，不分配新票，不改变任何状态"""
    device_id = request.args.get('device_id', '')
    if not device_id:
        return jsonify({'success': False, 'error': '缺少设备ID'}), 400

    ticket = get_current_ticket(current_user.id, device_id)
    if not ticket:
        return jsonify({'success': False, 'error': '当前无接单中的票'})
    return jsonify({'success': True, 'ticket': ticket.to_dict()})


@mode_a_bp.route('/stop', methods=['POST'])
@login_required
@login_required_json
def stop():
    device_id, _ = _get_device_info()
    if not device_id:
        return jsonify({'success': False, 'error': '缺少设备ID'}), 400

    result = stop_receiving(current_user.id, device_id)
    return jsonify(result)


@mode_a_bp.route('/previous', methods=['GET'])
@login_required
@login_required_json
def previous_ticket():
    device_id = request.args.get('device_id', '')
    offset = int(request.args.get('offset', 0))
    if not device_id:
        return jsonify({'success': False, 'error': '缺少设备ID'}), 400

    result = get_previous_ticket(current_user.id, device_id, offset)
    return jsonify(result)
