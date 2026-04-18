# Ubuntu 云服务器部署说明

> 文档状态：`历史参考（部署）`
>  
> 使用边界：仅在 Linux 生产部署或回滚排障时按需阅读；不属于日常接手必读文档。  
> 回归口径：默认执行主计划里的定向回归，**不做全量回归**；只有明确做部署验收时才结合本文。

## 推荐的生产形态

- `gunicorn workers=2`
- `PostgreSQL`
- `Redis`
- `DB_POOL_SIZE=5`
- `DB_MAX_OVERFLOW=5`

这是当前项目在你这个流量级别下，推荐的第一版生产配置。

## 一键部署

在一台全新的 Ubuntu 服务器上执行：

```bash
git clone -b main https://github.com/qiaosheng125/file-hub.git
cd file-hub
chmod +x scripts/deploy_production_ubuntu.sh
APP_DB_PASSWORD='替换成你的数据库密码' \
SECRET_KEY_VALUE='替换成长随机密钥' \
./scripts/deploy_production_ubuntu.sh
```

这个脚本会完成：

1. 安装 Python、PostgreSQL、Redis 和 nginx。
2. 创建 `.venv`。
3. 安装 Python 依赖。
4. 创建 PostgreSQL 用户和数据库。
5. 按生产默认值写入 `.env`。
6. 在禁用 scheduler 的情况下完成数据库初始化。
7. 创建并启动 `systemd` 服务。

## 服务管理

```bash
sudo systemctl status file-hub
sudo systemctl restart file-hub
sudo journalctl -u file-hub -n 200 --no-pager
```

## 部署后补跑高压测试（必做）

建议在以下时机各跑 1 轮：

1. 首次上线完成后。
2. 调整 `gunicorn` worker、数据库连接池、Redis 配置后。
3. 修复分票/会话/上传主链路后准备再次发布前。

### 1) 严格并发验收（正确性优先）

```bash
cd /path/to/file-hub
source .venv/bin/activate
export RUN_LIVE_CONCURRENCY_TESTS=1
export LIVE_TEST_SERVER_MODE=gunicorn
export LIVE_TEST_GUNICORN_WORKERS=2
export LIVE_TEST_STRICT_DEVICE_GUARD=1
python -m pytest -q tests/test_concurrent_20devices.py -s
```

### 2) 阶梯容量压测（观察容量拐点）

```bash
cd /path/to/file-hub
source .venv/bin/activate
./scripts/run_linux_capacity_sweep.sh
```

### 最小通过标准

1. 不能出现重复分票、串设备确认、压测结束后残留 `assigned`。
2. 不能穿透 `daily_ticket_limit` 和 `max_processing_b_mode`。
3. 文件计数与金额字段不能漂移。
4. 若出现失败，先保留现场日志并回滚到最近稳定版本，不要带故障继续放量。

## 说明

- `init_db.py` 现在会基于当前 `DATABASE_URL` 初始化数据库，并在初始化阶段自动禁用 scheduler，所以全新的 PostgreSQL 空库也能正常启动。
- `.env.example` 现在已经和部署脚本对齐，不再使用旧的 `user:password@localhost` 占位配置。
