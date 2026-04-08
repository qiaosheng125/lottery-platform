from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from models.settings import SystemSettings
from services.ticket_pool import get_pool_status
from utils.decorators import login_required_json

pool_bp = Blueprint('pool', __name__)
MODE_B_POOL_RESERVE = 20


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


@pool_bp.route('/status')
@login_required_json
@login_required
def pool_status():
    settings = SystemSettings.get()
    if not settings.pool_enabled:
        return jsonify({'total_pending': 0, 'by_type': [], 'assigned': 0, 'completed_today': 0, 'pool_enabled': False})
    if getattr(current_user, 'client_mode', None) == 'mode_b' and not settings.mode_b_enabled:
        return jsonify({'total_pending': 0, 'by_type': [], 'assigned': 0, 'completed_today': 0, 'pool_enabled': settings.pool_enabled})

    status = get_pool_status(current_user.get_blocked_lottery_types())
    if getattr(current_user, 'client_mode', None) == 'mode_b':
        status = _trim_status_for_mode_b(status)
    status['pool_enabled'] = settings.pool_enabled

    if not current_user.can_receive:
        status['total_pending'] = 0
        status['by_type'] = []

    return jsonify(status)
