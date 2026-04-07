from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from models.settings import SystemSettings
from services.ticket_pool import get_pool_status
from utils.decorators import login_required_json

pool_bp = Blueprint('pool', __name__)


@pool_bp.route('/status')
@login_required_json
@login_required
def pool_status():
    settings = SystemSettings.get()
    if not settings.pool_enabled:
        return jsonify({'total_pending': 0, 'by_type': [], 'assigned': 0, 'completed_today': 0, 'pool_enabled': False})

    status = get_pool_status()
    status['pool_enabled'] = settings.pool_enabled

    if not current_user.can_receive:
        status['total_pending'] = 0
        status['by_type'] = []

    return jsonify(status)
