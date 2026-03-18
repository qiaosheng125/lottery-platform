import os
from datetime import timedelta


def _engine_options(db_url: str) -> dict:
    """SQLite doesn't support pool_size etc."""
    if db_url.startswith('sqlite'):
        return {'pool_pre_ping': True}
    return {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 10,
        'max_overflow': 20,
    }


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    _db_url = os.environ.get('DATABASE_URL', 'sqlite:///lottery_dev.db')
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(_db_url)

    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

    # OSS
    OSS_ACCESS_KEY_ID = os.environ.get('OSS_ACCESS_KEY_ID', '')
    OSS_ACCESS_KEY_SECRET = os.environ.get('OSS_ACCESS_KEY_SECRET', '')
    OSS_BUCKET_NAME = os.environ.get('OSS_BUCKET_NAME', '')
    OSS_ENDPOINT = os.environ.get('OSS_ENDPOINT', 'oss-cn-hangzhou.aliyuncs.com')
    OSS_DOMAIN = os.environ.get('OSS_DOMAIN', '')

    # Upload
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))

    # SocketIO - use threading mode on Windows (gevent has socket binding issues)
    SOCKETIO_ASYNC_MODE = 'threading'

    # Session
    SESSION_LIFETIME_HOURS = 3
    DAILY_RESET_HOUR = 12

    # Ticket lock duration (minutes) - prevent network anomaly double-assignment
    TICKET_LOCK_MINUTES = 30


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}

