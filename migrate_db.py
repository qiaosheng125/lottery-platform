import sqlite3
import os

db_files = [
    'lottery.db',
    'lottery_dev.db',
    'instance/lottery.db',
]

for db_file in db_files:
    if not os.path.exists(db_file):
        print(f'{db_file}: not found')
        continue
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        print(f'{db_file}: {tables}')
        
        if 'users' in tables:
            cursor.execute("PRAGMA table_info(users)")
            columns = [r[1] for r in cursor.fetchall()]
            print(f'  users columns: {columns}')
            
            if 'blocked_lottery_types' not in columns:
                cursor.execute('ALTER TABLE users ADD COLUMN blocked_lottery_types TEXT')
                conn.commit()
                print(f'  Added blocked_lottery_types column')
            else:
                print(f'  blocked_lottery_types already exists')
        conn.close()
    except Exception as e:
        print(f'{db_file}: error - {e}')
