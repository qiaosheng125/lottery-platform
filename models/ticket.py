from datetime import datetime, timedelta
from extensions import db


def beijing_now():
    return datetime.utcnow() + timedelta(hours=8)


class LotteryTicket(db.Model):
    __tablename__ = 'lottery_tickets'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    source_file_id = db.Column(db.Integer, db.ForeignKey('uploaded_files.id'), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    raw_content = db.Column(db.Text, nullable=False)

    # Parsed fields (from raw_content and filename)
    lottery_type = db.Column(db.String(32), nullable=True, index=True)
    multiplier = db.Column(db.Integer, nullable=True)
    deadline_time = db.Column(db.DateTime, nullable=True, index=True)
    detail_period = db.Column(db.String(32), nullable=True, index=True)
    ticket_amount = db.Column(db.Numeric(12, 2), nullable=True)

    # Status
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    # pending | assigned | completed | revoked | expired

    # Assignment info
    assigned_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    assigned_username = db.Column(db.String(64), nullable=True)  # denormalized
    assigned_device_id = db.Column(db.String(64), nullable=True)
    download_filename = db.Column(db.String(512), nullable=True)

    admin_upload_time = db.Column(db.DateTime, nullable=True)
    assigned_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Winning
    is_winning = db.Column(db.Boolean, nullable=True)  # NULL=uncomputed, True=winning, False=not winning
    predicted_winning_gross = db.Column(db.Numeric(12, 2), nullable=True)
    predicted_winning_amount = db.Column(db.Numeric(12, 2), nullable=True)
    predicted_winning_tax = db.Column(db.Numeric(12, 2), nullable=True)
    winning_gross = db.Column(db.Numeric(12, 2), nullable=True)
    winning_amount = db.Column(db.Numeric(12, 2), nullable=True)
    winning_tax = db.Column(db.Numeric(12, 2), nullable=True)
    winning_image_url = db.Column(db.Text, nullable=True)

    # Concurrency control
    version = db.Column(db.Integer, default=0, nullable=False)  # optimistic lock
    locked_until = db.Column(db.DateTime, nullable=True)  # pessimistic lock expiry

    # Indexes for efficient queries (PostgreSQL-specific partial indexes are defined via migrations)
    __table_args__ = (
        db.Index('idx_tickets_user', 'assigned_user_id', 'status'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'source_file_id': self.source_file_id,
            'line_number': self.line_number,
            'raw_content': self.raw_content,
            'lottery_type': self.lottery_type,
            'multiplier': self.multiplier,
            'deadline_time': self.deadline_time.isoformat() if self.deadline_time else None,
            'detail_period': self.detail_period,
            'ticket_amount': float(self.ticket_amount) if self.ticket_amount else None,
            'status': self.status,
            'assigned_user_id': self.assigned_user_id,
            'assigned_username': self.assigned_username,
            'assigned_device_id': self.assigned_device_id,
            'download_filename': self.download_filename,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'is_winning': self.is_winning,
            'predicted_winning_gross': float(self.predicted_winning_gross) if self.predicted_winning_gross else None,
            'predicted_winning_amount': float(self.predicted_winning_amount) if self.predicted_winning_amount else None,
            'predicted_winning_tax': float(self.predicted_winning_tax) if self.predicted_winning_tax else None,
            'winning_gross': float(self.winning_gross) if self.winning_gross else None,
            'winning_amount': float(self.winning_amount) if self.winning_amount else None,
            'winning_tax': float(self.winning_tax) if self.winning_tax else None,
            'winning_image_url': self.winning_image_url,
        }
