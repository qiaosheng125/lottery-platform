"""
会话清理任务
"""

import logging
from services.session_service import clean_inactive_sessions as _clean

logger = logging.getLogger(__name__)


def clean_inactive_sessions():
    """清理无活动超时的会话，超时时长从管理员设置读取"""
    try:
        from models.settings import SystemSettings
        hours = SystemSettings.get().session_lifetime_hours
        count = _clean(hours=hours)
        if count:
            logger.info(f"Cleaned {count} inactive sessions (timeout={hours}h)")
    except Exception as e:
        logger.error(f"clean_inactive_sessions error: {e}")
