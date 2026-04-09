# Cloud Deploy On Ubuntu

## Recommended Production Shape

- `gunicorn workers=2`
- `PostgreSQL`
- `Redis`
- `DB_POOL_SIZE=5`
- `DB_MAX_OVERFLOW=5`

This is the recommended first production configuration for your current traffic profile.

## One-Command Deployment

On a fresh Ubuntu server:

```bash
git clone -b main https://github.com/qiaosheng125/file-hub.git
cd file-hub
chmod +x scripts/deploy_production_ubuntu.sh
APP_DB_PASSWORD='replace-this-password' \
SECRET_KEY_VALUE='replace-with-a-long-random-secret' \
./scripts/deploy_production_ubuntu.sh
```

What it does:

1. Installs Python, PostgreSQL, Redis, and nginx packages.
2. Creates `.venv`.
3. Installs Python dependencies.
4. Creates PostgreSQL role and database.
5. Updates `.env` with production defaults.
6. Bootstraps the schema with scheduler disabled.
7. Creates and starts a `systemd` service.

## Service Management

```bash
sudo systemctl status file-hub
sudo systemctl restart file-hub
sudo journalctl -u file-hub -n 200 --no-pager
```

## Notes

- `init_db.py` now disables scheduler during bootstrap so a fresh PostgreSQL database can initialize cleanly.
- `.env.example` now matches the deployment scripts and no longer points at the old `user:password@localhost` placeholder.
