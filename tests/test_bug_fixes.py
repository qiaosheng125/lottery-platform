import os
import sys
import builtins
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
    assert "showToast('已确认完成 ' + data.completed_count + ' 张票', 'success');" in content


def test_client_dashboard_replaces_processing_batches_from_server():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "this.bPendingBatches = data.batches || [];" in content


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


def test_admin_upload_template_uses_xlsx_export_label():
    upload_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "upload.html"
    content = upload_template.read_text(encoding="utf-8")
    assert "导出XLSX" in content
    assert "导出CSV" not in content


def test_admin_upload_template_loads_all_detail_pages():
    upload_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "upload.html"
    content = upload_template.read_text(encoding="utf-8")
    assert "let page = 1;" in content
    assert "let totalPages = 1;" in content
    assert "detail?page=${page}&per_page=100" in content
    assert "detailTickets.push(...(data.tickets || []));" in content
    assert "} while (page <= totalPages);" in content
    assert "showToast('加载详情失败，请稍后重试', 'danger');" in content
    assert "showToast('撤回失败，请稍后重试', 'danger');" in content
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
def test_admin_winning_template_handles_list_and_detail_load_failures():
    winning_template = Path(__file__).resolve().parents[1] / "templates" / "admin" / "winning.html"
    content = winning_template.read_text(encoding="utf-8")
    assert "throw new Error(data.error || '加载中奖记录失败');" in content
    assert "showToast(e.message || '加载中奖记录失败', 'danger');" in content
    assert "throw new Error(data.error || '加载赛果列表失败');" in content
    assert "showToast(e.message || '加载赛果列表失败', 'danger');" in content
    assert "throw new Error(data.error || '加载赛果详情失败');" in content
    assert "showToast(e.message || '加载赛果详情失败', 'danger');" in content
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
def test_client_dashboard_validates_winning_image_type_and_handles_password_http_errors():
    dashboard_template = Path(__file__).resolve().parents[1] / "templates" / "client" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")
    assert "if (!res.ok) {" in content
    assert "this.pwdError = data.error || '密码修改失败';" in content
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
