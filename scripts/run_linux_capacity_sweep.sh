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

run_stage() {
  local label="$1"
  local mode_a_accounts="$2"
  local mode_b_accounts="$3"
  local mode_a_devices="$4"
  local mode_b_devices="$5"
  local batch_count="$6"
  local max_slow="$7"

  echo
  echo "========== $label =========="
  export RUN_LIVE_CONCURRENCY_TESTS=1
  export LIVE_TEST_SERVER_MODE=gunicorn
  export LIVE_TEST_GUNICORN_WORKERS="${LIVE_TEST_GUNICORN_WORKERS:-2}"
  export LIVE_TEST_STRICT_DEVICE_GUARD=1
  export LIVE_TEST_MODE_A_ACCOUNTS="$mode_a_accounts"
  export LIVE_TEST_MODE_B_ACCOUNTS="$mode_b_accounts"
  export LIVE_TEST_MODE_A_DEVICES_PER_ACCOUNT="$mode_a_devices"
  export LIVE_TEST_MODE_B_DEVICES_PER_ACCOUNT="$mode_b_devices"
  export LIVE_TEST_MODE_B_BATCH_COUNT="$batch_count"
  export LIVE_TEST_MODE_A_REQUESTS_PER_DEVICE=1
  export LIVE_TEST_PENDING_HEADROOM=0
  export LIVE_TEST_MAX_SLOW_REQUESTS="$max_slow"

  pytest tests/test_concurrent_20devices.py -v -s
}

run_stage "40 devices" 8 4 2 6 1 10
run_stage "60 devices" 12 6 2 6 1 12
run_stage "80 devices" 16 8 2 6 1 16
run_stage "100 devices" 20 10 2 6 1 20
