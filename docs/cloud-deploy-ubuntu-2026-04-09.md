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

## 当前生产实例（2026-04-22）

- 服务器：`121.196.170.150`
- 主域名：`zdj8.fun`
- 附加域名：`www.zdj8.fun`
- HTTPS / 证书自动续期执行文档：`docs/https-acme-aliyun-2026-04-22.md`
- 当前统一口径：`nginx :443 -> gunicorn(127.0.0.1:5000) -> Flask`
- 当前证书方案：`acme.sh + dns_ali + Let's Encrypt`

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
./scripts/run_linux_strict_acceptance.sh
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
- 当前发布流程按“可清空重建数据库”执行，`init_db.py` 会直接建表；不依赖手工迁移脚本。

## 2026-04-20 发布补充（口径统一）

### 配置口径（统一版）
- 通用默认值仍为 `GUNICORN_WORKERS=2`（仓库脚本与 `.env.example` 默认值）。
- 若目标机为 `2核2G` 且出现登录高峰超时，可在压测通过后调优到 `GUNICORN_WORKERS=4`。
- 本次发布包含 `users` 表兼容修复：老库缺失新列时，应用启动会自动补齐，不需要手工改表。

### 2核2G 实测结论（2026-04-19）
- 稳定通过档位：16 / 24 / 28 / 32 设备（`errors=0`）。
- 32 设备实测：`slow_requests=3`（在阈值内）。
- 40/60/100 设备档在该机型出现较多登录超时（`ReadTimeout`），不建议作为常态档位。

### 推荐压测基线参数（2核2G）
```bash
export RUN_LIVE_CONCURRENCY_TESTS=1
export LIVE_TEST_SERVER_MODE=gunicorn
export LIVE_TEST_GUNICORN_WORKERS=4
export LIVE_TEST_MODE_A_ACCOUNTS=8
export LIVE_TEST_MODE_B_ACCOUNTS=4
export LIVE_TEST_MODE_A_DEVICES_PER_ACCOUNT=2
export LIVE_TEST_MODE_B_DEVICES_PER_ACCOUNT=4
export LIVE_TEST_MODE_B_BATCH_COUNT=1
export LIVE_TEST_MAX_SLOW_REQUESTS=20
pytest tests/test_concurrent_20devices.py -rs -vv -s
```

### 从 GitHub 更新并发布（main）
```bash
cd /root/file-hub
git status
git fetch origin
git pull --ff-only origin main

source .venv/bin/activate
pip install -r requirements.txt

# 本次发布包含 users 表 schema 兼容修复，必须执行
python init_db.py

systemctl restart file-hub.service
systemctl status file-hub.service --no-pager -l
curl -I http://127.0.0.1/auth/login
```

### 常见坑与可复用命令
- 仅删除项目目录不会停旧服务；`systemd` 残留会占用 `5000` 端口。
- Shell 环境变量会覆盖 `.env`，存在外部 `DATABASE_URL` 时可能误连其他库。
- Linux 脚本如有 `CRLF`，先执行 `dos2unix scripts/*.sh`。

```bash
# 清理旧服务残留
systemctl stop file-hub.service 2>/dev/null || true
systemctl disable file-hub.service 2>/dev/null || true
rm -f /etc/systemd/system/file-hub.service /etc/systemd/system/multi-user.target.wants/file-hub.service
systemctl daemon-reload
systemctl reset-failed

# 压测前清理端口占用
fuser -k 5000/tcp 2>/dev/null || true
ss -ltnp | grep ':5000' || echo '5000 free'
```

### 机器重启后检查
```bash
systemctl is-active file-hub nginx postgresql redis-server
```
- 若任一服务不是 `active`：
```bash
systemctl start postgresql redis-server nginx file-hub
```
