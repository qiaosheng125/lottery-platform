import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from sqlalchemy import inspect, text
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


def ensure_model_metadata_loaded():
    # Import every model module before create_all(), otherwise fresh databases
    # can miss tables that have not been imported into db.metadata yet.
    import models  # noqa: F401


def ensure_sqlite_bootstrap(app):
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not db_uri.startswith('sqlite'):
        return

    from models import User, SystemSettings

    ensure_model_metadata_loaded()
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    required_tables = set(db.metadata.tables.keys())

    if required_tables.issubset(existing_tables):
        return

    missing_tables = sorted(required_tables - existing_tables)
    app.logger.warning(
        'SQLite database missing tables %s; bootstrapping schema automatically',
        ', '.join(missing_tables),
    )
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
    ensure_model_metadata_loaded()
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    for table_name, table in db.metadata.tables.items():
        if table_name in existing_tables:
            continue
        app.logger.warning('Creating missing runtime table: %s', table_name)
        table.create(bind=db.engine, checkfirst=True)


def ensure_runtime_columns(app):
    ensure_model_metadata_loaded()
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    column_specs = {
        'users': {
            'client_mode': "VARCHAR(10) NOT NULL DEFAULT 'mode_a'",
            'max_devices': 'INTEGER NOT NULL DEFAULT 1',
            'max_processing_b_mode': 'INTEGER',
            'daily_ticket_limit': 'INTEGER',
            'blocked_lottery_types': 'TEXT',
            'is_active': 'BOOLEAN NOT NULL DEFAULT TRUE',
            'can_receive': 'BOOLEAN NOT NULL DEFAULT TRUE',
            'desktop_only_b_mode': 'BOOLEAN NOT NULL DEFAULT TRUE',
            'updated_at': 'TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP',
        },
        'result_files': {
            'upload_kind': "VARCHAR(20) NOT NULL DEFAULT 'final'",
        },
        'match_results': {
            'predicted_total_winning_amount': "NUMERIC(14, 2) NOT NULL DEFAULT 0",
        },
        'lottery_tickets': {
            'download_filename': 'VARCHAR(512)',
            'predicted_winning_gross': 'NUMERIC(12, 2)',
            'predicted_winning_amount': 'NUMERIC(12, 2)',
            'predicted_winning_tax': 'NUMERIC(12, 2)',
        },
        'archived_lottery_tickets': {
            'download_filename': 'VARCHAR(512)',
        },
        'system_settings': {
            'mode_b_pool_reserve': 'INTEGER NOT NULL DEFAULT 20',
        },
    }

    with db.engine.begin() as conn:
        for table_name, specs in column_specs.items():
            if table_name not in existing_tables:
                continue
            existing = {column['name'] for column in inspector.get_columns(table_name)}
            for column_name, ddl in specs.items():
                if column_name in existing:
                    continue
                app.logger.warning('Adding missing runtime column %s.%s', table_name, column_name)
                conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}'))


def ensure_runtime_indexes(app):
    ensure_model_metadata_loaded()
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    if 'uploaded_files' not in existing_tables:
        return

    existing_indexes = {idx['name'] for idx in inspector.get_indexes('uploaded_files')}
    if 'idx_uploaded_files_uploaded_at' in existing_indexes:
        return

    dialect = db.engine.dialect.name
    if dialect not in {'sqlite', 'postgresql'}:
        app.logger.warning(
            'Skipping automatic index creation for unsupported dialect %s: idx_uploaded_files_uploaded_at',
            dialect,
        )
        return

    app.logger.warning('Adding missing runtime index uploaded_files.uploaded_at')
    statement = 'CREATE INDEX IF NOT EXISTS idx_uploaded_files_uploaded_at ON uploaded_files (uploaded_at)'
    if dialect == 'postgresql':
        with db.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
            conn.execute(text(statement))
    else:
        with db.engine.begin() as conn:
            conn.execute(text(statement))


def should_start_scheduler(config_name: str = None) -> bool:
    # Explicit disable always wins.
    if os.environ.get('DISABLE_SCHEDULER', '0') == '1':
        return False

    # Explicit enable is for dedicated scheduler processes.
    if os.environ.get('ENABLE_SCHEDULER', '0') == '1':
        return True

    # Safe default: do not start scheduler in production web processes.
    # Prefer FLASK_ENV when set, otherwise fall back to app config name.
    effective_env = os.environ.get('FLASK_ENV') or config_name or 'development'
    return effective_env != 'production'


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
        ensure_runtime_columns(app)
        ensure_runtime_indexes(app)

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
            if req.path.startswith('/api') or req.path.startswith('/admin/api') or req.path == '/auth/heartbeat':
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
            if not sess or not cu.is_active:
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

    # Start scheduler unless a bootstrap/one-off task disables it explicitly.
    if should_start_scheduler(config_name):
        from tasks.scheduler import start_scheduler
        start_scheduler(app)

    return app


if __name__ == '__main__':
    app = create_app()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
