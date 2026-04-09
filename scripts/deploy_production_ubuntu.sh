#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
APP_DB_NAME="${APP_DB_NAME:-lottery_platform}"
APP_DB_USER="${APP_DB_USER:-lottery_app}"
APP_DB_PASSWORD="${APP_DB_PASSWORD:-change-this-password}"
SECRET_KEY_VALUE="${SECRET_KEY_VALUE:-change-this-to-a-random-secret-key-in-production}"
SERVICE_NAME="${SERVICE_NAME:-file-hub}"

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
fi

sudo systemctl enable postgresql
sudo systemctl enable redis-server
sudo systemctl restart postgresql
sudo systemctl restart redis-server

sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname = '${APP_DB_USER}'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE ${APP_DB_USER} LOGIN PASSWORD '${APP_DB_PASSWORD}';"

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '${APP_DB_NAME}'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE DATABASE ${APP_DB_NAME} OWNER ${APP_DB_USER};"

python - <<PY
from pathlib import Path

env_path = Path(r"$ROOT_DIR/.env")
updates = {
    "SECRET_KEY": r"$SECRET_KEY_VALUE",
    "FLASK_ENV": "production",
    "DATABASE_URL": "postgresql://$APP_DB_USER:$APP_DB_PASSWORD@127.0.0.1:5432/$APP_DB_NAME",
    "REDIS_URL": "redis://127.0.0.1:6379/0",
    "DB_POOL_SIZE": "5",
    "DB_MAX_OVERFLOW": "5",
    "DB_POOL_RECYCLE": "300",
    "GUNICORN_WORKERS": "2",
    "GUNICORN_TIMEOUT": "120",
    "GUNICORN_KEEPALIVE": "5",
}

lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
for key, value in updates.items():
    replaced = False
    for idx, raw in enumerate(lines):
        if raw.startswith(f"{key}="):
            lines[idx] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")

env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
print(f"Updated {env_path}")
PY

mkdir -p "$ROOT_DIR/uploads/images" "$ROOT_DIR/uploads/txt" "$ROOT_DIR/uploads/archive/txt"

set -a
source "$ROOT_DIR/.env"
set +a
python "$ROOT_DIR/init_db.py"

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=File Hub Gunicorn Service
After=network.target postgresql.service redis-server.service

[Service]
User=$(whoami)
WorkingDirectory=$ROOT_DIR
EnvironmentFile=$ROOT_DIR/.env
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/gunicorn -c $ROOT_DIR/gunicorn_config.py "app:create_app()"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo
echo "Deployment completed."
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true
