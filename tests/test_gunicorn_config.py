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
