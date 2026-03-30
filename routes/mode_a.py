from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from services.mode_a_service import (
    get_current_ticket,
    get_next_ticket,
    get_previous_ticket,
    stop_receiving,
)
from utils.decorators import can_receive_required, login_required_json

mode_a_bp = Blueprint('mode_a', __name__)


def _get_device_info():
    data = request.get_json(silent=True) or {}
    device_id = data.get('device_id') or request.args.get('device_id', '')
    device_name = data.get('device_name') or request.args.get('device_name', '')
    complete_current_ticket_id = data.get('complete_current_ticket_id')
    return device_id, device_name, complete_current_ticket_id


@mode_a_bp.route('/next', methods=['POST'])
@login_required
@login_required_json
@can_receive_required
def next_ticket():
    device_id, device_name, complete_current_ticket_id = _get_device_info()
    if not device_id:
        return jsonify({'success': False, 'error': '缺少设备ID'}), 400

    result = get_next_ticket(
        user_id=current_user.id,
        device_id=device_id,
        username=current_user.username,
        device_name=device_name,
        complete_current_ticket_id=complete_current_ticket_id,
    )
    return jsonify(result)


@mode_a_bp.route('/current', methods=['GET'])
@login_required
@login_required_json
def current_ticket():
    """Return the currently assigned ticket without mutating status."""
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
    device_id, _, _ = _get_device_info()
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
