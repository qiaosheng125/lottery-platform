from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from services.mode_a_service import (
    get_current_ticket,
    get_next_ticket,
    get_previous_ticket,
    stop_receiving,
)
from utils.decorators import can_receive_required, login_required_json, mode_a_required

mode_a_bp = Blueprint('mode_a', __name__)


def _validate_device_info(device_id: str, device_name: str = ''):
    device_id = (device_id or '').strip()
    device_name = (device_name or '').strip()
    if not device_id:
        return '缺少设备ID'
    if len(device_id) > 64 or not all(c.isalnum() or c in '-_' for c in device_id):
        return '无效的设备ID'
    if len(device_name) > 128:
        return '设备名称过长'
    return None


def _get_device_info():
    data = request.get_json(silent=True) or {}
    device_id = data.get('device_id') or request.args.get('device_id', '')
    device_name = data.get('device_name') or request.args.get('device_name', '')
    complete_current_ticket_id = data.get('complete_current_ticket_id')
    complete_current_ticket_action = data.get('complete_current_ticket_action') or 'completed'
    return device_id, device_name, complete_current_ticket_id, complete_current_ticket_action


def _parse_non_negative_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


@mode_a_bp.route('/next', methods=['POST'])
@login_required_json
@login_required
@mode_a_required
@can_receive_required
def next_ticket():
    device_id, device_name, complete_current_ticket_id, complete_current_ticket_action = _get_device_info()
    error = _validate_device_info(device_id, device_name)
    if error:
        return jsonify({'success': False, 'error': error}), 400

    result = get_next_ticket(
        user_id=current_user.id,
        device_id=device_id,
        username=current_user.username,
        device_name=device_name,
        complete_current_ticket_id=complete_current_ticket_id,
        complete_current_ticket_action=complete_current_ticket_action,
    )
    return jsonify(result)


@mode_a_bp.route('/current', methods=['GET'])
@login_required_json
@login_required
@mode_a_required
def current_ticket():
    """Return the currently assigned ticket without mutating status."""
    device_id = request.args.get('device_id', '')
    error = _validate_device_info(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400

    ticket = get_current_ticket(current_user.id, device_id)
    if not ticket:
        return jsonify({'success': False, 'error': '当前无接单中的票'})
    return jsonify({'success': True, 'ticket': ticket.to_dict()})


@mode_a_bp.route('/stop', methods=['POST'])
@login_required_json
@login_required
@mode_a_required
def stop():
    device_id, _, _, complete_current_ticket_action = _get_device_info()
    error = _validate_device_info(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400

    result = stop_receiving(current_user.id, device_id, current_ticket_action=complete_current_ticket_action)
    return jsonify(result)


@mode_a_bp.route('/previous', methods=['GET'])
@login_required_json
@login_required
@mode_a_required
def previous_ticket():
    device_id = request.args.get('device_id', '')
    offset = _parse_non_negative_int(request.args.get('offset', 0))
    error = _validate_device_info(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400
    if offset is None:
        return jsonify({'success': False, 'error': 'offset 必须是大于等于 0 的整数'}), 400

    result = get_previous_ticket(current_user.id, device_id, offset)
    return jsonify(result)
