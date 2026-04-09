# Multi-Worker Strict Acceptance

## Goal

Deploy on a `2-core / 2GB` host with:

- `PostgreSQL`
- `Redis`
- `gunicorn workers=2`

Core requirement: correctness first. Throughput gains do not count if any ticket state becomes wrong.

## Recommended Production Defaults

Use these environment variables:

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

Reasoning:

- `workers=2` matches the host CPU count without pushing process contention too early.
- Smaller DB pools are safer on a small host and reduce idle connection waste.
- `PostgreSQL` row locks and advisory locks provide cross-worker correctness.
- `Redis` keeps the shared pending pool consistent across workers.

## Strict Acceptance Rules

Every pressure-test run must reject the build if any of these happen:

1. One ticket is claimed twice.
2. A claimed ticket is not `completed` at the end of the full A/B workflow.
3. `assigned_user_id`, `assigned_username`, `assigned_device_id`, or `assigned_device_name` does not match the device that claimed the ticket.
4. Any touched test account still has `assigned` tickets after the run.
5. Any user exceeds `daily_ticket_limit`.
6. Any user exceeds `max_processing_b_mode`.
7. Any touched file has drifted `pending_count`, `assigned_count`, `completed_count`, `total_tickets`, or `actual_total_amount`.
8. Wrong-device B-mode confirmation succeeds.

## How To Run

Important:

- `LIVE_TEST_SERVER_MODE=gunicorn` must be executed on Linux.
- Windows cannot run this path because `gunicorn` depends on `fcntl`.
- If you only run the test on Windows, you are not proving multi-worker correctness.

Example strict run on a production-like host:

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

For heavier batches:

```powershell
$env:LIVE_TEST_MODE_A_ACCOUNTS='3'
$env:LIVE_TEST_MODE_B_ACCOUNTS='3'
$env:LIVE_TEST_DEVICES_PER_ACCOUNT='10'
$env:LIVE_TEST_MODE_B_BATCH_COUNT='30'
python -m pytest tests/test_concurrent_20devices.py -v -s
```

## What The Test Now Verifies

The live test script now checks both response-level and database-level invariants:

- duplicate ticket IDs in successful responses
- wrong-device confirm rejection
- no residual `assigned` tickets for test users
- every claimed ticket ends in `completed`
- ticket ownership fields match the claiming device exactly
- file counters and total amount stay in sync with actual ticket rows

This is the minimum standard before trusting a multi-worker deployment.
