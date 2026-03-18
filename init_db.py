"""
初始化数据库并创建默认管理员账号
运行方式: python init_db.py
"""
import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from extensions import db
from models.user import User
from models.settings import SystemSettings

app = create_app()

with app.app_context():
    db.create_all()
    print("数据库表创建成功")

    # Create default admin if not exists
    admin = User.query.filter_by(is_admin=True).first()
    if not admin:
        admin = User(username='zucaixu', is_admin=True)
        admin.set_password('zhongdajiang888')
        db.session.add(admin)
        db.session.commit()
        print("默认管理员账号创建成功: zucaixu / zhongdajiang888")
    else:
        print("管理员账号已存在")

    # Ensure system settings row exists
    SystemSettings.get()
    print("系统设置初始化完成")
    print("\n启动服务: python app.py")
