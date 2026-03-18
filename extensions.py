import redis
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_socketio import SocketIO
from flask_migrate import Migrate

db = SQLAlchemy()
login_manager = LoginManager()
bcrypt = Bcrypt()
socketio = SocketIO(async_mode='threading')
migrate = Migrate()
redis_client = None


def init_redis(app):
    global redis_client
    try:
        client = redis.from_url(
            app.config['REDIS_URL'],
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()  # test connection
        redis_client = client
        app.logger.info("Redis connected")
    except Exception as e:
        redis_client = None
        app.logger.warning(f"Redis unavailable (fallback to DB-only mode): {e}")
    return redis_client
