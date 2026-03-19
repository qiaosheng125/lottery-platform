"""
测试环境初始化脚本：
  - 创建 1个 mode_a 测试账号（10设备并发用）
  - 创建 1个 mode_b 测试账号（10设备并发用）
  - 上传桌面测试文件夹里的所有 TXT 文件到票池
  - 打印账号信息供压力测试使用

运行方式：
  cd Desktop/file-hub
  python tests/setup_test_env.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from extensions import db
from models.user import User
from models.settings import SystemSettings

TEST_USER_A = 'test_mode_a'
TEST_USER_B = 'test_mode_b'
TEST_PASS   = 'test123456'

TEST_FILES_DIR = os.path.expanduser('~/Desktop/测试')

app = create_app()

with app.app_context():
    db.create_all()

    # ── 创建 mode_a 账号 ──────────────────────────────────────────
    user_a = User.query.filter_by(username=TEST_USER_A).first()
    if not user_a:
        user_a = User(username=TEST_USER_A, client_mode='mode_a', max_devices=100, can_receive=True)
        user_a.set_password(TEST_PASS)
        db.session.add(user_a)
        print(f'创建账号: {TEST_USER_A} / {TEST_PASS}  (mode_a, max_devices=100)')
    else:
        user_a.max_devices = 100
        user_a.can_receive = True
        print(f'账号已存在，更新: {TEST_USER_A}')

    # ── 创建 mode_b 账号 ──────────────────────────────────────────
    user_b = User.query.filter_by(username=TEST_USER_B).first()
    if not user_b:
        user_b = User(username=TEST_USER_B, client_mode='mode_b', max_devices=100, can_receive=True)
        user_b.set_password(TEST_PASS)
        db.session.add(user_b)
        print(f'创建账号: {TEST_USER_B} / {TEST_PASS}  (mode_b, max_devices=100)')
    else:
        user_b.max_devices = 100
        user_b.can_receive = True
        print(f'账号已存在，更新: {TEST_USER_B}')

    db.session.commit()

    # ── 清理旧 session（避免设备数超限）──────────────────────────
    from models.user import UserSession
    for u in [user_a, user_b]:
        deleted = UserSession.query.filter_by(user_id=u.id).delete()
        if deleted:
            print(f'清理 {u.username} 旧session: {deleted} 条')
    db.session.commit()

    # ── 确保系统设置允许接单 ──────────────────────────────────────
    settings = SystemSettings.get()
    settings.mode_a_enabled = True
    settings.mode_b_enabled = True
    settings.pool_enabled = True
    db.session.commit()
    print('系统设置：mode_a/mode_b/pool 均已开启')

    # ── 上传测试文件 ──────────────────────────────────────────────
    if not os.path.isdir(TEST_FILES_DIR):
        print(f'测试文件夹不存在: {TEST_FILES_DIR}，跳过上传')
    else:
        txt_files = [f for f in os.listdir(TEST_FILES_DIR) if f.endswith('.txt')]
        if not txt_files:
            print('测试文件夹中没有 TXT 文件')
        else:
            from services.file_parser import process_uploaded_file
            from werkzeug.datastructures import FileStorage
            import io
            admin = User.query.filter_by(is_admin=True).first()
            if not admin:
                print('警告：没有管理员账号，跳过文件上传')
            else:
                uploaded = 0
                for fname in txt_files:
                    fpath = os.path.join(TEST_FILES_DIR, fname)
                    with open(fpath, 'rb') as f:
                        content = f.read()
                    try:
                        fs = FileStorage(stream=io.BytesIO(content), filename=fname, content_type='text/plain')
                        result = process_uploaded_file(fs, uploader_id=admin.id)
                        if result.get('success'):
                            print(f'  上传成功: {fname}  ({result.get("ticket_count", 0)} 张票)')
                            uploaded += 1
                        else:
                            print(f'  上传失败: {fname}  {result.get("error")}')
                    except Exception as e:
                        print(f'  上传异常: {fname}  {e}')
                print(f'共上传 {uploaded}/{len(txt_files)} 个文件')

    # ── 打印票池状态 ──────────────────────────────────────────────
    from services.ticket_pool import get_pool_status, get_pool_total_pending
    pool = get_pool_status()
    b_available = get_pool_total_pending()
    print(f'\n票池状态:')
    print(f'  总 pending: {pool["total_pending"]} 张')
    print(f'  B模式可用:  {b_available} 张（已扣除保留20张）')
    print(f'  已分配:     {pool["assigned"]} 张')
    print()
    print('环境准备完成，可以运行压力测试：')
    print('  python -m pytest tests/test_concurrent_20devices.py -v -s')
