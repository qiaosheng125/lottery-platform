from datetime import datetime, timedelta
from extensions import db


def beijing_now():
    return datetime.utcnow() + timedelta(hours=8)


class DeviceRegistry(db.Model):
    __tablename__ = 'device_registry'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    device_name = db.Column(db.String(128), nullable=True)
    client_info = db.Column(db.JSON, nullable=True)
    first_seen = db.Column(db.DateTime, default=beijing_now, nullable=False)
    last_active = db.Column(db.DateTime, default=beijing_now, nullable=False)
    is_authorized = db.Column(db.Boolean, default=True, nullable=False)

    def touch(self):
        self.last_active = beijing_now()

    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'user_id': self.user_id,
            'device_name': self.device_name,
            'client_info': self.client_info,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_active': self.last_active.isoformat() if self.last_active else None,
            'is_authorized': self.is_authorized,
        }
