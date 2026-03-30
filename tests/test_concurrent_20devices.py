"""
Live concurrency test for the core ticket assignment flow.

Scenario:
- 4 accounts total: 2 mode A, 2 mode B
- 10 devices per account, 40 devices concurrent
- Each mode B device downloads 20 tickets once
- Each mode A device requests one ticket once

Run manually:
  $env:RUN_LIVE_CONCURRENCY_TESTS=1
  python -m pytest tests/test_concurrent_20devices.py -v -s
"""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

import pytest
import requests
from werkzeug.datastructures import FileStorage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app import create_app
from extensions import db
from models.settings import SystemSettings
from models.file import UploadedFile
from models.ticket import LotteryTicket
from models.user import User, UserSession
from services.file_parser import process_uploaded_file
from services.ticket_pool import get_pool_status
import tasks.scheduler as scheduler_module

if os.environ.get("RUN_LIVE_CONCURRENCY_TESTS") != "1":
    pytest.skip(
        "live concurrency test is opt-in; set RUN_LIVE_CONCURRENCY_TESTS=1 to enable",
        allow_module_level=True,
    )


BASE_URL = "http://127.0.0.1:5000"
TEST_PASSWORD = "test123456"
DEVICES_PER_ACCOUNT = 10
MODE_B_BATCH_COUNT = 20
MODE_A_REQUESTS_PER_DEVICE = 1
SERVER_START_TIMEOUT_SECONDS = 30
DEVICE_REQUEST_TIMEOUT_SECONDS = 20
LIVE_TEST_FILES_DIR = ROOT / "tests" / "live_test_files"
SERVER_LOG_PATH = ROOT / "tests" / "live_concurrency_server.log"
RUN_LABEL = uuid.uuid4().hex[:6]

TEST_ACCOUNTS = [
    {"username": "load_mode_a_1", "client_mode": "mode_a"},
    {"username": "load_mode_a_2", "client_mode": "mode_a"},
    {"username": "load_mode_b_1", "client_mode": "mode_b"},
    {"username": "load_mode_b_2", "client_mode": "mode_b"},
]

RESULTS = []
LOCK = threading.Lock()


def ensure_admin() -> User:
    admin = User.query.filter_by(is_admin=True).first()
    if admin:
        return admin

    admin = User(username="zucaixu", is_admin=True)
    admin.set_password("zhongdajiang888")
    db.session.add(admin)
    db.session.commit()
    return admin


def ensure_test_accounts():
    for account in TEST_ACCOUNTS:
        user = User.query.filter_by(username=account["username"]).first()
        if not user:
            user = User(
                username=account["username"],
                client_mode=account["client_mode"],
                max_devices=DEVICES_PER_ACCOUNT + 2,
                can_receive=True,
            )
            user.set_password(TEST_PASSWORD)
            db.session.add(user)
        else:
            user.client_mode = account["client_mode"]
            user.max_devices = DEVICES_PER_ACCOUNT + 2
            user.can_receive = True
            user.is_active = True
            user.max_processing_b_mode = max(user.max_processing_b_mode or 0, DEVICES_PER_ACCOUNT * MODE_B_BATCH_COUNT + 50)
        if account["client_mode"] == "mode_b":
            user.max_processing_b_mode = DEVICES_PER_ACCOUNT * MODE_B_BATCH_COUNT * 3
    db.session.commit()

    usernames = [account["username"] for account in TEST_ACCOUNTS]
    user_ids = [user.id for user in User.query.filter(User.username.in_(usernames)).all()]
    if user_ids:
        UserSession.query.filter(UserSession.user_id.in_(user_ids)).delete(synchronize_session=False)
        db.session.commit()


def reset_test_account_tickets():
    usernames = [account["username"] for account in TEST_ACCOUNTS]
    users = User.query.filter(User.username.in_(usernames)).all()
    user_ids = [user.id for user in users]
    if not user_ids:
        return

    assigned_tickets = LotteryTicket.query.filter(
        LotteryTicket.assigned_user_id.in_(user_ids),
        LotteryTicket.status == 'assigned',
    ).all()

    touched_file_ids = set()
    for ticket in assigned_tickets:
        touched_file_ids.add(ticket.source_file_id)
        ticket.status = 'pending'
        ticket.assigned_user_id = None
        ticket.assigned_username = None
        ticket.assigned_device_id = None
        ticket.assigned_device_name = None
        ticket.assigned_at = None
        ticket.locked_until = None

    db.session.commit()

    for file_id in touched_file_ids:
        uploaded_file = UploadedFile.query.get(file_id)
        if not uploaded_file:
            continue
        uploaded_file.pending_count = LotteryTicket.query.filter_by(source_file_id=file_id, status='pending').count()
        uploaded_file.assigned_count = LotteryTicket.query.filter_by(source_file_id=file_id, status='assigned').count()
        uploaded_file.completed_count = LotteryTicket.query.filter_by(source_file_id=file_id, status='completed').count()
    db.session.commit()


def ensure_settings():
    settings = SystemSettings.get()
    settings.mode_a_enabled = True
    settings.mode_b_enabled = True
    settings.pool_enabled = True
    settings.registration_enabled = True
    db.session.commit()


def import_test_files_until_sufficient(required_pending: int):
    current_pending = get_pool_status()["total_pending"]
    if current_pending >= required_pending:
        print(f"[setup] existing pending tickets are sufficient: {current_pending}")
        return current_pending

    if not LIVE_TEST_FILES_DIR.exists():
        raise RuntimeError(f"missing live test files directory: {LIVE_TEST_FILES_DIR}")

    files = sorted(LIVE_TEST_FILES_DIR.glob("*.txt"))
    if not files:
        raise RuntimeError(f"no .txt files found in {LIVE_TEST_FILES_DIR}")

    admin = ensure_admin()
    uploaded_rounds = 0
    while current_pending < required_pending and uploaded_rounds < 10:
        uploaded_rounds += 1
        uploaded_in_round = 0
        for file_path in files:
            with open(file_path, "rb") as f:
                payload = f.read()
            storage = FileStorage(
                stream=io.BytesIO(payload),
                filename=file_path.name,
                content_type="text/plain",
            )
            result = process_uploaded_file(storage, uploader_id=admin.id)
            if result.get("success"):
                uploaded_in_round += result.get("ticket_count", 0)
        current_pending = get_pool_status()["total_pending"]
        print(f"[setup] upload round {uploaded_rounds}: +{uploaded_in_round} tickets, pending={current_pending}")

    if current_pending < required_pending:
        raise RuntimeError(
            f"pending tickets still insufficient after uploads: required={required_pending}, actual={current_pending}"
        )
    return current_pending


def prepare_live_environment():
    app = create_app()
    with app.app_context():
        db.create_all()
        ensure_admin()
        ensure_settings()
        ensure_test_accounts()
        reset_test_account_tickets()

        required_pending = DEVICES_PER_ACCOUNT * 2 * MODE_A_REQUESTS_PER_DEVICE
        required_pending += DEVICES_PER_ACCOUNT * 2 * MODE_B_BATCH_COUNT
        required_pending += 40  # leave headroom over the mode B reserve

        pending = import_test_files_until_sufficient(required_pending)
        print(f"[setup] environment ready, pending tickets={pending}")
    scheduler = scheduler_module.get_scheduler()
    if scheduler:
        scheduler.shutdown(wait=False)
        scheduler_module._scheduler = None


def wait_for_server():
    deadline = time.time() + SERVER_START_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", 5000), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("server did not start in time")


def start_server_process():
    log_file = open(SERVER_LOG_PATH, "w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from app import create_app; from extensions import socketio; "
            "app=create_app(); "
            "socketio.run(app, host='127.0.0.1', port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)",
        ],
        cwd=ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_for_server()
        return process, log_file
    except Exception:
        process.terminate()
        process.wait(timeout=10)
        log_file.close()
        raise


def stop_server_process(process: subprocess.Popen, log_file):
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
    log_file.close()


def make_session(username: str, device_label: str):
    session = requests.Session()
    device_id = f"{device_label}-{uuid.uuid4().hex[:8]}"
    device_name = f"{device_label}-{RUN_LABEL}"

    resp = session.post(
        f"{BASE_URL}/auth/login",
        json={"username": username, "password": TEST_PASSWORD, "device_id": device_id},
        timeout=DEVICE_REQUEST_TIMEOUT_SECONDS,
    )
    if resp.status_code != 200 or not resp.json().get("success"):
        return None, device_id, device_name, resp.text

    register_resp = session.post(
        f"{BASE_URL}/api/device/register",
        json={
            "device_id": device_id,
            "device_name": device_name,
            "client_info": {"test": True, "live_concurrency": True},
        },
        timeout=DEVICE_REQUEST_TIMEOUT_SECONDS,
    )
    if register_resp.status_code not in (200, 201):
        return None, device_id, device_name, register_resp.text

    return session, device_id, device_name, None


def worker_mode_a(username: str, device_label: str, assigned_ids: list[int], errors: list[str]):
    session, device_id, device_name, error = make_session(username, device_label)
    if session is None:
        with LOCK:
            errors.append(f"{device_label}: login/register failed: {error}")
        return

    for _ in range(MODE_A_REQUESTS_PER_DEVICE):
        started = time.time()
        try:
            resp = session.post(
                f"{BASE_URL}/api/mode-a/next",
                json={"device_id": device_id, "device_name": device_name},
                timeout=DEVICE_REQUEST_TIMEOUT_SECONDS,
            )
            elapsed = time.time() - started
            data = resp.json()
            ticket_id = data.get("ticket", {}).get("id") if data.get("ticket") else None
            if data.get("success") and ticket_id:
                stop_resp = session.post(
                    f"{BASE_URL}/api/mode-a/stop",
                    json={"device_id": device_id},
                    timeout=DEVICE_REQUEST_TIMEOUT_SECONDS,
                )
                stop_data = stop_resp.json()
                if not stop_data.get("success"):
                    raise RuntimeError(f"mode_a stop failed: {stop_data}")
            with LOCK:
                RESULTS.append(
                    {
                        "device": device_label,
                        "username": username,
                        "mode": "A",
                        "status_code": resp.status_code,
                        "elapsed": elapsed,
                        "success": data.get("success"),
                        "ticket_ids": [ticket_id] if ticket_id else [],
                        "error": data.get("error"),
                    }
                )
                if data.get("success") and ticket_id:
                    assigned_ids.append(ticket_id)
        except Exception as e:
            with LOCK:
                errors.append(f"{device_label} mode_a: {e}")


def worker_mode_b(username: str, device_label: str, assigned_ids: list[int], errors: list[str]):
    session, device_id, device_name, error = make_session(username, device_label)
    if session is None:
        with LOCK:
            errors.append(f"{device_label}: login/register failed: {error}")
        return

    started = time.time()
    try:
        resp = session.post(
            f"{BASE_URL}/api/mode-b/download",
            json={
                "count": MODE_B_BATCH_COUNT,
                "device_id": device_id,
                "device_name": device_name,
            },
            timeout=DEVICE_REQUEST_TIMEOUT_SECONDS,
        )
        elapsed = time.time() - started
        data = resp.json()
        ticket_ids = []
        if data.get("success"):
            for file_entry in data.get("files", []):
                ticket_ids.extend(file_entry.get("ticket_ids", []))
            if ticket_ids:
                confirm_resp = session.post(
                    f"{BASE_URL}/api/mode-b/confirm",
                    json={"ticket_ids": ticket_ids},
                    timeout=DEVICE_REQUEST_TIMEOUT_SECONDS,
                )
                confirm_data = confirm_resp.json()
                if not confirm_data.get("success"):
                    raise RuntimeError(f"mode_b confirm failed: {confirm_data}")

        with LOCK:
            RESULTS.append(
                {
                    "device": device_label,
                    "username": username,
                    "mode": "B",
                    "status_code": resp.status_code,
                    "elapsed": elapsed,
                    "success": data.get("success"),
                    "ticket_ids": ticket_ids,
                    "actual_count": data.get("actual_count", 0),
                    "error": data.get("error"),
                }
            )
            assigned_ids.extend(ticket_ids)
    except Exception as e:
        with LOCK:
            errors.append(f"{device_label} mode_b: {e}")


def build_threads(assigned_ids: list[int], errors: list[str]):
    threads = []
    for index in range(DEVICES_PER_ACCOUNT):
        threads.append(
            threading.Thread(
                target=worker_mode_a,
                args=("load_mode_a_1", f"A1-D{index + 1:02d}", assigned_ids, errors),
                daemon=True,
            )
        )
        threads.append(
            threading.Thread(
                target=worker_mode_a,
                args=("load_mode_a_2", f"A2-D{index + 1:02d}", assigned_ids, errors),
                daemon=True,
            )
        )
        threads.append(
            threading.Thread(
                target=worker_mode_b,
                args=("load_mode_b_1", f"B1-D{index + 1:02d}", assigned_ids, errors),
                daemon=True,
            )
        )
        threads.append(
            threading.Thread(
                target=worker_mode_b,
                args=("load_mode_b_2", f"B2-D{index + 1:02d}", assigned_ids, errors),
                daemon=True,
            )
        )
    return threads


def summarize_results(all_assigned_ids: list[int], errors: list[str], total_elapsed: float):
    success_results = [item for item in RESULTS if item.get("success")]
    failed_results = [item for item in RESULTS if not item.get("success")]
    duplicate_ids = [ticket_id for ticket_id, count in Counter(all_assigned_ids).items() if count > 1]
    slow_requests = [item for item in RESULTS if item.get("elapsed", 0) > 3.0]
    mode_a_success = sum(1 for item in success_results if item["mode"] == "A")
    mode_b_success = sum(1 for item in success_results if item["mode"] == "B")
    total_mode_b_tickets = sum(item.get("actual_count", 0) for item in success_results if item["mode"] == "B")

    print("\n" + "=" * 72)
    print(f"total elapsed: {total_elapsed:.2f}s")
    print(f"requests: {len(RESULTS)} success={len(success_results)} errors={len(errors)}")
    print(f"mode A success: {mode_a_success}")
    print(f"mode B success: {mode_b_success}, downloaded tickets={total_mode_b_tickets}")
    print(f"assigned ticket ids collected: {len(all_assigned_ids)}")
    print(f"duplicate ticket ids in responses: {duplicate_ids[:20]}")
    print(f"slow requests (>3s): {len(slow_requests)}")
    if failed_results:
        print("failed responses:")
        for item in failed_results[:20]:
            print(
                f"  - {item['device']} {item['mode']} status={item['status_code']} "
                f"error={item.get('error')} actual_count={item.get('actual_count')}"
            )
    if errors:
        print("errors:")
        for item in errors[:20]:
            print(f"  - {item}")

    checker = requests.Session()
    login_resp = checker.post(
        f"{BASE_URL}/auth/login",
        json={"username": "load_mode_b_1", "password": TEST_PASSWORD, "device_id": f"checker-{uuid.uuid4().hex[:6]}"},
        timeout=DEVICE_REQUEST_TIMEOUT_SECONDS,
    )
    if login_resp.status_code == 200:
        pool_resp = checker.get(f"{BASE_URL}/api/mode-b/pool-status", timeout=DEVICE_REQUEST_TIMEOUT_SECONDS)
        if pool_resp.status_code == 200:
            pool_data = pool_resp.json()
            print(f"pool remaining after run: {pool_data.get('total_pending', 0)}")
            print("pool by_type after run:")
            for entry in pool_data.get("by_type", [])[:20]:
                print(
                    f"  - type={entry.get('lottery_type')} "
                    f"deadline={entry.get('deadline_time')} count={entry.get('count')}"
                )

    print("=" * 72)
    return duplicate_ids, slow_requests


def test_concurrent_40_devices_core_ticket_distribution():
    RESULTS.clear()
    prepare_live_environment()
    process, log_file = start_server_process()

    try:
        errors = []
        all_assigned_ids = []
        threads = build_threads(all_assigned_ids, errors)

        inspector = requests.Session()
        inspector_login = inspector.post(
            f"{BASE_URL}/auth/login",
            json={"username": "load_mode_b_1", "password": TEST_PASSWORD, "device_id": f"inspector-{uuid.uuid4().hex[:6]}"},
            timeout=DEVICE_REQUEST_TIMEOUT_SECONDS,
        )
        if inspector_login.status_code == 200:
            before_pool_resp = inspector.get(f"{BASE_URL}/api/mode-b/pool-status", timeout=DEVICE_REQUEST_TIMEOUT_SECONDS)
            if before_pool_resp.status_code == 200:
                before_pool = before_pool_resp.json()
                print(f"pool before run: {before_pool.get('total_pending', 0)}")
                print("pool by_type before run:")
                for entry in before_pool.get("by_type", [])[:20]:
                    print(
                        f"  - type={entry.get('lottery_type')} "
                        f"deadline={entry.get('deadline_time')} count={entry.get('count')}"
                    )

        started = time.time()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=45)
        total_elapsed = time.time() - started

        duplicate_ids, slow_requests = summarize_results(all_assigned_ids, errors, total_elapsed)

        assert not errors, f"concurrency run produced errors: {errors[:10]}"
        assert RESULTS, "no requests were recorded"
        assert not duplicate_ids, f"duplicate ticket ids detected: {duplicate_ids[:10]}"

        expected_mode_a_success = DEVICES_PER_ACCOUNT * 2 * MODE_A_REQUESTS_PER_DEVICE
        expected_mode_b_success = DEVICES_PER_ACCOUNT * 2
        actual_mode_a_success = sum(1 for item in RESULTS if item["mode"] == "A" and item.get("success"))
        actual_mode_b_success = sum(1 for item in RESULTS if item["mode"] == "B" and item.get("success"))

        assert actual_mode_a_success == expected_mode_a_success, (
            f"mode A success mismatch: expected {expected_mode_a_success}, got {actual_mode_a_success}"
        )
        assert actual_mode_b_success == expected_mode_b_success, (
            f"mode B success mismatch: expected {expected_mode_b_success}, got {actual_mode_b_success}"
        )
        assert len(slow_requests) <= 5, f"too many slow requests: {len(slow_requests)}"

        app = create_app()
        with app.app_context():
            from models.ticket import LotteryTicket

            remaining_assigned = LotteryTicket.query.filter_by(status="assigned").count()
            assert remaining_assigned == 0, f"assigned tickets left behind after full flow: {remaining_assigned}"
    finally:
        stop_server_process(process, log_file)
