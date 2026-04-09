# Ubuntu VM Strict Load Test

## Goal

Run production-like strict acceptance on:

- Ubuntu 22.04
- 2 vCPU
- 2 GB RAM
- PostgreSQL
- Redis
- gunicorn `workers=2`

Correctness is the hard gate. Performance only matters after correctness passes.

## Files Added For This Flow

- `scripts/setup_ubuntu_vm.sh`
- `scripts/configure_postgres_redis.sh`
- `scripts/run_linux_app.sh`
- `scripts/run_linux_strict_acceptance.sh`

## One-Time VM Setup

Clone the repo, then run:

```bash
chmod +x scripts/*.sh
./scripts/setup_ubuntu_vm.sh
```

This installs system packages, creates `.venv`, installs Python dependencies, enables PostgreSQL and Redis, and creates `.env` from `.env.example` if missing.

## Configure PostgreSQL And Redis

Pick a DB password, then run:

```bash
export APP_DB_NAME=lottery_platform
export APP_DB_USER=lottery_app
export APP_DB_PASSWORD='replace-this'
./scripts/configure_postgres_redis.sh
```

Then write the emitted `DATABASE_URL` and `REDIS_URL` into `.env`.

Recommended `.env` values for a 2-core / 2GB VM:

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

## Start The App

```bash
./scripts/run_linux_app.sh
```

This initializes the schema and starts:

```bash
gunicorn -c gunicorn_config.py "app:create_app()"
```

## Strict Acceptance Run

The default strict run matches your current target:

- `30` users
- `100` devices
- `20` mode A accounts x `2` devices
- `10` mode B accounts x `6` devices

Run:

```bash
./scripts/run_linux_strict_acceptance.sh
```

## Custom Pressure-Test Parameters

Override env vars before the script when needed:

```bash
export LIVE_TEST_MODE_A_ACCOUNTS=20
export LIVE_TEST_MODE_B_ACCOUNTS=10
export LIVE_TEST_MODE_A_DEVICES_PER_ACCOUNT=2
export LIVE_TEST_MODE_B_DEVICES_PER_ACCOUNT=6
export LIVE_TEST_MODE_B_BATCH_COUNT=1
export LIVE_TEST_MAX_SLOW_REQUESTS=20
./scripts/run_linux_strict_acceptance.sh
```

## Pass Criteria

The test must fail immediately if any of these happen:

1. Duplicate ticket assignment.
2. Wrong-device B-mode confirm succeeds.
3. Any claimed ticket is not `completed`.
4. Ticket ownership fields do not match the claiming device.
5. Residual `assigned` tickets remain.
6. User limits are exceeded.
7. File counters or amount totals drift from actual ticket rows.

## Important Limits

- Multi-worker strict acceptance must be run on Linux.
- Windows is not valid for gunicorn multi-worker verification.
- SQLite is not valid for this acceptance run.
- Redis fallback mode is not valid for this acceptance run.
