import os


bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:5000")
worker_class = os.environ.get(
    "GUNICORN_WORKER_CLASS",
    "geventwebsocket.gunicorn.workers.GeventWebSocketWorker",
)
# Conservative default for a 2-core / 2GB host running PostgreSQL + Redis.
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "5"))


def _scheduler_raw_env():
    """
    Keep scheduler flags configurable by EnvironmentFile/.env only.
    When unset, do not override app-level scheduler defaults.
    """
    enable_scheduler = os.environ.get("ENABLE_SCHEDULER")
    disable_scheduler = os.environ.get("DISABLE_SCHEDULER")

    raw = []
    if enable_scheduler is not None:
        raw.append(f"ENABLE_SCHEDULER={enable_scheduler}")
    if disable_scheduler is not None:
        raw.append(f"DISABLE_SCHEDULER={disable_scheduler}")
    return raw


raw_env = _scheduler_raw_env()
