from flask import Blueprint, jsonify, request, session
from flask_login import current_user, login_required

from extensions import db
from models.settings import SystemSettings
from models.user import UserSession
from services.mode_b_service import (
    confirm_batch,
    download_batch,
    get_processing_batches,
    preview_batch,
)
from services.ticket_pool import get_mode_b_pool_reserve, get_pool_status
from utils.decorators import can_receive_required, login_required_json, mode_b_required, parse_json_object

mode_b_bp = Blueprint('mode_b', __name__)
MAX_BATCH_COUNT = 1000


def _validate_device_id(device_id: str):
    if not device_id:
        return '缺少设备ID'
    if len(device_id) > 20 or not all(c.isalnum() or c in '-_' for c in device_id):
        return '无效的设备ID'
    return None


def _is_browser_request(client_type: str = None) -> bool:
    normalized = (client_type or '').strip().lower() if isinstance(client_type, str) else ''

    user_agent = (request.user_agent.string or '').lower()

    desktop_agent_markers = (
        'python-requests',
        'postmanruntime',
        'curl/',
        'wget/',
        'okhttp',
        'go-http-client',
        'python-urllib',
    )
    if user_agent and any(marker in user_agent for marker in desktop_agent_markers):
        return False

    browser_markers = (
        'mozilla/',
        'applewebkit/',
        'chrome/',
        'safari/',
        'firefox/',
        'edg/',
    )
    is_browser_ua = user_agent and any(marker in user_agent for marker in browser_markers)
    if is_browser_ua:
        return True
    if normalized == 'web':
        return True
    if normalized == 'desktop':
        return False
    return False


def _parse_batch_count(value, default: int = 100):
    if value is None:
        value = default
    if isinstance(value, bool) or isinstance(value, float):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    if count < 1:
        return None
    if count > MAX_BATCH_COUNT:
        return None
    return count


def _batch_count_error():
    return f'count 必须是 1 到 {MAX_BATCH_COUNT} 之间的整数'


def _enforce_bound_session_device(device_id: str):
    token = session.get('session_token')
    if not token:
        return jsonify({'success': False, 'error': 'session invalid'}), 401

    session_record = UserSession.query.filter_by(session_token=token, user_id=current_user.id).first()
    if not session_record:
        return jsonify({'success': False, 'error': 'session invalid'}), 401

    bound_device_id = (session_record.device_id or '').strip()
    if bound_device_id and bound_device_id != device_id:
        return jsonify({'success': False, 'error': 'device_id mismatch with active session'}), 403

    if not bound_device_id:
        session_record.device_id = device_id
        db.session.commit()
    return None


def _trim_status_for_mode_b(status: dict) -> dict:
    available_total = max(0, int(status.get('total_pending') or 0) - get_mode_b_pool_reserve())
    trimmed_by_type = []
    remaining = available_total
    for item in status.get('by_type') or []:
        if remaining <= 0:
            break
        raw_count = int(item.get('count') or 0)
        if raw_count <= 0:
            continue
        visible_count = min(raw_count, remaining)
        trimmed_by_type.append({**item, 'count': visible_count})
        remaining -= visible_count
    return {
        **status,
        'total_pending': available_total,
        'by_type': trimmed_by_type,
    }


@mode_b_bp.route('/pool-status')
@login_required_json
@login_required
@mode_b_required
def pool_status():
    settings = SystemSettings.get()
    if not settings.mode_b_enabled or not settings.pool_enabled:
        return jsonify({'success': True, 'total_pending': 0, 'by_type': [], 'assigned': 0, 'completed_today': 0})

    status = _trim_status_for_mode_b(get_pool_status(current_user.get_blocked_lottery_types()))
    if not current_user.can_receive:
        status['total_pending'] = 0
        status['by_type'] = []
    return jsonify({'success': True, **status})


@mode_b_bp.route('/preview')
@login_required_json
@login_required
@mode_b_required
def preview():
    count = _parse_batch_count(request.args.get('count', 100))
    if count is None:
        return jsonify({'success': False, 'error': _batch_count_error()}), 400
    result = preview_batch(count, user_id=current_user.id)
    if not current_user.can_receive:
        result = {
            'available': 0,
            'requested': count,
            'sufficient': False,
        }
    return jsonify({'success': True, **result})


@mode_b_bp.route('/download', methods=['POST'])
@login_required_json
@login_required
@mode_b_required
@can_receive_required
def download():
    data, data_error = parse_json_object()
    if data_error:
        return data_error
    count = _parse_batch_count(data.get('count', 100) if data else 100)
    if count is None:
        return jsonify({'success': False, 'error': _batch_count_error()}), 400

    raw_device_id = data.get('device_id')
    if raw_device_id is None:
        device_id = ''
    elif isinstance(raw_device_id, str):
        device_id = raw_device_id.strip()
    else:
        return jsonify({'success': False, 'error': 'invalid device_id type'}), 400
    client_type = data.get('client_type')
    if not device_id:
        return jsonify({'success': False, 'error': '缺少设备ID'}), 400

    error = _validate_device_id(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400
    session_error = _enforce_bound_session_device(device_id)
    if session_error:
        return session_error

    if current_user.desktop_only_b_mode and _is_browser_request(client_type):
        return jsonify({'success': False, 'error': 'B 模式仅允许通过桌面端接单'}), 403

    result = download_batch(
        user_id=current_user.id,
        device_id=device_id,
        username=current_user.username,
        count=count,
    )

    if not result['success']:
        return jsonify(result), 400

    return jsonify(result)


@mode_b_bp.route('/processing')
@login_required_json
@login_required
@mode_b_required
def processing():
    device_id = (request.args.get('device_id') or '').strip()
    if not device_id:
        return jsonify({'success': False, 'error': '缺少设备ID'}), 400

    error = _validate_device_id(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400
    session_error = _enforce_bound_session_device(device_id)
    if session_error:
        return session_error

    batches = get_processing_batches(current_user.id, device_id)
    return jsonify({'success': True, 'batches': batches})


@mode_b_bp.route('/confirm', methods=['POST'])
@login_required_json
@login_required
@mode_b_required
def confirm():
    data, data_error = parse_json_object()
    if data_error:
        return data_error
    ticket_ids = data.get('ticket_ids', [])
    completed_count = data.get('completed_count')
    raw_device_id = data.get('device_id')
    if raw_device_id is None:
        device_id = ''
    elif isinstance(raw_device_id, str):
        device_id = raw_device_id.strip()
    else:
        return jsonify({'success': False, 'error': 'invalid device_id type'}), 400
    if not device_id:
        return jsonify({'success': False, 'error': '缺少设备ID'}), 400
    if isinstance(ticket_ids, bool):
        return jsonify({'success': False, 'error': '票ID必须是数组'}), 400
    if not isinstance(ticket_ids, list):
        return jsonify({'success': False, 'error': '票ID必须是数组'}), 400
    if any(isinstance(ticket_id, bool) for ticket_id in ticket_ids):
        return jsonify({'success': False, 'error': '票ID必须是整数'}), 400
    if any(isinstance(ticket_id, float) for ticket_id in ticket_ids):
        return jsonify({'success': False, 'error': 'ticket_id must be integer'}), 400
    if isinstance(completed_count, bool) or isinstance(completed_count, float):
        return jsonify({'success': False, 'error': 'completed_count must be integer'}), 400
    if not ticket_ids:
        return jsonify({'success': False, 'error': '缺少票ID'}), 400

    error = _validate_device_id(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400
    session_error = _enforce_bound_session_device(device_id)
    if session_error:
        return session_error

    try:
        parsed_ticket_ids = [int(i) for i in ticket_ids]
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': '票ID必须是整数'}), 400

    result = confirm_batch(parsed_ticket_ids, current_user.id, completed_count=completed_count, device_id=device_id or None)
    if not result.get('success'):
        return jsonify(result), 400
    return jsonify(result)

