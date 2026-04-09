#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"

sudo apt-get update
sudo apt-get install -y \
  python3 \
  python3-venv \
  python3-dev \
  build-essential \
  libpq-dev \
  postgresql \
  postgresql-contrib \
  redis-server \
  nginx

"$PYTHON_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
pip install -r "$ROOT_DIR/requirements.txt"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  echo "Created $ROOT_DIR/.env from .env.example. Review it before running production tests."
fi

mkdir -p "$ROOT_DIR/uploads/images" "$ROOT_DIR/uploads/txt" "$ROOT_DIR/uploads/archive/txt"

sudo systemctl enable postgresql
sudo systemctl enable redis-server
sudo systemctl restart postgresql
sudo systemctl restart redis-server

echo "Ubuntu VM dependencies installed."
echo "Next:"
echo "  1. Edit $ROOT_DIR/.env"
echo "  2. Run scripts/configure_postgres_redis.sh"
echo "  3. Run scripts/run_linux_strict_acceptance.sh"
