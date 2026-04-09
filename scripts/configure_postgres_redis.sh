#!/usr/bin/env bash
set -euo pipefail

APP_DB_NAME="${APP_DB_NAME:-lottery_platform}"
APP_DB_USER="${APP_DB_USER:-lottery_app}"
APP_DB_PASSWORD="${APP_DB_PASSWORD:-change-this-password}"
PGHOST_LOCAL="${PGHOST_LOCAL:-127.0.0.1}"
PGPORT_LOCAL="${PGPORT_LOCAL:-5432}"
REDIS_URL_LOCAL="${REDIS_URL_LOCAL:-redis://127.0.0.1:6379/0}"

sudo systemctl restart postgresql
sudo systemctl restart redis-server

sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname = '${APP_DB_USER}'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE ${APP_DB_USER} LOGIN PASSWORD '${APP_DB_PASSWORD}';"

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '${APP_DB_NAME}'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE DATABASE ${APP_DB_NAME} OWNER ${APP_DB_USER};"

sudo -u postgres psql -d "$APP_DB_NAME" -c "GRANT ALL PRIVILEGES ON DATABASE ${APP_DB_NAME} TO ${APP_DB_USER};"

python3 - <<PY
import redis
client = redis.from_url("${REDIS_URL_LOCAL}")
client.ping()
print("Redis ping OK")
PY

cat <<EOF
Database and Redis are ready.
Use this DATABASE_URL in .env:
DATABASE_URL=postgresql://${APP_DB_USER}:${APP_DB_PASSWORD}@${PGHOST_LOCAL}:${PGPORT_LOCAL}/${APP_DB_NAME}
REDIS_URL=${REDIS_URL_LOCAL}
EOF
