from datetime import datetime, timedelta
from extensions import db


def beijing_now():
    return datetime.utcnow() + timedelta(hours=8)


class UploadedFile(db.Model):
    __tablename__ = 'uploaded_files'

    id = db.Column(db.Integer, primary_key=True)
    display_id = db.Column(db.String(32), nullable=True)  # e.g. "2024/03/18-01"
    original_filename = db.Column(db.String(512), nullable=False)
    stored_filename = db.Column(db.String(512), nullable=False)

    # Parsed from filename
    identifier = db.Column(db.String(64), nullable=True)    # e.g. "军" or "岩"
    internal_code = db.Column(db.String(32), nullable=True)  # e.g. "V58"
    lottery_type = db.Column(db.String(32), nullable=True)   # e.g. "胜平负"
    multiplier = db.Column(db.Integer, nullable=True)         # e.g. 2
    declared_amount = db.Column(db.Numeric(12, 2), nullable=True)
    declared_count = db.Column(db.Integer, nullable=True)
    deadline_time = db.Column(db.DateTime, nullable=True)    # full datetime with date resolved
    detail_period = db.Column(db.String(32), nullable=True)  # e.g. "26034"

    status = db.Column(db.String(20), default='active', nullable=False, index=True)
    # active | revoked | exhausted | expired

    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=beijing_now, nullable=False)
    revoked_at = db.Column(db.DateTime, nullable=True)
    revoked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Counters (denormalized for performance)
    total_tickets = db.Column(db.Integer, default=0, nullable=False)
    pending_count = db.Column(db.Integer, default=0, nullable=False)
    assigned_count = db.Column(db.Integer, default=0, nullable=False)
    completed_count = db.Column(db.Integer, default=0, nullable=False)
    actual_total_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    # Relationships
    tickets = db.relationship('LotteryTicket', backref='source_file', lazy='dynamic',
                               foreign_keys='LotteryTicket.source_file_id')
    uploader = db.relationship('User', foreign_keys=[uploaded_by], backref='uploaded_files')
    revoker = db.relationship('User', foreign_keys=[revoked_by])

    def derived_status(self, now=None):
        now = now or beijing_now()
        if self.status == 'revoked':
            return 'revoked'
        if self.total_tickets > 0 and self.completed_count >= self.total_tickets:
            return 'exhausted'
        if self.pending_count == 0 and self.assigned_count == 0 and self.deadline_time and self.deadline_time <= now:
            return 'expired'
        return 'active'

    def to_dict(self):
        current_status = self.derived_status()
        return {
            'id': self.id,
            'display_id': self.display_id,
            'original_filename': self.original_filename,
            'identifier': self.identifier,
            'internal_code': self.internal_code,
            'lottery_type': self.lottery_type,
            'multiplier': self.multiplier,
            'declared_amount': float(self.declared_amount) if self.declared_amount else None,
            'declared_count': self.declared_count,
            'deadline_time': self.deadline_time.isoformat() if self.deadline_time else None,
            'detail_period': self.detail_period,
            'status': current_status,
            'uploaded_by': self.uploaded_by,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'total_tickets': self.total_tickets,
            'pending_count': self.pending_count,
            'assigned_count': self.assigned_count,
            'completed_count': self.completed_count,
            'actual_total_amount': float(self.actual_total_amount) if self.actual_total_amount else 0,
        }
