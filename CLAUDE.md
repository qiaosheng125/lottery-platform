# 项目说明

## 基本信息
- 项目名称：file-hub（原 lottery-platform）
- 技术栈：Flask + SQLite + Redis + Gunicorn + Gevent
- 功能：数据文件管理分发平台，管理员上传TXT文件，用户A/B两种模式接单处理

## 服务器
- 云服务商：阿里云
- 公网IP：121.196.170.150
- 系统：Ubuntu 22.04
- 部署路径：~/file-hub
- Python虚拟环境：.venv

## 常用命令
```bash
# 连接服务器
ssh root@121.196.170.150

# 启动服务
cd ~/file-hub
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
- 数据库文件：/root/file-hub/lottery.db
- 访问地址：http://121.196.170.150:5000

## 环境变量（.env）
```
SECRET_KEY=abc123xyz456def789ghi
DATABASE_URL=sqlite:////root/file-hub/lottery.db
REDIS_URL=redis://localhost:6379/0
UPLOAD_FOLDER=/root/file-hub/uploads
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
- 仓库：https://github.com/qiaosheng125/file-hub
- 分支：main

## ⭐ 并发安全（最高优先级，绝不能破坏）

**核心要求：同一张票永远只分配给一个设备，任意数量设备并发接单均不会重复分票（20设备只是测试用例，实际不限数量）。**

### 实现层
- **SQLite（开发）**：`services/ticket_pool.py` 模块级 `_sqlite_assign_lock = BoundedSemaphore(1)`（gevent 协程锁），所有分票操作在锁内串行执行，UPDATE 带 `WHERE status='pending'` 原子条件；持锁期间其他无关请求仍可正常响应
- **PostgreSQL（生产）**：`SELECT FOR UPDATE SKIP LOCKED` 行锁 + 条件 UPDATE

### 关键约束
- Gunicorn **必须** `workers = 1`，多 worker 会破坏 SQLite 进程锁
- B 模式始终保留 20 张给 A 模式缓冲（`RESERVE = 20`，`ticket_pool.py`）
- A 模式每台设备同时只持有 1 张票（点"下一张"才自动完成当前票）

## 本次会话完成的功能（2026-03-20）

1. **并发安全优化** — `services/ticket_pool.py` 将 `threading.Lock` 改为 `gevent.lock.BoundedSemaphore(1)`，持锁期间其他协程可继续响应无关请求，互斥性不变
2. **README 更新** — 替换所有 `lottery-platform` 为 `file-hub`，追加本周开发周报
3. **生成周报文件** — `docs/weekly-report-2026-03-20.md`

1. **修复设备限制检查** — `routes/auth.py` 登录时统计活跃设备数改为过滤 `last_seen` 超时的会话，过期会话不再占用设备名额
2. **会话清理读取管理员设置** — `tasks/clean_sessions.py` 从 `SystemSettings.session_lifetime_hours` 读取超时时长，不再硬编码 3 小时
3. **今日处理清单下载优化** — `routes/user.py` `export_daily()` 空结果不再返回 404，改为 JSON 提示；同时统计未到截止时间的票数，通过 `X-Pending-Count` 响应头传给前端；`dashboard.html` `exportDaily()` 改用 fetch 下载文件，有未到期票时弹 toast 提示

## 上次会话完成的功能（2026-03-19）

1. **B模式保留20张** — `services/ticket_pool.py` `assign_tickets_batch()` 加 `RESERVE=20`，`get_pool_total_pending()` 返回 `max(0, total-20)`
2. **中签记录显示设备** — `routes/winning.py` `my_winning()` 返回 `assigned_device_id/name`，`templates/client/dashboard.html` 中签卡片显示设备 badge
3. **接单页显示设备名** — `dashboard.html` 标题区加 `device-name-badge`，JS 读取本地存储设备名填入
4. **今日各设备出票统计** — `routes/user.py` `daily_stats()` 按 `assigned_device_id` 分组，`dashboard.html` 展示设备统计表（设备数>1时显示）
5. **上传成功自动清空队列** — `templates/admin/upload.html` `doUpload()` 全部成功则清空，有失败则只保留失败项
6. **20设备并发压力测试** — `tests/setup_test_env.py`（初始化测试账号）、`tests/test_concurrent_20devices.py`（10个A模式+10个B模式并发）
