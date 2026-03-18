import json
from datetime import datetime, timedelta
from extensions import db


def beijing_now():
    return datetime.utcnow() + timedelta(hours=8)


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    timestamp = db.Column(db.DateTime, default=beijing_now, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    device_id = db.Column(db.String(64), nullable=True)
    action_type = db.Column(db.String(64), nullable=False, index=True)
    # file_upload | file_revoke | ticket_assign | ticket_complete |
    # batch_download | winning_upload | user_login | force_logout | ...
    resource_type = db.Column(db.String(64), nullable=True)
    resource_id = db.Column(db.String(64), nullable=True)
    details = db.Column(db.Text, nullable=True)  # stored as JSON string
    status_code = db.Column(db.Integer, nullable=True)

    user = db.relationship('User', foreign_keys=[user_id])

    @classmethod
    def log(cls, action_type, user_id=None, ip_address=None, device_id=None,
            resource_type=None, resource_id=None, details=None, status_code=None):
        entry = cls(
            action_type=action_type,
            user_id=user_id,
            ip_address=ip_address,
            device_id=device_id,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            details=json.dumps(details, ensure_ascii=False) if isinstance(details, (dict, list)) else details,
            status_code=status_code,
        )
        db.session.add(entry)
        return entry

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'user_id': self.user_id,
            'ip_address': self.ip_address,
            'action_type': self.action_type,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'details': self.details,
            'status_code': self.status_code,
        }
