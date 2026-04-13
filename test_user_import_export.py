"""
测试用户导入导出功能
"""
from app import create_app
from extensions import db
from models.user import User
import os

app = create_app()

with app.app_context():
    # 创建几个测试用户
    test_users = [
        {'username': 'user_a1', 'password': '123456', 'client_mode': 'mode_a', 'max_devices': 2},
        {'username': 'user_a2', 'password': '123456', 'client_mode': 'mode_a', 'max_devices': 3},
        {'username': 'user_b1', 'password': '123456', 'client_mode': 'mode_b', 'max_devices': 1,
         'max_processing_b_mode': 500, 'daily_ticket_limit': 1000},
        {'username': 'user_b2', 'password': '123456', 'client_mode': 'mode_b', 'max_devices': 2,
         'desktop_only_b_mode': False},
    ]

    for user_data in test_users:
        existing = User.query.filter_by(username=user_data['username']).first()
        if not existing:
            user = User(**{k: v for k, v in user_data.items() if k != 'password'})
            user.set_password(user_data['password'])
            db.session.add(user)
            print(f'创建测试用户: {user_data["username"]}')
        else:
            print(f'用户已存在: {user_data["username"]}')

    db.session.commit()
    print('\n测试用户创建完成！')

    # 显示所有非管理员用户
    users = User.query.filter_by(is_admin=False).all()
    print(f'\n当前共有 {len(users)} 个非管理员用户：')
    for u in users:
        print(f'  - {u.username}: {u.client_mode}, 设备数={u.max_devices}, B模式上限={u.max_processing_b_mode}, 每日上限={u.daily_ticket_limit}, 仅桌面端={u.desktop_only_b_mode}')
