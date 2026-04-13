"""
数据库迁移脚本：为 users 表添加 desktop_only_b_mode 字段
用于控制 B 模式用户是否仅限桌面端接单
"""
import os
import sys

# 支持 SQLite 和 PostgreSQL
def migrate_sqlite(db_file):
    import sqlite3
    if not os.path.exists(db_file):
        print(f'{db_file}: not found')
        return False

    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        if not cursor.fetchone():
            print(f'{db_file}: users table not found')
            conn.close()
            return False

        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(users)")
        columns = [r[1] for r in cursor.fetchall()]

        if 'desktop_only_b_mode' in columns:
            print(f'{db_file}: desktop_only_b_mode already exists')
            conn.close()
            return True

        # 添加新字段，默认值为 1 (True)
        cursor.execute('ALTER TABLE users ADD COLUMN desktop_only_b_mode BOOLEAN NOT NULL DEFAULT 1')
        conn.commit()
        print(f'{db_file}: Added desktop_only_b_mode column (default=True)')
        conn.close()
        return True
    except Exception as e:
        print(f'{db_file}: error - {e}')
        return False


def migrate_postgresql(db_uri):
    try:
        import psycopg2
        from urllib.parse import urlparse

        parsed = urlparse(db_uri)
        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=parsed.path.lstrip('/'),
            user=parsed.username,
            password=parsed.password
        )
        cursor = conn.cursor()

        # 检查字段是否已存在
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='users' AND column_name='desktop_only_b_mode'
        """)

        if cursor.fetchone():
            print('PostgreSQL: desktop_only_b_mode already exists')
            conn.close()
            return True

        # 添加新字段，默认值为 true
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN desktop_only_b_mode BOOLEAN NOT NULL DEFAULT true
        """)
        conn.commit()
        print('PostgreSQL: Added desktop_only_b_mode column (default=true)')
        conn.close()
        return True
    except Exception as e:
        print(f'PostgreSQL: error - {e}')
        return False


if __name__ == '__main__':
    # 尝试从环境变量或配置文件获取数据库配置
    db_uri = os.environ.get('DATABASE_URL') or os.environ.get('SQLALCHEMY_DATABASE_URI')

    if db_uri:
        if db_uri.startswith('sqlite:///'):
            db_file = db_uri.replace('sqlite:///', '')
            success = migrate_sqlite(db_file)
        elif db_uri.startswith('postgresql://') or db_uri.startswith('postgres://'):
            success = migrate_postgresql(db_uri)
        else:
            print(f'Unsupported database type: {db_uri.split("://")[0]}')
            success = False
    else:
        # 默认尝试 SQLite 文件
        db_files = [
            'lottery.db',
            'lottery_dev.db',
            'instance/lottery.db',
        ]
        success = False
        for db_file in db_files:
            if migrate_sqlite(db_file):
                success = True

    sys.exit(0 if success else 1)
