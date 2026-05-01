import pytest
from pydantic import ValidationError

from app.infrastructure.config import AppSettings


BASE_ENV = {
    "PORT": "8080",
    "LOG_LEVEL": "info",
    "APP_ENV": "test",
    "TOOLS_SHARED_SECRET": "x" * 32,
    "SQUARE_ACCESS_TOKEN": "tok",
    "SQUARE_ENVIRONMENT": "sandbox",
    "SQUARE_WEBHOOK_SIGNATURE_KEY": "sig",
    "SQUARE_WEBHOOK_URL": "https://example.com",
    "CONFIGS_DIR": "./configs",
    "EVENT_LOG_PATH": "./data/events.jsonl",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_loads_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, BASE_ENV)
    s = AppSettings()
    assert s.port == 8080
    assert s.square_environment == "sandbox"
    assert s.tools_shared_secret == "x" * 32


def test_rejects_short_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, BASE_ENV | {"TOOLS_SHARED_SECRET": "short"})
    with pytest.raises(ValidationError):
        AppSettings()


def test_rejects_invalid_env_value(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, BASE_ENV | {"SQUARE_ENVIRONMENT": "moon"})
    with pytest.raises(ValidationError):
        AppSettings()
