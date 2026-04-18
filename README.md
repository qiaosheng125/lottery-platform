# file-hub

数据文件管理与分发平台。管理员上传 TXT 文件，系统拆分成票据后分发给 A / B 两种模式的设备处理，并支持状态流转、中奖图片上传、结果计算和导出。

## 当前生产结论

- 生产推荐配置：`PostgreSQL + Redis + Gunicorn workers=2`
- 开发环境可用 `SQLite`，但只建议 `workers=1`
- 核心正确性目标：
  - 同一张票不能重复分给多个设备
  - 不能串设备确认
  - 不能残留 `assigned`
  - 文件计数和金额不能漂移

## 2026-04-18 最新更新（上线前统一口径）

- 执行完整回归：`python -m pytest -q` -> `339 passed, 1 skipped, 42 warnings`（约 `19m14s`）
- 当前未发现阻断上线的 P0/P1 新缺陷；42 条告警均为测试代码中的 SQLAlchemy `LegacyAPIWarning`
- 文档口径已统一到“生产部署 / 并发验收 / 变更汇总”三个执行入口
- 并发验收文档已改为 Linux `bash` 主路径示例，避免与 PowerShell 指令混用导致误执行

## 并发安全说明

### SQLite

- 只建议开发/本地使用
- 必须 `workers=1`
- 依赖进程内锁 `_sqlite_assign_lock`
- 如果改成多 worker，SQLite 进程锁会失效

### PostgreSQL

- 生产推荐使用
- 推荐 `workers=2`
- 分票正确性依赖数据库并发控制，而不是单进程锁
- 关键机制：
  - `FOR UPDATE SKIP LOCKED`
  - 条件 `UPDATE ... WHERE status='pending'`
  - 用户级 advisory lock，防止每日上限和 B 模式处理中上限被并发穿透

## 技术栈

- Flask 3.x
- Flask-SocketIO
- SQLAlchemy 2.x
- PostgreSQL
- Redis
- Gunicorn + gevent-websocket
- APScheduler

## 推荐环境变量

参考 `.env.example`：

```env
SECRET_KEY=change-this-to-a-random-secret-key-in-production
FLASK_ENV=production
DATABASE_URL=postgresql://lottery_app:change-this-password@127.0.0.1:5432/lottery_platform
REDIS_URL=redis://127.0.0.1:6379/0
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
DB_POOL_RECYCLE=300
GUNICORN_WORKERS=2
GUNICORN_TIMEOUT=120
GUNICORN_KEEPALIVE=5
UPLOAD_FOLDER=uploads
MAX_CONTENT_LENGTH=16777216
```

## 本地启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python init_db.py
./scripts/run_linux_app.sh
```

Windows 本地开发时可继续使用 `.venv\Scripts\activate`。

## Ubuntu 一键部署

```bash
git clone -b main https://github.com/qiaosheng125/file-hub.git
cd file-hub
chmod +x scripts/deploy_production_ubuntu.sh
APP_DB_PASSWORD='replace-this-password' \
SECRET_KEY_VALUE='replace-with-a-long-random-secret' \
./scripts/deploy_production_ubuntu.sh
```

这个脚本会：

1. 安装 Python、PostgreSQL、Redis、nginx
2. 创建 `.venv`
3. 安装依赖
4. 初始化 PostgreSQL 用户和数据库
5. 更新 `.env`
6. 基于当前 `DATABASE_URL` 初始化 PostgreSQL 数据库
7. 创建并启动 `systemd` 服务

## 压测

严格压测：

```bash
./scripts/run_linux_strict_acceptance.sh
```

阶梯压测：

```bash
./scripts/run_linux_capacity_sweep.sh
```

部署后补跑高压测试（必做）请按部署文档执行：`docs/cloud-deploy-ubuntu-2026-04-09.md` 的“部署后补跑高压测试（必做）”章节。

阶梯压测默认执行：

- `40` 设备
- `60` 设备
- `80` 设备
- `100` 设备

## 压测参数基线（统一口径）

| 场景 | 必备条件 | 默认参数 |
|---|---|---|
| 严格并发验收 | Linux + `gunicorn` + PostgreSQL + Redis | `RUN_LIVE_CONCURRENCY_TESTS=1` `LIVE_TEST_SERVER_MODE=gunicorn` `LIVE_TEST_GUNICORN_WORKERS=2` |
| 阶梯容量压测 | Linux + PostgreSQL + Redis | `40/60/80/100` 设备分档 |
| 本地功能回归 | 任意开发机 | `python -m pytest -q` |

## 文档口径与生效日期

- 当前统一口径生效日期：`2026-04-18`
- 生产部署执行文档：`docs/cloud-deploy-ubuntu-2026-04-09.md`
- 多 worker 并发验收执行文档：`docs/multi-worker-strict-acceptance-2026-04-09.md`
- 变更汇总：`docs/project-change-summary.md`

## 关键文件

- `app.py`：应用工厂
- `config.py`：配置
- `gunicorn_config.py`：Gunicorn 配置
- `init_db.py`：数据库初始化
- `services/ticket_pool.py`：分票核心逻辑
- `services/file_parser.py`：TXT 解析和导入
- `routes/winning.py`：中奖图片与状态流转
- `scripts/deploy_production_ubuntu.sh`：生产一键部署
- `scripts/run_linux_strict_acceptance.sh`：严格压测
- `scripts/run_linux_capacity_sweep.sh`：阶梯压测

## 上线前首要风险点（非唯一）

瞬时登录高峰仍是首要风险。

当前 Linux 实测显示，系统先暴露的是登录/会话超时，而不是核心分票正确性错误。真实业务里应尽量避免大量设备在同一时刻集中重登；同时继续观察导出链路随数据增长的耗时变化，并按计划执行周期性并发活体验收。
