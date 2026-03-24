from datetime import datetime, timedelta
from flask_login import UserMixin
from extensions import db, login_manager


def beijing_now():
    return datetime.utcnow() + timedelta(hours=8)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    client_mode = db.Column(db.String(10), default='mode_a', nullable=False)  # 'mode_a' | 'mode_b'
    max_devices = db.Column(db.Integer, default=1, nullable=False)
    max_processing_b_mode = db.Column(db.Integer, nullable=True)  # B模式处理中票数上限，None表示不限制
    daily_ticket_limit = db.Column(db.Integer, nullable=True)  # 每日可处理票数上限，None表示不限制
    is_active = db.Column(db.Boolean, default=True, nullable=False)  # account active
    can_receive = db.Column(db.Boolean, default=True, nullable=False)  # admin-controlled receive switch
    created_at = db.Column(db.DateTime, default=beijing_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=beijing_now, onupdate=beijing_now, nullable=False)

    # Relationships
    sessions = db.relationship('UserSession', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    devices = db.relationship('DeviceRegistry', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        from extensions import bcrypt
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        from extensions import bcrypt
        return bcrypt.check_password_hash(self.password_hash, password)

    def get_active_sessions(self):
        return UserSession.query.filter_by(user_id=self.id).all()

    def session_count(self):
        return UserSession.query.filter_by(user_id=self.id).count()

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'is_admin': self.is_admin,
            'client_mode': self.client_mode,
            'max_devices': self.max_devices,
            'max_processing_b_mode': self.max_processing_b_mode,
            'daily_ticket_limit': self.daily_ticket_limit,
            'is_active': self.is_active,
            'can_receive': self.can_receive,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class UserSession(db.Model):
    __tablename__ = 'user_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    session_token = db.Column(db.String(128), unique=True, nullable=False, index=True)
    device_id = db.Column(db.String(64), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=beijing_now, nullable=False)
    last_seen = db.Column(db.DateTime, default=beijing_now, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)

    def is_expired(self):
        if self.expires_at and beijing_now() > self.expires_at:
            return True
        return False

    def touch(self):
        self.last_seen = beijing_now()

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'device_id': self.device_id,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
        }
