# Ubuntu 虚拟机严格压测说明

> 文档状态：`历史参考（容量压测）`
>  
> 使用边界：仅在明确做容量上限评估时使用。  
> 回归口径：默认执行主计划定向回归，**不做全量回归**；只有需要并发/容量结论时才执行本文流程。

## 目标

在以下环境里执行接近生产的严格验收：

- Ubuntu 22.04
- 2 vCPU
- 2 GB RAM
- PostgreSQL
- Redis
- gunicorn `workers=2`

正确性是硬门槛，只有正确性通过之后，性能结果才有意义。

## 这条流程涉及的脚本

- `scripts/setup_ubuntu_vm.sh`
- `scripts/configure_postgres_redis.sh`
- `scripts/run_linux_app.sh`
- `scripts/run_linux_strict_acceptance.sh`
- `scripts/run_linux_capacity_sweep.sh`

## 虚拟机的一次性初始化

先克隆仓库，然后执行：

```bash
chmod +x scripts/*.sh
./scripts/setup_ubuntu_vm.sh
```

这个脚本会：

- 安装系统依赖
- 创建 `.venv`
- 安装 Python 依赖
- 启用 PostgreSQL 和 Redis
- 如果 `.env` 不存在，就基于 `.env.example` 自动生成

## 配置 PostgreSQL 和 Redis

先选一个数据库密码，然后执行：

```bash
export APP_DB_NAME=lottery_platform
export APP_DB_USER=lottery_app
export APP_DB_PASSWORD='替换成你的密码'
./scripts/configure_postgres_redis.sh
```

执行完成后，把脚本输出的 `DATABASE_URL` 和 `REDIS_URL` 写进 `.env`。

推荐的 `.env` 配置如下，适合 `2 核 / 2GB` 虚拟机：

```env
FLASK_ENV=production
DATABASE_URL=postgresql://lottery_app:replace-this@127.0.0.1:5432/lottery_platform
REDIS_URL=redis://127.0.0.1:6379/0
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
DB_POOL_RECYCLE=300
GUNICORN_WORKERS=2
GUNICORN_TIMEOUT=120
GUNICORN_KEEPALIVE=5
```

## 启动应用

```bash
./scripts/run_linux_app.sh
```

这个脚本会先初始化数据库，然后启动：

```bash
gunicorn -c gunicorn_config.py "app:create_app()"
```

## 严格验收压测

默认的严格压测参数，就是你之前要测的那组目标：

- `30` 个用户
- `100` 台设备
- `20` 个 A 模式账号，每个 `2` 台设备
- `10` 个 B 模式账号，每个 `6` 台设备

执行：

```bash
./scripts/run_linux_strict_acceptance.sh
```

## 自定义压测参数

如果你想自己覆盖参数，可以先设置环境变量再执行脚本：

```bash
export LIVE_TEST_MODE_A_ACCOUNTS=20
export LIVE_TEST_MODE_B_ACCOUNTS=10
export LIVE_TEST_MODE_A_DEVICES_PER_ACCOUNT=2
export LIVE_TEST_MODE_B_DEVICES_PER_ACCOUNT=6
export LIVE_TEST_MODE_B_BATCH_COUNT=1
export LIVE_TEST_MAX_SLOW_REQUESTS=20
./scripts/run_linux_strict_acceptance.sh
```

## 阶梯压测

如果要先找到稳定上限，再决定是否继续冲 `100` 设备，可以执行：

```bash
./scripts/run_linux_capacity_sweep.sh
```

这个脚本会依次跑：

- `40` 台设备
- `60` 台设备
- `80` 台设备
- `100` 台设备

它的目标是把“正确性失败”和“容量不够导致的超时失败”区分开，并找出第一档不稳定的位置。

## 通过标准

只要出现下面任意一种情况，本轮测试就必须立即判定失败：

1. 重复分票。
2. 错误设备的 B 模式确认成功。
3. 任意已领取票最终不是 `completed`。
4. 票归属字段和实际领票设备不一致。
5. 压测结束后仍残留 `assigned`。
6. 用户限制被穿透。
7. 文件计数或总金额和真实票数据发生漂移。

## 重要边界

- 多 worker 严格验收必须在 Linux 下执行。
- Windows 不能作为 gunicorn 多 worker 验证环境。
- SQLite 不能用于这轮严格验收。
- Redis fallback 模式也不能用于这轮严格验收。
