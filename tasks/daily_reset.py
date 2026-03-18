"""
每日12点会话重置任务
"""

import logging
from services.session_service import daily_reset_sessions

logger = logging.getLogger(__name__)


def daily_session_reset():
    """每日12点重置所有会话"""
    try:
        count = daily_reset_sessions()
        logger.info(f"Daily reset: cleared {count} sessions")
    except Exception as e:
        logger.error(f"daily_session_reset error: {e}")
