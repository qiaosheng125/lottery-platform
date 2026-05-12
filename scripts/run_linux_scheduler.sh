#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/.venv/bin/activate"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi

export FLASK_ENV="${FLASK_ENV:-production}"
export ENABLE_SCHEDULER="1"
export DISABLE_SCHEDULER="0"
export PROCESS_ROLE=scheduler

cd "$ROOT_DIR"
ENABLE_SCHEDULER=0 DISABLE_SCHEDULER=1 python init_db.py
exec python "$ROOT_DIR/run_scheduler.py"
