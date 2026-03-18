from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from services.ticket_pool import get_pool_status
from models.settings import SystemSettings

pool_bp = Blueprint('pool', __name__)


@pool_bp.route('/status')
@login_required
def pool_status():
    settings = SystemSettings.get()
    if not settings.pool_enabled:
        if not current_user.can_receive:
            return jsonify({'total_pending': 0, 'by_type': [], 'pool_enabled': False})

    status = get_pool_status()
    status['pool_enabled'] = settings.pool_enabled
    return jsonify(status)
