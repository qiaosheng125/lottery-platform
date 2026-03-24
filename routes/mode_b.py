from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from services.mode_b_service import preview_batch, download_batch, confirm_batch, get_processing_batches
from services.ticket_pool import get_pool_status
from utils.decorators import login_required_json, can_receive_required

mode_b_bp = Blueprint('mode_b', __name__)


@mode_b_bp.route('/pool-status')
@login_required
@login_required_json
def pool_status():
    """返回当前票池状态（按彩种+截止时间分组），供B模式用户参考"""
    status = get_pool_status()
    # 被禁止接单的用户看到的待处理数量为0
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
    device_id = data.get('device_id', '')
    device_name = data.get('device_name', '')

    if not device_id:
        return jsonify({'success': False, 'error': '缺少设备ID'}), 400

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
    """返回当前用户处理中（assigned）的票，按批次分组"""
    batches = get_processing_batches(current_user.id)
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
