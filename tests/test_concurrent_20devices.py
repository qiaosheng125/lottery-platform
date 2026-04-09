"""
Live concurrency test for the core ticket assignment flow.

Default scenario:
- 4 accounts total: 2 mode A, 2 mode B
- 10 devices per account, 40 devices concurrent
- Each mode B device downloads 20 tickets once
- Each mode A device requests one ticket once

This script also supports strict multi-worker acceptance runs via env vars.

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
from decimal import Decimal
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
DEVICES_PER_ACCOUNT = int(os.environ.get("LIVE_TEST_DEVICES_PER_ACCOUNT", "10"))
MODE_A_DEVICES_PER_ACCOUNT = int(os.environ.get("LIVE_TEST_MODE_A_DEVICES_PER_ACCOUNT", str(DEVICES_PER_ACCOUNT)))
MODE_B_DEVICES_PER_ACCOUNT = int(os.environ.get("LIVE_TEST_MODE_B_DEVICES_PER_ACCOUNT", str(DEVICES_PER_ACCOUNT)))
MODE_B_BATCH_COUNT = int(os.environ.get("LIVE_TEST_MODE_B_BATCH_COUNT", "20"))
MODE_A_REQUESTS_PER_DEVICE = int(os.environ.get("LIVE_TEST_MODE_A_REQUESTS_PER_DEVICE", "1"))
MODE_A_ACCOUNT_COUNT = int(os.environ.get("LIVE_TEST_MODE_A_ACCOUNTS", "2"))
MODE_B_ACCOUNT_COUNT = int(os.environ.get("LIVE_TEST_MODE_B_ACCOUNTS", "2"))
PENDING_HEADROOM = int(os.environ.get("LIVE_TEST_PENDING_HEADROOM", "40"))
SERVER_START_TIMEOUT_SECONDS = 30
DEVICE_REQUEST_TIMEOUT_SECONDS = 20
LIVE_TEST_FILES_DIR = ROOT / "tests" / "live_test_files"
SERVER_LOG_PATH = ROOT / "tests" / "live_concurrency_server.log"
RUN_LABEL = uuid.uuid4().hex[:6]
LIVE_TEST_SERVER_MODE = os.environ.get("LIVE_TEST_SERVER_MODE", "socketio").lower()
LIVE_TEST_GUNICORN_WORKERS = int(os.environ.get("LIVE_TEST_GUNICORN_WORKERS", "2"))
LIVE_TEST_STRICT_DEVICE_GUARD = os.environ.get("LIVE_TEST_STRICT_DEVICE_GUARD", "1") == "1"
LIVE_TEST_MAX_SLOW_REQUESTS = int(os.environ.get("LIVE_TEST_MAX_SLOW_REQUESTS", "5"))

TEST_ACCOUNTS = (
    [{"username": f"load_mode_a_{i}", "client_mode": "mode_a"} for i in range(1, MODE_A_ACCOUNT_COUNT + 1)]
    + [{"username": f"load_mode_b_{i}", "client_mode": "mode_b"} for i in range(1, MODE_B_ACCOUNT_COUNT + 1)]
)

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
                max_devices=(
                    MODE_A_DEVICES_PER_ACCOUNT + 2
                    if account["client_mode"] == "mode_a"
                    else MODE_B_DEVICES_PER_ACCOUNT + 2
                ),
                can_receive=True,
            )
            user.set_password(TEST_PASSWORD)
            db.session.add(user)
        else:
            user.client_mode = account["client_mode"]
            user.max_devices = (
                MODE_A_DEVICES_PER_ACCOUNT + 2
                if account["client_mode"] == "mode_a"
                else MODE_B_DEVICES_PER_ACCOUNT + 2
            )
            user.can_receive = True
            user.is_active = True
            user.max_processing_b_mode = max(
                user.max_processing_b_mode or 0,
                MODE_B_DEVICES_PER_ACCOUNT * MODE_B_BATCH_COUNT + 50,
            )
        if account["client_mode"] == "mode_b":
            user.max_processing_b_mode = MODE_B_DEVICES_PER_ACCOUNT * MODE_B_BATCH_COUNT * 3
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

    recycled_tickets = LotteryTicket.query.filter(
        LotteryTicket.assigned_user_id.in_(user_ids),
        LotteryTicket.status.in_(["assigned", "completed"]),
    ).all()

    touched_file_ids = set()
    for ticket in recycled_tickets:
        touched_file_ids.add(ticket.source_file_id)
        ticket.status = 'pending'
        ticket.assigned_user_id = None
        ticket.assigned_username = None
        ticket.assigned_device_id = None
        ticket.assigned_device_name = None
        ticket.assigned_at = None
        ticket.completed_at = None
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

        required_pending = MODE_A_DEVICES_PER_ACCOUNT * MODE_A_ACCOUNT_COUNT * MODE_A_REQUESTS_PER_DEVICE
        required_pending += MODE_B_DEVICES_PER_ACCOUNT * MODE_B_ACCOUNT_COUNT * MODE_B_BATCH_COUNT
        required_pending += PENDING_HEADROOM

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
    if LIVE_TEST_SERVER_MODE == "gunicorn":
        if os.name == "nt":
            log_file.close()
            raise RuntimeError(
                "gunicorn multi-worker live validation is unsupported on Windows; "
                "run this test on a Linux host with PostgreSQL + Redis"
            )
        command = [
            sys.executable,
            "-m",
            "gunicorn",
            "-c",
            str(ROOT / "gunicorn_config.py"),
            "-w",
            str(LIVE_TEST_GUNICORN_WORKERS),
            "-b",
            "127.0.0.1:5000",
            "app:create_app()",
        ]
    else:
        command = [
            sys.executable,
            "-c",
            "from app import create_app; from extensions import socketio; "
            "app=create_app(); "
            "socketio.run(app, host='127.0.0.1', port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)",
        ]

    process = subprocess.Popen(
        command,
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

    try:
        resp = session.post(
            f"{BASE_URL}/auth/login",
            json={"username": username, "password": TEST_PASSWORD, "device_id": device_id},
            timeout=DEVICE_REQUEST_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200 or not resp.json().get("success"):
            return None, device_id, device_name, f"login failed: status={resp.status_code} body={resp.text}"

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
            return None, device_id, device_name, (
                f"register failed: status={register_resp.status_code} body={register_resp.text}"
            )
    except Exception as exc:
        return None, device_id, device_name, f"{type(exc).__name__}: {exc}"

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
                        "device_id": device_id,
                        "device_name": device_name,
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
                if LIVE_TEST_STRICT_DEVICE_GUARD:
                    wrong_confirm_resp = session.post(
                        f"{BASE_URL}/api/mode-b/confirm",
                        json={"ticket_ids": ticket_ids, "device_id": f"wrong-{device_id}"},
                        timeout=DEVICE_REQUEST_TIMEOUT_SECONDS,
                    )
                    wrong_confirm_data = wrong_confirm_resp.json()
                    if wrong_confirm_data.get("success"):
                        raise RuntimeError(
                            f"mode_b wrong-device confirm unexpectedly succeeded: {wrong_confirm_data}"
                        )

                confirm_resp = session.post(
                    f"{BASE_URL}/api/mode-b/confirm",
                    json={"ticket_ids": ticket_ids, "device_id": device_id},
                    timeout=DEVICE_REQUEST_TIMEOUT_SECONDS,
                )
                confirm_data = confirm_resp.json()
                if not confirm_data.get("success"):
                    raise RuntimeError(f"mode_b confirm failed: {confirm_data}")

        with LOCK:
            RESULTS.append(
                {
                    "device": device_label,
                    "device_id": device_id,
                    "device_name": device_name,
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
    for account in TEST_ACCOUNTS:
        prefix = "A" if account["client_mode"] == "mode_a" else "B"
        suffix = account["username"].rsplit("_", 1)[-1]
        worker = worker_mode_a if account["client_mode"] == "mode_a" else worker_mode_b
        per_account_devices = (
            MODE_A_DEVICES_PER_ACCOUNT if account["client_mode"] == "mode_a" else MODE_B_DEVICES_PER_ACCOUNT
        )
        for index in range(per_account_devices):
            threads.append(
                threading.Thread(
                    target=worker,
                    args=(account["username"], f"{prefix}{suffix}-D{index + 1:02d}", assigned_ids, errors),
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

    checker_account = next((account for account in TEST_ACCOUNTS if account["client_mode"] == "mode_b"), None)
    if checker_account:
        checker = requests.Session()
        login_resp = checker.post(
            f"{BASE_URL}/auth/login",
            json={"username": checker_account["username"], "password": TEST_PASSWORD, "device_id": f"checker-{uuid.uuid4().hex[:6]}"},
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


def validate_strict_invariants():
    app = create_app()
    with app.app_context():
        usernames = [account["username"] for account in TEST_ACCOUNTS]
        test_users = {
            user.username: user
            for user in User.query.filter(User.username.in_(usernames)).all()
        }
        assert len(test_users) == len(TEST_ACCOUNTS), "missing test accounts in database"

        success_results = [item for item in RESULTS if item.get("success")]
        ownership = {}
        for item in success_results:
            for ticket_id in item.get("ticket_ids", []):
                if ticket_id in ownership:
                    raise AssertionError(f"ticket {ticket_id} claimed twice in success results")
                ownership[ticket_id] = item

        if not ownership:
            raise AssertionError("strict validation found no successfully claimed ticket ids")

        tickets = LotteryTicket.query.filter(LotteryTicket.id.in_(list(ownership.keys()))).all()
        ticket_map = {ticket.id: ticket for ticket in tickets}
        missing_ids = [ticket_id for ticket_id in ownership if ticket_id not in ticket_map]
        assert not missing_ids, f"claimed tickets missing from database: {missing_ids[:10]}"

        touched_file_ids = set()
        per_user_completed = Counter()
        per_user_assigned = Counter()

        for ticket_id, result in ownership.items():
            ticket = ticket_map[ticket_id]
            touched_file_ids.add(ticket.source_file_id)
            expected_user = test_users[result["username"]]

            assert ticket.status == "completed", f"ticket {ticket_id} not completed: {ticket.status}"
            assert ticket.assigned_user_id == expected_user.id, (
                f"ticket {ticket_id} assigned_user mismatch: expected {expected_user.id}, got {ticket.assigned_user_id}"
            )
            assert ticket.assigned_username == result["username"], (
                f"ticket {ticket_id} assigned_username mismatch: expected {result['username']}, got {ticket.assigned_username}"
            )
            assert ticket.assigned_device_id == result["device_id"], (
                f"ticket {ticket_id} device mismatch: expected {result['device_id']}, got {ticket.assigned_device_id}"
            )
            assert ticket.assigned_device_name == result["device_name"], (
                f"ticket {ticket_id} device_name mismatch: expected {result['device_name']}, got {ticket.assigned_device_name}"
            )
            assert ticket.completed_at is not None, f"ticket {ticket_id} completed_at missing"
            per_user_completed[result["username"]] += 1

        lingering_assigned = LotteryTicket.query.filter(
            LotteryTicket.assigned_user_id.in_([user.id for user in test_users.values()]),
            LotteryTicket.status == "assigned",
        ).all()
        assert not lingering_assigned, f"assigned tickets left behind: {[ticket.id for ticket in lingering_assigned[:10]]}"

        for username, user in test_users.items():
            per_user_assigned[username] = LotteryTicket.query.filter(
                LotteryTicket.assigned_user_id == user.id,
                LotteryTicket.status == "assigned",
            ).count()
            if user.daily_ticket_limit is not None:
                assert per_user_completed[username] <= user.daily_ticket_limit, (
                    f"user {username} exceeded daily_ticket_limit: {per_user_completed[username]} > {user.daily_ticket_limit}"
                )
            if user.max_processing_b_mode is not None:
                assert per_user_assigned[username] <= user.max_processing_b_mode, (
                    f"user {username} exceeded max_processing_b_mode: {per_user_assigned[username]} > {user.max_processing_b_mode}"
                )

        for file_id in touched_file_ids:
            uploaded_file = db.session.get(UploadedFile, file_id)
            assert uploaded_file is not None, f"missing uploaded_file {file_id}"
            pending_count = LotteryTicket.query.filter_by(source_file_id=file_id, status="pending").count()
            assigned_count = LotteryTicket.query.filter_by(source_file_id=file_id, status="assigned").count()
            completed_count = LotteryTicket.query.filter_by(source_file_id=file_id, status="completed").count()
            expired_count = LotteryTicket.query.filter_by(source_file_id=file_id, status="expired").count()
            revoked_count = LotteryTicket.query.filter_by(source_file_id=file_id, status="revoked").count()

            actual_total = pending_count + assigned_count + completed_count + expired_count + revoked_count
            assert uploaded_file.total_tickets == actual_total, (
                f"file {file_id} total mismatch: denorm={uploaded_file.total_tickets}, actual={actual_total}"
            )
            assert uploaded_file.pending_count == pending_count, (
                f"file {file_id} pending_count mismatch: denorm={uploaded_file.pending_count}, actual={pending_count}"
            )
            assert uploaded_file.assigned_count == assigned_count, (
                f"file {file_id} assigned_count mismatch: denorm={uploaded_file.assigned_count}, actual={assigned_count}"
            )
            assert uploaded_file.completed_count == completed_count, (
                f"file {file_id} completed_count mismatch: denorm={uploaded_file.completed_count}, actual={completed_count}"
            )

            amount_total = db.session.query(db.func.coalesce(db.func.sum(LotteryTicket.ticket_amount), Decimal("0"))).filter(
                LotteryTicket.source_file_id == file_id
            ).scalar()
            assert Decimal(uploaded_file.actual_total_amount or 0) == Decimal(amount_total or 0), (
                f"file {file_id} actual_total_amount drifted: denorm={uploaded_file.actual_total_amount}, actual={amount_total}"
            )


def test_concurrent_40_devices_core_ticket_distribution():
    RESULTS.clear()
    prepare_live_environment()
    process, log_file = start_server_process()

    try:
        errors = []
        all_assigned_ids = []
        threads = build_threads(all_assigned_ids, errors)

        inspector_account = next((account for account in TEST_ACCOUNTS if account["client_mode"] == "mode_b"), None)
        if inspector_account:
            inspector = requests.Session()
            inspector_login = inspector.post(
                f"{BASE_URL}/auth/login",
                json={"username": inspector_account["username"], "password": TEST_PASSWORD, "device_id": f"inspector-{uuid.uuid4().hex[:6]}"},
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

        expected_mode_a_success = MODE_A_DEVICES_PER_ACCOUNT * MODE_A_ACCOUNT_COUNT * MODE_A_REQUESTS_PER_DEVICE
        expected_mode_b_success = MODE_B_DEVICES_PER_ACCOUNT * MODE_B_ACCOUNT_COUNT
        actual_mode_a_success = sum(1 for item in RESULTS if item["mode"] == "A" and item.get("success"))
        actual_mode_b_success = sum(1 for item in RESULTS if item["mode"] == "B" and item.get("success"))

        assert actual_mode_a_success == expected_mode_a_success, (
            f"mode A success mismatch: expected {expected_mode_a_success}, got {actual_mode_a_success}"
        )
        assert actual_mode_b_success == expected_mode_b_success, (
            f"mode B success mismatch: expected {expected_mode_b_success}, got {actual_mode_b_success}"
        )
        assert len(slow_requests) <= LIVE_TEST_MAX_SLOW_REQUESTS, (
            f"too many slow requests: {len(slow_requests)} > {LIVE_TEST_MAX_SLOW_REQUESTS}"
        )

        validate_strict_invariants()

        app = create_app()
        with app.app_context():
            remaining_assigned = LotteryTicket.query.filter_by(status="assigned").count()
            assert remaining_assigned == 0, f"assigned tickets left behind after full flow: {remaining_assigned}"
    finally:
        stop_server_process(process, log_file)
