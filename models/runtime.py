from extensions import db
from utils.time_utils import beijing_now


class RuntimeStatus(db.Model):
    __tablename__ = 'runtime_statuses'

    service_name = db.Column(db.String(64), primary_key=True)
    status = db.Column(db.String(32), nullable=False, default='unknown')
    payload = db.Column(db.JSON, nullable=True)
    updated_at = db.Column(db.DateTime, default=beijing_now, nullable=False)

    @classmethod
    def upsert(cls, service_name: str, status: str, payload=None):
        record = db.session.get(cls, service_name)
        if record is None:
            record = cls(service_name=service_name)
            db.session.add(record)

        record.status = status
        record.payload = payload or {}
        record.updated_at = beijing_now()
        db.session.commit()
        return record
