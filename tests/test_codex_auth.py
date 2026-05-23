from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import wabot_agent.codex_device_login as codex_device_login
from wabot_agent.codex_auth import (
    codex_auth_path,
    detect_model_provider,
    ensure_codex_home,
    load_codex_credentials,
    model_provider_explicitly_set,
    require_safe_codex_url,
)
from wabot_agent.codex_device_login import DeviceLoginSession, device_login_view
from wabot_agent.config import Settings
from wabot_agent.runtime_overrides import save_overrides


def test_load_codex_credentials_from_auth_file(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "test-access-token",
                    "account_id": "acct-123",
                },
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        model_provider="codex",
        codex_auth_path=auth_path,
        codex_access_token="override-token",
        offline_mode=False,
        _env_file=None,
    )
    creds = load_codex_credentials(settings)
    assert creds is not None
    assert creds.access_token == "test-access-token"
    assert creds.account_id == "acct-123"
    assert settings.live_model_enabled


def test_runtime_override_token_wins_over_auth_file(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {"access_token": "file-token", "account_id": "acct-file"},
            }
        ),
        encoding="utf-8",
    )
    overrides_path = tmp_path / "runtime_overrides.json"
    save_overrides(
        overrides_path,
        {"codex_access_token": "override-token", "codex_account_id": "acct-override"},
    )
    settings = Settings(
        model_provider="codex",
        codex_auth_path=auth_path,
        codex_access_token="bootstrap-token",
        runtime_overrides_path=overrides_path,
        offline_mode=False,
        _env_file=None,
    )
    creds = load_codex_credentials(settings)
    assert creds is not None
    assert creds.access_token == "override-token"
    assert creds.account_id == "acct-override"


def test_env_token_used_when_auth_file_missing(tmp_path: Path) -> None:
    settings = Settings(
        model_provider="codex",
        codex_auth_path=tmp_path / "missing-auth.json",
        codex_access_token="env-token",
        offline_mode=False,
        _env_file=None,
    )
    creds = load_codex_credentials(settings)
    assert creds is not None
    assert creds.access_token == "env-token"


def test_codex_live_requires_credentials(tmp_path: Path) -> None:
    settings = Settings(
        model_provider="codex",
        codex_auth_path=tmp_path / "missing-auth.json",
        offline_mode=False,
        _env_file=None,
    )
    assert load_codex_credentials(settings) is None
    assert not settings.live_model_enabled


def test_require_safe_codex_url_rejects_untrusted_host() -> None:
    with pytest.raises(ValueError, match="chatgpt.com"):
        require_safe_codex_url("https://evil.example/v1")


def test_require_safe_codex_url_accepts_default() -> None:
    require_safe_codex_url("https://chatgpt.com/backend-api/codex")


def test_ensure_codex_home_creates_directory(tmp_path: Path) -> None:
    auth_path = tmp_path / "nested" / ".codex" / "auth.json"
    settings = Settings(
        data_dir=tmp_path / "data",
        codex_auth_path=auth_path,
        _env_file=None,
    )
    home = ensure_codex_home(settings)
    assert home == auth_path.parent
    assert home.is_dir()


def test_legacy_home_codex_path_redirects_to_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = Settings(
        data_dir=tmp_path / "data",
        codex_auth_path=Path("~/.codex/auth.json"),
        _env_file=None,
    )
    resolved = codex_auth_path(settings)
    assert resolved == (tmp_path / "data" / "codex" / "auth.json").resolve()


def test_detect_model_provider_prefers_codex_auth_file(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {"access_token": "file-token"},
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        openrouter_api_key="sk-or-test",
        codex_auth_path=auth_path,
        _env_file=None,
    )
    assert detect_model_provider(settings) == "codex"
    assert not model_provider_explicitly_set()


def test_detect_model_provider_prefers_openai_key(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {"access_token": "file-token"},
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        openai_api_key="sk-openai-test",
        openrouter_api_key="sk-or-test",
        codex_auth_path=auth_path,
        _env_file=None,
    )
    assert detect_model_provider(settings) == "openai"


def test_device_login_view_not_logged_in_while_pending(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {"access_token": "existing-token"},
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        model_provider="codex",
        codex_auth_path=auth_path,
        _env_file=None,
    )
    previous = codex_device_login._session
    codex_device_login._session = DeviceLoginSession(status="pending")
    try:
        view = device_login_view(settings)
        assert view["logged_in"] is False
        assert view["session"]["status"] == "pending"
    finally:
        codex_device_login._session = previous


def test_auth_file_refreshed_requires_mtime_increase(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{}", encoding="utf-8")
    settings = Settings(codex_auth_path=auth_path, _env_file=None)
    mtime = auth_path.stat().st_mtime
    codex_device_login._auth_mtime_at_start = mtime
    try:
        assert not codex_device_login._auth_file_refreshed(settings)
        auth_path.write_text(
            json.dumps({"tokens": {"access_token": "new"}}),
            encoding="utf-8",
        )
        os.utime(auth_path, (mtime + 2, mtime + 2))
        assert codex_device_login._auth_file_refreshed(settings)
    finally:
        codex_device_login._auth_mtime_at_start = None
