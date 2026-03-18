from datetime import datetime, timedelta
from extensions import db


def beijing_now():
    return datetime.utcnow() + timedelta(hours=8)


class WinningRecord(db.Model):
    __tablename__ = 'winning_records'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.BigInteger, db.ForeignKey('lottery_tickets.id'), nullable=False, index=True)
    source_file_id = db.Column(db.Integer, db.ForeignKey('uploaded_files.id'), nullable=True)
    detail_period = db.Column(db.String(32), nullable=True, index=True)
    lottery_type = db.Column(db.String(32), nullable=True)
    winning_amount = db.Column(db.Numeric(12, 2), nullable=True)
    winning_image_url = db.Column(db.Text, nullable=True)
    image_oss_key = db.Column(db.String(512), nullable=True)

    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=beijing_now, nullable=False)
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    ticket = db.relationship('LotteryTicket', backref=db.backref('winning_record', uselist=False))
    uploader = db.relationship('User', foreign_keys=[uploaded_by])
    verifier = db.relationship('User', foreign_keys=[verified_by])

    def to_dict(self):
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'source_file_id': self.source_file_id,
            'detail_period': self.detail_period,
            'lottery_type': self.lottery_type,
            'winning_amount': float(self.winning_amount) if self.winning_amount else None,
            'winning_image_url': self.winning_image_url,
            'uploaded_by': self.uploaded_by,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'notes': self.notes,
        }
