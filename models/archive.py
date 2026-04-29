from datetime import datetime, timedelta

from extensions import db


def beijing_now():
    return datetime.utcnow() + timedelta(hours=8)


class ArchivedLotteryTicket(db.Model):
    __tablename__ = 'archived_lottery_tickets'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    original_ticket_id = db.Column(db.Integer, unique=True, nullable=False, index=True)

    source_file_id = db.Column(db.Integer, nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    raw_content = db.Column(db.Text, nullable=False)

    lottery_type = db.Column(db.String(32), nullable=True, index=True)
    multiplier = db.Column(db.Integer, nullable=True)
    deadline_time = db.Column(db.DateTime, nullable=True, index=True)
    detail_period = db.Column(db.String(32), nullable=True, index=True)
    ticket_amount = db.Column(db.Numeric(12, 2), nullable=True)

    status = db.Column(db.String(20), nullable=False, index=True)

    assigned_user_id = db.Column(db.Integer, nullable=True, index=True)
    assigned_username = db.Column(db.String(64), nullable=True)
    assigned_device_id = db.Column(db.String(64), nullable=True)
    download_filename = db.Column(db.String(512), nullable=True)

    admin_upload_time = db.Column(db.DateTime, nullable=True)
    assigned_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    terminal_at = db.Column(db.DateTime, nullable=True, index=True)

    is_winning = db.Column(db.Boolean, nullable=True)
    winning_gross = db.Column(db.Numeric(12, 2), nullable=True)
    winning_amount = db.Column(db.Numeric(12, 2), nullable=True)
    winning_tax = db.Column(db.Numeric(12, 2), nullable=True)
    winning_image_url = db.Column(db.Text, nullable=True)

    version = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    archived_at = db.Column(db.DateTime, default=beijing_now, nullable=False, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'original_ticket_id': self.original_ticket_id,
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
            'admin_upload_time': self.admin_upload_time.isoformat() if self.admin_upload_time else None,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'terminal_at': self.terminal_at.isoformat() if self.terminal_at else None,
            'is_winning': self.is_winning,
            'winning_gross': float(self.winning_gross) if self.winning_gross else None,
            'winning_amount': float(self.winning_amount) if self.winning_amount else None,
            'winning_tax': float(self.winning_tax) if self.winning_tax else None,
            'winning_image_url': self.winning_image_url,
            'version': self.version,
            'locked_until': self.locked_until.isoformat() if self.locked_until else None,
            'archived_at': self.archived_at.isoformat() if self.archived_at else None,
        }
