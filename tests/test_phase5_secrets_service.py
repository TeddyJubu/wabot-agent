"""Phase 5 — secrets_service tests.

All offline — no network, no composio package calls.
"""
from __future__ import annotations

import stat
from pathlib import Path

import pytest

from wabot_agent.config import Settings
from wabot_agent.secrets_service import (
    delete_runtime_secret,
    maybe_write_env_file,
    read_runtime_secrets,
    write_runtime_secret,
)


def make_settings(tmp_path: Path) -> Settings:
    # Explicitly pass COMPOSIO_API_KEY=None to override any value the
    # developer's real ~/.env or shell env might contribute — the reload
    # tests assume the initial value is unset.
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path / "data",
        WABOT_AGENT_DB_PATH=tmp_path / "data" / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "data" / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "data" / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SKILLS_DIR=tmp_path / "skills",
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="test-inbound",
        OPENROUTER_API_KEY=None,
        COMPOSIO_API_KEY=None,
        _env_file=None,
    )


# ---------------------------------------------------------------------------
# read on empty
# ---------------------------------------------------------------------------


def test_read_runtime_secrets_missing(tmp_path):
    settings = make_settings(tmp_path)
    result = read_runtime_secrets(settings)
    assert result == {}


# ---------------------------------------------------------------------------
# write + read round-trip
# ---------------------------------------------------------------------------


def test_write_and_read(tmp_path):
    settings = make_settings(tmp_path)
    write_runtime_secret(settings, "COMPOSIO_API_KEY", "supersecretkey123")
    result = read_runtime_secrets(settings)
    assert result["COMPOSIO_API_KEY"] == "supersecretkey123"


def test_write_creates_parent_dirs(tmp_path):
    settings = make_settings(tmp_path)
    # data dir not yet created
    assert not (tmp_path / "data").exists()
    write_runtime_secret(settings, "MY_KEY", "myvalue123")
    assert (tmp_path / "data" / "runtime_secrets.json").exists()


# ---------------------------------------------------------------------------
# chmod 0o600
# ---------------------------------------------------------------------------


def test_write_sets_0o600(tmp_path):
    settings = make_settings(tmp_path)
    write_runtime_secret(settings, "COMPOSIO_API_KEY", "mykey123456")
    path = tmp_path / "data" / "runtime_secrets.json"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_removes_key(tmp_path):
    settings = make_settings(tmp_path)
    write_runtime_secret(settings, "COMPOSIO_API_KEY", "key123")
    write_runtime_secret(settings, "OTHER_KEY", "other123")
    delete_runtime_secret(settings, "COMPOSIO_API_KEY")
    result = read_runtime_secrets(settings)
    assert "COMPOSIO_API_KEY" not in result
    assert result["OTHER_KEY"] == "other123"


def test_delete_no_op_if_absent(tmp_path):
    settings = make_settings(tmp_path)
    # Should not raise
    delete_runtime_secret(settings, "NONEXISTENT_KEY")


# ---------------------------------------------------------------------------
# value never logged
# ---------------------------------------------------------------------------


def test_write_does_not_log_value(tmp_path, caplog):
    import logging

    settings = make_settings(tmp_path)
    secret_value = "my-very-secret-api-key-12345"
    with caplog.at_level(logging.DEBUG, logger="wabot_agent.secrets_service"):
        write_runtime_secret(settings, "COMPOSIO_API_KEY", secret_value)
    # The full secret must not appear in any log record
    for record in caplog.records:
        assert secret_value not in record.getMessage()


# ---------------------------------------------------------------------------
# maybe_write_env_file — disabled when flag not set
# ---------------------------------------------------------------------------


def test_maybe_write_env_file_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("WABOT_AGENT_ALLOW_ENV_WRITE", raising=False)
    settings = make_settings(tmp_path)
    result = maybe_write_env_file(settings, "COMPOSIO_API_KEY", "key123456")
    assert result is False


# ---------------------------------------------------------------------------
# maybe_write_env_file — enabled
# ---------------------------------------------------------------------------


def test_maybe_write_env_file_creates_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WABOT_AGENT_ALLOW_ENV_WRITE", "true")
    settings = make_settings(tmp_path)
    result = maybe_write_env_file(settings, "COMPOSIO_API_KEY", "mykey999")
    assert result is True
    # Find the .env file
    env_path = tmp_path / ".env"
    if not env_path.exists():
        env_path = tmp_path / "data" / ".." / ".env"
    # Check that the key appears somewhere in tmp area
    found = False
    for candidate in [tmp_path / ".env", tmp_path / "data" / ".env"]:
        if candidate.exists():
            content = candidate.read_text()
            if "COMPOSIO_API_KEY=mykey999" in content:
                found = True
    assert found, "COMPOSIO_API_KEY not written to .env"


def test_maybe_write_env_file_updates_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("WABOT_AGENT_ALLOW_ENV_WRITE", "true")
    settings = make_settings(tmp_path)
    # First write
    maybe_write_env_file(settings, "COMPOSIO_API_KEY", "old_key_123")
    # Second write — should update in place
    maybe_write_env_file(settings, "COMPOSIO_API_KEY", "new_key_456")

    # Find the .env file
    for candidate in [tmp_path / ".env", tmp_path / "data" / ".env"]:
        if candidate.exists():
            content = candidate.read_text()
            assert "new_key_456" in content
            # Should not appear twice
            lines_with_key = [ln for ln in content.splitlines() if "COMPOSIO_API_KEY=" in ln]
            assert len(lines_with_key) == 1, f"Key appeared {len(lines_with_key)} times"
            return
    pytest.fail("No .env file found after write")


# ---------------------------------------------------------------------------
# reload_from_runtime_secrets
# ---------------------------------------------------------------------------


def test_reload_from_runtime_secrets_overlays_key(tmp_path):
    settings = make_settings(tmp_path)
    assert settings.composio_api_key is None
    write_runtime_secret(settings, "COMPOSIO_API_KEY", "reloaded_key_xyz")
    changed = settings.reload_from_runtime_secrets()
    assert settings.composio_api_key == "reloaded_key_xyz"
    assert "composio_api_key" in changed
    assert settings.composio_enabled is True


def test_reload_from_runtime_secrets_no_change_if_same(tmp_path):
    settings = make_settings(tmp_path)
    write_runtime_secret(settings, "COMPOSIO_API_KEY", "same_key_abc")
    settings.reload_from_runtime_secrets()
    # Second reload with same value
    changed = settings.reload_from_runtime_secrets()
    assert "composio_api_key" not in changed
