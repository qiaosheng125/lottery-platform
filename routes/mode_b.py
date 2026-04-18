from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from models.settings import SystemSettings
from services.mode_b_service import (
    confirm_batch,
    download_batch,
    get_processing_batches,
    preview_batch,
)
from services.ticket_pool import get_pool_status
from utils.decorators import can_receive_required, login_required_json, mode_b_required

mode_b_bp = Blueprint('mode_b', __name__)
MODE_B_POOL_RESERVE = 20


def _validate_device_id(device_id: str):
    device_id = (device_id or '').strip()
    if not device_id:
        return '缺少设备ID'
    if len(device_id) > 20 or not all(c.isalnum() or c in '-_' for c in device_id):
        return '无效的设备ID'
    return None


def _is_browser_request(client_type: str = None) -> bool:
    normalized = (client_type or '').strip().lower()
    if normalized == 'web':
        return True
    if normalized == 'desktop':
        return False

    user_agent = (request.user_agent.string or '').lower()
    if not user_agent:
        return False

    desktop_agent_markers = (
        'python-requests',
        'postmanruntime',
        'curl/',
        'wget/',
        'okhttp',
        'go-http-client',
        'python-urllib',
    )
    if any(marker in user_agent for marker in desktop_agent_markers):
        return False

    browser_markers = (
        'mozilla/',
        'applewebkit/',
        'chrome/',
        'safari/',
        'firefox/',
        'edg/',
    )
    return any(marker in user_agent for marker in browser_markers)


def _parse_batch_count(value, default: int = 100):
    try:
        count = int(value if value is not None else default)
    except (TypeError, ValueError):
        return None
    if count < 1:
        return None
    return count


def _trim_status_for_mode_b(status: dict) -> dict:
    available_total = max(0, int(status.get('total_pending') or 0) - MODE_B_POOL_RESERVE)
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
        return jsonify({'success': False, 'error': 'count 必须是大于 0 的整数'}), 400
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
    data = request.get_json(silent=True) or {}
    count = _parse_batch_count(data.get('count', 100) if data else 100)
    if count is None:
        return jsonify({'success': False, 'error': 'count 必须是大于 0 的整数'}), 400

    device_id = (data.get('device_id') or '').strip()
    client_type = data.get('client_type')
    if not device_id:
        return jsonify({'success': False, 'error': '缺少设备ID'}), 400

    error = _validate_device_id(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400

    if current_user.desktop_only_b_mode and _is_browser_request(client_type):
        return jsonify({'success': False, 'error': 'B模式仅允许通过桌面端接单'}), 403

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

    batches = get_processing_batches(current_user.id, device_id)
    return jsonify({'success': True, 'batches': batches})


@mode_b_bp.route('/confirm', methods=['POST'])
@login_required_json
@login_required
@mode_b_required
def confirm():
    data = request.get_json(silent=True) or {}
    ticket_ids = data.get('ticket_ids', [])
    completed_count = data.get('completed_count')
    device_id = (data.get('device_id') or '').strip()
    if not device_id:
        return jsonify({'success': False, 'error': '缺少设备ID'}), 400
    if not ticket_ids:
        return jsonify({'success': False, 'error': '缺少票ID'}), 400
    if not isinstance(ticket_ids, list):
        return jsonify({'success': False, 'error': '票ID必须是数组'}), 400

    error = _validate_device_id(device_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400

    try:
        parsed_ticket_ids = [int(i) for i in ticket_ids]
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': '票ID必须是整数'}), 400

    result = confirm_batch(parsed_ticket_ids, current_user.id, completed_count=completed_count, device_id=device_id or None)
    if not result.get('success') and (('未找到' in (result.get('error') or '')) or ('不属于当前设备' in (result.get('error') or ''))):
        return jsonify(result), 400
    return jsonify(result)
