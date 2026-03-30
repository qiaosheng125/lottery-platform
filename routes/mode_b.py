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
from utils.decorators import can_receive_required, login_required_json

mode_b_bp = Blueprint('mode_b', __name__)


@mode_b_bp.route('/pool-status')
@login_required
@login_required_json
def pool_status():
    """Return grouped pool status for mode B users."""
    settings = SystemSettings.get()
    if not settings.pool_enabled:
        return jsonify({'success': True, 'total_pending': 0, 'by_type': [], 'assigned': 0, 'completed_today': 0})

    status = get_pool_status()
    if not current_user.can_receive:
        status['total_pending'] = 0
        status['by_type'] = []
    return jsonify({'success': True, **status})


@mode_b_bp.route('/preview')
@login_required
@login_required_json
def preview():
    count = int(request.args.get('count', 100))
    result = preview_batch(count)
    return jsonify({'success': True, **result})


@mode_b_bp.route('/download', methods=['POST'])
@login_required
@login_required_json
@can_receive_required
def download():
    data = request.get_json()
    count = int(data.get('count', 100))
    device_id = data.get('device_id') or 'Web'
    device_name = data.get('device_name') or '网页浏览器'

    result = download_batch(
        user_id=current_user.id,
        device_id=device_id,
        username=current_user.username,
        count=count,
        device_name=device_name,
    )

    if not result['success']:
        return jsonify(result), 400

    return jsonify(result)


@mode_b_bp.route('/processing')
@login_required
@login_required_json
def processing():
    """Return assigned batches for the current user."""
    device_id = (request.args.get('device_id') or '').strip()
    if device_id and (len(device_id) > 50 or not all(c.isalnum() or c in '-_' for c in device_id)):
        return jsonify({'success': False, 'error': '无效的设备ID'}), 400

    batches = get_processing_batches(current_user.id, device_id or None)
    return jsonify({'success': True, 'batches': batches})


@mode_b_bp.route('/confirm', methods=['POST'])
@login_required
@login_required_json
def confirm():
    data = request.get_json()
    ticket_ids = data.get('ticket_ids', [])
    if not ticket_ids:
        return jsonify({'success': False, 'error': '缺少票ID列表'}), 400

    result = confirm_batch([int(i) for i in ticket_ids], current_user.id)
    return jsonify(result)
