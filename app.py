import os
from flask import Flask
from dotenv import load_dotenv
from config import config
from extensions import db, login_manager, bcrypt, socketio, migrate, init_redis

load_dotenv()


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(
        app,
        async_mode=app.config.get('SOCKETIO_ASYNC_MODE', 'gevent'),
        cors_allowed_origins='*',
        logger=False,
        engineio_logger=False,
    )
    init_redis(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = '请先登录'
    login_manager.login_message_category = 'warning'

    # Register blueprints
    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.pool import pool_bp
    from routes.mode_a import mode_a_bp
    from routes.mode_b import mode_b_bp
    from routes.winning import winning_bp
    from routes.device import device_bp
    from routes.user import user_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(pool_bp, url_prefix='/api/pool')
    app.register_blueprint(mode_a_bp, url_prefix='/api/mode-a')
    app.register_blueprint(mode_b_bp, url_prefix='/api/mode-b')
    app.register_blueprint(winning_bp, url_prefix='/api/winning')
    app.register_blueprint(device_bp, url_prefix='/api/device')
    app.register_blueprint(user_bp, url_prefix='/api/user')

    # Register SocketIO event handlers
    from sockets import pool_events, admin_events  # noqa: F401

    # Update last_seen on every authenticated request
    @app.before_request
    def update_last_seen():
        from flask import session as flask_session, request as req
        from flask_login import current_user as cu
        # Skip static files
        if req.path.startswith('/static'):
            return
        if cu.is_authenticated:
            token = flask_session.get('session_token')
            if token:
                from models.user import UserSession
                sess = UserSession.query.filter_by(session_token=token).first()
                if sess:
                    sess.touch()
                    try:
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

    # Register main index route
    from flask import redirect, url_for
    from flask_login import current_user

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            if current_user.is_admin:
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('user.dashboard'))
        return redirect(url_for('auth.login'))

    # Start scheduler
    from tasks.scheduler import start_scheduler
    start_scheduler(app)

    return app


if __name__ == '__main__':
    app = create_app()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
