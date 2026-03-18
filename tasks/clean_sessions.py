"""
会话清理任务
"""

import logging
from services.session_service import clean_inactive_sessions as _clean

logger = logging.getLogger(__name__)


def clean_inactive_sessions():
    """清理3小时无活动的会话"""
    try:
        count = _clean(hours=3)
        if count:
            logger.info(f"Cleaned {count} inactive sessions")
    except Exception as e:
        logger.error(f"clean_inactive_sessions error: {e}")
