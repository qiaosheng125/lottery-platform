"""
测试用户导出导入功能（包含密码哈希）
"""
from app import create_app
from extensions import db
from models.user import User
import requests

app = create_app()

print("=" * 60)
print("测试用户导出导入功能")
print("=" * 60)

with app.app_context():
    # 显示当前用户
    users = User.query.filter_by(is_admin=False).all()
    print(f"\n当前共有 {len(users)} 个非管理员用户：")
    for u in users:
        print(f"  - {u.username}: 密码哈希前10位={u.password_hash[:10]}...")

    print("\n测试说明：")
    print("1. 导出的文件包含加密后的密码哈希")
    print("2. 导入时会自动识别密码哈希并直接使用")
    print("3. 这样导出的文件可以直接导入，密码保持不变")
    print("\n请手动测试：")
    print("1. 访问 http://localhost:5000/admin/users")
    print("2. 点击'导出用户'按钮下载 XLSX 文件")
    print("3. 打开文件查看密码列（应该是加密后的哈希值）")
    print("4. 修改用户名（避免重复），然后点击'导入用户'上传文件")
    print("5. 导入成功后，新用户应该可以用原密码登录")
