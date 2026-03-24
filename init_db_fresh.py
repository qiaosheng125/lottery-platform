"""
重新初始化数据库（删除旧数据库并创建新的）
运行方式: python init_db_fresh.py
"""
import os
import sys
from dotenv import load_dotenv
load_dotenv()

# 删除旧的数据库文件
db_file = 'lottery_dev.db'
if os.path.exists(db_file):
    try:
        os.remove(db_file)
        print(f"[OK] 已删除旧数据库文件: {db_file}")
    except Exception as e:
        print(f"[ERROR] 无法删除数据库文件: {e}")
        print("请手动删除 lottery_dev.db 文件后重试")
        sys.exit(1)

from app import create_app
from extensions import db
from models.user import User
from models.settings import SystemSettings

app = create_app()

with app.app_context():
    db.create_all()
    print("[OK] 数据库表创建成功")

    # Create default admin
    admin = User(username='zucaixu', is_admin=True)
    admin.set_password('zhongdajiang888')
    db.session.add(admin)
    db.session.commit()
    print("[OK] 默认管理员账号创建成功: zucaixu / zhongdajiang888")

    # Ensure system settings row exists
    SystemSettings.get()
    print("[OK] 系统设置初始化完成")
    print("\n[INFO] 启动服务: python run.py")
