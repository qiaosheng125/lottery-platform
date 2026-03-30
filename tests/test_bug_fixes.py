import os
import sys
from pathlib import Path
from datetime import timedelta
import io

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tasks.scheduler as scheduler_module
from app import create_app
from extensions import db
from models.settings import SystemSettings
from models.file import UploadedFile
from models.ticket import LotteryTicket
from models.user import User
from utils.time_utils import beijing_now
from routes.admin import _database_display_info


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setattr(scheduler_module, "start_scheduler", lambda app: None)

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    with app.app_context():
        db.drop_all()
        db.create_all()
        SystemSettings.get()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def create_user(username: str, password: str, client_mode: str = "mode_b") -> User:
    user = User(username=username, client_mode=client_mode, max_devices=5, can_receive=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, username: str, password: str):
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )


def test_login_json_post_stays_json_for_authenticated_user(app, client):
    with app.app_context():
        create_user("login_json_user", "secret123", client_mode="mode_a")

    first = login(client, "login_json_user", "secret123")
    assert first.status_code == 200
    assert first.is_json is True

    second = login(client, "login_json_user", "secret123")
    assert second.status_code == 200
    assert second.is_json is True
    data = second.get_json()
    assert data["success"] is True
    assert data["redirect"] == "/api/user/dashboard"


def test_create_app_bootstraps_empty_sqlite(monkeypatch, tmp_path):
    db_path = tmp_path / "bootstrap.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setattr(scheduler_module, "start_scheduler", lambda app: None)

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        admin = User.query.filter_by(username="zucaixu", is_admin=True).first()
        settings = SystemSettings.get()
        assert admin is not None
        assert settings is not None


def test_create_app_normalizes_relative_sqlite_path(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///single.db")
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setattr(scheduler_module, "start_scheduler", lambda app: None)

    app = create_app()
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    assert uri.startswith("sqlite:///")
    assert uri.endswith("/instance/single.db")


def test_database_display_info_uses_runtime_sqlite_path(app):
    with app.app_context():
        info = _database_display_info()
        assert info["engine"] == "sqlite"
        assert "test.sqlite" in info["path"]


def create_assigned_ticket(user: User, device_id: str, raw_content: str, line_number: int) -> LotteryTicket:
    ticket = LotteryTicket(
        source_file_id=1,
        line_number=line_number,
        raw_content=raw_content,
        status="assigned",
        assigned_user_id=user.id,
        assigned_username=user.username,
        assigned_device_id=device_id,
        assigned_device_name=device_id,
        assigned_at=beijing_now(),
    )
    db.session.add(ticket)
    db.session.commit()
    return ticket


def create_pending_ticket(raw_content: str, line_number: int) -> LotteryTicket:
    ticket = LotteryTicket(
        source_file_id=1,
        line_number=line_number,
        raw_content=raw_content,
        status="pending",
        deadline_time=(beijing_now() + timedelta(hours=1)).replace(microsecond=0),
    )
    db.session.add(ticket)
    db.session.commit()
    return ticket


def test_mode_b_processing_without_device_id_returns_all_batches(app, client):
    with app.app_context():
        user = create_user("modeb_user", "secret123", client_mode="mode_b")
        create_assigned_ticket(user, "device-a", "A001", 1)
        create_assigned_ticket(user, "device-b", "B001", 2)

    resp = login(client, "modeb_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-b/processing")
    assert resp.status_code == 200

    data = resp.get_json()
    assert data["success"] is True
    total_count = sum(batch["count"] for batch in data["batches"])
    all_ticket_ids = sorted(ticket_id for batch in data["batches"] for ticket_id in batch["ticket_ids"])
    assert total_count == 2
    assert len(all_ticket_ids) == 2


def test_mode_b_processing_with_device_id_filters_batches(app, client):
    with app.app_context():
        user = create_user("modeb_user_filter", "secret123", client_mode="mode_b")
        create_assigned_ticket(user, "device-a", "A001", 1)
        create_assigned_ticket(user, "device-b", "B001", 2)

    resp = login(client, "modeb_user_filter", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-b/processing?device_id=device-a")
    assert resp.status_code == 200

    data = resp.get_json()
    assert data["success"] is True
    assert len(data["batches"]) == 1
    assert data["batches"][0]["count"] == 1


def test_mode_a_next_does_not_complete_current_ticket_without_explicit_ticket_id(app, client):
    with app.app_context():
        user = create_user("modea_user", "secret123", client_mode="mode_a")
        current_ticket = create_assigned_ticket(user, "device-a", "CUR001", 1)
        create_pending_ticket("NEXT001", 2)
        current_ticket_id = current_ticket.id

    resp = login(client, "modea_user", "secret123")
    assert resp.status_code == 200

    resp = client.post("/api/mode-a/next", json={"device_id": "device-a", "device_name": "Device A"})
    assert resp.status_code == 200

    data = resp.get_json()
    assert data["success"] is True
    assert data["ticket"]["id"] == current_ticket_id

    with app.app_context():
        current = LotteryTicket.query.get(current_ticket_id)
        pending = LotteryTicket.query.filter_by(raw_content="NEXT001").first()
        assert current.status == "assigned"
        assert pending.status == "pending"


def test_mode_a_next_ignores_stale_completion_ticket_id(app, client):
    with app.app_context():
        user = create_user("modea_retry_user", "secret123", client_mode="mode_a")
        first_ticket = create_assigned_ticket(user, "device-a", "CUR001", 1)
        next_ticket = create_pending_ticket("NEXT001", 2)
        first_ticket_id = first_ticket.id
        next_ticket_id = next_ticket.id

    resp = login(client, "modea_retry_user", "secret123")
    assert resp.status_code == 200

    resp = client.post(
            "/api/mode-a/next",
            json={
                "device_id": "device-a",
                "device_name": "Device A",
                "complete_current_ticket_id": first_ticket_id,
            },
        )
    data = resp.get_json()
    assert data["success"] is True
    assert data["ticket"]["id"] == next_ticket_id

    resp = client.post(
            "/api/mode-a/next",
            json={
                "device_id": "device-a",
                "device_name": "Device A",
                "complete_current_ticket_id": first_ticket_id,
            },
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["ticket"]["id"] == next_ticket_id

    with app.app_context():
        first = LotteryTicket.query.get(first_ticket_id)
        current = LotteryTicket.query.get(next_ticket_id)
        assert first.status == "completed"
        assert current.status == "assigned"


def test_pool_status_returns_empty_when_pool_disabled(app, client):
    with app.app_context():
        user = create_user("pool_user", "secret123", client_mode="mode_b")
        create_pending_ticket("PENDING001", 1)
        settings = SystemSettings.get()
        settings.pool_enabled = False
        db.session.commit()

    resp = login(client, "pool_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/pool/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["pool_enabled"] is False
    assert data["total_pending"] == 0
    assert data["by_type"] == []


def test_mode_b_pool_status_returns_empty_when_pool_disabled(app, client):
    with app.app_context():
        user = create_user("pool_mode_b_user", "secret123", client_mode="mode_b")
        create_pending_ticket("PENDING002", 1)
        settings = SystemSettings.get()
        settings.pool_enabled = False
        db.session.commit()

    resp = login(client, "pool_mode_b_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-b/pool-status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["total_pending"] == 0
    assert data["by_type"] == []


def test_deleted_user_session_invalidates_api_access(app, client):
    with app.app_context():
        user = create_user("session_user", "secret123", client_mode="mode_a")

    resp = login(client, "session_user", "secret123")
    assert resp.status_code == 200

    with app.app_context():
        from models.user import UserSession

        UserSession.query.delete()
        db.session.commit()

    resp = client.get("/api/user/daily-stats")
    assert resp.status_code == 401
    data = resp.get_json()
    assert data["success"] is False


def test_expired_user_session_invalidates_api_access(app, client):
    with app.app_context():
        user = create_user("expired_session_user", "secret123", client_mode="mode_a")

    resp = login(client, "expired_session_user", "secret123")
    assert resp.status_code == 200

    with app.app_context():
        from models.user import UserSession

        session = UserSession.query.first()
        session.expires_at = beijing_now() - timedelta(minutes=1)
        db.session.commit()

    resp = client.get("/api/user/daily-stats")
    assert resp.status_code == 401
    data = resp.get_json()
    assert data["success"] is False


def test_upload_winning_image_creates_winning_record(app, client):
    from PIL import Image

    with app.app_context():
        user = create_user("winning_user", "secret123", client_mode="mode_a")
        ticket = create_assigned_ticket(user, "device-a", "WIN001", 1)
        user_id = user.id
        ticket_id = ticket.id

    resp = login(client, "winning_user", "secret123")
    assert resp.status_code == 200

    image_bytes = io.BytesIO()
    Image.new("RGB", (20, 20), color="red").save(image_bytes, format="PNG")
    image_bytes.seek(0)

    resp = client.post(
        f"/api/winning/upload-image/{ticket_id}",
        data={"image": (image_bytes, "winning.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True

    with app.app_context():
        from models.winning import WinningRecord

        ticket = LotteryTicket.query.get(ticket_id)
        record = WinningRecord.query.filter_by(ticket_id=ticket_id).first()
        assert ticket.winning_image_url
        assert ticket.is_winning is True
        assert record is not None
        assert record.winning_image_url == ticket.winning_image_url
        assert record.uploaded_by == user_id


def test_expire_overdue_tickets_updates_file_counters(app):
    from tasks.expire_tickets import expire_overdue_tickets

    with app.app_context():
        user = create_user("expire_user", "secret123", client_mode="mode_a")
        uploaded_file = UploadedFile(
            display_id="2026/03/30-01",
            original_filename="expired.txt",
            stored_filename="expired.txt",
            uploaded_by=user.id,
            total_tickets=2,
            pending_count=1,
            assigned_count=1,
            completed_count=0,
        )
        db.session.add(uploaded_file)
        db.session.commit()

        db.session.add(LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=1,
            raw_content="PENDING-EXPIRED",
            status="pending",
            deadline_time=beijing_now() - timedelta(minutes=1),
        ))
        db.session.add(LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=2,
            raw_content="ASSIGNED-EXPIRED",
            status="assigned",
            assigned_user_id=user.id,
            assigned_username=user.username,
            assigned_device_id="device-a",
            assigned_device_name="device-a",
            deadline_time=beijing_now() - timedelta(minutes=1),
        ))
        db.session.commit()

        expire_overdue_tickets()

        refreshed = UploadedFile.query.get(uploaded_file.id)
        statuses = {t.status for t in LotteryTicket.query.filter_by(source_file_id=uploaded_file.id).all()}
        assert statuses == {"expired"}
        assert refreshed.pending_count == 0
        assert refreshed.assigned_count == 0


def test_public_register_page_redirects_to_login(client):
    resp = client.get("/auth/register", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/auth/login")


def test_public_register_json_returns_403(client):
    resp = client.post(
        "/auth/register",
        json={"username": "new_form_user", "password": "secret123"},
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False


def test_dashboard_uses_correct_change_password_endpoint():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "fetch('/api/user/change-password'" in content
    assert "fetch('/user/change-password'" not in content
