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
    assigned_device_name = db.Column(db.String(128), nullable=True)  # denormalized

    admin_upload_time = db.Column(db.DateTime, nullable=True)
    assigned_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Winning
    is_winning = db.Column(db.Boolean, nullable=True)  # NULL=未计算, True=中奖, False=未中
    winning_gross = db.Column(db.Numeric(12, 2), nullable=True)   # 税前金额
    winning_amount = db.Column(db.Numeric(12, 2), nullable=True)  # 税后金额（实得）
    winning_tax = db.Column(db.Numeric(12, 2), nullable=True)     # 扣税金额
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
            'assigned_device_name': self.assigned_device_name,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'is_winning': self.is_winning,
            'winning_gross': float(self.winning_gross) if self.winning_gross else None,
            'winning_amount': float(self.winning_amount) if self.winning_amount else None,
            'winning_tax': float(self.winning_tax) if self.winning_tax else None,
            'winning_image_url': self.winning_image_url,
        }
