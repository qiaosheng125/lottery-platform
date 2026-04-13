"""
会话管理服务
"""

import secrets
from datetime import timedelta
from typing import Optional

from flask import current_app
from sqlalchemy import and_, or_

from extensions import db
from models.user import User, UserSession
from utils.time_utils import beijing_now


def create_session(user: User, device_id: str = None, ip_address: str = None) -> UserSession:
    """创建新会话"""
    token = secrets.token_urlsafe(64)
    try:
        from models.settings import SystemSettings

        hours = SystemSettings.get().session_lifetime_hours
    except Exception:
        hours = current_app.config.get('SESSION_LIFETIME_HOURS', 3)
    expires_at = beijing_now() + timedelta(hours=hours)

    session = UserSession(
        user_id=user.id,
        session_token=token,
        device_id=device_id,
        ip_address=ip_address,
        expires_at=expires_at,
    )
    db.session.add(session)
    db.session.commit()
    return session


def get_session_by_token(token: str) -> Optional[UserSession]:
    return UserSession.query.filter_by(session_token=token).first()


def touch_session(token: str):
    """更新 last_seen"""
    now = beijing_now()
    try:
        from models.settings import SystemSettings

        hours = SystemSettings.get().session_lifetime_hours
    except Exception:
        hours = current_app.config.get('SESSION_LIFETIME_HOURS', 3)
    UserSession.query.filter_by(session_token=token).update({
        'last_seen': now,
        'expires_at': now + timedelta(hours=hours),
    })
    db.session.commit()


def delete_session(token: str):
    UserSession.query.filter_by(session_token=token).delete()
    db.session.commit()


def force_logout_user(user_id: int, reason: str = '管理员强制下线') -> int:
    """强制下线指定用户所有会话"""
    from services.notify_service import notify_user
    count = UserSession.query.filter_by(user_id=user_id).delete()
    db.session.commit()
    notify_user(user_id, 'force_logout', {'reason': reason})
    return count


def clean_inactive_sessions(hours: int = 3) -> int:
    """清理超过 hours 小时无活动的会话"""
    now = beijing_now()
    cutoff = beijing_now() - timedelta(hours=hours)
    count = UserSession.query.filter(
        or_(
            UserSession.last_seen < cutoff,
            and_(UserSession.expires_at.isnot(None), UserSession.expires_at < now),
        )
    ).delete(synchronize_session=False)
    db.session.commit()
    return count


def daily_reset_sessions() -> int:
    """每日12点重置所有会话（强制全员重新登录）"""
    from services.notify_service import notify_all
    count = UserSession.query.delete()
    db.session.commit()
    notify_all('force_logout', {'reason': '每日定时重置，请重新登录'})
    return count
