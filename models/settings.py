from datetime import datetime, timedelta
from extensions import db


def beijing_now():
    return datetime.utcnow() + timedelta(hours=8)


class SystemSettings(db.Model):
    __tablename__ = 'system_settings'

    id = db.Column(db.Integer, primary_key=True, default=1)
    registration_enabled = db.Column(db.Boolean, default=True, nullable=False)
    pool_enabled = db.Column(db.Boolean, default=True, nullable=False)
    mode_a_enabled = db.Column(db.Boolean, default=True, nullable=False)
    mode_b_enabled = db.Column(db.Boolean, default=True, nullable=False)
    mode_b_options = db.Column(db.JSON, default=lambda: [50, 100, 200, 300, 400, 500])
    mode_b_pool_reserve = db.Column(db.Integer, default=20, nullable=False)
    session_lifetime_hours = db.Column(db.Integer, default=3, nullable=False)
    daily_reset_hour = db.Column(db.Integer, default=12, nullable=False)

    oss_bucket_name = db.Column(db.String(256), nullable=True)
    oss_endpoint = db.Column(db.String(256), nullable=True)
    oss_domain = db.Column(db.String(256), nullable=True)

    announcement = db.Column(db.Text, nullable=True)
    announcement_enabled = db.Column(db.Boolean, default=False, nullable=False)

    updated_at = db.Column(db.DateTime, default=beijing_now, onupdate=beijing_now, nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    @classmethod
    def get(cls):
        settings = cls.query.filter_by(id=1).first()
        if not settings:
            settings = cls(id=1)
            db.session.add(settings)
            db.session.commit()
        return settings

    def to_dict(self):
        return {
            'registration_enabled': self.registration_enabled,
            'pool_enabled': self.pool_enabled,
            'mode_a_enabled': self.mode_a_enabled,
            'mode_b_enabled': self.mode_b_enabled,
            'mode_b_options': self.mode_b_options or [50, 100, 200, 300, 400, 500],
            'mode_b_pool_reserve': int(self.mode_b_pool_reserve or 20),
            'session_lifetime_hours': self.session_lifetime_hours,
            'daily_reset_hour': self.daily_reset_hour,
            'announcement': self.announcement,
            'announcement_enabled': self.announcement_enabled,
        }
