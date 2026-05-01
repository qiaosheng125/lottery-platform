from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from services.mode_a_service import (
    get_current_ticket_data,
    get_device_daily_records,
    get_next_ticket,
    get_previous_ticket,
    stop_receiving,
)
from utils.decorators import can_receive_required, login_required_json, mode_a_required, parse_json_object

mode_a_bp = Blueprint('mode_a', __name__)


def _normalize_device_id(raw_device_id: str) -> str:
    if raw_device_id is None:
        return ''
    if not isinstance(raw_device_id, str):
        return None
    return raw_device_id.strip()


def _validate_device_id(device_id: str):
    if not device_id:
        return '缺少设备ID'
    if len(device_id) > 20 or not all(c.isalnum() or c in '-_' for c in device_id):
        return '无效的设备ID'
    return None


def _get_device_payload():
    data, data_error = parse_json_object()
    if data_error:
        return None, None, None, data_error
    device_id = _normalize_device_id(data.get('device_id') or request.args.get('device_id', ''))
    if device_id is None:
        return None, None, None, (jsonify({'success': False, 'error': 'invalid device_id type'}), 400)
    complete_current_ticket_id = data.get('complete_current_ticket_id')
    complete_current_ticket_action = data.get('complete_current_ticket_action') or 'completed'
    return device_id, complete_current_ticket_id, complete_current_ticket_action, None


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
    device_id, complete_current_ticket_id, complete_current_ticket_action, data_error = _get_device_payload()
    if data_error:
        return data_error
    error = _validate_device_id(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400

    result = get_next_ticket(
        user_id=current_user.id,
        device_id=device_id,
        username=current_user.username,
        complete_current_ticket_id=complete_current_ticket_id,
        complete_current_ticket_action=complete_current_ticket_action,
    )
    return jsonify(result)


@mode_a_bp.route('/current', methods=['GET'])
@login_required_json
@login_required
@mode_a_required
def current_ticket():
    device_id = _normalize_device_id(request.args.get('device_id', ''))
    error = _validate_device_id(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400

    ticket = get_current_ticket_data(current_user.id, device_id)
    if not ticket:
        return jsonify({'success': False, 'error': '当前没有进行中的票'})
    return jsonify({'success': True, 'ticket': ticket})


@mode_a_bp.route('/stop', methods=['POST'])
@login_required_json
@login_required
@mode_a_required
def stop():
    device_id, _, complete_current_ticket_action, data_error = _get_device_payload()
    if data_error:
        return data_error
    error = _validate_device_id(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400

    result = stop_receiving(current_user.id, device_id, current_ticket_action=complete_current_ticket_action)
    return jsonify(result)


@mode_a_bp.route('/previous', methods=['GET'])
@login_required_json
@login_required
@mode_a_required
def previous_ticket():
    device_id = _normalize_device_id(request.args.get('device_id', ''))
    offset = _parse_non_negative_int(request.args.get('offset', 0))
    error = _validate_device_id(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400
    if offset is None:
        return jsonify({'success': False, 'error': 'offset 必须是大于等于 0 的整数'}), 400

    result = get_previous_ticket(current_user.id, device_id, offset)
    return jsonify(result)


@mode_a_bp.route('/device-daily', methods=['GET'])
@login_required_json
@login_required
@mode_a_required
def device_daily():
    device_id = _normalize_device_id(request.args.get('device_id', ''))
    error = _validate_device_id(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400

    result = get_device_daily_records(current_user.id, device_id)
    return jsonify(result)
