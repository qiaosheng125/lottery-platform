#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/.venv/bin/activate"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi

cd "$ROOT_DIR"

: "${DATABASE_URL:?DATABASE_URL must be set to PostgreSQL before strict acceptance runs}"
: "${REDIS_URL:?REDIS_URL must be set before strict acceptance runs}"

if [[ "$DATABASE_URL" != postgresql* ]]; then
  echo "DATABASE_URL must point to PostgreSQL for strict acceptance runs." >&2
  exit 1
fi

python - <<'PY'
from app import create_app
import extensions

app = create_app("production")
with app.app_context():
    extensions.db.session.execute(extensions.db.text("SELECT 1"))
    if extensions.redis_client is None:
        raise RuntimeError("Redis client is unavailable")
    extensions.redis_client.ping()
print("PostgreSQL and Redis health checks passed.")
PY

python init_db.py

export RUN_LIVE_CONCURRENCY_TESTS="${RUN_LIVE_CONCURRENCY_TESTS:-1}"
export LIVE_TEST_SERVER_MODE="${LIVE_TEST_SERVER_MODE:-gunicorn}"
export LIVE_TEST_GUNICORN_WORKERS="${LIVE_TEST_GUNICORN_WORKERS:-2}"
export LIVE_TEST_STRICT_DEVICE_GUARD="${LIVE_TEST_STRICT_DEVICE_GUARD:-1}"
export LIVE_TEST_MODE_A_ACCOUNTS="${LIVE_TEST_MODE_A_ACCOUNTS:-20}"
export LIVE_TEST_MODE_B_ACCOUNTS="${LIVE_TEST_MODE_B_ACCOUNTS:-10}"
export LIVE_TEST_MODE_A_DEVICES_PER_ACCOUNT="${LIVE_TEST_MODE_A_DEVICES_PER_ACCOUNT:-2}"
export LIVE_TEST_MODE_B_DEVICES_PER_ACCOUNT="${LIVE_TEST_MODE_B_DEVICES_PER_ACCOUNT:-6}"
export LIVE_TEST_MODE_B_BATCH_COUNT="${LIVE_TEST_MODE_B_BATCH_COUNT:-1}"
export LIVE_TEST_MODE_A_REQUESTS_PER_DEVICE="${LIVE_TEST_MODE_A_REQUESTS_PER_DEVICE:-1}"
export LIVE_TEST_PENDING_HEADROOM="${LIVE_TEST_PENDING_HEADROOM:-0}"
export LIVE_TEST_MAX_SLOW_REQUESTS="${LIVE_TEST_MAX_SLOW_REQUESTS:-20}"

echo "Running strict acceptance with:"
echo "  mode_a_accounts=$LIVE_TEST_MODE_A_ACCOUNTS mode_b_accounts=$LIVE_TEST_MODE_B_ACCOUNTS"
echo "  mode_a_devices=$LIVE_TEST_MODE_A_DEVICES_PER_ACCOUNT mode_b_devices=$LIVE_TEST_MODE_B_DEVICES_PER_ACCOUNT"
echo "  mode_b_batch_count=$LIVE_TEST_MODE_B_BATCH_COUNT max_slow_requests=$LIVE_TEST_MAX_SLOW_REQUESTS"

pytest tests/test_concurrent_20devices.py -v -s
