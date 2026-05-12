# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

`file-hub` 是一个数据文件管理与分发平台。管理员上传 TXT 文件，系统拆分成票据后分发给 A / B 两种模式的设备处理，支持状态流转、中奖图片上传、结果计算和导出。

技术栈：`Flask 3.x + SQLAlchemy 2.x + Flask-SocketIO + PostgreSQL + Redis + Gunicorn + gevent`

## 常用命令

```bash
# 安装依赖
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 初始化数据库（创建表 + 默认管理员）
python init_db.py

# 开发启动（SQLite，单进程，含 scheduler）
python run.py

# 生产启动（Gunicorn + gevent）
./scripts/run_linux_app.sh

# 仅启动 scheduler（独立进程）
ENABLE_SCHEDULER=1 DISABLE_SCHEDULER=0 ./scripts/run_linux_scheduler.sh

# 运行全部测试
python -m pytest -q

# 运行单个测试文件
python -m pytest tests/test_bug_fixes.py -v

# 运行并发验收测试（需要先启动服务）
RUN_LIVE_CONCURRENCY_TESTS=1 python -m pytest tests/test_concurrent_20devices.py -v -s

# 严格压测 / 阶梯压测
./scripts/run_linux_strict_acceptance.sh
./scripts/run_linux_capacity_sweep.sh
```

## 架构概览

### 应用工厂

`app.py` 中的 `create_app()` 是应用入口。启动时自动执行：
1. 加载配置（`config.py`），支持运行时 `DATABASE_URL` 覆盖
2. 规范化 SQLite URI 路径（`normalize_sqlite_db_uri`）
3. 检查并补齐缺失的表、字段、索引（`ensure_runtime_*` 系列函数）
4. 如果是 SQLite，bootstrap 默认管理员和系统设置
5. 注册所有 blueprint 和 SocketIO 事件处理器
6. 通过 `before_request` 钩子验证 DB-backed session 并刷新 `last_seen`
7. 决定是否启动 APScheduler（`should_start_scheduler`）

### 双数据库路径设计

整个代码库围绕 **SQLite（开发） vs PostgreSQL（生产）** 两条执行路径设计：

- **SQLite 路径**：用 `_sqlite_assign_lock`（`gevent.BoundedSemaphore`）串行化关键操作。只适合 `workers=1`。
- **PostgreSQL 路径**：依赖数据库级并发控制，不依赖单进程锁。

关键判断函数：`_is_postgres()` 检查 `DATABASE_URL`。

### 并发安全机制（核心）

`services/ticket_pool.py` 包含最关键的并发安全逻辑：

1. **`SELECT ... FOR UPDATE SKIP LOCKED`**：原子获取一张 pending 票，跳过已被其他事务锁定的行
2. **条件 `UPDATE ... WHERE status='pending'`**：只有当前状态仍为 pending 的票才会被分配，防止重复分配
3. **`pg_advisory_xact_lock`（ns=1001, user_id）**：串行化单用户的每日上限检查，防止 B 模式处理中上限被并发穿透
4. **`pg_advisory_xact_lock`（ns=1002, lock_key）**：B 模式保留票计算和文件上传去重的全局串行化
5. **乐观锁**：`LotteryTicket.version` 字段，每次更新 +1
6. **悲观锁**：`locked_until` 过期时间，防止网络异常导致票长时间锁定

### 票据生命周期

```
pending → assigned → completed
                   → expired
pending → revoked
assigned → revoked
pending → expired（超过 deadline_time）
```

文件状态 counter 是反规范化的（`pending_count`、`assigned_count`、`completed_count`），每次票状态变更时同步更新。

### 两种工作模式

- **Mode A**（`routes/mode_a.py`, `services/mode_a_service.py`）：设备每次请求一张票，由服务器决定分配哪张。支持数量提示弹窗和倒计时确认。
- **Mode B**（`routes/mode_b.py`, `services/mode_b_service.py`）：设备批量下载指定张数的票，服务器按截止时间升序选择单一彩种分配。支持处理中上限、每日上限、彩种屏蔽。

### 目录结构

| 目录 | 职责 |
|------|------|
| `models/` | SQLAlchemy 模型：User, LotteryTicket, UploadedFile, WinningRecord, MatchResult, DeviceRegistry, SystemSettings 等 |
| `routes/` | Flask Blueprint：auth, admin, pool, mode_a, mode_b, winning, device, user |
| `services/` | 核心业务逻辑：ticket_pool（分票）、file_parser（TXT 解析）、mode_a_service、mode_b_service、winning_calc_service、ticket_recycle_service、notify_service（WebSocket 推送） |
| `tasks/` | APScheduler 定时任务：expire_tickets（每分钟）、clean_sessions（15 分钟）、daily_reset（每日 12:00）、archive（每周一凌晨） |
| `sockets/` | SocketIO 事件处理器：pool_events、admin_events |
| `utils/` | 工具函数：filename_parser、amount_parser、time_utils、winning_calculator、image_upload |
| `static/js/` | 前端 JS：app.js（主逻辑）、socket_client.js（WebSocket 客户端）、mode_a.js、mode_b.js、ticket_renderer.js |
| `templates/` | Jinja2 模板：admin（dashboard、upload、winning、users、settings、recycle）、client（dashboard） |
| `scripts/` | 运维脚本：部署、压测、启动 |
| `tests/` | pytest 测试：test_bug_fixes.py（功能回归）、test_concurrent_20devices.py（并发验收） |

### 关键设计决策

- **Redis 作为可选项**：`init_redis()` 失败不阻断启动，系统降级为纯 DB 模式。`pool:pending` 列表用于加速分票查询。
- **Session 管理**：使用 DB-backed session（`UserSession`），而非 Flask 默认的 cookie session。每次请求通过 `before_request` 验证 token 有效性并刷新过期时间。
- **Scheduler 多 worker 安全**：PostgreSQL 下用 `pg_try_advisory_xact_lock` 确保同一 job 不会在多个 gunicorn worker 中并发执行。
- **文件上传去重**：同一业务日（12:00-次日 12:00）内不允许上传同名文件或相同 internal_code 的文件，通过 advisory lock 串行化检查。
- **业务日**：以每日 12:00 为分界（`DAILY_RESET_HOUR=12`），daily_reset 任务也在此刻执行。

## 并发安全结论

- SQLite 只适合开发，必须 `workers=1`
- PostgreSQL + Redis 是生产推荐方案，推荐 `workers=2`
- 核心正确性依赖：`FOR UPDATE SKIP LOCKED` + 条件 UPDATE + advisory lock
- 压力测试显示系统先暴露的是登录/会话超时，不是核心分票正确性问题
