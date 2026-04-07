import os
import sys
import builtins
from pathlib import Path
from datetime import datetime, timedelta
import io

import pytest
from werkzeug.datastructures import FileStorage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tasks.scheduler as scheduler_module
from app import create_app
from extensions import db
from models.audit import AuditLog
from models.settings import SystemSettings
from models.file import UploadedFile
from models.ticket import LotteryTicket
from models.user import User
from models.result import MatchResult
from models.archive import ArchivedLotteryTicket
from models.winning import WinningRecord
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
    assert data["client_mode"] == "mode_a"


def test_login_json_returns_client_mode(app, client):
    with app.app_context():
        create_user("login_modeb_user", "secret123", client_mode="mode_b")

    resp = login(client, "login_modeb_user", "secret123")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["client_mode"] == "mode_b"


def test_login_handles_empty_json_body(app, client):
    resp = client.post("/auth/login", data="", content_type="application/json")
    assert resp.status_code == 401
    data = resp.get_json()
    assert data["success"] is False
    assert "用户名或密码错误" in data["error"]


def test_login_does_not_treat_stale_same_device_session_as_active(app, client):
    with app.app_context():
        user = create_user("login_stale_device_user", "secret123", client_mode="mode_b")
        user.max_devices = 1
        db.session.commit()

        from models.user import UserSession

        db.session.add_all([
            UserSession(
                user_id=user.id,
                session_token="active-other-device",
                device_id="device-active",
                last_seen=beijing_now(),
                expires_at=beijing_now() + timedelta(hours=3),
            ),
            UserSession(
                user_id=user.id,
                session_token="stale-same-device",
                device_id="device-stale",
                last_seen=beijing_now() - timedelta(hours=5),
                expires_at=beijing_now() - timedelta(hours=2),
            ),
        ])
        db.session.commit()

    resp = client.post(
        "/auth/login",
        json={"username": "login_stale_device_user", "password": "secret123", "device_id": "device-stale"},
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False
    assert "最大设备数" in data["error"]


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


def test_admin_create_user_rejects_invalid_client_mode(app, client):
    with app.app_context():
        admin = User(username="admin_invalid_create_mode", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_invalid_create_mode", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post(
        "/admin/api/users",
        json={"username": "bad_mode_user", "password": "secret123", "client_mode": "desktop"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "mode_a 或 mode_b" in data["error"]


def test_admin_create_user_rejects_short_password(app, client):
    with app.app_context():
        admin = User(username="admin_short_create_pwd", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_short_create_pwd", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post(
        "/admin/api/users",
        json={"username": "short_pwd_user", "password": "12345", "client_mode": "mode_a"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "至少需要 6 位" in data["error"]


def test_admin_update_user_rejects_invalid_client_mode(app, client):
    with app.app_context():
        admin = User(username="admin_invalid_update_mode", is_admin=True)
        admin.set_password("secret123")
        user = create_user("update_bad_mode_user", "secret123", client_mode="mode_a")
        db.session.add(admin)
        db.session.commit()
        user_id = user.id

    resp = client.post("/auth/login", json={"username": "admin_invalid_update_mode", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.put(f"/admin/api/users/{user_id}", json={"client_mode": "desktop"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "mode_a 或 mode_b" in data["error"]

    with app.app_context():
        refreshed_user = User.query.get(user_id)
        assert refreshed_user.client_mode == "mode_a"


def test_admin_update_user_rejects_short_password(app, client):
    with app.app_context():
        admin = User(username="admin_short_update_pwd", is_admin=True)
        admin.set_password("secret123")
        user = create_user("short_update_pwd_user", "secret123", client_mode="mode_a")
        db.session.add(admin)
        db.session.commit()
        user_id = user.id

    resp = client.post("/auth/login", json={"username": "admin_short_update_pwd", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.put(f"/admin/api/users/{user_id}", json={"password": "12345"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "至少需要 6 位" in data["error"]


def test_admin_update_user_parses_string_boolean_flags(app, client):
    with app.app_context():
        admin = User(username="admin_bool_flag_update", is_admin=True)
        admin.set_password("secret123")
        user = create_user("bool_flag_user", "secret123", client_mode="mode_a")
        db.session.add(admin)
        db.session.commit()
        user_id = user.id

    resp = client.post("/auth/login", json={"username": "admin_bool_flag_update", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.put(f"/admin/api/users/{user_id}", json={"is_active": "false", "can_receive": "0"})
    assert resp.status_code == 200

    with app.app_context():
        refreshed_user = User.query.get(user_id)
        assert refreshed_user.is_active is False
        assert refreshed_user.can_receive is False


def test_admin_disabling_user_forces_logout_existing_sessions(app, client):
    notifications = []

    with app.app_context():
        admin = User(username="admin_disable_user", is_admin=True)
        admin.set_password("secret123")
        user = create_user("disable_me_user", "secret123", client_mode="mode_a")
        db.session.add(admin)
        db.session.commit()
        user_id = user.id

        from services.session_service import create_session

        create_session(user, device_id="device-a", ip_address="127.0.0.1")

    resp = client.post("/auth/login", json={"username": "admin_disable_user", "password": "secret123"})
    assert resp.status_code == 200

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("services.notify_service.notify_user", lambda user_id, event, data: notifications.append((user_id, event, data)))
        resp = client.put(f"/admin/api/users/{user_id}", json={"is_active": False})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True

    with app.app_context():
        refreshed_user = User.query.get(user_id)
        assert refreshed_user.is_active is False
        from models.user import UserSession
        assert UserSession.query.filter_by(user_id=user_id).count() == 0
        disable_logs = AuditLog.query.filter_by(action_type='force_logout', resource_id=str(user_id)).all()
        assert disable_logs

    assert notifications
    assert notifications[0][0] == user_id
    assert notifications[0][1] == 'force_logout'
    assert '禁用' in notifications[0][2]['reason']


def test_admin_toggle_can_receive_rejects_invalid_boolean(app, client):
    with app.app_context():
        admin = User(username="admin_toggle_invalid_bool", is_admin=True)
        admin.set_password("secret123")
        user = create_user("toggle_invalid_bool_user", "secret123", client_mode="mode_a")
        db.session.add(admin)
        db.session.commit()
        user_id = user.id

    resp = client.post("/auth/login", json={"username": "admin_toggle_invalid_bool", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.put(f"/admin/api/users/{user_id}/can-receive", json={"can_receive": "not-bool"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "必须是布尔值" in data["error"]

    with app.app_context():
        refreshed_user = User.query.get(user_id)
        assert refreshed_user.can_receive is True


def test_admin_update_settings_parses_boolean_flags(app, client):
    with app.app_context():
        admin = User(username="admin_settings_bool_flags", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_settings_bool_flags", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.put("/admin/api/settings", json={
        "pool_enabled": "false",
        "mode_a_enabled": "0",
        "mode_b_enabled": "true",
        "announcement_enabled": "1",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    settings = data["settings"]
    assert settings["pool_enabled"] is False
    assert settings["mode_a_enabled"] is False
    assert settings["mode_b_enabled"] is True
    assert settings["announcement_enabled"] is True


def test_admin_update_settings_emits_pool_toggle_events(app, client, monkeypatch):
    emitted = []

    def fake_notify(event, payload):
        emitted.append((event, payload))

    monkeypatch.setattr("routes.admin.notify_all", fake_notify)

    with app.app_context():
        admin = User(username="admin_settings_pool_events", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_settings_pool_events", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.put("/admin/api/settings", json={"pool_enabled": False})
    assert resp.status_code == 200
    resp = client.put("/admin/api/settings", json={"pool_enabled": True})
    assert resp.status_code == 200

    assert ("pool_disabled", {"message": "票池已关闭"}) in emitted
    assert ("pool_enabled", {"message": "票池已开启"}) in emitted


def test_admin_update_settings_rejects_invalid_boolean_flag(app, client):
    with app.app_context():
        admin = User(username="admin_settings_invalid_bool", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_settings_invalid_bool", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.put("/admin/api/settings", json={"pool_enabled": "not-bool"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "pool_enabled 必须是布尔值" in data["error"]


def test_process_uploaded_file_returns_filename_on_success_and_failure(app, monkeypatch):
    from io import BytesIO
    from services import file_parser

    with app.app_context():
        user = create_user("upload_filename_user", "secret123", client_mode="mode_b")
        monkeypatch.setattr(
            file_parser,
            "build_uploaded_txt_relative_path",
            lambda filename, upload_dt=None: "txt/2026-04-07/mock-upload-success.txt",
        )
        monkeypatch.setattr(
            file_parser,
            "parse_filename",
            lambda filename, upload_dt=None: {
                "identifier": "AA",
                "internal_code": "P7",
                "lottery_type": "TEST",
                "multiplier": 3,
                "declared_amount": 600.0,
                "declared_count": 47,
                "deadline_hhmm": "23.55",
                "deadline_time": datetime(2026, 4, 7, 23, 55, 0),
                "detail_period": "26034",
            },
        )
        good_result = file_parser.process_uploaded_file(
            make_upload_file("AA_P7TEST_600_47_00.55_26034.txt", "SPF|1=3|1*1|2\n"),
            uploader_id=user.id,
        )
        assert good_result["success"] is True
        assert good_result["filename"] == "AA_P7TEST_600_47_00.55_26034.txt"

        bad_result = file_parser.process_uploaded_file(
            FileStorage(stream=BytesIO(b"content\n"), filename="bad-name.txt"),
            uploader_id=user.id,
        )
        assert bad_result["success"] is False
        assert bad_result["filename"] == "bad-name.txt"


def test_process_uploaded_file_marks_overdue_tickets_expired_on_import(app, monkeypatch):
    from services import file_parser

    fixed_now = datetime(2026, 4, 7, 1, 0, 0)
    monkeypatch.setattr(file_parser, "beijing_now", lambda: fixed_now)
    monkeypatch.setattr(
        file_parser,
        "build_uploaded_txt_relative_path",
        lambda filename, upload_dt=None: "txt/2026-04-06/mock-overdue.txt",
    )
    monkeypatch.setattr(
        file_parser,
        "parse_filename",
        lambda filename, upload_dt=None: {
            "identifier": "AA",
            "internal_code": "P7",
            "lottery_type": "TEST",
            "multiplier": 3,
            "declared_amount": 600.0,
            "declared_count": 47,
            "deadline_hhmm": "00.55",
            "deadline_time": datetime(2026, 4, 7, 0, 55, 0),
            "detail_period": "26034",
        },
    )

    with app.app_context():
        user = create_user("upload_overdue_user", "secret123", client_mode="mode_b")
        result = file_parser.process_uploaded_file(
            make_upload_file("AA_P7TEST_600_47_00.55_26034.txt", "SPF|1=3|1*1|2\nSPF|1=0|1*1|2\n"),
            uploader_id=user.id,
        )
        assert result["success"] is True
        assert result["ticket_count"] == 2
        assert result["pending_ticket_count"] == 0
        assert result["expired_ticket_count"] == 2

        uploaded = UploadedFile.query.get(result["file_id"])
        tickets = LotteryTicket.query.filter_by(source_file_id=uploaded.id).all()

        assert uploaded.pending_count == 0
        assert uploaded.assigned_count == 0
        assert uploaded.completed_count == 0
        assert {ticket.status for ticket in tickets} == {"expired"}


def test_process_uploaded_file_rejects_invalid_ticket_line_without_partial_import(app, monkeypatch):
    from services import file_parser

    with app.app_context():
        user = create_user("upload_invalid_line_user", "secret123", client_mode="mode_b")
        before_files = UploadedFile.query.count()
        before_tickets = LotteryTicket.query.count()

        monkeypatch.setattr(
            file_parser,
            "build_uploaded_txt_relative_path",
            lambda filename, upload_dt=None: "txt/2026-04-07/mock-invalid-line.txt",
        )
        monkeypatch.setattr(
            file_parser,
            "parse_filename",
            lambda filename, upload_dt=None: {
                "identifier": "AA",
                "internal_code": "P7",
                "lottery_type": "TEST",
                "multiplier": 3,
                "declared_amount": 600.0,
                "declared_count": 47,
                "deadline_hhmm": "23.55",
                "deadline_time": datetime(2026, 4, 7, 23, 55, 0),
                "detail_period": "26034",
            },
        )

        result = file_parser.process_uploaded_file(
            make_upload_file(
                "AA_P7TEST_600_47_00.55_26034.txt",
                "SPF|1=3|1*1|2\nbad-line\n",
            ),
            uploader_id=user.id,
        )

        assert result["success"] is False
        assert result["file_id"] is None
        assert "2" in result["message"]
        assert UploadedFile.query.count() == before_files
        assert LotteryTicket.query.count() == before_tickets


def test_process_uploaded_file_rejects_unknown_text_encoding_cleanly(app, monkeypatch):
    from io import BytesIO
    from werkzeug.datastructures import FileStorage
    from services import file_parser

    with app.app_context():
        user = create_user("upload_bad_encoding_user", "secret123", client_mode="mode_b")
        before_count = UploadedFile.query.count()
        monkeypatch.setattr(
            file_parser,
            "build_uploaded_txt_relative_path",
            lambda filename, upload_dt=None: "txt/2026-04-07/mock-bad-encoding.txt",
        )
        monkeypatch.setattr(
            file_parser,
            "parse_filename",
            lambda filename, upload_dt=None: {
                "identifier": "AA",
                "internal_code": "P7",
                "lottery_type": "TEST",
                "multiplier": 3,
                "declared_amount": 600.0,
                "declared_count": 47,
                "deadline_hhmm": "23.55",
                "deadline_time": datetime(2026, 4, 7, 23, 55, 0),
                "detail_period": "26034",
            },
        )
        result = file_parser.process_uploaded_file(
            FileStorage(
                stream=BytesIO(b"\x80\x80\x80"),
                filename="AA_P7TEST_600_47_00.55_26034.txt",
            ),
            uploader_id=user.id,
        )

        assert result["success"] is False
        assert result["file_id"] is None
        assert result["filename"] == "AA_P7TEST_600_47_00.55_26034.txt"
        assert "UTF-8" in result["message"]
        assert "GBK" in result["message"]
        assert UploadedFile.query.count() == before_count


def test_process_uploaded_file_rejects_same_business_day_duplicate_filename(app, monkeypatch):
    from services import file_parser
    first_now = datetime(2026, 4, 7, 13, 0, 0)
    second_now = datetime(2026, 4, 7, 13, 5, 0)
    calls = {"count": 0}

    def fake_now():
        calls["count"] += 1
        return first_now if calls["count"] == 1 else second_now

    monkeypatch.setattr(file_parser, "beijing_now", fake_now)
    monkeypatch.setattr(
        file_parser,
        "build_uploaded_txt_relative_path",
        lambda filename, upload_dt=None: "txt/2026-04-07/mock-duplicate.txt",
    )
    monkeypatch.setattr(
        file_parser,
        "parse_filename",
        lambda filename, upload_dt=None: {
            "identifier": "AA",
            "internal_code": "P7",
            "lottery_type": "TEST",
            "multiplier": 3,
            "declared_amount": 600.0,
            "declared_count": 47,
            "deadline_hhmm": "23.55",
            "deadline_time": datetime(2026, 4, 7, 23, 55, 0),
            "detail_period": "26034",
        },
    )

    with app.app_context():
        user = create_user("upload_duplicate_name_user", "secret123", client_mode="mode_b")
        first_result = file_parser.process_uploaded_file(
            make_upload_file("AA_P7TEST_600_47_00.55_26034.txt", "SPF|1=3|1*1|2\n"),
            uploader_id=user.id,
        )
        assert first_result["success"] is True

        second_result = file_parser.process_uploaded_file(
            make_upload_file("AA_P7TEST_600_47_00.55_26034.txt", "SPF|1=0|1*1|2\n"),
            uploader_id=user.id,
        )
        assert second_result["success"] is False
        assert second_result["message"].startswith("当前业务日内已上传同名文件")

        assert UploadedFile.query.count() == 1


def test_process_uploaded_file_rejects_case_only_duplicate_filename_same_business_day(app, monkeypatch):
    from services import file_parser
    first_now = datetime(2026, 4, 7, 13, 0, 0)
    second_now = datetime(2026, 4, 7, 13, 5, 0)
    calls = {"count": 0}

    def fake_now():
        calls["count"] += 1
        return first_now if calls["count"] == 1 else second_now

    monkeypatch.setattr(file_parser, "beijing_now", fake_now)
    monkeypatch.setattr(
        file_parser,
        "build_uploaded_txt_relative_path",
        lambda filename, upload_dt=None: "txt/2026-04-07/mock-duplicate-case.txt",
    )
    monkeypatch.setattr(
        file_parser,
        "parse_filename",
        lambda filename, upload_dt=None: {
            "identifier": "AA",
            "internal_code": "P7",
            "lottery_type": "TEST",
            "multiplier": 3,
            "declared_amount": 600.0,
            "declared_count": 47,
            "deadline_hhmm": "23.55",
            "deadline_time": datetime(2026, 4, 7, 23, 55, 0),
            "detail_period": "26034",
        },
    )

    with app.app_context():
        user = create_user("upload_duplicate_case_user", "secret123", client_mode="mode_b")
        first_result = file_parser.process_uploaded_file(
            make_upload_file("AA_P7TEST_600_47_00.55_26034.TXT", "SPF|1=3|1*1|2\n"),
            uploader_id=user.id,
        )
        assert first_result["success"] is True

        second_result = file_parser.process_uploaded_file(
            make_upload_file("AA_P7TEST_600_47_00.55_26034.txt", "SPF|1=0|1*1|2\n"),
            uploader_id=user.id,
        )
        assert second_result["success"] is False
        assert second_result["message"].startswith("当前业务日内已上传同名文件")

        assert UploadedFile.query.count() == 1


def test_admin_file_upload_returns_http_400_when_all_files_fail(app, client, monkeypatch):
    import routes.admin as admin_routes
    from services import notify_service

    notified = {"count": 0}

    def fake_process_uploaded_file(file, uploader_id):
        return {
            "success": False,
            "filename": file.filename,
            "message": "当前业务日内已上传同名文件",
        }

    def fake_notify_pool_update(_payload):
        notified["count"] += 1

    monkeypatch.setattr(admin_routes, "process_uploaded_file", fake_process_uploaded_file)
    monkeypatch.setattr(notify_service, "notify_pool_update", fake_notify_pool_update)

    with app.app_context():
        admin = User(username="admin_upload_all_fail", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_upload_all_fail", "password": "secret123"})
    assert resp.status_code == 200

    upload = client.post(
        "/admin/files/upload",
        data={"files": (make_upload_file("mock-upload.txt", "3\n1\n"), "mock-upload.txt")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 400
    data = upload.get_json()
    assert data["success"] is False
    assert data["error"] == "本次上传全部失败"
    assert data["results"][0]["success"] is False
    assert data["results"][0]["filename"] == "mock-upload.txt"
    assert "同名文件" in data["results"][0]["message"]
    assert notified["count"] == 0


def test_admin_file_upload_keeps_batch_running_when_one_file_raises(app, client, monkeypatch):
    import routes.admin as admin_routes
    from services import notify_service

    notified = {"count": 0}

    def fake_process_uploaded_file(file, uploader_id):
        if file.filename == "boom.txt":
            raise RuntimeError("解析异常")
        return {
            "success": True,
            "filename": file.filename,
            "file_id": 123,
            "message": "ok",
        }

    def fake_notify_pool_update(_payload):
        notified["count"] += 1

    monkeypatch.setattr(admin_routes, "process_uploaded_file", fake_process_uploaded_file)
    monkeypatch.setattr(notify_service, "notify_pool_update", fake_notify_pool_update)

    with app.app_context():
        admin = User(username="admin_upload_partial_exception", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_upload_partial_exception", "password": "secret123"})
    assert resp.status_code == 200

    upload = client.post(
        "/admin/files/upload",
        data={
            "files": [
                (make_upload_file("boom.txt", "1\n"), "boom.txt"),
                (make_upload_file("ok.txt", "2\n"), "ok.txt"),
            ]
        },
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200
    data = upload.get_json()
    assert data["success"] is True
    assert [item["filename"] for item in data["results"]] == ["boom.txt", "ok.txt"]
    assert data["results"][0]["success"] is False
    assert "上传处理失败" in data["results"][0]["message"]
    assert data["results"][1]["success"] is True
    assert notified["count"] == 1


def test_admin_delete_user_rejects_user_with_ticket_history(app, client):
    with app.app_context():
        admin = User(username="admin_delete_guard", is_admin=True)
        admin.set_password("secret123")
        user = create_user("delete_guard_user", "secret123", client_mode="mode_a")
        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="DELETE-GUARD-001",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
        )
        db.session.add_all([admin, ticket])
        db.session.commit()
        user_id = user.id

    resp = client.post("/auth/login", json={"username": "admin_delete_guard", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.delete(f"/admin/api/users/{user_id}")
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["success"] is False
    assert "不能直接删除" in data["error"]

    with app.app_context():
        assert User.query.get(user_id) is not None


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


def make_upload_file(filename: str, content: str) -> FileStorage:
    return FileStorage(stream=io.BytesIO(content.encode("utf-8")), filename=filename, content_type="text/plain")


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


def test_mode_b_pool_status_reflects_reserve_adjusted_available_counts(app, client):
    with app.app_context():
        user = create_user("modeb_pool_status_user", "secret123", client_mode="mode_b")
        first_deadline = beijing_now() + timedelta(hours=1)
        second_deadline = beijing_now() + timedelta(hours=2)
        tickets = []
        for idx in range(12):
            tickets.append(
                LotteryTicket(
                    source_file_id=1,
                    line_number=idx + 1,
                    raw_content=f"EARLY-{idx}",
                    status="pending",
                    lottery_type="胜平负",
                    deadline_time=first_deadline,
                )
            )
        for idx in range(13):
            tickets.append(
                LotteryTicket(
                    source_file_id=1,
                    line_number=100 + idx,
                    raw_content=f"LATE-{idx}",
                    status="pending",
                    lottery_type="让球胜平负",
                    deadline_time=second_deadline,
                )
            )
        db.session.add_all(tickets)
        db.session.commit()

    resp = login(client, "modeb_pool_status_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-b/pool-status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["total_pending"] == 5
    assert len(data["by_type"]) == 1
    assert data["by_type"][0]["lottery_type"] == "胜平负"
    assert data["by_type"][0]["count"] == 5


def test_mode_b_pool_status_hides_blocked_lottery_types(app, client):
    with app.app_context():
        user = create_user("modeb_pool_blocked_user", "secret123", client_mode="mode_b")
        user.set_blocked_lottery_types(["胜平负"])
        first_deadline = beijing_now() + timedelta(hours=1)
        second_deadline = beijing_now() + timedelta(hours=2)
        tickets = []
        for idx in range(25):
            tickets.append(
                LotteryTicket(
                    source_file_id=1,
                    line_number=idx + 1,
                    raw_content=f"BLOCKED-{idx}",
                    status="pending",
                    lottery_type="胜平负",
                    deadline_time=first_deadline,
                )
            )
        for idx in range(25):
            tickets.append(
                LotteryTicket(
                    source_file_id=1,
                    line_number=100 + idx,
                    raw_content=f"ALLOWED-{idx}",
                    status="pending",
                    lottery_type="让球胜平负",
                    deadline_time=second_deadline,
                )
            )
        db.session.add_all(tickets)
        db.session.commit()

    resp = login(client, "modeb_pool_blocked_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-b/pool-status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["total_pending"] == 5
    assert len(data["by_type"]) == 1
    assert data["by_type"][0]["lottery_type"] == "让球胜平负"
    assert data["by_type"][0]["count"] == 5


def test_mode_a_routes_reject_invalid_device_id_and_name(app, client):
    with app.app_context():
        create_user("mode_a_device_guard_user", "secret123", client_mode="mode_a")

    resp = login(client, "mode_a_device_guard_user", "secret123")
    assert resp.status_code == 200

    invalid_id_resp = client.post("/api/mode-a/next", json={"device_id": "bad id", "device_name": "Device A"})
    assert invalid_id_resp.status_code == 400
    assert "无效的设备ID" in invalid_id_resp.get_json()["error"]

    long_name_resp = client.post("/api/mode-a/next", json={"device_id": "device-a", "device_name": "x" * 129})
    assert long_name_resp.status_code == 400
    assert "设备名称过长" in long_name_resp.get_json()["error"]


def test_mode_b_download_rejects_invalid_device_info(app, client):
    with app.app_context():
        create_user("mode_b_device_guard_user", "secret123", client_mode="mode_b")

    resp = login(client, "mode_b_device_guard_user", "secret123")
    assert resp.status_code == 200

    invalid_id_resp = client.post("/api/mode-b/download", json={"count": 1, "device_id": "bad id", "device_name": "设备1"})
    assert invalid_id_resp.status_code == 400
    assert "无效的设备ID" in invalid_id_resp.get_json()["error"]

    long_name_resp = client.post("/api/mode-b/download", json={"count": 1, "device_id": "dev-1", "device_name": "x" * 129})
    assert long_name_resp.status_code == 400
    assert "设备名称过长" in long_name_resp.get_json()["error"]


def test_mode_b_confirm_rejects_non_integer_ticket_ids(app, client):
    with app.app_context():
        create_user("modeb_confirm_guard_user", "secret123", client_mode="mode_b")

    resp = login(client, "modeb_confirm_guard_user", "secret123")
    assert resp.status_code == 200

    resp = client.post("/api/mode-b/confirm", json={"ticket_ids": ["abc"]})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "整数" in data["error"]


def test_mode_b_processing_keeps_same_minute_batches_separate(app, client):
    with app.app_context():
        user = create_user("modeb_processing_separate_user", "secret123", client_mode="mode_b")
        first_time = datetime(2026, 4, 7, 10, 30, 0, 111111)
        second_time = datetime(2026, 4, 7, 10, 30, 0, 222222)
        deadline = datetime(2026, 4, 7, 18, 0, 0)

        tickets = [
            LotteryTicket(
                source_file_id=1,
                line_number=1,
                raw_content="BATCH-SAME-MIN-001",
                lottery_type="胜平负",
                status="assigned",
                assigned_user_id=user.id,
                assigned_username=user.username,
                assigned_device_id="device-b",
                assigned_device_name="device-b",
                assigned_at=first_time,
                deadline_time=deadline,
                ticket_amount=2,
            ),
            LotteryTicket(
                source_file_id=1,
                line_number=2,
                raw_content="BATCH-SAME-MIN-002",
                lottery_type="胜平负",
                status="assigned",
                assigned_user_id=user.id,
                assigned_username=user.username,
                assigned_device_id="device-b",
                assigned_device_name="device-b",
                assigned_at=second_time,
                deadline_time=deadline,
                ticket_amount=2,
            ),
        ]
        db.session.add_all(tickets)
        db.session.commit()

    resp = login(client, "modeb_processing_separate_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-b/processing?device_id=device-b")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert len(data["batches"]) == 2
    assert all(batch["count"] == 1 for batch in data["batches"])


def test_mode_b_download_uses_unique_assigned_at_per_device_batch(app, monkeypatch):
    from services.mode_b_service import download_batch

    fixed_now = datetime(2026, 4, 7, 10, 30, 0, 123456)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)

    with app.app_context():
        user = create_user("modeb_unique_assigned_at_user", "secret123", client_mode="mode_b")

        existing_assigned = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="EXISTING-BATCH-001",
            lottery_type="胜平负",
            status="assigned",
            assigned_user_id=user.id,
            assigned_username=user.username,
            assigned_device_id="device-b",
            assigned_device_name="device-b",
            assigned_at=fixed_now,
            deadline_time=datetime(2026, 4, 7, 18, 0, 0),
            ticket_amount=2,
        )
        db.session.add(existing_assigned)

        for line_number in range(2, 23):
            db.session.add(LotteryTicket(
                source_file_id=1,
                line_number=line_number,
                raw_content=f"PENDING-BATCH-{line_number:03d}",
                lottery_type="胜平负",
                status="pending",
                deadline_time=datetime(2026, 4, 7, 18, 0, 0),
                ticket_amount=2,
            ))

        db.session.commit()

        result = download_batch(
            user_id=user.id,
            device_id="device-b",
            username=user.username,
            count=1,
            device_name="device-b",
        )

        assert result["success"] is True
        assigned_ticket_id = result["ticket_ids"][0]
        assigned_ticket = LotteryTicket.query.get(assigned_ticket_id)
        assert assigned_ticket.assigned_at > fixed_now
        assert assigned_ticket.assigned_at == fixed_now + timedelta(microseconds=1)


def test_mode_b_download_returns_no_pool_error_when_below_processing_limit(app):
    from services.mode_b_service import download_batch

    with app.app_context():
        user = create_user("modeb_empty_pool_user", "secret123", client_mode="mode_b")
        user.max_processing_b_mode = 5
        db.session.add(LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="ASSIGNED-ONLY-001",
            lottery_type="胜平负",
            status="assigned",
            assigned_user_id=user.id,
            assigned_username=user.username,
            assigned_device_id="device-b",
            assigned_device_name="device-b",
            assigned_at=beijing_now(),
            deadline_time=beijing_now() + timedelta(hours=1),
            ticket_amount=2,
        ))
        db.session.commit()

        result = download_batch(
            user_id=user.id,
            device_id="device-b",
            username=user.username,
            count=1,
            device_name="device-b",
        )

    assert result["success"] is False
    assert result["error"] == "当前票池无可用票"


def test_mode_b_download_rejects_when_pool_disabled(app):
    from services.mode_b_service import download_batch

    with app.app_context():
        user = create_user("mode_b_pool_disabled_user", "secret123", client_mode="mode_b")
        settings = SystemSettings.get()
        settings.pool_enabled = False
        db.session.commit()

        result = download_batch(
            user_id=user.id,
            device_id="device-b",
            username=user.username,
            count=2,
            device_name="设备B",
        )

    assert result["success"] is False
    assert result["error"] == "票池已关闭"


def test_mode_b_preview_returns_zero_when_pool_disabled(app):
    from services.mode_b_service import preview_batch

    with app.app_context():
        settings = SystemSettings.get()
        settings.pool_enabled = False
        db.session.commit()

        result = preview_batch(5)

    assert result == {"available": 0, "requested": 5, "sufficient": False}


def test_mode_b_preview_returns_zero_when_user_cannot_receive(app, client):
    with app.app_context():
        user = create_user("mode_b_preview_paused_user", "secret123", client_mode="mode_b")
        user.can_receive = False
        create_pending_ticket("PREVIEW-PAUSED-001", 1)
        db.session.commit()

    resp = login(client, "mode_b_preview_paused_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-b/preview?count=1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["available"] == 0
    assert data["requested"] == 1
    assert data["sufficient"] is False


def test_mode_b_preview_excludes_blocked_lottery_types(app, client):
    with app.app_context():
        user = create_user("mode_b_preview_blocked_user", "secret123", client_mode="mode_b")
        user.set_blocked_lottery_types(["胜平负"])
        blocked_deadline = beijing_now() + timedelta(hours=1)
        allowed_deadline = beijing_now() + timedelta(hours=2)
        tickets = []
        for idx in range(30):
            tickets.append(
                LotteryTicket(
                    source_file_id=1,
                    line_number=idx + 1,
                    raw_content=f"PREVIEW-BLOCKED-{idx}",
                    status="pending",
                    lottery_type="胜平负",
                    deadline_time=blocked_deadline,
                )
            )
        for idx in range(25):
            tickets.append(
                LotteryTicket(
                    source_file_id=1,
                    line_number=100 + idx,
                    raw_content=f"PREVIEW-ALLOWED-{idx}",
                    status="pending",
                    lottery_type="让球胜平负",
                    deadline_time=allowed_deadline,
                )
            )
        db.session.add_all(tickets)
        db.session.commit()

    resp = login(client, "mode_b_preview_blocked_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-b/preview?count=6")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["available"] == 5
    assert data["requested"] == 6
    assert data["sufficient"] is False


def test_mode_b_preview_matches_single_batch_selection_capacity(app, client):
    with app.app_context():
        user = create_user("mode_b_preview_batch_capacity", "secret123", client_mode="mode_b")
        early_deadline = beijing_now() + timedelta(hours=1)
        later_deadline = beijing_now() + timedelta(hours=2)
        for idx in range(30):
            db.session.add(LotteryTicket(
                source_file_id=1,
                line_number=idx + 1,
                raw_content=f"PREVIEW-EARLY-{idx}",
                status="pending",
                lottery_type="胜平负",
                deadline_time=early_deadline,
            ))
        for idx in range(70):
            db.session.add(LotteryTicket(
                source_file_id=1,
                line_number=100 + idx,
                raw_content=f"PREVIEW-LATER-{idx}",
                status="pending",
                lottery_type="让球胜平负",
                deadline_time=later_deadline,
            ))
        db.session.commit()

    resp = login(client, "mode_b_preview_batch_capacity", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-b/preview?count=50")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["available"] == 30
    assert data["requested"] == 50
    assert data["sufficient"] is False


def test_mode_b_download_prefers_daily_limit_error_over_generic_limit_message(app):
    from services.mode_b_service import download_batch

    with app.app_context():
        user = create_user("modeb_daily_limit_user", "secret123", client_mode="mode_b")
        user.max_processing_b_mode = 5
        user.daily_ticket_limit = 1
        db.session.add(LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="COMPLETED-TODAY-001",
            lottery_type="胜平负",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
            deadline_time=beijing_now() + timedelta(hours=1),
            ticket_amount=2,
        ))
        for idx in range(2, 24):
            db.session.add(LotteryTicket(
                source_file_id=1,
                line_number=idx,
                raw_content=f"PENDING-TICKET-{idx:03d}",
                lottery_type="胜平负",
                status="pending",
                deadline_time=beijing_now() + timedelta(hours=1),
                ticket_amount=2,
            ))
        db.session.commit()

        result = download_batch(
            user_id=user.id,
            device_id="device-b",
            username=user.username,
            count=1,
            device_name="device-b",
        )

    assert result["success"] is False
    assert result["error"] == "已达到今日处理上限"


def test_mode_b_postgres_batch_assignment_uses_consistent_now_guard(app, monkeypatch):
    from types import SimpleNamespace
    from services.ticket_pool import assign_tickets_batch

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)
    deadline = datetime(2026, 4, 7, 18, 0, 0)
    captured = []

    class FakeResult:
        def __init__(self, *, fetchall_data=None, scalar_value=None, rowcount=1):
            self._fetchall_data = fetchall_data or []
            self._scalar_value = scalar_value
            self.rowcount = rowcount

        def fetchall(self):
            return self._fetchall_data

        def scalar(self):
            return self._scalar_value

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return [SimpleNamespace(id=123, assigned_at=fixed_now, deadline_time=deadline)]

    class FakeColumn:
        def in_(self, ids):
            return ids

    class FakeLotteryTicket:
        id = FakeColumn()
        query = FakeQuery()

    def fake_execute(statement, params=None):
        sql = str(statement)
        captured.append((sql, params or {}))
        if "SELECT lottery_type, deadline_time, COUNT(*) as cnt" in sql:
            return FakeResult(fetchall_data=[SimpleNamespace(lottery_type="胜平负", deadline_time=deadline, cnt=25)])
        if "SELECT id FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql:
            return FakeResult(fetchall_data=[(123,)])
        if "UPDATE lottery_tickets" in sql and "SET status = 'assigned'" in sql:
            return FakeResult(fetchall_data=[(123,)], rowcount=1)
        if "UPDATE uploaded_files" in sql:
            return FakeResult(rowcount=1)
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool._ensure_unique_batch_assigned_at", lambda user_id, device_id, assigned_at: assigned_at)
    monkeypatch.setattr("services.ticket_pool.LotteryTicket", FakeLotteryTicket)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)

    with app.app_context():
        tickets, adjustment_message = assign_tickets_batch(
            user_id=1,
            device_id="device-b",
            username="tester",
            count=1,
            device_name="设备B",
        )

    assert adjustment_message is None
    assert len(tickets) == 1

    sql_texts = [sql for sql, _ in captured]
    assert any("deadline_time > :now" in sql for sql in sql_texts if "SELECT lottery_type, deadline_time, COUNT(*) as cnt" in sql)
    assert any("deadline_time > :now" in sql for sql in sql_texts if "SELECT id FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql)
    assert any("AND deadline_time > :now" in sql for sql in sql_texts if "UPDATE lottery_tickets" in sql and "SET status = 'assigned'" in sql)
    assert all("NOW()" not in sql for sql in sql_texts)


def test_mode_b_postgres_batch_assignment_updates_only_returned_ids(app, monkeypatch):
    from types import SimpleNamespace
    from services.ticket_pool import assign_tickets_batch

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)
    deadline = datetime(2026, 4, 7, 18, 0, 0)
    captured = []

    class FakeResult:
        def __init__(self, *, fetchall_data=None):
            self._fetchall_data = fetchall_data or []

        def fetchall(self):
            return self._fetchall_data

    class FakeFilterQuery:
        def __init__(self):
            self.ids = []

        def all(self):
            return [SimpleNamespace(id=current_id) for current_id in self.ids]

    class FakeColumn:
        def __init__(self, query):
            self.query = query

        def in_(self, ids):
            self.query.ids = list(ids)
            return ids

    fake_filter_query = FakeFilterQuery()

    class FakeLotteryQuery:
        def filter(self, *args, **kwargs):
            return fake_filter_query

    class FakeLotteryTicket:
        id = FakeColumn(fake_filter_query)
        query = FakeLotteryQuery()

    def fake_execute(statement, params=None):
        sql = str(statement)
        params = params or {}
        captured.append((sql, params))
        if "SELECT lottery_type, deadline_time, COUNT(*) as cnt" in sql:
            return FakeResult(fetchall_data=[SimpleNamespace(lottery_type="胜平负", deadline_time=deadline, cnt=25)])
        if "SELECT id FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql:
            return FakeResult(fetchall_data=[(101,), (102,)])
        if "UPDATE lottery_tickets" in sql and "RETURNING id" in sql:
            return FakeResult(fetchall_data=[(102,)])
        if "UPDATE uploaded_files" in sql:
            assert params["ids"] == [102]
            return FakeResult(fetchall_data=[])
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool._ensure_unique_batch_assigned_at", lambda user_id, device_id, assigned_at: assigned_at)
    monkeypatch.setattr("services.ticket_pool.LotteryTicket", FakeLotteryTicket)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)
    monkeypatch.setattr("services.ticket_pool.db.session.rollback", lambda: None)

    with app.app_context():
        tickets, adjustment_message = assign_tickets_batch(
            user_id=1,
            device_id="device-b",
            username="tester",
            count=2,
            device_name="设备B",
        )

    assert adjustment_message is None
    assert [ticket.id for ticket in tickets] == [102]


def test_mode_a_postgres_assignment_update_uses_deadline_guard(app, monkeypatch):
    from types import SimpleNamespace
    from services.ticket_pool import assign_ticket_atomic

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)
    captured = []

    class FakeResult:
        def __init__(self, *, fetchone_data=None, rowcount=1):
            self._fetchone_data = fetchone_data
            self.rowcount = rowcount

        def fetchone(self):
            return self._fetchone_data

    class FakeTicketRow:
        def __init__(self):
            self.deadline_time = datetime(2026, 4, 7, 18, 0, 0)
            self.lottery_type = "胜平负"
            self.source_file_id = 1

    def fake_execute(statement, params=None):
        sql = str(statement)
        captured.append((sql, params or {}))
        if "SELECT id FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql:
            return FakeResult(fetchone_data=(321,))
        if "SELECT * FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql:
            return FakeResult(fetchone_data=FakeTicketRow())
        if "UPDATE lottery_tickets" in sql and "SET status = 'assigned'" in sql:
            assert "deadline_time > :now" in sql
            return FakeResult(rowcount=1)
        if "UPDATE uploaded_files" in sql:
            return FakeResult(rowcount=1)
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool._get_redis", lambda: None)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)
    monkeypatch.setattr("services.ticket_pool.db.session.rollback", lambda: None)
    monkeypatch.setattr("services.ticket_pool.LotteryTicket", SimpleNamespace(query=SimpleNamespace(get=lambda _id: SimpleNamespace(id=_id, assigned_at=fixed_now))))

    with app.app_context():
        result = assign_ticket_atomic(user_id=1, device_id="device-a", username="tester", device_name="设备A")

    assert result is not None
    assert any("deadline_time > :now" in sql for sql, _ in captured if "UPDATE lottery_tickets" in sql and "SET status = 'assigned'" in sql)


def test_mode_a_postgres_assignment_clamps_file_pending_count(app, monkeypatch):
    from types import SimpleNamespace
    from services.ticket_pool import assign_ticket_atomic

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)

    class FakeResult:
        def __init__(self, *, fetchone_data=None, rowcount=1):
            self._fetchone_data = fetchone_data
            self.rowcount = rowcount

        def fetchone(self):
            return self._fetchone_data

    class FakeTicketRow:
        def __init__(self):
            self.deadline_time = datetime(2026, 4, 7, 18, 0, 0)
            self.lottery_type = "鑳滃钩璐?"
            self.source_file_id = 1

    def fake_execute(statement, params=None):
        sql = str(statement)
        if "SELECT id FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql:
            return FakeResult(fetchone_data=(321,))
        if "SELECT * FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql:
            return FakeResult(fetchone_data=FakeTicketRow())
        if "UPDATE lottery_tickets" in sql and "SET status = 'assigned'" in sql:
            return FakeResult(rowcount=1)
        if "UPDATE uploaded_files" in sql and "assigned_count = assigned_count + 1" in sql:
            assert "GREATEST(pending_count - 1, 0)" in sql
            assert "AND pending_count > 0" not in sql
            return FakeResult(rowcount=1)
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool._get_redis", lambda: None)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)
    monkeypatch.setattr("services.ticket_pool.db.session.rollback", lambda: None)
    monkeypatch.setattr("services.ticket_pool.LotteryTicket", SimpleNamespace(query=SimpleNamespace(get=lambda _id: SimpleNamespace(id=_id, assigned_at=fixed_now))))

    with app.app_context():
        result = assign_ticket_atomic(user_id=1, device_id="device-a", username="tester", device_name="璁惧A")

    assert result is not None


def test_mode_a_postgres_assignment_falls_back_when_redis_returns_stale_id(app, monkeypatch):
    from types import SimpleNamespace
    from services.ticket_pool import assign_ticket_atomic

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)

    class FakeRedis:
        def __init__(self):
            self.calls = 0

        def lpop(self, key):
            self.calls += 1
            return "999" if self.calls == 1 else None

    class FakeResult:
        def __init__(self, *, fetchone_data=None, rowcount=1):
            self._fetchone_data = fetchone_data
            self.rowcount = rowcount

        def fetchone(self):
            return self._fetchone_data

    class FakeTicketRow:
        def __init__(self):
            self.deadline_time = datetime(2026, 4, 7, 18, 0, 0)
            self.lottery_type = "胜平负"
            self.source_file_id = 1

    def fake_execute(statement, params=None):
        sql = str(statement)
        if "SELECT id FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql:
            return FakeResult(fetchone_data=(321,))
        if "SELECT * FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql:
            if params["id"] == 999:
                return FakeResult(fetchone_data=None)
            assert params["id"] == 321
            return FakeResult(fetchone_data=FakeTicketRow())
        if "UPDATE lottery_tickets" in sql and "SET status = 'assigned'" in sql:
            assert params["id"] == 321
            return FakeResult(rowcount=1)
        if "UPDATE uploaded_files" in sql:
            assert params["id"] == 321
            return FakeResult(rowcount=1)
        raise AssertionError(f"Unexpected SQL: {sql}")

    fake_redis = FakeRedis()
    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool._get_redis", lambda: fake_redis)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)
    monkeypatch.setattr("services.ticket_pool.db.session.rollback", lambda: None)
    monkeypatch.setattr("services.ticket_pool.LotteryTicket", SimpleNamespace(query=SimpleNamespace(get=lambda _id: SimpleNamespace(id=_id, assigned_at=fixed_now))))

    with app.app_context():
        result = assign_ticket_atomic(user_id=1, device_id="device-a", username="tester", device_name="设备A")

    assert result is not None
    assert result.id == 321


def test_mode_a_postgres_blocked_fallback_ticket_does_not_duplicate_redis_queue(app, monkeypatch):
    from services.ticket_pool import assign_ticket_atomic

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)

    class FakeRedis:
        def __init__(self):
            self.requeued = []

        def lpop(self, key):
            return None

        def rpush(self, key, value):
            self.requeued.append((key, value))

    class FakeResult:
        def __init__(self, *, fetchone_data=None, rowcount=1):
            self._fetchone_data = fetchone_data
            self.rowcount = rowcount

        def fetchone(self):
            return self._fetchone_data

    class FakeTicketRow:
        def __init__(self):
            self.deadline_time = datetime(2026, 4, 7, 18, 0, 0)
            self.lottery_type = "胜平负"
            self.source_file_id = 1

    fake_redis = FakeRedis()
    db_select_calls = {"count": 0}

    def fake_execute(statement, params=None):
        sql = str(statement)
        if "SELECT id FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql:
            db_select_calls["count"] += 1
            if db_select_calls["count"] == 1:
                return FakeResult(fetchone_data=(321,))
            return FakeResult(fetchone_data=None)
        if "SELECT * FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql:
            return FakeResult(fetchone_data=FakeTicketRow())
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool._get_redis", lambda: fake_redis)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)
    monkeypatch.setattr("services.ticket_pool.db.session.rollback", lambda: None)

    with app.app_context():
        result = assign_ticket_atomic(
            user_id=1,
            device_id="device-a",
            username="tester",
            device_name="设备A",
            blocked_lottery_types=["胜平负"],
        )

    assert result is None
    assert fake_redis.requeued == []


def test_mode_a_sqlite_assignment_retries_after_guarded_update_miss(app, monkeypatch):
    from types import SimpleNamespace
    from services.ticket_pool import assign_ticket_atomic

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)
    selected_ids = iter([101, 102])
    update_attempts = []
    rollbacks = []

    class FakeResult:
        def __init__(self, *, fetchone_data=None, rowcount=1):
            self._fetchone_data = fetchone_data
            self.rowcount = rowcount

        def fetchone(self):
            return self._fetchone_data

    def fake_execute(statement, params=None):
        sql = str(statement)
        if "SELECT id FROM lottery_tickets" in sql and "LIMIT 1" in sql:
            try:
                return FakeResult(fetchone_data=(next(selected_ids),))
            except StopIteration:
                return FakeResult(fetchone_data=None)
        if "UPDATE lottery_tickets" in sql and "SET status = 'assigned'" in sql:
            update_attempts.append(params["id"])
            return FakeResult(rowcount=0 if params["id"] == 101 else 1)
        if "UPDATE uploaded_files" in sql:
            assert params["id"] == 102
            return FakeResult(rowcount=1)
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: False)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool._get_redis", lambda: None)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)
    monkeypatch.setattr("services.ticket_pool.db.session.rollback", lambda: rollbacks.append(True))
    monkeypatch.setattr(
        "services.ticket_pool.LotteryTicket",
        SimpleNamespace(query=SimpleNamespace(get=lambda ticket_id: SimpleNamespace(id=ticket_id, assigned_at=fixed_now))),
    )

    with app.app_context():
        result = assign_ticket_atomic(user_id=1, device_id="device-a", username="tester", device_name="设备A")

    assert result is not None
    assert result.id == 102
    assert update_attempts == [101, 102]
    assert len(rollbacks) == 1


def test_mode_b_sqlite_batch_assignment_returns_only_freshly_assigned_tickets(app, monkeypatch):
    from types import SimpleNamespace
    from services.ticket_pool import assign_tickets_batch

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)

    class FakeRow:
        def __init__(self, value):
            self.value = value

        def __getitem__(self, idx):
            return self.value

    class FakeTicketRecord:
        def __init__(self, ticket_id):
            self.id = ticket_id

    class FakeAssignedQuery:
        def all(self):
            return [FakeTicketRecord(202)]

    class FakeLotteryQuery:
        def filter(self, *args, **kwargs):
            return FakeAssignedQuery()

    class FakeLotteryTicket:
        query = FakeLotteryQuery()
        id = SimpleNamespace(in_=lambda ids: ids)
        assigned_user_id = object()
        status = object()
        assigned_at = object()

    call_state = {"count": 0}

    def fake_execute(statement, params=None):
        sql = str(statement)
        if "SELECT COUNT(*) FROM lottery_tickets WHERE status='pending'" in sql:
            call_state["count"] += 1
            return SimpleNamespace(scalar=lambda: 25)
        if "SELECT lottery_type, deadline_time, COUNT(*) as cnt" in sql:
            return SimpleNamespace(fetchall=lambda: [SimpleNamespace(lottery_type="胜平负", deadline_time=datetime(2026, 4, 7, 18, 0, 0), cnt=25)])
        if "SELECT id FROM lottery_tickets" in sql and "LIMIT :count" in sql:
            return SimpleNamespace(fetchall=lambda: [FakeRow(201), FakeRow(202)])
        if "UPDATE lottery_tickets" in sql and "WHERE id IN" in sql:
            assert "deadline_time > :now" in sql
            return SimpleNamespace(rowcount=1)
        if "UPDATE uploaded_files" in sql:
            assert params["id"] == 202
            return SimpleNamespace(rowcount=1)
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: False)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool._ensure_unique_batch_assigned_at", lambda user_id, device_id, assigned_at: assigned_at)
    monkeypatch.setattr("services.ticket_pool.LotteryTicket", FakeLotteryTicket)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)
    monkeypatch.setattr("services.ticket_pool.db.session.rollback", lambda: None)

    with app.app_context():
        tickets, adjustment_message = assign_tickets_batch(
            user_id=1,
            device_id="device-b",
            username="tester",
            count=2,
            device_name="设备B",
        )

    assert adjustment_message is None
    assert [ticket.id for ticket in tickets] == [202]


def test_mode_b_postgres_batch_assignment_enforces_max_processing_limit(app, monkeypatch):
    from types import SimpleNamespace
    from services.ticket_pool import assign_tickets_batch

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)
    deadline = datetime(2026, 4, 7, 18, 0, 0)

    class FakeResult:
        def __init__(self, *, fetchall_data=None, scalar_data=None, rowcount=1):
            self._fetchall_data = fetchall_data or []
            self._scalar_data = scalar_data
            self.rowcount = rowcount

        def fetchall(self):
            return self._fetchall_data

        def scalar(self):
            return self._scalar_data

    class FakeTicketRecord:
        def __init__(self, ticket_id):
            self.id = ticket_id

    class FakeAssignedQuery:
        def all(self):
            return [FakeTicketRecord(123)]

    class FakeLotteryQuery:
        def filter(self, *args, **kwargs):
            return FakeAssignedQuery()

    class FakeLotteryTicket:
        query = FakeLotteryQuery()
        id = SimpleNamespace(in_=lambda ids: ids)

    def fake_execute(statement, params=None):
        sql = str(statement)
        if "SELECT COUNT(*) FROM lottery_tickets WHERE assigned_user_id = :user_id AND status = 'assigned'" in sql:
            return FakeResult(scalar_data=4)
        if "SELECT lottery_type, deadline_time, COUNT(*) as cnt" in sql:
            return FakeResult(fetchall_data=[SimpleNamespace(lottery_type="胜平负", deadline_time=deadline, cnt=25)])
        if "SELECT id FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql:
            assert params["count"] == 1
            return FakeResult(fetchall_data=[(123,)])
        if "UPDATE lottery_tickets" in sql and "RETURNING id" in sql:
            return FakeResult(fetchall_data=[(123,)], rowcount=1)
        if "UPDATE uploaded_files f" in sql:
            assert params["ids"] == [123]
            return FakeResult(rowcount=1)
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool._ensure_unique_batch_assigned_at", lambda user_id, device_id, assigned_at: assigned_at)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)
    monkeypatch.setattr("services.ticket_pool.LotteryTicket", FakeLotteryTicket)

    with app.app_context():
        tickets, adjustment_message = assign_tickets_batch(
            user_id=1,
            device_id="device-b",
            username="tester",
            count=3,
            device_name="设备B",
            max_processing=5,
        )

    assert [ticket.id for ticket in tickets] == [123]
    assert adjustment_message == "已自动调整为1张（当前处理中4张，上限5张）"


def test_mode_b_postgres_batch_assignment_clamps_file_pending_count(app, monkeypatch):
    from types import SimpleNamespace
    from services.ticket_pool import assign_tickets_batch

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)
    deadline = datetime(2026, 4, 7, 18, 0, 0)

    class FakeResult:
        def __init__(self, *, fetchall_data=None, scalar_data=None, rowcount=1):
            self._fetchall_data = fetchall_data or []
            self._scalar_data = scalar_data
            self.rowcount = rowcount

        def fetchall(self):
            return self._fetchall_data

        def scalar(self):
            return self._scalar_data

    class FakeTicketRecord:
        def __init__(self, ticket_id):
            self.id = ticket_id

    class FakeAssignedQuery:
        def all(self):
            return [FakeTicketRecord(123), FakeTicketRecord(124)]

    class FakeLotteryQuery:
        def filter(self, *args, **kwargs):
            return FakeAssignedQuery()

    class FakeLotteryTicket:
        query = FakeLotteryQuery()
        id = SimpleNamespace(in_=lambda ids: ids)

    def fake_execute(statement, params=None):
        sql = str(statement)
        if "SELECT lottery_type, deadline_time, COUNT(*) as cnt" in sql:
            return FakeResult(fetchall_data=[SimpleNamespace(lottery_type="?????", deadline_time=deadline, cnt=25)])
        if "SELECT id FROM lottery_tickets" in sql and "FOR UPDATE SKIP LOCKED" in sql:
            return FakeResult(fetchall_data=[(123,), (124,)])
        if "UPDATE lottery_tickets" in sql and "RETURNING id" in sql:
            return FakeResult(fetchall_data=[(123,), (124,)], rowcount=2)
        if "UPDATE uploaded_files f" in sql and "assigned_count = assigned_count + sub.cnt" in sql:
            assert "GREATEST(pending_count - sub.cnt, 0)" in sql
            return FakeResult(rowcount=1)
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool._ensure_unique_batch_assigned_at", lambda user_id, device_id, assigned_at: assigned_at)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)
    monkeypatch.setattr("services.ticket_pool.LotteryTicket", FakeLotteryTicket)

    with app.app_context():
        tickets, adjustment_message = assign_tickets_batch(
            user_id=1,
            device_id="device-b",
            username="tester",
            count=2,
            device_name="???B",
        )

    assert adjustment_message is None
    assert [ticket.id for ticket in tickets] == [123, 124]


def test_mode_b_postgres_complete_updates_file_counts_only_for_completed_ids(app, monkeypatch):
    from services.ticket_pool import complete_tickets_batch

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)

    class FakeResult:
        def __init__(self, *, fetchall_data=None):
            self._fetchall_data = fetchall_data or []

        def fetchall(self):
            return self._fetchall_data

    def fake_execute(statement, params=None):
        sql = str(statement)
        if "UPDATE lottery_tickets" in sql and "SET status = 'completed'" in sql:
            assert "RETURNING id" in sql
            return FakeResult(fetchall_data=[(201,)])
        if "UPDATE uploaded_files f" in sql:
            assert params["ids"] == [201]
            return FakeResult(fetchall_data=[])
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)

    with app.app_context():
        result = complete_tickets_batch([201, 202], user_id=1)

    assert result == 1


def test_mode_b_postgres_complete_clamps_assigned_count_when_updating_files(app, monkeypatch):
    from services.ticket_pool import complete_tickets_batch

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)

    class FakeResult:
        def __init__(self, *, fetchall_data=None):
            self._fetchall_data = fetchall_data or []

        def fetchall(self):
            return self._fetchall_data

    def fake_execute(statement, params=None):
        sql = str(statement)
        if "UPDATE lottery_tickets" in sql and "SET status = 'completed'" in sql:
            return FakeResult(fetchall_data=[(201,)])
        if "UPDATE uploaded_files f" in sql and "completed_count = completed_count + sub.cnt" in sql:
            assert "GREATEST(assigned_count - sub.cnt, 0)" in sql
            return FakeResult(fetchall_data=[])
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)

    with app.app_context():
        assert complete_tickets_batch([201], user_id=1) == 1


def test_mode_a_postgres_complete_ticket_uses_updated_rowcount(app, monkeypatch):
    from services.ticket_pool import complete_ticket

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)

    class FakeResult:
        def __init__(self, *, rowcount=0):
            self.rowcount = rowcount

    calls = []

    def fake_execute(statement, params=None):
        sql = str(statement)
        calls.append((sql, params or {}))
        if "UPDATE lottery_tickets" in sql and "SET status = 'completed'" in sql:
            return FakeResult(rowcount=1)
        if "UPDATE uploaded_files" in sql and "completed_count = completed_count + 1" in sql:
            assert params["id"] == 501
            return FakeResult(rowcount=1)
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)

    with app.app_context():
        assert complete_ticket(501, user_id=7) is True

    assert any("UPDATE lottery_tickets" in sql for sql, _ in calls)
    assert any("UPDATE uploaded_files" in sql for sql, _ in calls)


def test_mode_a_postgres_complete_ticket_clamps_negative_assigned_count(app, monkeypatch):
    from services.ticket_pool import complete_ticket

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)

    class FakeResult:
        def __init__(self, *, rowcount=0):
            self.rowcount = rowcount

    def fake_execute(statement, params=None):
        sql = str(statement)
        if "UPDATE lottery_tickets" in sql and "SET status = 'completed'" in sql:
            return FakeResult(rowcount=1)
        if "UPDATE uploaded_files" in sql and "completed_count = completed_count + 1" in sql:
            assert "WHEN assigned_count > 0 THEN assigned_count - 1" in sql
            return FakeResult(rowcount=1)
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)

    with app.app_context():
        assert complete_ticket(501, user_id=7) is True


def test_mode_a_complete_ticket_repairs_file_completed_count_when_assigned_counter_drifted(app):
    from services.ticket_pool import complete_ticket

    with app.app_context():
        user = create_user("mode_a_counter_repair_user", "secret123", client_mode="mode_a")
        uploaded_file = UploadedFile(
            display_id="2026/04/07-01",
            original_filename="repair_a.txt",
            stored_filename="txt/2026-04-07/repair_a.txt",
            status="active",
            uploaded_by=user.id,
            total_tickets=1,
            pending_count=0,
            assigned_count=0,
            completed_count=0,
        )
        db.session.add(uploaded_file)
        db.session.flush()
        ticket = LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=1,
            raw_content="A-REPAIR-001",
            status="assigned",
            assigned_user_id=user.id,
            assigned_username=user.username,
            assigned_at=beijing_now(),
        )
        db.session.add(ticket)
        db.session.commit()
        ticket_id = ticket.id
        file_id = uploaded_file.id

        assert complete_ticket(ticket_id, user.id) is True

        refreshed_ticket = LotteryTicket.query.get(ticket_id)
        refreshed_file = UploadedFile.query.get(file_id)
        assert refreshed_ticket.status == "completed"
        assert refreshed_file.assigned_count == 0
        assert refreshed_file.completed_count == 1


def test_mode_b_finalize_repairs_file_counters_when_assigned_counter_drifted(app):
    from services.ticket_pool import finalize_tickets_batch

    with app.app_context():
        user = create_user("mode_b_counter_repair_user", "secret123", client_mode="mode_b")
        uploaded_file = UploadedFile(
            display_id="2026/04/07-02",
            original_filename="repair_b.txt",
            stored_filename="txt/2026-04-07/repair_b.txt",
            status="active",
            uploaded_by=user.id,
            total_tickets=2,
            pending_count=0,
            assigned_count=0,
            completed_count=0,
        )
        db.session.add(uploaded_file)
        db.session.flush()
        ticket1 = LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=1,
            raw_content="B-REPAIR-001",
            status="assigned",
            assigned_user_id=user.id,
            assigned_username=user.username,
            assigned_at=beijing_now(),
        )
        ticket2 = LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=2,
            raw_content="B-REPAIR-002",
            status="assigned",
            assigned_user_id=user.id,
            assigned_username=user.username,
            assigned_at=beijing_now(),
        )
        db.session.add_all([ticket1, ticket2])
        db.session.commit()

        result = finalize_tickets_batch([ticket1.id, ticket2.id], user.id, completed_count=1)

        refreshed_file = UploadedFile.query.get(uploaded_file.id)
        refreshed_ticket1 = LotteryTicket.query.get(ticket1.id)
        refreshed_ticket2 = LotteryTicket.query.get(ticket2.id)
        assert result == {"completed_count": 1, "expired_count": 1}
        assert refreshed_ticket1.status == "completed"
        assert refreshed_ticket2.status == "expired"
        assert refreshed_file.assigned_count == 0
        assert refreshed_file.completed_count == 1


def test_mode_b_postgres_finalize_updates_counts_only_for_returned_ids(app, monkeypatch):
    from services.ticket_pool import finalize_tickets_batch

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)

    class FakeResult:
        def __init__(self, *, fetchall_data=None):
            self._fetchall_data = fetchall_data or []

        def fetchall(self):
            return self._fetchall_data

    update_calls = []

    def fake_execute(statement, params=None):
        sql = str(statement)
        if "UPDATE lottery_tickets" in sql and "SET status = 'completed'" in sql and "RETURNING id" in sql:
            update_calls.append(("completed", params["ids"]))
            return FakeResult(fetchall_data=[(301,)])
        if "UPDATE lottery_tickets" in sql and "SET status = 'expired'" in sql and "RETURNING id" in sql:
            update_calls.append(("expired", params["ids"]))
            return FakeResult(fetchall_data=[(303,)])
        if "UPDATE uploaded_files f" in sql and "completed_count = completed_count + sub.cnt" in sql:
            assert params["ids"] == [301]
            return FakeResult(fetchall_data=[])
        if "UPDATE uploaded_files f" in sql and "SET assigned_count = GREATEST(assigned_count - sub.cnt, 0)" in sql:
            assert params["ids"] == [303]
            return FakeResult(fetchall_data=[])
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)

    with app.app_context():
        result = finalize_tickets_batch([301, 302, 303], user_id=1, completed_count=2)

    assert update_calls == [("completed", [301, 302]), ("expired", [303])]
    assert result == {"completed_count": 1, "expired_count": 1}


def test_mode_b_postgres_finalize_clamps_assigned_count_when_updating_files(app, monkeypatch):
    from services.ticket_pool import finalize_tickets_batch

    fixed_now = datetime(2026, 4, 7, 10, 30, 0)

    class FakeResult:
        def __init__(self, *, fetchall_data=None):
            self._fetchall_data = fetchall_data or []

        def fetchall(self):
            return self._fetchall_data

    def fake_execute(statement, params=None):
        sql = str(statement)
        if "UPDATE lottery_tickets" in sql and "SET status = 'completed'" in sql and "RETURNING id" in sql:
            return FakeResult(fetchall_data=[(301,)])
        if "UPDATE lottery_tickets" in sql and "SET status = 'expired'" in sql and "RETURNING id" in sql:
            return FakeResult(fetchall_data=[(302,)])
        if "UPDATE uploaded_files f" in sql and "completed_count = completed_count + sub.cnt" in sql:
            assert "GREATEST(assigned_count - sub.cnt, 0)" in sql
            return FakeResult(fetchall_data=[])
        if "UPDATE uploaded_files f" in sql and "SET assigned_count = GREATEST(assigned_count - sub.cnt, 0)" in sql:
            return FakeResult(fetchall_data=[])
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("services.ticket_pool._is_postgres", lambda: True)
    monkeypatch.setattr("services.ticket_pool.beijing_now", lambda: fixed_now)
    monkeypatch.setattr("services.ticket_pool.db.session.execute", fake_execute)
    monkeypatch.setattr("services.ticket_pool.db.session.commit", lambda: None)

    with app.app_context():
        result = finalize_tickets_batch([301, 302], user_id=1, completed_count=1)

    assert result == {"completed_count": 1, "expired_count": 1}


def test_mode_b_endpoints_reject_mode_a_user(app, client):
    with app.app_context():
        create_user("mode_a_blocked_user", "secret123", client_mode="mode_a")

    resp = login(client, "mode_a_blocked_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-b/pool-status")
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False
    assert "仅 B 模式用户" in data["error"]


def test_mode_a_endpoints_reject_mode_b_user(app, client):
    with app.app_context():
        create_user("mode_b_blocked_user", "secret123", client_mode="mode_b")

    resp = login(client, "mode_b_blocked_user", "secret123")
    assert resp.status_code == 200

    responses = [
        client.post("/api/mode-a/next", json={"device_id": "device-a"}),
        client.get("/api/mode-a/current?device_id=device-a"),
        client.post("/api/mode-a/stop", json={"device_id": "device-a"}),
        client.get("/api/mode-a/previous?device_id=device-a"),
    ]

    for resp in responses:
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["success"] is False
        assert "仅 A 模式用户" in data["error"]


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


def test_mode_a_next_can_expire_overdue_current_ticket(app, client):
    with app.app_context():
        user = create_user("modea_expire_user", "secret123", client_mode="mode_a")
        current_ticket = create_assigned_ticket(user, "device-a", "CUR-EXPIRE", 1)
        current_ticket.deadline_time = beijing_now() - timedelta(minutes=1)
        next_ticket = create_pending_ticket("NEXT-AFTER-EXPIRE", 2)
        current_ticket_id = current_ticket.id
        next_ticket_id = next_ticket.id
        db.session.commit()

    resp = login(client, "modea_expire_user", "secret123")
    assert resp.status_code == 200

    resp = client.post(
        "/api/mode-a/next",
        json={
            "device_id": "device-a",
            "device_name": "Device A",
            "complete_current_ticket_id": current_ticket_id,
            "complete_current_ticket_action": "expired",
        },
    )
    assert resp.status_code == 200

    data = resp.get_json()
    assert data["success"] is True
    assert data["ticket"]["id"] == next_ticket_id

    with app.app_context():
        expired_ticket = LotteryTicket.query.get(current_ticket_id)
        assigned_next = LotteryTicket.query.get(next_ticket_id)
        assert expired_ticket.status == "expired"
        assert assigned_next.status == "assigned"


def test_mode_a_next_stops_after_completing_current_when_pool_disabled(app):
    from services.mode_a_service import get_next_ticket

    with app.app_context():
        user = create_user("modea_pool_disabled_user", "secret123", client_mode="mode_a")
        settings = SystemSettings.get()
        settings.pool_enabled = False
        db.session.commit()

        current_ticket = create_assigned_ticket(user, "device-a", "MODEA-POOL-DISABLED", 1)
        current_ticket_id = current_ticket.id

        result = get_next_ticket(
            user_id=user.id,
            device_id="device-a",
            username=user.username,
            device_name="设备A",
            complete_current_ticket_id=current_ticket_id,
            complete_current_ticket_action="completed",
        )

        refreshed = LotteryTicket.query.get(current_ticket_id)
        assert refreshed.status == "completed"
        assert result["success"] is False
        assert result["error"] == "票池已关闭"
        assert result["completed_current"] is True


def test_mode_a_current_prefers_latest_assigned_ticket_for_device(app, client):
    with app.app_context():
        user = create_user("modea_latest_current_user", "secret123", client_mode="mode_a")
        older = create_assigned_ticket(user, "device-a", "CUR-OLDER", 1)
        newer = create_assigned_ticket(user, "device-a", "CUR-NEWER", 2)
        older.assigned_at = datetime(2026, 4, 7, 10, 0, 0)
        newer.assigned_at = datetime(2026, 4, 7, 10, 5, 0)
        db.session.commit()
        newer_id = newer.id

    resp = login(client, "modea_latest_current_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-a/current?device_id=device-a")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["ticket"]["id"] == newer_id


def test_mode_a_previous_rejects_invalid_offset(app, client):
    with app.app_context():
        create_user("modea_previous_guard_user", "secret123", client_mode="mode_a")

    resp = login(client, "modea_previous_guard_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-a/previous?device_id=device-a&offset=bad")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "offset" in data["error"]


def test_mode_a_stop_reports_finalize_race_failure(app, client, monkeypatch):
    with app.app_context():
        user = create_user("modea_stop_race_user", "secret123", client_mode="mode_a")
        create_assigned_ticket(user, "device-stop-race", "STOP-RACE-001", 1)

    resp = login(client, "modea_stop_race_user", "secret123")
    assert resp.status_code == 200

    monkeypatch.setattr("services.mode_a_service.finalize_ticket", lambda *args, **kwargs: False)

    resp = client.post("/api/mode-a/stop", json={"device_id": "device-stop-race"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is False
    assert "状态已变化" in data["error"]


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


def test_pool_status_hides_blocked_lottery_types_for_user(app, client):
    with app.app_context():
        user = create_user("pool_blocked_user", "secret123", client_mode="mode_a")
        user.set_blocked_lottery_types(["胜平负"])
        blocked_deadline = beijing_now() + timedelta(hours=1)
        allowed_deadline = beijing_now() + timedelta(hours=2)
        db.session.add_all([
            LotteryTicket(source_file_id=1, line_number=1, raw_content="POOL-BLOCKED-1", status="pending", lottery_type="胜平负", deadline_time=blocked_deadline),
            LotteryTicket(source_file_id=1, line_number=2, raw_content="POOL-ALLOWED-1", status="pending", lottery_type="让球胜平负", deadline_time=allowed_deadline),
        ])
        db.session.commit()

    resp = login(client, "pool_blocked_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/pool/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_pending"] == 1
    assert len(data["by_type"]) == 1
    assert data["by_type"][0]["lottery_type"] == "让球胜平负"


def test_pool_status_uses_mode_b_reserve_rule_for_mode_b_users(app, client):
    with app.app_context():
        user = create_user("pool_mode_b_reserve_user", "secret123", client_mode="mode_b")
        deadline = beijing_now() + timedelta(hours=1)
        tickets = [
            LotteryTicket(
                source_file_id=1,
                line_number=index + 1,
                raw_content=f"POOL-MODEB-{index}",
                status="pending",
                lottery_type="胜平负",
                deadline_time=deadline,
            )
            for index in range(25)
        ]
        db.session.add_all(tickets)
        db.session.commit()

    resp = login(client, "pool_mode_b_reserve_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/pool/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_pending"] == 5
    assert len(data["by_type"]) == 1
    assert data["by_type"][0]["count"] == 5


def test_pool_status_requires_login_json_response(app, client):
    resp = client.get("/api/pool/status")
    assert resp.status_code == 401
    assert resp.is_json is True
    data = resp.get_json()
    assert data["success"] is False
    assert "请先登录" in data["error"]


def test_heartbeat_requires_login_json_response(app, client):
    resp = client.post("/auth/heartbeat")
    assert resp.status_code == 401
    assert resp.is_json is True
    data = resp.get_json()
    assert data["success"] is False
    assert "请先登录" in data["error"]


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


def test_device_register_handles_empty_json_body(app, client):
    with app.app_context():
        create_user("device_empty_body_user", "secret123", client_mode="mode_b")

    resp = login(client, "device_empty_body_user", "secret123")
    assert resp.status_code == 200

    resp = client.post("/api/device/register", data="", content_type="application/json")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "设备ID" in data["error"]


def test_device_register_rejects_claiming_other_users_device_id(app, client):
    with app.app_context():
        user_a = create_user("device_owner_user", "secret123", client_mode="mode_b")
        create_user("device_other_user", "secret123", client_mode="mode_b")
        from models.device import DeviceRegistry

        db.session.add(DeviceRegistry(device_id="shared-device", user_id=user_a.id, device_name="A设备"))
        db.session.commit()

    resp = login(client, "device_other_user", "secret123")
    assert resp.status_code == 200

    resp = client.post("/api/device/register", json={"device_id": "shared-device", "device_name": "B设备"})
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["success"] is False
    assert "其他用户" in data["error"]


def test_device_register_requires_login_json_response(app, client):
    resp = client.post("/api/device/register", json={"device_id": "device-a"})
    assert resp.status_code == 401
    assert resp.is_json is True
    data = resp.get_json()
    assert data["success"] is False
    assert "请先登录" in data["error"]


def test_device_register_rejects_invalid_device_id_format(app, client):
    with app.app_context():
        create_user("device_invalid_format_user", "secret123", client_mode="mode_b")

    resp = login(client, "device_invalid_format_user", "secret123")
    assert resp.status_code == 200

    resp = client.post("/api/device/register", json={"device_id": "bad id"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "设备ID只能包含字母、数字、连字符和下划线" in data["error"]


def test_device_update_name_rejects_too_long_name(app, client):
    with app.app_context():
        user = create_user("device_long_name_user", "secret123", client_mode="mode_b")
        from models.device import DeviceRegistry

        db.session.add(DeviceRegistry(device_id="device-a", user_id=user.id, device_name="旧设备名"))
        db.session.commit()

    resp = login(client, "device_long_name_user", "secret123")
    assert resp.status_code == 200

    resp = client.put("/api/device/device-a/name", json={"name": "x" * 21})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "长度不能超过 20" in data["error"]


def test_device_update_name_returns_json_for_missing_device(app, client):
    with app.app_context():
        create_user("device_missing_name_user", "secret123", client_mode="mode_b")

    resp = login(client, "device_missing_name_user", "secret123")
    assert resp.status_code == 200

    resp = client.put("/api/device/missing-device/name", json={"name": "新设备名"})
    assert resp.status_code == 404
    assert resp.is_json is True
    data = resp.get_json()
    assert data["success"] is False
    assert "设备不存在" in data["error"]


def test_change_password_handles_empty_json_body(app, client):
    with app.app_context():
        create_user("change_password_empty_body_user", "secret123", client_mode="mode_a")

    resp = login(client, "change_password_empty_body_user", "secret123")
    assert resp.status_code == 200

    resp = client.post("/api/user/change-password", data="", content_type="application/json")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "请填写完整" in data["error"]


def test_mode_b_confirm_handles_empty_json_body(app, client):
    with app.app_context():
        create_user("modeb_empty_confirm_user", "secret123", client_mode="mode_b")

    resp = login(client, "modeb_empty_confirm_user", "secret123")
    assert resp.status_code == 200

    resp = client.post("/api/mode-b/confirm", data="", content_type="application/json")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "票ID列表" in data["error"]


def test_heartbeat_can_backfill_session_device_id(app, client):
    with app.app_context():
        user = create_user("heartbeat_device_user", "secret123", client_mode="mode_b")
        user_id = user.id
        settings = SystemSettings.get()
        settings.session_lifetime_hours = 6
        db.session.commit()

    resp = login(client, "heartbeat_device_user", "secret123")
    assert resp.status_code == 200

    with app.app_context():
        from models.user import UserSession

        session = UserSession.query.filter_by(user_id=user_id).first()
        session.expires_at = beijing_now() + timedelta(minutes=1)
        db.session.commit()

    resp = client.post("/auth/heartbeat", json={"device_id": "device-01"})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with app.app_context():
        from models.user import UserSession

        session = UserSession.query.filter_by(user_id=user_id).first()
        assert session is not None
        assert session.device_id == "device-01"
        remaining_hours = (session.expires_at - beijing_now()).total_seconds() / 3600
        assert remaining_hours > 5.8


def test_create_session_uses_db_session_lifetime_setting(app):
    from services.session_service import create_session

    with app.app_context():
        user = create_user("session_lifetime_user", "secret123", client_mode="mode_b")
        settings = SystemSettings.get()
        settings.session_lifetime_hours = 6
        db.session.commit()

        before = beijing_now()
        session = create_session(user, device_id="device-session")
        delta_hours = (session.expires_at - before).total_seconds() / 3600

    assert 5.9 <= delta_hours <= 6.1


def test_authenticated_request_extends_session_expiry(app, client):
    with app.app_context():
        user = create_user("session_extend_user", "secret123", client_mode="mode_a")
        settings = SystemSettings.get()
        settings.session_lifetime_hours = 6
        db.session.commit()

    resp = login(client, "session_extend_user", "secret123")
    assert resp.status_code == 200

    with app.app_context():
        from models.user import UserSession

        session = UserSession.query.first()
        session.expires_at = beijing_now() + timedelta(minutes=1)
        db.session.commit()

    resp = client.get("/api/user/daily-stats")
    assert resp.status_code == 200

    with app.app_context():
        from models.user import UserSession

        session = UserSession.query.first()
        remaining_hours = (session.expires_at - beijing_now()).total_seconds() / 3600

    assert remaining_hours > 5.8


def test_time_utils_use_configured_daily_reset_hour(app):
    from utils.time_utils import get_business_date, get_business_window, resolve_deadline_datetime

    with app.app_context():
        settings = SystemSettings.get()
        settings.daily_reset_hour = 6
        db.session.commit()

        assert str(get_business_date(datetime(2026, 4, 7, 5, 59, 0))) == "2026-04-06"
        assert str(get_business_date(datetime(2026, 4, 7, 6, 0, 0))) == "2026-04-07"

        window_start, window_end = get_business_window(datetime(2026, 4, 7).date())
        assert window_start == datetime(2026, 4, 7, 6, 0, 0)
        assert window_end == datetime(2026, 4, 8, 6, 0, 0)

        deadline = resolve_deadline_datetime("05.30", datetime(2026, 4, 7, 7, 0, 0))
        assert deadline == datetime(2026, 4, 8, 5, 30, 0)


def test_my_winning_uses_configured_business_reset_hour(app, client):
    with app.app_context():
        user = create_user("winning_reset_hour_user", "secret123", client_mode="mode_a")
        settings = SystemSettings.get()
        settings.daily_reset_hour = 6

        inside_window = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-RESET-INSIDE",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=datetime(2026, 4, 7, 5, 30, 0),
            is_winning=True,
        )
        outside_window = LotteryTicket(
            source_file_id=1,
            line_number=2,
            raw_content="WIN-RESET-OUTSIDE",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=datetime(2026, 4, 7, 6, 30, 0),
            is_winning=True,
        )
        db.session.add_all([inside_window, outside_window])
        db.session.commit()

    resp = login(client, "winning_reset_hour_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/winning/my?date=2026-04-06")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    records = data["grouped"]["2026-04-06"]
    raw_contents = [record["raw_content"] for record in records]
    assert "WIN-RESET-INSIDE" in raw_contents
    assert "WIN-RESET-OUTSIDE" not in raw_contents


def test_user_daily_stats_uses_current_business_window_before_noon(app, client, monkeypatch):
    business_start = datetime(2026, 4, 6, 12, 0, 0)
    business_end = datetime(2026, 4, 7, 12, 0, 0)

    with app.app_context():
        user = create_user("daily_stats_user", "secret123", client_mode="mode_b")

        in_window = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="IN-WINDOW",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            assigned_device_id="device-a",
            assigned_device_name="设备A",
            ticket_amount=2,
            completed_at=business_start + timedelta(hours=1),
        )
        out_of_window = LotteryTicket(
            source_file_id=1,
            line_number=2,
            raw_content="OUT-OF-WINDOW",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            assigned_device_id="device-a",
            assigned_device_name="设备A",
            ticket_amount=3,
            completed_at=business_start - timedelta(hours=1),
        )
        db.session.add_all([in_window, out_of_window])
        db.session.commit()

    monkeypatch.setattr("routes.user.get_today_noon", lambda: business_start)
    monkeypatch.setattr("routes.user.get_business_date", lambda dt=None: business_start.date())

    resp = login(client, "daily_stats_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/user/daily-stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["ticket_count"] == 1
    assert data["total_amount"] == 2.0
    assert data["today"] == "2026-04-06"
    assert data["device_stats"][0]["count"] == 1
    assert data["device_stats"][0]["amount"] == 2.0


def test_user_daily_stats_pool_total_pending_excludes_blocked_lottery_types(app, client):
    with app.app_context():
        user = create_user("daily_stats_blocked_user", "secret123", client_mode="mode_a")
        user.set_blocked_lottery_types(["胜平负"])
        blocked_deadline = beijing_now() + timedelta(hours=1)
        allowed_deadline = beijing_now() + timedelta(hours=2)
        db.session.add_all([
            LotteryTicket(source_file_id=1, line_number=1, raw_content="STATS-BLOCKED-1", status="pending", lottery_type="胜平负", deadline_time=blocked_deadline),
            LotteryTicket(source_file_id=1, line_number=2, raw_content="STATS-ALLOWED-1", status="pending", lottery_type="让球胜平负", deadline_time=allowed_deadline),
        ])
        db.session.commit()

    resp = login(client, "daily_stats_blocked_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/user/daily-stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["pool_total_pending"] == 1


def test_user_daily_stats_pool_total_pending_uses_mode_b_reserve_rule(app, client):
    with app.app_context():
        user = create_user("daily_stats_mode_b_reserve_user", "secret123", client_mode="mode_b")
        deadline = beijing_now() + timedelta(hours=1)
        tickets = [
            LotteryTicket(
                source_file_id=1,
                line_number=index + 1,
                raw_content=f"MODEB-POOL-{index}",
                status="pending",
                lottery_type="胜平负",
                deadline_time=deadline,
            )
            for index in range(25)
        ]
        db.session.add_all(tickets)
        db.session.commit()

    resp = login(client, "daily_stats_mode_b_reserve_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/user/daily-stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["pool_total_pending"] == 5


def test_user_daily_stats_pool_total_pending_is_zero_when_pool_disabled(app, client):
    with app.app_context():
        create_user("daily_stats_pool_disabled", "secret123", client_mode="mode_b")
        settings = SystemSettings.get()
        settings.pool_enabled = False
        db.session.add(LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="POOL-DISABLED-1",
            status="pending",
            lottery_type="让球胜平负",
            deadline_time=beijing_now() + timedelta(hours=1),
        ))
        db.session.commit()

    resp = login(client, "daily_stats_pool_disabled", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/user/daily-stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["pool_total_pending"] == 0


def test_file_display_id_uses_business_date_before_noon(app, monkeypatch):
    fixed_now = datetime(2026, 4, 7, 11, 0, 0)

    with app.app_context():
        monkeypatch.setattr("services.file_parser.beijing_now", lambda: fixed_now)

        from services.file_parser import _generate_display_id

        display_id = _generate_display_id()
        assert display_id == "2026/04/06-01"


def test_upload_winning_image_creates_winning_record(app, client):
    from PIL import Image

    with app.app_context():
        user = create_user("winning_user", "secret123", client_mode="mode_a")
        ticket = create_assigned_ticket(user, "device-a", "WIN001", 1)
        ticket.is_winning = True
        db.session.commit()
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


def test_upload_winning_image_works_without_pillow(app, client, monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PIL":
            raise ModuleNotFoundError("No module named 'PIL'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with app.app_context():
        user = create_user("winning_user_no_pillow", "secret123", client_mode="mode_a")
        ticket = create_assigned_ticket(user, "device-b", "WIN002", 2)
        ticket.is_winning = True
        db.session.commit()
        ticket_id = ticket.id

    resp = login(client, "winning_user_no_pillow", "secret123")
    assert resp.status_code == 200

    raw_image = io.BytesIO(b"raw-image-without-pillow")
    resp = client.post(
        f"/api/winning/upload-image/{ticket_id}",
        data={"image": (raw_image, "winning.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["image_url"].startswith("/uploads/images/winning_")


def test_upload_winning_image_rejects_empty_filename(app, client):
    with app.app_context():
        user = create_user("winning_empty_filename_user", "secret123", client_mode="mode_a")
        ticket = create_assigned_ticket(user, "device-empty-image", "WIN-EMPTY-NAME", 1)
        ticket.is_winning = True
        db.session.commit()
        ticket_id = ticket.id

    resp = login(client, "winning_empty_filename_user", "secret123")
    assert resp.status_code == 200

    resp = client.post(
        f"/api/winning/upload-image/{ticket_id}",
        data={"image": (io.BytesIO(b"fake-image"), "")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "文件名不能为空" in data["error"]


def test_upload_winning_image_replaces_old_local_file(app, client):
    from PIL import Image

    with app.app_context():
        user = create_user("winning_replace_user", "secret123", client_mode="mode_a")
        ticket = create_assigned_ticket(user, "device-c", "WIN003", 3)
        ticket.is_winning = True
        db.session.commit()
        ticket_id = ticket.id

    resp = login(client, "winning_replace_user", "secret123")
    assert resp.status_code == 200

    first_image = io.BytesIO()
    Image.new("RGB", (20, 20), color="red").save(first_image, format="PNG")
    first_image.seek(0)
    first_resp = client.post(
        f"/api/winning/upload-image/{ticket_id}",
        data={"image": (first_image, "winning1.png")},
        content_type="multipart/form-data",
    )
    assert first_resp.status_code == 200
    first_url = first_resp.get_json()["image_url"]

    with app.app_context():
        first_record = WinningRecord.query.filter_by(ticket_id=ticket_id).first()
        first_path = Path(app.config["UPLOAD_FOLDER"]) / "images" / first_url.rsplit("/", 1)[-1]
        assert first_record is not None
        assert first_path.exists()

    second_image = io.BytesIO()
    Image.new("RGB", (20, 20), color="blue").save(second_image, format="PNG")
    second_image.seek(0)
    second_resp = client.post(
        f"/api/winning/upload-image/{ticket_id}",
        data={"image": (second_image, "winning2.png")},
        content_type="multipart/form-data",
    )
    assert second_resp.status_code == 200
    second_url = second_resp.get_json()["image_url"]

    with app.app_context():
        refreshed_record = WinningRecord.query.filter_by(ticket_id=ticket_id).first()
        second_path = Path(app.config["UPLOAD_FOLDER"]) / "images" / second_url.rsplit("/", 1)[-1]

    assert first_url != second_url
    assert not first_path.exists()
    assert second_path.exists()
    assert refreshed_record.winning_image_url == second_url


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


def test_expire_overdue_tickets_removes_pending_ids_from_redis(app, monkeypatch):
    from tasks.expire_tickets import expire_overdue_tickets

    removed = []

    class FakePipe:
        def lrem(self, key, count, value):
            removed.append((key, count, value))
            return self

        def execute(self):
            return True

    class FakeRedis:
        def pipeline(self):
            return FakePipe()

    monkeypatch.setattr("extensions.redis_client", FakeRedis())

    with app.app_context():
        user = create_user("expire_redis_user", "secret123", client_mode="mode_a")
        uploaded_file = UploadedFile(
            display_id="2026/03/30-02",
            original_filename="expired-redis.txt",
            stored_filename="expired-redis.txt",
            uploaded_by=user.id,
            total_tickets=2,
            pending_count=1,
            assigned_count=1,
            completed_count=0,
        )
        db.session.add(uploaded_file)
        db.session.commit()

        pending_ticket = LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=1,
            raw_content="PENDING-REDIS-EXPIRED",
            status="pending",
            deadline_time=beijing_now() - timedelta(minutes=1),
        )
        assigned_ticket = LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=2,
            raw_content="ASSIGNED-REDIS-EXPIRED",
            status="assigned",
            assigned_user_id=user.id,
            assigned_username=user.username,
            assigned_device_id="device-a",
            assigned_device_name="device-a",
            deadline_time=beijing_now() - timedelta(minutes=1),
        )
        db.session.add_all([pending_ticket, assigned_ticket])
        db.session.commit()
        pending_ticket_id = pending_ticket.id
        assigned_ticket_id = assigned_ticket.id

        expire_overdue_tickets()

    assert ("pool:pending", 0, str(pending_ticket_id)) in removed
    assert ("pool:pending", 0, str(assigned_ticket_id)) not in removed


def test_expire_overdue_tickets_pushes_pool_update(app, monkeypatch):
    from tasks.expire_tickets import expire_overdue_tickets

    pushed = []

    monkeypatch.setattr("services.notify_service.notify_pool_update", lambda payload: pushed.append(payload))
    monkeypatch.setattr("services.ticket_pool.get_pool_status", lambda: {"total_pending": 0, "by_type": [], "assigned": 0, "completed_today": 0})

    with app.app_context():
        user = create_user("expire_notify_user", "secret123", client_mode="mode_a")
        uploaded_file = UploadedFile(
            display_id="2026/03/30-03",
            original_filename="expired-notify.txt",
            stored_filename="expired-notify.txt",
            uploaded_by=user.id,
            total_tickets=1,
            pending_count=1,
            assigned_count=0,
            completed_count=0,
        )
        db.session.add(uploaded_file)
        db.session.flush()
        db.session.add(LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=1,
            raw_content="PENDING-NOTIFY-EXPIRED",
            status="pending",
            deadline_time=beijing_now() - timedelta(minutes=1),
        ))
        db.session.commit()

        expire_overdue_tickets()

    assert pushed == [{"total_pending": 0, "by_type": [], "assigned": 0, "completed_today": 0}]


def test_archive_old_tickets_deletes_completed_ticket_after_retention(app):
    from tasks.archive import archive_old_tickets

    with app.app_context():
        user = create_user("archive_completed_user", "secret123", client_mode="mode_b")
        uploaded_file = UploadedFile(
            display_id="2026/03/01-01",
            original_filename="archive_completed.txt",
            stored_filename="archive_completed.txt",
            uploaded_by=user.id,
            total_tickets=1,
            completed_count=1,
        )
        db.session.add(uploaded_file)
        db.session.commit()

        ticket = LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=1,
            raw_content="ARCHIVE-COMPLETED",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            assigned_device_id="device-a",
            assigned_device_name="device-a",
            admin_upload_time=beijing_now() - timedelta(days=40),
            assigned_at=beijing_now() - timedelta(days=40),
            completed_at=beijing_now() - timedelta(days=35),
        )
        db.session.add(ticket)
        db.session.commit()
        ticket_id = ticket.id

        deleted_count = archive_old_tickets(days_ago=30)
        archived = ArchivedLotteryTicket.query.filter_by(original_ticket_id=ticket_id).first()
        remaining = LotteryTicket.query.get(ticket_id)

    assert deleted_count == 1
    assert archived is None
    assert remaining is None


def test_archive_old_tickets_deletes_stale_winning_image_files(app):
    from tasks.archive import archive_old_tickets

    with app.app_context():
        user = create_user("archive_winning_image_user", "secret123", client_mode="mode_b")
        uploaded_file = UploadedFile(
            display_id="2026/03/01-03",
            original_filename="archive_winning_image.txt",
            stored_filename="archive_winning_image.txt",
            uploaded_by=user.id,
            total_tickets=1,
            completed_count=1,
        )
        db.session.add(uploaded_file)
        db.session.commit()

        image_dir = Path(app.config["UPLOAD_FOLDER"]) / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / "archive-winning-stale.png"
        image_path.write_bytes(b"stale-image")

        ticket = LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=1,
            raw_content="ARCHIVE-WIN-IMAGE",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now() - timedelta(days=35),
            is_winning=True,
            winning_image_url="/uploads/images/archive-winning-stale.png",
        )
        db.session.add(ticket)
        db.session.commit()
        db.session.add(WinningRecord(
            ticket_id=ticket.id,
            source_file_id=uploaded_file.id,
            winning_image_url=ticket.winning_image_url,
            uploaded_by=user.id,
        ))
        db.session.commit()

        deleted_count = archive_old_tickets(days_ago=30)

    assert deleted_count == 1
    assert not image_path.exists()


def test_archive_old_tickets_uses_fallback_terminal_time_for_expired_and_revoked(app):
    from tasks.archive import archive_old_tickets

    with app.app_context():
        user = create_user("archive_terminal_user", "secret123", client_mode="mode_a")
        uploaded_file = UploadedFile(
            display_id="2026/03/01-02",
            original_filename="archive_terminal.txt",
            stored_filename="archive_terminal.txt",
            uploaded_by=user.id,
            total_tickets=2,
        )
        db.session.add(uploaded_file)
        db.session.commit()

        expired_ticket = LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=1,
            raw_content="ARCHIVE-EXPIRED",
            status="expired",
            deadline_time=beijing_now() - timedelta(days=31),
            admin_upload_time=beijing_now() - timedelta(days=32),
        )
        revoked_ticket = LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=2,
            raw_content="ARCHIVE-REVOKED",
            status="revoked",
            admin_upload_time=beijing_now() - timedelta(days=33),
        )
        db.session.add_all([expired_ticket, revoked_ticket])
        db.session.commit()
        expired_id = expired_ticket.id
        revoked_id = revoked_ticket.id

        deleted_count = archive_old_tickets(days_ago=30)
        remaining_ids = {
            row.id
            for row in LotteryTicket.query.filter(LotteryTicket.id.in_([expired_id, revoked_id])).all()
        }

    assert deleted_count == 2
    assert remaining_ids == set()


def test_process_uploaded_file_stores_txt_under_business_date_folder(app, monkeypatch):
    from services import file_parser

    monkeypatch.setattr(
        file_parser,
        "build_uploaded_txt_relative_path",
        lambda filename, upload_dt=None: "txt/2026-04-07/mock-folder-check.txt",
    )
    monkeypatch.setattr(
        file_parser,
        "parse_filename",
        lambda filename, upload_dt=None: {
            "identifier": "AA",
            "internal_code": "P7",
            "lottery_type": "TEST",
            "multiplier": 3,
            "declared_amount": 600.0,
            "declared_count": 47,
            "deadline_hhmm": "23.55",
            "deadline_time": datetime(2026, 4, 7, 23, 55, 0),
            "detail_period": "26034",
        },
    )

    with app.app_context():
        user = create_user("upload_folder_user", "secret123", client_mode="mode_b")
        result = file_parser.process_uploaded_file(
            make_upload_file("AA_P7TEST_600_47_00.55_26034.txt", "SPF|1=3|1*1|2\n"),
            uploader_id=user.id,
        )
        assert result["success"] is True

        uploaded = UploadedFile.query.get(result["file_id"])
        assert uploaded is not None
        normalized = uploaded.stored_filename.replace('\\', '/')
        assert normalized.startswith('txt/2026-04-07/')


def test_archive_old_uploaded_txt_files_deletes_closed_txt_after_retention(app):
    from services.file_parser import process_uploaded_file, resolve_uploaded_txt_path
    from tasks.archive import archive_old_tickets, archive_old_uploaded_txt_files

    with app.app_context():
        user = create_user("archive_txt_user", "secret123", client_mode="mode_b")
        result = process_uploaded_file(
            make_upload_file("芳_P7胜平负3倍投_金额600元_47张_00.55_26034.txt", "3\n1\n"),
            uploader_id=user.id,
        )
        uploaded = UploadedFile.query.get(result["file_id"])
        old_path = resolve_uploaded_txt_path(uploaded.stored_filename, app.config["UPLOAD_FOLDER"])
        assert os.path.exists(old_path)

        uploaded.uploaded_at = beijing_now() - timedelta(days=31)
        uploaded.pending_count = 0
        uploaded.assigned_count = 0
        uploaded.completed_count = uploaded.total_tickets

        for ticket in LotteryTicket.query.filter_by(source_file_id=uploaded.id).all():
            ticket.status = "completed"
            ticket.completed_at = beijing_now() - timedelta(days=31)
        db.session.commit()

        archive_old_tickets(days_ago=30)
        moved = archive_old_uploaded_txt_files(days_ago=30)
        remaining = UploadedFile.query.get(result["file_id"])

    assert moved == 1
    assert not os.path.exists(old_path)
    assert remaining is None


def test_archive_old_uploaded_txt_files_keeps_file_with_recent_ticket_history(app):
    from services.file_parser import process_uploaded_file, resolve_uploaded_txt_path
    from tasks.archive import archive_old_uploaded_txt_files

    with app.app_context():
        user = create_user("archive_txt_recent_ticket_user", "secret123", client_mode="mode_b")
        result = process_uploaded_file(
            make_upload_file("芳_P7胜平负3倍投_金额600元_47张_00.55_26034.txt", "3\n1\n"),
            uploader_id=user.id,
        )
        uploaded = UploadedFile.query.get(result["file_id"])
        old_path = resolve_uploaded_txt_path(uploaded.stored_filename, app.config["UPLOAD_FOLDER"])
        assert os.path.exists(old_path)

        uploaded.uploaded_at = beijing_now() - timedelta(days=31)
        uploaded.pending_count = 0
        uploaded.assigned_count = 0
        uploaded.completed_count = uploaded.total_tickets

        ticket = LotteryTicket.query.filter_by(source_file_id=uploaded.id).first()
        ticket.status = "completed"
        ticket.completed_at = beijing_now() - timedelta(days=5)
        db.session.commit()

        moved = archive_old_uploaded_txt_files(days_ago=30)
        remaining = UploadedFile.query.get(result["file_id"])

    assert moved == 0
    assert os.path.exists(old_path)
    assert remaining is not None


def test_purge_old_auxiliary_records_deletes_old_match_results_before_result_files(app):
    from tasks.archive import purge_old_auxiliary_records
    from models.result import MatchResult, ResultFile

    with app.app_context():
        user = create_user("purge_aux_user", "secret123", client_mode="mode_b")
        result_file = ResultFile(
            original_filename="results.txt",
            stored_filename="results_old.txt",
            uploaded_by=user.id,
            uploaded_at=beijing_now() - timedelta(days=31),
            periods_count=1,
        )
        db.session.add(result_file)
        db.session.commit()

        stored_path = Path(app.config["UPLOAD_FOLDER"]) / result_file.stored_filename
        stored_path.write_text("old result payload", encoding="utf-8")

        match_result = MatchResult(
            detail_period="26034",
            lottery_type="P7",
            result_data={"61": {"SPF": {"result": "3", "sp": 1.85}}},
            result_file_id=result_file.id,
            uploaded_by=user.id,
            uploaded_at=beijing_now() - timedelta(days=31),
        )
        db.session.add(match_result)
        db.session.commit()
        result_file_id = result_file.id
        match_result_id = match_result.id

        purge_old_auxiliary_records(days_ago=30)

        remaining_result_file = ResultFile.query.get(result_file_id)
        remaining_match_result = MatchResult.query.get(match_result_id)

    assert remaining_match_result is None
    assert remaining_result_file is None
    assert not stored_path.exists()


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


def test_login_page_submits_device_id():
    login_template = Path(__file__).resolve().parents[1] / "templates" / "login.html"
    content = login_template.read_text(encoding="utf-8")
    assert "getOrCreateDeviceId" in content
    assert "device_id: deviceId || undefined" in content


def test_login_page_uses_readable_chinese_labels():
    login_template = Path(__file__).resolve().parents[1] / "templates" / "login.html"
    content = login_template.read_text(encoding="utf-8")
    assert "登录 - 数据文件管理平台" in content
    assert "📁 数据文件管理平台" in content
    assert "用户名" in content
    assert "请输入用户名" in content
    assert "密码" in content
    assert "请输入密码" in content
    assert "鐧诲綍" not in content


def test_admin_dashboard_template_uses_readable_chinese_labels():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "管理后台" in content
    # 数据库信息已迁移到设置页，不再在 dashboard 中
    assert "总速度(张/分)" in content
    assert "暂无在线用户" in content
    assert "showToast(data.error || '操作失败', 'danger');" in content


def test_admin_settings_template_handles_save_failures():
    settings_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "settings.html"
    content = settings_template.read_text(encoding="utf-8")
    assert "v-if=\"error\"" in content
    assert "error: ''" in content
    assert "this.error = data.error || '保存失败';" in content
    assert "this.error = '保存失败';" in content
    assert "this.error = '加载设置失败';" in content


def test_admin_users_template_uses_readable_chinese_labels():
    users_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "users.html"
    content = users_template.read_text(encoding="utf-8")
    assert "用户管理" in content
    assert "最大设备数" in content
    assert "接单开关" in content
    assert "确认踢出用户" in content
    assert "请输入用户名和密码" in content


def test_admin_users_template_handles_update_failures():
    users_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "users.html"
    content = users_template.read_text(encoding="utf-8")
    assert "const original = {" in content
    assert "Object.assign(u, original);" in content
    assert "showToast(data.error || '更新失败', 'danger');" in content


def test_winning_presign_uses_local_upload_api_when_oss_disabled(app):
    with app.app_context():
        from services.oss_service import generate_presign_url

        url, oss_key = generate_presign_url("winning/2026/04/07/123.jpg")

    assert url == "/api/winning/upload-local?key=winning_2026_04_07_123.jpg"
    assert oss_key == "winning_2026_04_07_123.jpg"


def test_winning_upload_local_saves_image_under_uploads_images(app, client):
    from PIL import Image

    with app.app_context():
        user = create_user("winning_local_upload_user", "secret123", client_mode="mode_a")
        upload_folder = Path(app.config["UPLOAD_FOLDER"])
        ticket = create_assigned_ticket(user, "device-local", "WIN-LOCAL-001", 1)
        ticket.is_winning = True
        db.session.commit()
        ticket_id = ticket.id

    resp = login(client, "winning_local_upload_user", "secret123")
    assert resp.status_code == 200

    presign_resp = client.get(f"/api/winning/presign?ticket_id={ticket_id}")
    assert presign_resp.status_code == 200
    presign_data = presign_resp.get_json()
    assert presign_data["success"] is True
    assert presign_data["url"].startswith("/api/winning/upload-local?key=")

    image_bytes = io.BytesIO()
    Image.new("RGB", (20, 20), color="blue").save(image_bytes, format="PNG")
    image_bytes.seek(0)

    upload_resp = client.post(
        presign_data["url"],
        data={"file": (image_bytes, "winning.png")},
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 200
    upload_data = upload_resp.get_json()
    assert upload_data["success"] is True
    assert upload_data["image_url"].startswith("/uploads/images/winning_")
    assert upload_data["oss_key"].startswith("winning_")

    saved_path = upload_folder / "images" / upload_data["oss_key"]
    assert saved_path.exists()


def test_winning_upload_local_requires_matching_ticket_key(app, client):
    from PIL import Image

    with app.app_context():
        user = create_user("winning_local_guard_user", "secret123", client_mode="mode_a")
        ticket = create_assigned_ticket(user, "device-local", "WIN-LOCAL-GUARD", 1)
        ticket.is_winning = True
        db.session.commit()
        ticket_id = ticket.id

    resp = login(client, "winning_local_guard_user", "secret123")
    assert resp.status_code == 200

    image_bytes = io.BytesIO()
    Image.new("RGB", (20, 20), color="green").save(image_bytes, format="PNG")
    image_bytes.seek(0)

    upload_resp = client.post(
        f"/api/winning/upload-local?ticket_id={ticket_id}&key=winning_2026_04_07_999.jpg",
        data={"file": (image_bytes, "winning.png")},
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 400
    data = upload_resp.get_json()
    assert data["success"] is False
    assert "不匹配" in data["error"]


def test_admin_export_tickets_csv_uses_business_window_without_name_error(app, client, monkeypatch):
    business_start = datetime(2026, 4, 6, 12, 0, 0)

    with app.app_context():
        admin = User(username="admin_csv_export_user", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

        in_window = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="CSV-IN-WINDOW",
            status="completed",
            assigned_username="user-a",
            completed_at=business_start + timedelta(hours=1),
        )
        out_of_window = LotteryTicket(
            source_file_id=1,
            line_number=2,
            raw_content="CSV-OUT-OF-WINDOW",
            status="completed",
            assigned_username="user-a",
            completed_at=business_start - timedelta(hours=1),
        )
        db.session.add_all([in_window, out_of_window])
        db.session.commit()

    monkeypatch.setattr("routes.admin.get_today_noon", lambda: business_start)
    monkeypatch.setattr("routes.admin.get_business_date", lambda dt=None: business_start.date())

    resp = client.post("/auth/login", json={"username": "admin_csv_export_user", "password": "secret123"})
    assert resp.status_code == 200

    export_resp = client.get("/admin/api/tickets/export")
    assert export_resp.status_code == 200
    csv_text = export_resp.data.decode("utf-8-sig")
    assert "CSV-IN-WINDOW" in csv_text
    assert "CSV-OUT-OF-WINDOW" not in csv_text


def test_admin_files_list_rejects_invalid_page_params(app, client):
    with app.app_context():
        admin = User(username="admin_invalid_page_user", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_invalid_page_user", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.get("/admin/api/files?page=bad")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "分页参数" in data["error"]


def test_uploaded_file_to_dict_uses_derived_status(app):
    with app.app_context():
        completed_file = UploadedFile(
            display_id="2026/04/07-01",
            original_filename="done.txt",
            stored_filename="txt/2026-04-07/done.txt",
            uploaded_by=1,
            total_tickets=5,
            completed_count=5,
            pending_count=0,
            assigned_count=0,
            deadline_time=beijing_now() + timedelta(hours=1),
        )
        expired_file = UploadedFile(
            display_id="2026/04/07-02",
            original_filename="expired.txt",
            stored_filename="txt/2026-04-07/expired.txt",
            uploaded_by=1,
            total_tickets=5,
            completed_count=2,
            pending_count=0,
            assigned_count=0,
            deadline_time=beijing_now() - timedelta(hours=1),
        )
        db.session.add_all([completed_file, expired_file])
        db.session.commit()

        assert completed_file.to_dict()["status"] == "exhausted"
        assert expired_file.to_dict()["status"] == "expired"


def test_admin_files_list_filters_by_derived_status(app, client):
    with app.app_context():
        admin = User(username="admin_file_status_filter", is_admin=True)
        admin.set_password("secret123")
        exhausted_file = UploadedFile(
            display_id="2026/04/07-03",
            original_filename="exhausted.txt",
            stored_filename="txt/2026-04-07/exhausted.txt",
            uploaded_by=1,
            total_tickets=3,
            completed_count=3,
            pending_count=0,
            assigned_count=0,
            deadline_time=beijing_now() + timedelta(hours=1),
        )
        active_file = UploadedFile(
            display_id="2026/04/07-04",
            original_filename="active.txt",
            stored_filename="txt/2026-04-07/active.txt",
            uploaded_by=1,
            total_tickets=3,
            completed_count=1,
            pending_count=2,
            assigned_count=0,
            deadline_time=beijing_now() + timedelta(hours=1),
        )
        db.session.add_all([admin, exhausted_file, active_file])
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_file_status_filter", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.get("/admin/api/files?status=exhausted")
    assert resp.status_code == 200
    data = resp.get_json()
    names = [item["original_filename"] for item in data["files"]]
    assert "exhausted.txt" in names
    assert "active.txt" not in names


def test_admin_file_management_endpoints_require_login_json_response(app, client):
    list_resp = client.get("/admin/api/files")
    assert list_resp.status_code == 401
    assert list_resp.is_json is True
    assert list_resp.get_json()["success"] is False

    upload_resp = client.post("/admin/files/upload")
    assert upload_resp.status_code == 401
    assert upload_resp.is_json is True
    assert upload_resp.get_json()["success"] is False


def test_admin_file_detail_returns_json_for_missing_file(app, client):
    with app.app_context():
        admin = User(username="admin_missing_file_detail", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_missing_file_detail", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.get("/admin/api/files/999999/detail")
    assert resp.status_code == 404
    assert resp.is_json is True
    data = resp.get_json()
    assert data["success"] is False
    assert "文件不存在" in data["error"]


def test_admin_revoke_missing_file_returns_404_json(app, client):
    with app.app_context():
        admin = User(username="admin_missing_revoke_file", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_missing_revoke_file", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post("/admin/api/files/999999/revoke")
    assert resp.status_code == 404
    assert resp.is_json is True
    data = resp.get_json()
    assert data["success"] is False
    assert "文件不存在" in data["message"]


def test_admin_create_user_rejects_invalid_max_devices(app, client):
    with app.app_context():
        admin = User(username="admin_create_user_guard", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_create_user_guard", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post(
        "/admin/api/users",
        json={"username": "bad_max_devices_user", "password": "secret123", "max_devices": "bad"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "最大设备数" in data["error"]


def test_admin_update_settings_handles_empty_json_body(app, client):
    with app.app_context():
        admin = User(username="admin_settings_empty_body", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_settings_empty_body", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.put("/admin/api/settings", data="", content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "settings" in data


def test_admin_update_settings_rejects_invalid_session_hours(app, client):
    with app.app_context():
        admin = User(username="admin_settings_hours_guard", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_settings_hours_guard", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.put("/admin/api/settings", json={"session_lifetime_hours": 0})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "无活动超时" in data["error"]


def test_admin_update_settings_reschedules_daily_reset_job(app, client, monkeypatch):
    rescheduled = []

    def fake_reschedule(app_obj, hour):
        rescheduled.append(hour)

    monkeypatch.setattr("tasks.scheduler.reschedule_daily_reset", fake_reschedule)

    with app.app_context():
        admin = User(username="admin_settings_reschedule", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_settings_reschedule", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.put("/admin/api/settings", json={"daily_reset_hour": 8})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["settings"]["daily_reset_hour"] == 8
    assert rescheduled == [8]


def test_admin_update_settings_normalizes_mode_b_options(app, client):
    with app.app_context():
        admin = User(username="admin_settings_modeb_guard", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_settings_modeb_guard", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.put("/admin/api/settings", json={"mode_b_options": [200, "50", 200, "100"]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["settings"]["mode_b_options"] == [200, 50, 100]


def test_admin_winning_template_uses_readable_chinese_labels():
    winning_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "winning.html"
    content = winning_template.read_text(encoding="utf-8")
    assert "结果管理" in content
    assert "全部图片状态" in content
    assert "税后合计：" in content
    assert "确认将这条中奖记录标记为已检查吗？" in content
    assert "上传成功，已解析 ${data.count} 条赛果，中奖计算已加入队列" in content
    assert "showToast(data.success ? '已提交重算' : (data.error || '提交失败')" in content


def test_admin_winning_template_declares_match_results_and_uploading_state():
    winning_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "winning.html"
    content = winning_template.read_text(encoding="utf-8")
    assert "matchResults: [], mrFilterDate: '', mrDateOptions: []" in content
    assert "uploadingImageId: null" in content


def test_client_dashboard_template_uses_readable_chinese_labels():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "我的主页" in content
    assert "今日处理张数" in content
    assert "今日各设备出票统计" in content
    assert "确认停止接单？当前票将标记为已完成。" in content


def test_client_dashboard_preserves_winning_group_mode_after_filter():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "this.applyWinningGrouping();" in content
    assert "const key = r.business_date || 'unknown';" in content
    assert "this.winningGroupBy === 'date'" in content


def test_client_dashboard_clears_password_success_timer_before_reopen():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "pwdSuccessTimer: null" in content
    assert "clearTimeout(this.pwdSuccessTimer);" in content
    assert "this.pwdSuccessTimer = setTimeout(() => {" in content


def test_client_dashboard_only_shows_no_ticket_toast_once():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert content.count("showToast(data.error || '暂无可用票', 'warning');") == 1


def test_client_dashboard_handles_mode_a_stop_failures_and_localizes_next_ticket_messages():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "showToast('请等待 ' + remaining + ' 秒后再获取下一张', 'warning');" in content
    assert "showToast(data.error || '暂无可用票', 'warning');" in content
    assert "showToast('获取下一张失败，请稍后重试', 'danger');" in content
    assert "if (!data.success) {" in content
    assert "showToast(data.error || '停止接单失败', 'danger');" in content
    assert "showToast(data.message || '已停止接单', 'success');" in content
    assert "this.countdown = '已截止';" in content


def test_admin_winning_template_uses_api_mark_checked_endpoint():
    winning_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "winning.html"
    content = winning_template.read_text(encoding="utf-8")
    assert "fetch(`/api/winning/admin/mark-checked/${record.winning_record_id}`" in content
    assert "fetch(`/winning/admin/mark-checked/${record.winning_record_id}`" not in content


def test_admin_winning_template_tracks_summary_tax_and_missing():
    winning_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "winning.html"
    content = winning_template.read_text(encoding="utf-8")
    assert "summaryTax" in content
    assert "summaryMissing" in content
    assert "data.summary.tax" in content
    assert "data.summary.missing" in content


def test_admin_winning_export_preserves_checked_filter():
    winning_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "winning.html"
    content = winning_template.read_text(encoding="utf-8")
    assert "params.set('checked_status', this.filterChecked)" in content


def test_admin_winning_export_honors_checked_status_filter(app, client):
    from io import BytesIO
    from openpyxl import load_workbook

    with app.app_context():
        admin = User(username="admin_export_user", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)

        ticket_checked = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="CHK-001",
            status="completed",
            assigned_username="user-a",
            completed_at=beijing_now(),
            is_winning=True,
        )
        ticket_unchecked = LotteryTicket(
            source_file_id=1,
            line_number=2,
            raw_content="UNCHK-001",
            status="completed",
            assigned_username="user-a",
            completed_at=beijing_now(),
            is_winning=True,
        )
        db.session.add_all([ticket_checked, ticket_unchecked])
        db.session.commit()

        db.session.add(WinningRecord(ticket_id=ticket_checked.id, is_checked=True, uploaded_by=admin.id))
        db.session.add(WinningRecord(ticket_id=ticket_unchecked.id, is_checked=False, uploaded_by=admin.id))
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_export_user", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.get("/admin/api/winning/export?checked_status=checked")
    assert resp.status_code == 200
    wb = load_workbook(BytesIO(resp.data))
    ws = wb.active
    exported_values = [row[1] for row in ws.iter_rows(min_row=2, values_only=True)]
    assert "CHK-001" in exported_values
    assert "UNCHK-001" not in exported_values


def test_admin_checked_winning_record_cannot_replace_image(app, client):
    from io import BytesIO

    with app.app_context():
        admin = User(username="admin_checked_image", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)

        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="CHK-IMG-001",
            status="completed",
            assigned_username="user-a",
            completed_at=beijing_now(),
            is_winning=True,
            winning_image_url="/uploads/images/original.jpg",
        )
        db.session.add(ticket)
        db.session.commit()

        db.session.add(WinningRecord(ticket_id=ticket.id, is_checked=True, uploaded_by=admin.id))
        db.session.commit()
        ticket_id = ticket.id

    resp = client.post("/auth/login", json={"username": "admin_checked_image", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post(
        f"/admin/api/winning/{ticket_id}/upload-image",
        data={"image": (BytesIO(b"fake-image"), "winning.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False
    assert "已检查" in data["error"]


def test_admin_winning_record_creates_winning_record(app, client):
    with app.app_context():
        admin = User(username="admin_record_creator", is_admin=True)
        admin.set_password("secret123")
        user = create_user("admin_record_target", "secret123", client_mode="mode_a")
        db.session.add(admin)
        db.session.commit()

        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="ADMIN-OSS-001",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
            is_winning=True,
        )
        db.session.add(ticket)
        db.session.commit()
        ticket_id = ticket.id

    resp = client.post("/auth/login", json={"username": "admin_record_creator", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post(
        "/admin/api/winning/record",
        json={"ticket_id": ticket_id, "oss_key": "winning/test/admin-001.jpg"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["record"]["ticket_id"] == ticket_id

    with app.app_context():
        ticket = LotteryTicket.query.get(ticket_id)
        record = WinningRecord.query.filter_by(ticket_id=ticket_id).first()
        assert ticket.is_winning is True
        assert ticket.winning_image_url
        assert record is not None
        assert record.image_oss_key == "winning/test/admin-001.jpg"


def test_record_winning_does_not_delete_reuploaded_same_oss_key(app, client, monkeypatch):
    deleted = []
    monkeypatch.setattr("services.oss_service.delete_stored_image", lambda key=None, url=None: deleted.append((key, url)))
    monkeypatch.setattr("services.oss_service.get_public_url", lambda oss_key: f"https://oss.example.com/{oss_key}")

    with app.app_context():
        user = create_user("winning_same_key_user", "secret123", client_mode="mode_a")
        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-SAME-KEY",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
            is_winning=True,
            winning_image_url="https://oss.example.com/winning/2026/04/07/1.jpg",
        )
        db.session.add(ticket)
        db.session.commit()
        db.session.add(WinningRecord(
            ticket_id=ticket.id,
            source_file_id=ticket.source_file_id,
            detail_period=ticket.detail_period,
            lottery_type=ticket.lottery_type,
            winning_image_url=ticket.winning_image_url,
            image_oss_key="winning/2026/04/07/1.jpg",
            uploaded_by=user.id,
        ))
        db.session.commit()
        ticket_id = ticket.id

    resp = login(client, "winning_same_key_user", "secret123")
    assert resp.status_code == 200

    resp = client.post(
        "/api/winning/record",
        json={"ticket_id": ticket_id, "oss_key": "winning/2026/04/07/1.jpg"},
    )
    assert resp.status_code == 200
    assert deleted == []


def test_record_winning_rejects_checked_record_replacement(app, client):
    with app.app_context():
        user = create_user("winning_checked_guard_user", "secret123", client_mode="mode_a")
        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-CHECKED-GUARD",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
            is_winning=True,
            winning_image_url="https://oss.example.com/winning/original.jpg",
        )
        db.session.add(ticket)
        db.session.commit()
        db.session.add(WinningRecord(
            ticket_id=ticket.id,
            source_file_id=ticket.source_file_id,
            detail_period=ticket.detail_period,
            lottery_type=ticket.lottery_type,
            winning_image_url=ticket.winning_image_url,
            image_oss_key="winning/original.jpg",
            uploaded_by=user.id,
            is_checked=True,
        ))
        db.session.commit()
        ticket_id = ticket.id

    resp = login(client, "winning_checked_guard_user", "secret123")
    assert resp.status_code == 200

    resp = client.post(
        "/api/winning/record",
        json={"ticket_id": ticket_id, "oss_key": "winning/replaced.jpg", "winning_amount": 100},
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False
    assert "已检查" in data["error"]


def test_winning_presign_rejects_checked_record(app, client):
    with app.app_context():
        user = create_user("winning_presign_checked_user", "secret123", client_mode="mode_a")
        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-PRESIGN-CHECKED",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
            is_winning=True,
        )
        db.session.add(ticket)
        db.session.commit()
        db.session.add(WinningRecord(ticket_id=ticket.id, uploaded_by=user.id, is_checked=True))
        db.session.commit()
        ticket_id = ticket.id

    resp = login(client, "winning_presign_checked_user", "secret123")
    assert resp.status_code == 200

    resp = client.get(f"/api/winning/presign?ticket_id={ticket_id}")
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False
    assert "已检查" in data["error"]


def test_record_winning_handles_empty_json_body(app, client):
    with app.app_context():
        user = create_user("winning_record_empty_body_user", "secret123", client_mode="mode_a")
        create_assigned_ticket(user, "device-win-empty", "WIN-EMPTY", 1)

    resp = login(client, "winning_record_empty_body_user", "secret123")
    assert resp.status_code == 200

    resp = client.post("/api/winning/record", data="", content_type="application/json")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "参数不完整" in data["error"]


def test_admin_winning_record_does_not_delete_reuploaded_same_oss_key(app, client, monkeypatch):
    deleted = []
    monkeypatch.setattr("services.oss_service.delete_stored_image", lambda key=None, url=None: deleted.append((key, url)))
    monkeypatch.setattr("services.oss_service.get_public_url", lambda oss_key: f"https://oss.example.com/{oss_key}")

    with app.app_context():
        admin = User(username="admin_same_key", is_admin=True)
        admin.set_password("secret123")
        user = create_user("admin_same_key_target", "secret123", client_mode="mode_a")
        db.session.add(admin)
        db.session.commit()

        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="ADMIN-SAME-KEY",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
            is_winning=True,
            winning_image_url="https://oss.example.com/winning/2026/04/07/2.jpg",
        )
        db.session.add(ticket)
        db.session.commit()
        db.session.add(WinningRecord(
            ticket_id=ticket.id,
            source_file_id=ticket.source_file_id,
            detail_period=ticket.detail_period,
            lottery_type=ticket.lottery_type,
            winning_image_url=ticket.winning_image_url,
            image_oss_key="winning/2026/04/07/2.jpg",
            uploaded_by=admin.id,
        ))
        db.session.commit()
        ticket_id = ticket.id

    resp = client.post("/auth/login", json={"username": "admin_same_key", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post(
        "/admin/api/winning/record",
        json={"ticket_id": ticket_id, "oss_key": "winning/2026/04/07/2.jpg"},
    )
    assert resp.status_code == 200
    assert deleted == []


def test_admin_winning_record_rejects_empty_oss_key(app, client):
    with app.app_context():
        admin = User(username="admin_empty_oss_key", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="ADMIN-EMPTY-KEY",
            status="completed",
            completed_at=beijing_now(),
        )
        db.session.add(ticket)
        db.session.commit()
        ticket_id = ticket.id

    resp = client.post("/auth/login", json={"username": "admin_empty_oss_key", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post("/admin/api/winning/record", json={"ticket_id": ticket_id, "oss_key": ""})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "oss_key" in data["error"]


def test_admin_winning_record_handles_empty_json_body(app, client):
    with app.app_context():
        admin = User(username="admin_winning_empty_body", is_admin=True)
        admin.set_password("secret123")
        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="ADMIN-WIN-EMPTY",
            status="completed",
            completed_at=beijing_now(),
            is_winning=True,
        )
        db.session.add_all([admin, ticket])
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_winning_empty_body", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post("/admin/api/winning/record", data="", content_type="application/json")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "oss_key" in data["error"]


def test_admin_winning_record_checked_error_uses_readable_chinese(app, client):
    with app.app_context():
        admin = User(username="admin_checked_record_text", is_admin=True)
        admin.set_password("secret123")
        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="ADMIN-CHECKED-TEXT",
            status="completed",
            completed_at=beijing_now(),
            is_winning=True,
        )
        db.session.add_all([admin, ticket])
        db.session.commit()
        db.session.add(WinningRecord(ticket_id=ticket.id, is_checked=True, uploaded_by=admin.id))
        db.session.commit()
        ticket_id = ticket.id

    resp = client.post("/auth/login", json={"username": "admin_checked_record_text", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post(
        "/admin/api/winning/record",
        json={"ticket_id": ticket_id, "oss_key": "winning/test/admin-checked.jpg"},
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False
    assert "已检查" in data["error"]
    assert "璇" not in data["error"]


def test_admin_winning_presign_rejects_checked_record(app, client):
    with app.app_context():
        admin = User(username="admin_presign_checked_record", is_admin=True)
        admin.set_password("secret123")
        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="ADMIN-PRESIGN-CHECKED",
            status="completed",
            completed_at=beijing_now(),
            is_winning=True,
        )
        db.session.add_all([admin, ticket])
        db.session.commit()
        db.session.add(WinningRecord(ticket_id=ticket.id, uploaded_by=admin.id, is_checked=True))
        db.session.commit()
        ticket_id = ticket.id

    resp = client.post("/auth/login", json={"username": "admin_presign_checked_record", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post(f"/admin/api/winning/{ticket_id}/presign")
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False
    assert "已检查" in data["error"]


def test_winning_presign_rejects_invalid_ticket_id(app, client):
    with app.app_context():
        user = create_user("winning_invalid_ticket_id_user", "secret123", client_mode="mode_a")

    resp = login(client, "winning_invalid_ticket_id_user", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/winning/presign?ticket_id=abc")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "票ID必须是整数" in data["error"]


def test_winning_record_rejects_non_winning_ticket(app, client):
    with app.app_context():
        user = create_user("winning_non_winning_user", "secret123", client_mode="mode_a")
        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="NOT-WIN-001",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
            is_winning=False,
        )
        db.session.add(ticket)
        db.session.commit()
        ticket_id = ticket.id

    resp = login(client, "winning_non_winning_user", "secret123")
    assert resp.status_code == 200

    resp = client.post(
        "/api/winning/record",
        json={"ticket_id": ticket_id, "oss_key": "winning/test/not-win.jpg"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "未被系统判定为中奖" in data["error"]

    with app.app_context():
        ticket = LotteryTicket.query.get(ticket_id)
        assert ticket.is_winning is False
        assert WinningRecord.query.filter_by(ticket_id=ticket_id).first() is None


def test_admin_winning_record_rejects_invalid_ticket_id(app, client):
    with app.app_context():
        admin = User(username="admin_invalid_winning_ticket_id", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_invalid_winning_ticket_id", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post(
        "/admin/api/winning/record",
        json={"ticket_id": "bad-id", "oss_key": "winning/test/admin-invalid.jpg"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "票ID必须是大于 0 的整数" in data["error"]


def test_admin_winning_presign_rejects_non_winning_ticket(app, client):
    with app.app_context():
        admin = User(username="admin_presign_non_winning", is_admin=True)
        admin.set_password("secret123")
        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="ADMIN-NOT-WIN-001",
            status="completed",
            completed_at=beijing_now(),
            is_winning=False,
        )
        db.session.add_all([admin, ticket])
        db.session.commit()
        ticket_id = ticket.id

    resp = client.post("/auth/login", json={"username": "admin_presign_non_winning", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post(f"/admin/api/winning/{ticket_id}/presign")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "未被系统判定为中奖" in data["error"]


def test_admin_upload_winning_image_creates_winning_record(app, client):
    from io import BytesIO
    from PIL import Image

    with app.app_context():
        admin = User(username="admin_upload_creator", is_admin=True)
        admin.set_password("secret123")
        user = create_user("admin_upload_target", "secret123", client_mode="mode_a")
        db.session.add(admin)
        db.session.commit()

        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="ADMIN-UPLOAD-001",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
            is_winning=True,
        )
        db.session.add(ticket)
        db.session.commit()
        ticket_id = ticket.id

    resp = client.post("/auth/login", json={"username": "admin_upload_creator", "password": "secret123"})
    assert resp.status_code == 200

    image_bytes = BytesIO()
    Image.new("RGB", (20, 20), color="blue").save(image_bytes, format="PNG")
    image_bytes.seek(0)

    resp = client.post(
        f"/admin/api/winning/{ticket_id}/upload-image",
        data={"image": (image_bytes, "winning.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["record"]["ticket_id"] == ticket_id

    with app.app_context():
        ticket = LotteryTicket.query.get(ticket_id)
        record = WinningRecord.query.filter_by(ticket_id=ticket_id).first()
        assert ticket.is_winning is True
        assert ticket.winning_image_url
        assert record is not None
        assert record.winning_image_url == ticket.winning_image_url


def test_my_winning_returns_business_date(app, client):
    with app.app_context():
        user = create_user("winning_business_date", "secret123", client_mode="mode_a")
        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-BIZ-001",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            assigned_device_id="device-a",
            assigned_device_name="device-a",
            completed_at=beijing_now(),
            is_winning=True,
        )
        db.session.add(ticket)
        db.session.commit()

    resp = login(client, "winning_business_date", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/winning/my")
    assert resp.status_code == 200
    data = resp.get_json()
    records = [item for items in data["grouped"].values() for item in items]
    assert records
    assert records[0]["business_date"]


def test_my_winning_keeps_recent_four_business_days(app, client, monkeypatch):
    business_today = datetime(2026, 4, 7, 13, 0, 0)

    with app.app_context():
        user = create_user("winning_recent_four", "secret123", client_mode="mode_a")
        keep_ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-KEEP-4D",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=datetime(2026, 4, 4, 13, 0, 0),
            is_winning=True,
        )
        drop_ticket = LotteryTicket(
            source_file_id=1,
            line_number=2,
            raw_content="WIN-DROP-5D",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=datetime(2026, 4, 3, 11, 0, 0),
            is_winning=True,
        )
        db.session.add_all([keep_ticket, drop_ticket])
        db.session.commit()

    monkeypatch.setattr("routes.winning.get_business_date", lambda dt=None: (dt or business_today).date() if dt else business_today.date())

    resp = login(client, "winning_recent_four", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/winning/my")
    assert resp.status_code == 200
    data = resp.get_json()
    records = [item["raw_content"] for items in data["grouped"].values() for item in items]
    assert "WIN-KEEP-4D" in records
    assert "WIN-DROP-5D" not in records


def test_winning_calc_includes_expired_but_excludes_revoked(app, monkeypatch):
    from services.winning_calc_service import process_match_result

    def fake_calculate_winning(raw_content, result_data, multiplier):
        if raw_content in {"WIN-COMPLETED", "WIN-EXPIRED"}:
            return True, 100, 100, 0
        return False, 0, 0, 0

    monkeypatch.setattr("services.winning_calc_service.calculate_winning", fake_calculate_winning)

    with app.app_context():
        user = create_user("winning_calc_status_user", "secret123", client_mode="mode_b")
        match_result = MatchResult(
            detail_period="26066",
            result_data={"1": {"SPF": {"result": "3", "sp": 1.23}}},
            uploaded_by=user.id,
        )
        db.session.add(match_result)
        db.session.commit()

        completed_ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-COMPLETED",
            status="completed",
            detail_period="26066",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
        )
        expired_ticket = LotteryTicket(
            source_file_id=1,
            line_number=2,
            raw_content="WIN-EXPIRED",
            status="expired",
            detail_period="26066",
            assigned_user_id=user.id,
            assigned_username=user.username,
            deadline_time=beijing_now(),
        )
        revoked_ticket = LotteryTicket(
            source_file_id=1,
            line_number=3,
            raw_content="WIN-REVOKED",
            status="revoked",
            detail_period="26066",
            assigned_user_id=user.id,
            assigned_username=user.username,
            admin_upload_time=beijing_now(),
        )
        db.session.add_all([completed_ticket, expired_ticket, revoked_ticket])
        db.session.commit()

        process_match_result(match_result.id, app=app)
        db.session.expire_all()

        refreshed_completed = LotteryTicket.query.get(completed_ticket.id)
        refreshed_expired = LotteryTicket.query.get(expired_ticket.id)
        refreshed_revoked = LotteryTicket.query.get(revoked_ticket.id)
        refreshed_result = MatchResult.query.get(match_result.id)

    assert refreshed_completed.is_winning is True
    assert refreshed_expired.is_winning is True
    assert refreshed_revoked.is_winning is None
    assert refreshed_result.tickets_total == 2
    assert refreshed_result.tickets_winning == 2


def test_winning_calc_clears_stale_amounts_when_ticket_calc_errors(app, monkeypatch):
    from services.winning_calc_service import process_match_result

    def fake_calculate_winning(raw_content, result_data, multiplier):
        raise RuntimeError("boom")

    monkeypatch.setattr("services.winning_calc_service.calculate_winning", fake_calculate_winning)

    with app.app_context():
        user = create_user("winning_calc_error_user", "secret123", client_mode="mode_b")
        match_result = MatchResult(
            detail_period="26067",
            result_data={"1": {"SPF": {"result": "3", "sp": 1.23}}},
            uploaded_by=user.id,
        )
        db.session.add(match_result)
        db.session.commit()

        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-ERROR",
            status="completed",
            detail_period="26067",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
            is_winning=True,
            winning_gross=123,
            winning_amount=100,
            winning_tax=23,
        )
        db.session.add(ticket)
        db.session.commit()

        process_match_result(match_result.id, app=app)
        db.session.expire_all()

        refreshed_ticket = LotteryTicket.query.get(ticket.id)
        refreshed_result = MatchResult.query.get(match_result.id)

    assert refreshed_ticket.is_winning is False
    assert refreshed_ticket.winning_gross is None
    assert refreshed_ticket.winning_amount is None
    assert refreshed_ticket.winning_tax is None
    assert refreshed_result.tickets_winning == 0
    assert float(refreshed_result.total_winning_amount or 0) == 0.0


def test_winning_calc_removes_stale_winning_record_when_ticket_is_no_longer_winning(app, monkeypatch):
    from services.winning_calc_service import process_match_result

    def fake_calculate_winning(raw_content, result_data, multiplier):
        return False, 0, 0, 0

    monkeypatch.setattr("services.winning_calc_service.calculate_winning", fake_calculate_winning)

    with app.app_context():
        user = create_user("winning_calc_stale_record_user", "secret123", client_mode="mode_b")
        match_result = MatchResult(
            detail_period="26068",
            result_data={"1": {"SPF": {"result": "3", "sp": 1.23}}},
            uploaded_by=user.id,
        )
        db.session.add(match_result)
        db.session.commit()

        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-STALE-RECORD",
            status="completed",
            detail_period="26068",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
            is_winning=True,
            winning_image_url="/uploads/images/stale.png",
        )
        db.session.add(ticket)
        db.session.commit()
        db.session.add(WinningRecord(
            ticket_id=ticket.id,
            source_file_id=ticket.source_file_id,
            detail_period=ticket.detail_period,
            lottery_type=ticket.lottery_type,
            winning_image_url=ticket.winning_image_url,
            uploaded_by=user.id,
        ))
        db.session.commit()

        process_match_result(match_result.id, app=app)
        db.session.expire_all()

        refreshed_ticket = LotteryTicket.query.get(ticket.id)
        refreshed_record = WinningRecord.query.filter_by(ticket_id=ticket.id).first()

    assert refreshed_ticket.is_winning is False
    assert refreshed_ticket.winning_image_url is None
    assert refreshed_record is None


def test_winning_calc_removes_stale_local_image_when_ticket_is_no_longer_winning(app, monkeypatch):
    from services.winning_calc_service import process_match_result

    def fake_calculate_winning(raw_content, result_data, multiplier):
        return False, 0, 0, 0

    monkeypatch.setattr("services.winning_calc_service.calculate_winning", fake_calculate_winning)

    with app.app_context():
        user = create_user("winning_calc_stale_image_user", "secret123", client_mode="mode_b")
        match_result = MatchResult(
            detail_period="26069",
            result_data={"1": {"SPF": {"result": "3", "sp": 1.23}}},
            uploaded_by=user.id,
        )
        db.session.add(match_result)
        db.session.commit()

        images_dir = Path(app.config["UPLOAD_FOLDER"]) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        stale_path = images_dir / "stale-winning.png"
        stale_path.write_bytes(b"stale-image")

        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-STALE-IMAGE",
            status="completed",
            detail_period="26069",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
            is_winning=True,
            winning_image_url="/uploads/images/stale-winning.png",
        )
        db.session.add(ticket)
        db.session.commit()
        db.session.add(WinningRecord(
            ticket_id=ticket.id,
            source_file_id=ticket.source_file_id,
            detail_period=ticket.detail_period,
            lottery_type=ticket.lottery_type,
            winning_image_url=ticket.winning_image_url,
            uploaded_by=user.id,
        ))
        db.session.commit()

        process_match_result(match_result.id, app=app)

    assert not stale_path.exists()


def test_admin_winning_lists_expired_ticket_with_special_status(app, client):
    from io import BytesIO
    from openpyxl import load_workbook

    with app.app_context():
        admin = User(username="admin_winning_expired", is_admin=True)
        admin.set_password("secret123")
        user = create_user("expired_winning_user", "secret123", client_mode="mode_a")
        db.session.add(admin)
        db.session.commit()

        expired_ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-EXPIRED-LIST",
            status="expired",
            assigned_user_id=user.id,
            assigned_username=user.username,
            deadline_time=datetime(2026, 4, 7, 11, 0, 0),
            is_winning=True,
            winning_amount=88,
        )
        db.session.add(expired_ticket)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_winning_expired", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.get("/admin/api/winning?date=2026-04-06")
    assert resp.status_code == 200
    data = resp.get_json()
    assert [r["raw_content"] for r in data["records"]] == ["WIN-EXPIRED-LIST"]
    assert data["records"][0]["status"] == "expired"
    assert data["records"][0]["status_label"] == "已过期未出票"
    assert data["records"][0]["terminal_at"].startswith("2026-04-07T11:00:00")

    export_resp = client.get("/admin/api/winning/export?date=2026-04-06")
    assert export_resp.status_code == 200
    wb = load_workbook(BytesIO(export_resp.data))
    ws = wb.active
    header = [cell for cell in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    row = [cell for cell in next(ws.iter_rows(min_row=2, max_row=2, values_only=True))]
    assert "状态" in header
    assert "终态时间" in header
    assert "已过期未出票" in row
    assert "2026-04-07 11:00:00" in row


def test_my_winning_still_hides_expired_tickets(app, client):
    with app.app_context():
        user = create_user("winning_hide_expired", "secret123", client_mode="mode_a")
        completed_ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-COMPLETED-VIEW",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
            is_winning=True,
        )
        expired_ticket = LotteryTicket(
            source_file_id=1,
            line_number=2,
            raw_content="WIN-EXPIRED-HIDDEN",
            status="expired",
            assigned_user_id=user.id,
            assigned_username=user.username,
            deadline_time=beijing_now(),
            is_winning=True,
        )
        db.session.add_all([completed_ticket, expired_ticket])
        db.session.commit()

    resp = login(client, "winning_hide_expired", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/winning/my")
    assert resp.status_code == 200
    data = resp.get_json()
    records = [item["raw_content"] for items in data["grouped"].values() for item in items]
    assert "WIN-COMPLETED-VIEW" in records
    assert "WIN-EXPIRED-HIDDEN" not in records


def test_admin_file_list_uses_business_date_for_date_filter(app, client):
    with app.app_context():
        admin = User(username="admin_file_date", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

        file_prev_business = UploadedFile(
            display_id="2026/04/06-01",
            original_filename="before_noon.txt",
            stored_filename="before_noon.txt",
            uploaded_by=admin.id,
            total_tickets=1,
            pending_count=1,
            uploaded_at=datetime(2026, 4, 7, 11, 0, 0),
        )
        file_current_business = UploadedFile(
            display_id="2026/04/07-01",
            original_filename="after_noon.txt",
            stored_filename="after_noon.txt",
            uploaded_by=admin.id,
            total_tickets=1,
            pending_count=1,
            uploaded_at=datetime(2026, 4, 7, 13, 0, 0),
        )
        db.session.add_all([file_prev_business, file_current_business])
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_file_date", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.get("/admin/api/files?date=2026-04-06")
    assert resp.status_code == 200
    data = resp.get_json()
    assert [f["original_filename"] for f in data["files"]] == ["before_noon.txt"]
    assert "2026-04-06" in data["date_options"]
    assert "2026-04-07" in data["date_options"]


def test_admin_winning_uses_business_date_for_date_filter(app, client):
    with app.app_context():
        admin = User(username="admin_winning_date", is_admin=True)
        admin.set_password("secret123")
        user = create_user("winning_date_user", "secret123", client_mode="mode_a")

        db.session.add(admin)
        db.session.commit()

        ticket_prev_business = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="WIN-PREV-BIZ",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=datetime(2026, 4, 7, 11, 0, 0),
            is_winning=True,
        )
        ticket_current_business = LotteryTicket(
            source_file_id=1,
            line_number=2,
            raw_content="WIN-CUR-BIZ",
            status="completed",
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=datetime(2026, 4, 7, 13, 0, 0),
            is_winning=True,
        )
        db.session.add_all([ticket_prev_business, ticket_current_business])
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_winning_date", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.get("/admin/api/winning/filter-options")
    assert resp.status_code == 200
    options = resp.get_json()
    assert "2026-04-06" in options["dates"]
    assert "2026-04-07" in options["dates"]

    resp = client.get("/admin/api/winning?date=2026-04-06")
    assert resp.status_code == 200
    data = resp.get_json()
    assert [r["raw_content"] for r in data["records"]] == ["WIN-PREV-BIZ"]

    export_resp = client.get("/admin/api/winning/export?date=2026-04-06")
    assert export_resp.status_code == 200
    assert export_resp.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_admin_match_results_use_business_date_for_date_filter(app, client):
    with app.app_context():
        admin = User(username="admin_match_result_date", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

        prev_business = MatchResult(
            detail_period="26034",
            result_data={"1": {"SPF": {"result": "3", "sp": 1.23}}},
            uploaded_by=admin.id,
            uploaded_at=datetime(2026, 4, 7, 11, 0, 0),
        )
        current_business = MatchResult(
            detail_period="26035",
            result_data={"1": {"SPF": {"result": "1", "sp": 2.34}}},
            uploaded_by=admin.id,
            uploaded_at=datetime(2026, 4, 7, 13, 0, 0),
        )
        db.session.add_all([prev_business, current_business])
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_match_result_date", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.get("/admin/api/match-results?date=2026-04-06")
    assert resp.status_code == 200
    data = resp.get_json()
    assert [r["detail_period"] for r in data["results"]] == ["26034"]
    assert "2026-04-06" in data["dates"]
    assert "2026-04-07" in data["dates"]


def test_upload_match_result_falls_back_to_sync_calc_when_scheduler_missing(app, client, monkeypatch):
    monkeypatch.setattr("tasks.scheduler.get_scheduler", lambda: None)

    with app.app_context():
        admin = User(username="admin_result_sync", is_admin=True)
        admin.set_password("secret123")
        user = create_user("result_sync_user", "secret123", client_mode="mode_b")
        ticket = LotteryTicket(
            source_file_id=1,
            line_number=1,
            raw_content="SPF|1=3|1*1|1",
            status="completed",
            detail_period="26080",
            multiplier=1,
            assigned_user_id=user.id,
            assigned_username=user.username,
            completed_at=beijing_now(),
        )
        db.session.add_all([admin, ticket])
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_result_sync", "password": "secret123"})
    assert resp.status_code == 200

    payload = "序号\t让球胜平负彩果\t让球胜平负SP值\n1\t3\t1.85\n".encode("utf-8")
    resp = client.post(
        "/admin/match-results/upload",
        data={
            "detail_period": "26080",
            "file": (io.BytesIO(payload), "result.txt"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200

    with app.app_context():
        match_result = MatchResult.query.filter_by(detail_period="26080").first()
        ticket = LotteryTicket.query.filter_by(detail_period="26080").first()

    assert match_result is not None
    assert match_result.calc_status == "done"
    assert ticket.is_winning is True


def test_upload_match_result_rejects_empty_filename(app, client):
    with app.app_context():
        admin = User(username="admin_result_empty_name", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()

    resp = client.post("/auth/login", json={"username": "admin_result_empty_name", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post(
        "/admin/match-results/upload",
        data={
            "detail_period": "26100",
            "file": (io.BytesIO(b"payload"), ""),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "文件名不能为空" in data["error"]


def test_parse_result_file_updates_latest_duplicate_match_result(app, tmp_path):
    from services.result_parser import parse_result_file

    with app.app_context():
        admin = User(username="result_duplicate_admin", is_admin=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

        older = MatchResult(
            detail_period="26099",
            result_data={"61": {"SPF": {"result": "0", "sp": 1.1}}},
            uploaded_by=admin_id,
            uploaded_at=beijing_now() - timedelta(days=2),
        )
        newer = MatchResult(
            detail_period="26099",
            result_data={"61": {"SPF": {"result": "1", "sp": 1.2}}},
            uploaded_by=admin_id,
            uploaded_at=beijing_now() - timedelta(days=1),
        )
        db.session.add_all([older, newer])
        db.session.commit()
        older_id = older.id
        newer_id = newer.id

    result_file = tmp_path / "result_duplicate.txt"
    result_file.write_text(
        "序号\t让球胜平负彩果\t让球胜平负SP值\n61\t3\t1.88\n",
        encoding="utf-8",
    )

    with app.app_context():
        result = parse_result_file(str(result_file), "26099", admin_id)
        assert result["success"] is True
        assert result["match_result_id"] == newer_id

        refreshed_older = MatchResult.query.get(older_id)
        refreshed_newer = MatchResult.query.get(newer_id)

    assert refreshed_older.result_data == {"61": {"SPF": {"result": "0", "sp": 1.1}}}
    assert refreshed_newer.result_data["61"]["SPF"]["result"] == "3"


def test_recalc_resets_stale_summary_when_scheduler_missing(app, client, monkeypatch):
    monkeypatch.setattr("tasks.scheduler.get_scheduler", lambda: None)
    monkeypatch.setattr("services.winning_calc_service.process_match_result", lambda result_id, app=None: None)

    with app.app_context():
        admin = User(username="admin_recalc_reset", is_admin=True)
        admin.set_password("secret123")
        match_result = MatchResult(
            detail_period="26081",
            result_data={"1": {"SPF": {"result": "3", "sp": 1.23}}},
            uploaded_by=1,
            calc_status="done",
            calc_started_at=beijing_now(),
            calc_finished_at=beijing_now(),
            tickets_total=12,
            tickets_winning=5,
            total_winning_amount=666,
        )
        db.session.add_all([admin, match_result])
        db.session.commit()
        result_id = match_result.id

    resp = client.post("/auth/login", json={"username": "admin_recalc_reset", "password": "secret123"})
    assert resp.status_code == 200

    resp = client.post(f"/admin/api/match-results/{result_id}/recalc")
    assert resp.status_code == 200

    with app.app_context():
        refreshed = MatchResult.query.get(result_id)

    assert refreshed.calc_status == "pending"
    assert refreshed.calc_started_at is None
    assert refreshed.calc_finished_at is None
    assert refreshed.tickets_total == 0
    assert refreshed.tickets_winning == 0
    assert float(refreshed.total_winning_amount or 0) == 0.0


def test_admin_user_management_endpoints_reject_admin_targets(app, client):
    with app.app_context():
        super_admin = User(username="admin_guard_actor", is_admin=True)
        super_admin.set_password("secret123")
        protected_admin = User(username="admin_guard_target", is_admin=True)
        protected_admin.set_password("secret123")
        db.session.add_all([super_admin, protected_admin])
        db.session.commit()
        protected_admin_id = protected_admin.id

    resp = client.post("/auth/login", json={"username": "admin_guard_actor", "password": "secret123"})
    assert resp.status_code == 200

    update_resp = client.put(f"/admin/api/users/{protected_admin_id}", json={"max_devices": 9})
    assert update_resp.status_code == 403
    assert "管理员账号" in update_resp.get_json()["error"]

    delete_resp = client.delete(f"/admin/api/users/{protected_admin_id}")
    assert delete_resp.status_code == 403
    assert "管理员账号" in delete_resp.get_json()["error"]

    logout_resp = client.post(f"/admin/api/users/{protected_admin_id}/force-logout")
    assert logout_resp.status_code == 403
    assert "管理员账号" in logout_resp.get_json()["error"]


def test_mode_b_confirm_returns_error_when_nothing_completed(app):
    from services.mode_b_service import confirm_batch

    with app.app_context():
        result = confirm_batch([], user_id=1)
    assert result["success"] is False
    assert "票据" in result["error"]


def test_mode_b_confirm_can_complete_prefix_and_expire_rest(app):
    from services.mode_b_service import confirm_batch

    with app.app_context():
        user = create_user("modeb_partial_user", "secret123", client_mode="mode_b")
        first = create_assigned_ticket(user, "device-b", "BATCH-001", 1)
        second = create_assigned_ticket(user, "device-b", "BATCH-002", 2)
        third = create_assigned_ticket(user, "device-b", "BATCH-003", 3)
        for ticket in (first, second, third):
            ticket.deadline_time = beijing_now() - timedelta(minutes=1)
        db.session.commit()

        result = confirm_batch([first.id, second.id, third.id], user_id=user.id, completed_count=2)
        db.session.expire_all()
        refreshed = [LotteryTicket.query.get(ticket_id) for ticket_id in (first.id, second.id, third.id)]

    assert result["success"] is True
    assert result["completed_count"] == 2
    assert result["expired_count"] == 1
    assert [ticket.status for ticket in refreshed] == ["completed", "completed", "expired"]


def test_mode_b_finalize_ignores_duplicate_ticket_ids(app):
    from services.ticket_pool import finalize_tickets_batch

    with app.app_context():
        user = create_user("modeb_duplicate_finalize_user", "secret123", client_mode="mode_b")
        uploaded = UploadedFile(
            display_id="2026/04/07-99",
            original_filename="duplicate-finalize.txt",
            stored_filename="txt/2026-04-07/duplicate-finalize.txt",
            uploaded_by=user.id,
            total_tickets=1,
            pending_count=0,
            assigned_count=1,
            completed_count=0,
        )
        db.session.add(uploaded)
        db.session.flush()

        ticket = LotteryTicket(
            source_file_id=uploaded.id,
            line_number=1,
            raw_content="DUP-FINALIZE-001",
            status="assigned",
            assigned_user_id=user.id,
            assigned_username=user.username,
            assigned_device_id="device-b",
            assigned_device_name="device-b",
            assigned_at=beijing_now(),
            deadline_time=beijing_now() - timedelta(minutes=1),
        )
        db.session.add(ticket)
        db.session.commit()

        result = finalize_tickets_batch([ticket.id, ticket.id], user.id, completed_count=2)
        db.session.expire_all()
        refreshed_ticket = LotteryTicket.query.get(ticket.id)
        refreshed_file = UploadedFile.query.get(uploaded.id)

    assert result == {"completed_count": 1, "expired_count": 0}
    assert refreshed_ticket.status == "completed"
    assert refreshed_file.assigned_count == 0
    assert refreshed_file.completed_count == 1


def test_mode_b_preview_rejects_invalid_count(app, client):
    with app.app_context():
        user = create_user("mode_b_preview_invalid", "secret123", client_mode="mode_b")

    resp = login(client, "mode_b_preview_invalid", "secret123")
    assert resp.status_code == 200

    resp = client.get("/api/mode-b/preview?count=abc")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "下载张数" in data["error"]


def test_mode_b_download_rejects_invalid_count(app, client):
    with app.app_context():
        user = create_user("mode_b_download_invalid", "secret123", client_mode="mode_b")

    resp = login(client, "mode_b_download_invalid", "secret123")
    assert resp.status_code == 200

    resp = client.post("/api/mode-b/download", json={"count": 0, "device_id": "dev-1", "device_name": "设备1"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "下载张数" in data["error"]


def test_client_dashboard_handles_mode_b_confirm_failure():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "showToast(data.error || '确认失败', 'danger');" in content
    assert "body: JSON.stringify({ ticket_ids: batch.ticket_ids, completed_count: completedCount })," in content
    assert "showToast(message, 'success');" in content
    assert "showToast('请等待 1 秒后再下载', 'warning');" in content
    assert "bDownloadCooldownUntil > Date.now()" in content


def test_client_dashboard_replaces_processing_batches_from_server():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "this.bPendingBatches = data.batches || [];" in content


def test_client_dashboard_resets_matching_state_on_load_failures():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "} catch(e) {\n        this.stats = { ticket_count: 0, total_amount: 0, pool_total_pending: 0, active_count: 0, device_stats: [] };\n      }\n    }," in content
    assert "throw new Error(data.error || '加载处理中批次失败');" in content
    assert "} catch(e) {\n        this.bPendingBatches = [];\n      }\n    },\n    async loadPoolStatus()" in content
    assert "throw new Error(data.error || '加载票池状态失败');" in content


def test_client_dashboard_only_calls_mode_b_endpoints_for_mode_b_users():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "isModeB: {% if current_user.client_mode == 'mode_b' %}true{% else %}false{% endif %}," in content
    assert "if (this.isModeB) {\n      this.loadPoolStatus();\n      this.loadProcessingBatches();\n    }" in content
    assert "if (this.isModeB) {\n      setInterval(this.loadPoolStatus, 15000);\n    }" in content
    assert "if (this.isModeB) {\n        this.loadPoolStatus();\n      }\n      this.loadStats();" in content


def test_client_dashboard_listens_for_realtime_revoke_and_announcement_events():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "window.addEventListener('pool_updated', this._onPoolUpdated);" in content
    assert "window.addEventListener('announcement', this._onAnnouncement);" in content
    assert "window.addEventListener('pool_disabled', this._onPoolDisabled);" in content
    assert "window.addEventListener('pool_enabled', this._onPoolEnabled);" in content
    assert "window.addEventListener('file_revoked', this._onFileRevoked);" in content
    assert "this._onPoolUpdated = () => {" in content
    assert "this.loadProcessingBatches();" in content
    assert "this.currentTicket = null;" in content


def test_client_dashboard_handles_mode_b_preview_failure():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "this.bPreview = null;" in content
    assert "showToast(data.error || '预览失败', 'danger');" in content


def test_client_dashboard_handles_export_daily_network_failure():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "showToast('导出失败，请稍后重试', 'danger');" in content


def test_client_dashboard_merges_returned_winning_record_after_upload():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "Object.assign(record, data.record || {}, { winning_image_url: data.image_url });" in content


def test_admin_winning_template_merges_returned_winning_record_after_upload():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "winning.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "Object.assign(record, data.record || {}, { winning_image_url: data.image_url });" in content


def test_socket_client_dispatches_realtime_custom_events():
    socket_client = Path(__file__).resolve().parents[1] / "static" / "js" / "socket_client.js"
    content = socket_client.read_text(encoding="utf-8")
    assert "window.dispatchEvent(new CustomEvent('announcement', { detail: data }));" in content
    assert "window.dispatchEvent(new CustomEvent('pool_disabled', { detail: data }));" in content
    assert "window.dispatchEvent(new CustomEvent('pool_enabled', { detail: data }));" in content


def test_socket_request_pool_status_trims_mode_b_counts(app, monkeypatch):
    from types import SimpleNamespace
    from sockets.pool_events import on_request_pool_status

    emitted = []

    monkeypatch.setattr(
        "sockets.pool_events.current_user",
        SimpleNamespace(
            is_authenticated=True,
            client_mode="mode_b",
            get_blocked_lottery_types=lambda: ["胜平负"],
        ),
    )
    monkeypatch.setattr(
        "sockets.pool_events.emit",
        lambda event, payload: emitted.append((event, payload)),
    )
    monkeypatch.setattr(
        "services.ticket_pool.get_pool_status",
        lambda blocked_types=None: {
            "total_pending": 25,
            "by_type": [
                {"lottery_type": "让球胜平负", "deadline_time": "2026-04-08T10:00:00", "count": 25}
            ],
            "assigned": 0,
            "completed_today": 0,
        },
    )

    with app.app_context():
        on_request_pool_status()

    assert emitted == [
        (
            "pool_updated",
            {
                "total_pending": 5,
                "by_type": [
                    {"lottery_type": "让球胜平负", "deadline_time": "2026-04-08T10:00:00", "count": 5}
                ],
                "assigned": 0,
                "completed_today": 0,
            },
        )
    ]


def test_admin_upload_template_uses_xlsx_export_label():
    upload_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "upload.html"
    content = upload_template.read_text(encoding="utf-8")
    assert "导出XLSX" in content
    assert "导出CSV" not in content


def test_admin_upload_template_uses_server_derived_file_status():
    upload_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "upload.html"
    content = upload_template.read_text(encoding="utf-8")
    assert "if (f.status === 'exhausted') return 'bg-success';" in content
    assert "if (f.status === 'expired') return 'bg-secondary';" in content
    assert "if (f.status === 'exhausted') return '已完成';" in content
    assert "if (f.status === 'expired') return '已过期';" in content
    assert "new Date(f.deadline_time) < new Date()" not in content


def test_admin_upload_template_loads_all_detail_pages():
    upload_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "upload.html"
    content = upload_template.read_text(encoding="utf-8")
    assert "let page = 1;" in content
    assert "let totalPages = 1;" in content
    assert "detail?page=${page}&per_page=100" in content
    assert "if (!res.ok || data.success === false) {" in content
    assert "detailTickets.push(...(data.tickets || []));" in content
    assert "} while (page <= totalPages);" in content
    assert "showToast(e.message || '加载详情失败，请稍后重试', 'danger');" in content
    assert "showToast(e.message || '撤回失败，请稍后重试', 'danger');" in content


def test_admin_upload_template_accepts_uppercase_txt_files():
    upload_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "upload.html"
    content = upload_template.read_text(encoding="utf-8")
    assert 'accept=".txt,.TXT"' in content
    assert "f.name.toLowerCase().endsWith('.txt')" in content


def test_admin_users_template_handles_initial_load_failures():
    users_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "users.html"
    content = users_template.read_text(encoding="utf-8")
    assert "v-if=\"loadError\"" in content
    assert "loadError: ''" in content
    assert "showToast(e.message || '加载彩种列表失败', 'danger');" in content
    assert "this.loadError = e.message || '加载用户列表失败';" in content
    assert "showToast(this.loadError, 'danger');" in content
    assert "finally {" in content
    assert "this.loading = false;" in content


def test_admin_users_template_handles_action_network_failures():
    users_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "users.html"
    content = users_template.read_text(encoding="utf-8")
    assert "this.createError = '网络异常，请稍后重试';" in content
    assert "showToast('更新失败，请稍后重试', 'danger');" in content
    assert "showToast('操作失败，请稍后重试', 'danger');" in content
    assert "showToast('删除失败，请稍后重试', 'danger');" in content


def test_admin_upload_template_handles_file_list_failures():
    upload_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "upload.html"
    content = upload_template.read_text(encoding="utf-8")
    assert "v-if=\"listError\"" in content
    assert "listError: ''" in content
    assert "this.listError = '';" in content
    assert "throw new Error(data.error || '加载文件列表失败');" in content
    assert "this.listError = e.message || '加载文件列表失败';" in content
    assert "showToast(this.listError, 'danger');" in content
    assert "finally {" in content
    assert "this.loading = false;" in content


def test_admin_upload_template_handles_http_upload_failures():
    upload_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "upload.html"
    content = upload_template.read_text(encoding="utf-8")
    assert "if (!res.ok || data.success === false) {" in content
    assert "throw new Error(data.error || '上传失败');" in content
    assert "i.message=e.message || '上传失败'" in content
    assert "showToast(e.message || '上传失败', 'danger');" in content
    assert "throw new Error(data.error || data.message || '撤回失败');" in content


def test_admin_winning_template_handles_list_and_detail_load_failures():
    winning_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "winning.html"
    content = winning_template.read_text(encoding="utf-8")
    assert "throw new Error(data.error || '加载中奖记录失败');" in content
    assert "showToast(e.message || '加载中奖记录失败', 'danger');" in content
    assert "throw new Error(data.error || '加载赛果列表失败');" in content
    assert "showToast(e.message || '加载赛果列表失败', 'danger');" in content
    assert "throw new Error(data.error || '加载赛果详情失败');" in content
    assert "showToast(e.message || '加载赛果详情失败', 'danger');" in content


def test_admin_winning_defaults_date_filter_to_current_business_day():
    winning_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "winning.html"
    content = winning_template.read_text(encoding="utf-8")
    assert "currentBusinessDate: ''" in content
    assert "this.currentBusinessDate = data.current_business_date || '';" in content
    assert "if (!this.filterDate && this.currentBusinessDate) {" in content
    assert "this.filterDate = this.currentBusinessDate;" in content
    assert "resetWinningFilters()" in content

def test_client_dashboard_handles_mode_b_network_failures():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "showToast('预览失败，请稍后重试', 'danger');" in content
    assert "showToast('确认失败，请稍后重试', 'danger');" in content
def test_client_dashboard_handles_download_and_open_winning_failures():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "showToast('下载失败，请稍后重试', 'danger');" in content
    assert "showToast(data.error || '加载中奖记录失败', 'danger');" in content
    assert "showToast('加载中奖记录失败，请稍后重试', 'danger');" in content


def test_admin_dashboard_marks_refresh_failure_in_indicator():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "const onlineIndicator = document.getElementById('online-indicator');" in content
    assert "throw new Error(data.error ||" in content
    assert "onlineIndicator.textContent = '连接异常';" in content
    assert "onlineIndicator.className = 'badge bg-danger';" in content


def test_admin_dashboard_contains_announcement_panel():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "发送公告" in content
    assert "id=\"announcement-input\"" in content
    assert "async function loadAnnouncementSettings()" in content
    assert "async function saveAnnouncement()" in content
    assert "loadAnnouncementSettings();" in content


def test_admin_settings_no_longer_renders_announcement_editor():
    settings_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "settings.html"
    content = settings_template.read_text(encoding="utf-8")
    assert "公告内容" not in content
    assert "显示公告" not in content
def test_client_dashboard_validates_winning_image_type_and_handles_password_http_errors():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "if (!res.ok) {" in content
    assert "showToast(data.error || '获取下一张失败，请稍后重试', 'danger');" in content
    assert "if (!file.type.startsWith('image/')) {" in content
    assert "showToast('请上传图片文件', 'warning');" in content
    assert "if (res.ok && data.success) {" in content
def test_admin_settings_template_checks_http_status_on_load():
    settings_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "settings.html"
    content = settings_template.read_text(encoding="utf-8")
    assert "if (!res.ok || data.success === false) {" in content
    assert "throw new Error(data.error ||" in content
    assert "if (res.ok && data.success) {" in content


def test_database_info_moves_to_settings_page():
    settings_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "settings.html"
    settings_content = settings_template.read_text(encoding="utf-8")
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "dashboard.html"
    dashboard_content = dashboard_template.read_text(encoding="utf-8")
    assert "数据库信息" in settings_content
    assert "databaseInfo.engine" in settings_content
    assert "databaseInfo.path" in settings_content
    assert "数据库信息" not in dashboard_content


def test_admin_settings_api_includes_database_info():
    admin_route = Path(__file__).resolve().parents[1] / "routes" / "admin.py"
    content = admin_route.read_text(encoding="utf-8")
    assert "payload['database_info'] = _database_display_info()" in content
    assert "return jsonify(payload)" in content
    assert "return render_template('admin/dashboard.html')" in content
    assert "return render_template('admin/dashboard.html', database_info=_database_display_info())" not in content


def test_admin_winning_template_handles_filter_option_failures_and_localizes_mark_checked():
    winning_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "winning.html"
    content = winning_template.read_text(encoding="utf-8")
    assert "throw new Error(data.error ||" in content
    assert "showToast(e.message ||" in content
    assert "showToast(" in content and "success" in content
def test_client_dashboard_clears_stale_state_when_background_loads_fail():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "this.stats = { ticket_count: 0, total_amount: 0, pool_total_pending: 0, active_count: 0, device_stats: [] };" in content
    assert "this.bPendingBatches = [];" in content
    assert "this.poolStatus = { total_pending: 0, by_type: [] };" in content
def test_templates_use_chinese_for_recent_admin_prompt_fixes():
    winning_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "winning.html"
    winning_content = winning_template.read_text(encoding="utf-8")
    settings_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "settings.html"
    settings_content = settings_template.read_text(encoding="utf-8")
    login_template = Path(__file__).resolve().parents[1] / "templates" / "login.html"
    login_content = login_template.read_text(encoding="utf-8")
    assert "throw new Error(data.error ||" in winning_content
    assert "showToast(" in winning_content and "'success'" in winning_content
    assert "加载设置失败" in settings_content
    assert "登录失败（HTTP ${res.status}）" in login_content
    assert "this.error = data.error || '登录失败';" in login_content
    assert "this.error = '网络异常，请稍后重试';" in login_content
