import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError
from config import config
from config import _engine_options
from extensions import db, login_manager, bcrypt, socketio, migrate, init_redis


def apply_runtime_database_config(app):
    db_uri = os.environ.get('DATABASE_URL')
    if not db_uri:
        return

    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = _engine_options(db_uri)


def normalize_sqlite_db_uri(app):
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not db_uri.startswith('sqlite:///') or db_uri.startswith('sqlite:////'):
        return

    relative_path = db_uri[len('sqlite:///'):]
    resolved_path = Path(app.instance_path) / relative_path
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{resolved_path.as_posix()}"
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
    app.logger.warning('Using SQLite database at %s', resolved_path)


def ensure_sqlite_bootstrap(app):
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not db_uri.startswith('sqlite'):
        return

    from models import User, SystemSettings

    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    required_tables = {'users', 'system_settings'}

    if required_tables.issubset(existing_tables):
        return

    app.logger.warning('SQLite database missing core tables; bootstrapping schema automatically')
    try:
        db.create_all()
    except OperationalError as exc:
        db.session.rollback()
        if 'already exists' not in str(exc).lower():
            raise
    SystemSettings.get()

    admin = User.query.filter_by(is_admin=True).first()
    if not admin:
        admin = User(username='zucaixu', is_admin=True)
        admin.set_password('zhongdajiang888')
        db.session.add(admin)
        db.session.commit()
        app.logger.warning('Bootstrapped default admin account: zucaixu')


def ensure_runtime_aux_tables(app):
    from models.archive import ArchivedLotteryTicket

    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    if ArchivedLotteryTicket.__tablename__ not in existing_tables:
        app.logger.warning('Creating missing auxiliary table: %s', ArchivedLotteryTicket.__tablename__)
        ArchivedLotteryTicket.__table__.create(bind=db.engine, checkfirst=True)


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])
    apply_runtime_database_config(app)
    normalize_sqlite_db_uri(app)

    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'images'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'txt'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'archive', 'txt'), exist_ok=True)

    # Serve uploaded images
    from flask import send_from_directory
    @app.route('/uploads/images/<path:filename>')
    def uploaded_image(filename):
        images_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'images')
        return send_from_directory(images_dir, filename)

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

    with app.app_context():
        ensure_sqlite_bootstrap(app)
        ensure_runtime_aux_tables(app)

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

    # Validate the DB-backed session on every authenticated request and refresh last_seen.
    @app.before_request
    def update_last_seen():
        from flask import jsonify, redirect, request as req, session as flask_session, url_for
        from flask_login import logout_user
        from flask_login import current_user as cu
        from utils.time_utils import beijing_now

        def invalidate_current_session():
            flask_session.pop('session_token', None)
            logout_user()
            if req.path.startswith('/api') or req.path == '/auth/heartbeat':
                return jsonify({'success': False, 'error': '会话已失效，请重新登录'}), 401
            return redirect(url_for('auth.login'))

        # Skip static files
        if req.path.startswith('/static'):
            return
        if cu.is_authenticated:
            token = flask_session.get('session_token')
            if not token:
                return invalidate_current_session()

            from models.user import UserSession
            sess = UserSession.query.filter_by(session_token=token).first()
            if not sess:
                return invalidate_current_session()
            if sess.is_expired():
                db.session.delete(sess)
                db.session.commit()
                return invalidate_current_session()

            sess.last_seen = beijing_now()
            from models.settings import SystemSettings
            hours = SystemSettings.get().session_lifetime_hours
            sess.expires_at = sess.last_seen + timedelta(hours=hours)
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
