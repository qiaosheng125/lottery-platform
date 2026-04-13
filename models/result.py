from datetime import datetime, timedelta
from extensions import db


def beijing_now():
    return datetime.utcnow() + timedelta(hours=8)


class ResultFile(db.Model):
    __tablename__ = 'result_files'

    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(512), nullable=False)
    stored_filename = db.Column(db.String(512), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=beijing_now, nullable=False)
    periods_count = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(20), default='parsed', nullable=False)  # parsed | error
    parse_error = db.Column(db.Text, nullable=True)

    uploader = db.relationship('User', foreign_keys=[uploaded_by])
    match_results = db.relationship('MatchResult', backref='result_file', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'original_filename': self.original_filename,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'periods_count': self.periods_count,
            'status': self.status,
            'parse_error': self.parse_error,
        }


class MatchResult(db.Model):
    __tablename__ = 'match_results'

    id = db.Column(db.Integer, primary_key=True)
    detail_period = db.Column(db.String(32), nullable=False, index=True)
    lottery_type = db.Column(db.String(32), nullable=True)  # NULL means applies to all types
    result_data = db.Column(db.JSON, nullable=False)
    # Structure: {"61": {"SPF": {"result": "3", "sp": 1.85}, "CBF": {...}, ...}, "62": {...}}

    result_file_id = db.Column(db.Integer, db.ForeignKey('result_files.id'), nullable=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=beijing_now, nullable=False)

    calc_status = db.Column(db.String(20), default='pending', nullable=False)
    # pending | processing | done | error
    calc_started_at = db.Column(db.DateTime, nullable=True)
    calc_finished_at = db.Column(db.DateTime, nullable=True)

    tickets_total = db.Column(db.Integer, default=0, nullable=False)
    tickets_winning = db.Column(db.Integer, default=0, nullable=False)
    total_winning_amount = db.Column(db.Numeric(14, 2), default=0, nullable=False)

    uploader = db.relationship('User', foreign_keys=[uploaded_by])

    # No unique constraint on detail_period — multiple uploads allowed, latest wins

    def to_dict(self):
        return {
            'id': self.id,
            'detail_period': self.detail_period,
            'result_data': self.result_data,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'calc_status': self.calc_status,
            'tickets_total': self.tickets_total,
            'tickets_winning': self.tickets_winning,
            'total_winning_amount': float(self.total_winning_amount) if self.total_winning_amount else 0,
        }
