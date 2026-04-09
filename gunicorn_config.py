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
