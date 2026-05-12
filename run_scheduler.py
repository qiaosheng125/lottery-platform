"""
Standalone APScheduler process.

This process owns background jobs so Gunicorn web workers only handle requests.
"""

import logging
import os
import signal
import time

from dotenv import load_dotenv


def main():
    load_dotenv()
    os.environ.setdefault("FLASK_ENV", "production")
    os.environ["ENABLE_SCHEDULER"] = "1"
    os.environ["DISABLE_SCHEDULER"] = "0"
    os.environ["PROCESS_ROLE"] = "scheduler"

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    from app import create_app
    from tasks.scheduler import get_scheduler

    create_app()
    scheduler = get_scheduler()
    if scheduler is None:
        raise RuntimeError("scheduler did not start")

    logging.getLogger(__name__).info("start standalone scheduler process")

    stopping = False

    def _request_stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    try:
        while not stopping:
            time.sleep(1)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
