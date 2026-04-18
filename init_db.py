"""
Initialize schema and seed the default admin/settings rows for the database
pointed to by DATABASE_URL.

Run with:
    python init_db.py
"""

import os

from dotenv import load_dotenv
from sqlalchemy.engine.url import make_url

load_dotenv()
os.environ.setdefault("DISABLE_SCHEDULER", "1")

from app import create_app
from extensions import db
import models  # noqa: F401
from models.settings import SystemSettings
from models.user import User


def describe_database(uri: str) -> str:
    url = make_url(uri)
    if url.drivername.startswith("postgresql") or url.drivername.startswith("postgres"):
        host = url.host or "localhost"
        port = url.port or 5432
        database = url.database or ""
        return f"PostgreSQL {host}:{port}/{database}"
    if url.drivername.startswith("sqlite"):
        return f"SQLite {url.database or ''}"
    return uri


app = create_app()

with app.app_context():
    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    print(f"[INFO] 初始化数据库: {describe_database(db_uri)}")

    db.create_all()
    print("[OK] 数据库表创建完成")

    admin = User.query.filter_by(is_admin=True).first()
    if not admin:
        admin = User(username="zucaixu", is_admin=True)
        admin.set_password("zhongdajiang888")
        db.session.add(admin)
        db.session.commit()
        print("[OK] 默认管理员已创建: zucaixu / zhongdajiang888")
    else:
        print(f"[INFO] 默认管理员已存在: {admin.username}")

    SystemSettings.get()
    print("[OK] 系统设置初始化完成")
