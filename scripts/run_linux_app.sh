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
export GUNICORN_WORKERS="${GUNICORN_WORKERS:-2}"
export GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"
export GUNICORN_KEEPALIVE="${GUNICORN_KEEPALIVE:-5}"

cd "$ROOT_DIR"
python init_db.py
exec gunicorn -c "$ROOT_DIR/gunicorn_config.py" "app:create_app()"
