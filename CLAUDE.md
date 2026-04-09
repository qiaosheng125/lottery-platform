# 项目说明

## 基本信息

- 项目名称：`file-hub`
- 当前推荐生产栈：`Flask + PostgreSQL + Redis + Gunicorn + gevent`
- 当前推荐生产部署：`workers=2`
- 开发环境可用 `SQLite`，但仅限 `workers=1`

## 当前生产建议

- 生产数据库：`PostgreSQL`
- 缓存/共享池：`Redis`
- Gunicorn：`workers=2`
- 数据库池：
  - `DB_POOL_SIZE=5`
  - `DB_MAX_OVERFLOW=5`
  - `DB_POOL_RECYCLE=300`

## 常用命令

```bash
# 更新代码
cd ~/file-hub
git pull origin main

# 启动服务
cd ~/file-hub
source .venv/bin/activate
./scripts/run_linux_app.sh

# 一键部署
cd ~/file-hub
chmod +x scripts/deploy_production_ubuntu.sh
APP_DB_PASSWORD='replace-this-password' \
SECRET_KEY_VALUE='replace-with-a-long-random-secret' \
./scripts/deploy_production_ubuntu.sh

# 严格压测
./scripts/run_linux_strict_acceptance.sh

# 阶梯压测
./scripts/run_linux_capacity_sweep.sh
```

## 并发安全结论

### SQLite

- 只适合开发/本地
- 必须 `workers=1`
- 依赖 `services/ticket_pool.py` 里的进程内锁
- 任何“生产也用 SQLite + 多 worker”的做法都不安全

### PostgreSQL + Redis

- 这是当前生产推荐方案
- 推荐 `workers=2`
- 正确性依赖数据库锁，不依赖单 worker
- 关键点：
  - `FOR UPDATE SKIP LOCKED`
  - 条件更新防重复抢票
  - 用户级 advisory lock 防止每日上限 / B 模式处理中上限被并发穿透

## 2026-04-09 最近更新

1. 修复 PostgreSQL 空库首次启动时 `system_settings` 未建表导致初始化失败的问题
2. 新增 Ubuntu 一键部署脚本 `scripts/deploy_production_ubuntu.sh`
3. 新增 Linux 严格压测脚本 `scripts/run_linux_strict_acceptance.sh`
4. 新增 Linux 阶梯压测脚本 `scripts/run_linux_capacity_sweep.sh`
5. 更新 `.env.example`，统一为生产推荐的 PostgreSQL/Redis 示例
6. 更新 `init_db.py`，初始化时默认禁用 scheduler，避免 bootstrap 顺序问题

## Linux 压测结论

- `40` 设备档通过
- `60` 设备档开始首先出现登录/会话超时
- 当前没有证据显示 `workers=2 + PostgreSQL + Redis` 会导致重复分票或串设备
- 当前最值得注意的风险点是瞬时登录高峰，不是核心票务正确性

## 唯一最该注意的风险点

如果大量设备在同一时刻重新登录，系统会先出现登录/会话超时。

这和“重复分票”不是一类问题。当前成功档位没有看到核心正确性被打穿，但登录高峰仍然需要在生产上重点关注。
