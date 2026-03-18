# 项目说明

## 基本信息
- 项目名称：file-hub（原 lottery-platform）
- 技术栈：Flask + SQLite + Redis + Gunicorn + Gevent
- 功能：数据文件管理分发平台，管理员上传TXT文件，用户A/B两种模式接单处理

## 服务器
- 云服务商：阿里云
- 公网IP：121.196.170.150
- 系统：Ubuntu 22.04
- 部署路径：~/lottery-platform（待改名为 ~/file-hub）
- Python虚拟环境：.venv

## 常用命令
```bash
# 连接服务器
ssh root@121.196.170.150

# 启动服务
cd ~/lottery-platform
source .venv/bin/activate
gunicorn -c gunicorn_config.py run:app

# 后台常驻
systemctl start lottery
systemctl status lottery

# 更新代码
git pull origin main
pkill -f gunicorn
gunicorn -c gunicorn_config.py run:app
```

## 账号信息
- 管理员用户名：zucaixu
- 数据库文件：/root/lottery-platform/lottery.db
- 访问地址：http://121.196.170.150:5000

## 环境变量（.env）
```
SECRET_KEY=abc123xyz456def789ghi
DATABASE_URL=sqlite:////root/lottery-platform/lottery.db
REDIS_URL=redis://localhost:6379/0
UPLOAD_FOLDER=/root/lottery-platform/uploads
FLASK_ENV=production
```

## 项目结构
- `routes/` — 路由蓝图（admin, auth, mode_a, mode_b, winning, user, pool, device）
- `services/` — 业务逻辑（ticket_pool, mode_a_service, mode_b_service, file_parser, winning_calc_service）
- `models/` — 数据模型（user, device, file, ticket, winning, settings）
- `tasks/` — 定时任务（scheduler, expire_tickets, clean_sessions, daily_reset）
- `templates/` — 前端模板（base, login, admin/, client/）
- `utils/` — 工具函数（time_utils, filename_parser, winning_calculator, amount_parser）

## 关键设计
- 并发安全：Redis LPOP 原子弹出 + SQLite 单worker，100用户并发无问题
- 基注：1元（utils/winning_calculator.py BASE_STAKE）
- 业务日期分割线：每天12点
- 会话有效期：3小时无活动自动清理
- Gunicorn：单worker + gevent协程模式

## GitHub
- 仓库：https://github.com/qiaosheng125/lottery-platform（待改名为 file-hub）
- 分支：main
