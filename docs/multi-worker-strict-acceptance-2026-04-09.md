# 多 Worker 严格验收说明

## 目标

在一台 `2 核 / 2GB` 主机上，以以下形态部署：

- `PostgreSQL`
- `Redis`
- `gunicorn workers=2`

核心要求只有一条：正确性优先。只要票状态有任何错乱，吞吐提升都没有意义。

## 推荐的生产默认值

建议使用以下环境变量：

```env
DATABASE_URL=postgresql://user:password@host:5432/lottery_platform
REDIS_URL=redis://host:6379/0
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
DB_POOL_RECYCLE=300
GUNICORN_WORKERS=2
GUNICORN_TIMEOUT=120
GUNICORN_KEEPALIVE=5
```

原因：

- `workers=2` 和主机 CPU 核数匹配，不会太早把进程竞争放大。
- 小一点的数据库连接池更适合小机器，也能减少空闲连接浪费。
- `PostgreSQL` 的行锁和 advisory lock 能保证跨 worker 的正确性。
- `Redis` 能保证共享 pending 池在多 worker 下保持一致。

## 严格验收规则

只要出现下面任意一种情况，本轮压测就必须判定失败：

1. 同一张票被领取两次。
2. 一张已领取的票在完整 A/B 流程结束后不是 `completed`。
3. `assigned_user_id`、`assigned_username`、`assigned_device_id`、`assigned_device_name` 任一字段和实际领票设备不一致。
4. 任意测试账号在压测结束后仍残留 `assigned` 票。
5. 任意用户穿透 `daily_ticket_limit`。
6. 任意用户穿透 `max_processing_b_mode`。
7. 任意测试文件的 `pending_count`、`assigned_count`、`completed_count`、`total_tickets`、`actual_total_amount` 与真实票数据发生漂移。
8. 错误设备的 B 模式确认请求居然成功。

## 如何执行

注意：

- `LIVE_TEST_SERVER_MODE=gunicorn` 必须在 Linux 下执行。
- Windows 不能用于这条路径，因为 `gunicorn` 依赖 `fcntl`。
- 如果只在 Windows 上跑测试，不能证明多 worker 正确性。

在接近生产的 Linux 主机上，可以这样跑一轮严格验收：

```powershell
$env:RUN_LIVE_CONCURRENCY_TESTS=1
$env:LIVE_TEST_SERVER_MODE='gunicorn'
$env:LIVE_TEST_GUNICORN_WORKERS='2'
$env:LIVE_TEST_STRICT_DEVICE_GUARD='1'
$env:LIVE_TEST_MODE_A_ACCOUNTS='4'
$env:LIVE_TEST_MODE_B_ACCOUNTS='4'
$env:LIVE_TEST_DEVICES_PER_ACCOUNT='10'
$env:LIVE_TEST_MODE_B_BATCH_COUNT='20'
python -m pytest tests/test_concurrent_20devices.py -v -s
```

如果要测更重的 B 模式批次：

```powershell
$env:LIVE_TEST_MODE_A_ACCOUNTS='3'
$env:LIVE_TEST_MODE_B_ACCOUNTS='3'
$env:LIVE_TEST_DEVICES_PER_ACCOUNT='10'
$env:LIVE_TEST_MODE_B_BATCH_COUNT='30'
python -m pytest tests/test_concurrent_20devices.py -v -s
```

## 这套测试现在会校验什么

当前的活体压测脚本会同时校验接口层和数据库层的不变量：

- 成功响应里是否出现重复票 ID
- 错误设备确认是否被正确拒绝
- 测试账号是否还残留 `assigned` 票
- 每一张领取成功的票最终是否都落到 `completed`
- 票的归属字段是否和实际设备完全一致
- 文件计数和总金额是否始终和真实票数据一致

这是当前项目在信任多 worker 生产部署之前，至少必须通过的基线标准。
