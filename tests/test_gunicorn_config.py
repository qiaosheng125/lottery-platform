import importlib
import sys


def _load_gunicorn_config(monkeypatch, env_overrides=None):
    env_overrides = env_overrides or {}
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)
    monkeypatch.delenv("DISABLE_SCHEDULER", raising=False)

    for key, value in env_overrides.items():
        monkeypatch.setenv(key, value)

    sys.modules.pop("gunicorn_config", None)
    return importlib.import_module("gunicorn_config")


def test_gunicorn_config_does_not_override_scheduler_flags_by_default(monkeypatch):
    module = _load_gunicorn_config(monkeypatch)
    assert module.raw_env == []


def test_gunicorn_config_honors_explicit_scheduler_env(monkeypatch):
    module = _load_gunicorn_config(
        monkeypatch,
        {
            "ENABLE_SCHEDULER": "0",
            "DISABLE_SCHEDULER": "1",
        },
    )
    assert module.raw_env == ["ENABLE_SCHEDULER=0", "DISABLE_SCHEDULER=1"]


def test_production_deploy_disables_scheduler_in_web_service():
    from pathlib import Path

    script = Path("scripts/deploy_production_ubuntu.sh").read_text(encoding="utf-8")
    assert '"ENABLE_SCHEDULER": "0"' in script
    assert '"DISABLE_SCHEDULER": "1"' in script
    assert 'existing.get("GUNICORN_WORKERS")' in script
    assert 'SCHEDULER_SERVICE_NAME="${SCHEDULER_SERVICE_NAME:-${SERVICE_NAME}-scheduler}"' in script
    assert "run_scheduler.py" in script


def test_run_linux_app_forces_scheduler_off_for_web_workers():
    from pathlib import Path

    script = Path("scripts/run_linux_app.sh").read_text(encoding="utf-8")
    assert 'export ENABLE_SCHEDULER="0"' in script
    assert 'export DISABLE_SCHEDULER="1"' in script


def test_run_linux_scheduler_forces_single_scheduler_process():
    from pathlib import Path

    script = Path("scripts/run_linux_scheduler.sh").read_text(encoding="utf-8")
    assert 'export ENABLE_SCHEDULER="1"' in script
    assert 'export DISABLE_SCHEDULER="0"' in script
    assert 'exec python "$ROOT_DIR/run_scheduler.py"' in script


def test_run_scheduler_entrypoint_exists_and_enables_scheduler():
    from pathlib import Path

    content = Path("run_scheduler.py").read_text(encoding="utf-8")
    assert 'os.environ["ENABLE_SCHEDULER"] = "1"' in content
    assert 'os.environ["DISABLE_SCHEDULER"] = "0"' in content
    assert "start standalone scheduler process" in content
