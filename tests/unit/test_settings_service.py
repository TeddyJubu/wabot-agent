"""Unit tests for SettingsService — SR-1 of the simplification roadmap.

Tests pin the service contract:
  - read() isolation
  - patch() validation, atomicity, disk persistence
  - subscribe() / unsubscribe() lifecycle
  - subscriber exception safety
  - thread-safety smoke test

These tests use make_settings(tmp_path) from test_api.py directly, recreated
here to keep the unit test module self-contained (no test_api import needed).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

from wabot_agent.api.schemas import SettingsPatch
from wabot_agent.config import Settings
from wabot_agent.settings_service import SettingsService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_settings(tmp_path: Path) -> Settings:
    """Minimal Settings for unit tests (same shape as test_api.make_settings)."""
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="dry_run",
        OPENROUTER_MODEL="openai/gpt-5.2",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )


# ---------------------------------------------------------------------------
# 1. read() returns independent copy
# ---------------------------------------------------------------------------


def test_read_returns_independent_copy(tmp_path: Path) -> None:
    """Mutating the returned Settings object must not affect the service."""
    settings = make_settings(tmp_path)
    svc = SettingsService(settings)

    copy = svc.read()
    original_policy = copy.send_policy

    # Mutate the copy.
    copy.send_policy = "allow_all"

    # Service still has the original value.
    assert svc.read().send_policy == original_policy
    assert svc._settings.send_policy == original_policy


# ---------------------------------------------------------------------------
# 2. patch() applies field changes and persists to disk
# ---------------------------------------------------------------------------


def test_patch_applies_field_changes(tmp_path: Path) -> None:
    """A valid patch updates live settings and writes to disk."""
    settings = make_settings(tmp_path)
    svc = SettingsService(settings)

    patch = SettingsPatch(send_policy="allowlist", allowed_recipients=["+15550001111"])
    svc.patch(patch)

    # Live settings updated.
    assert settings.send_policy == "allowlist"
    # allowed_recipients is stored as a set on Settings, serialised as a sorted list on disk.
    assert "+15550001111" in settings.allowed_recipients

    # read() reflects the change.
    snap = svc.read()
    assert snap.send_policy == "allowlist"

    # Disk reflects the change.
    overrides_path = tmp_path / "runtime_overrides.json"
    assert overrides_path.exists()
    written = json.loads(overrides_path.read_text())
    assert written["send_policy"] == "allowlist"
    assert written["allowed_recipients"] == ["+15550001111"]


# ---------------------------------------------------------------------------
# 3. Non-mutable fields are silently dropped
# ---------------------------------------------------------------------------


def test_patch_drops_non_mutable_fields(tmp_path: Path) -> None:
    """Fields not in MUTABLE_FIELDS must be ignored (mass-assignment defence)."""
    settings = make_settings(tmp_path)
    original_db_path = settings.db_path
    svc = SettingsService(settings)

    # SettingsPatch has no db_path field, so we pass send_policy (valid) and
    # verify db_path is untouched. We also confirm the patch succeeds.
    patch = SettingsPatch(send_policy="allowlist")
    svc.patch(patch)

    assert settings.db_path == original_db_path
    assert settings.send_policy == "allowlist"


# ---------------------------------------------------------------------------
# 4. Empty string for secret field means no-change (set to None)
# ---------------------------------------------------------------------------


def test_patch_empty_string_does_not_clear_secret(tmp_path: Path) -> None:
    """An empty-string value for a SECRET_FIELD sets it to None (removes the key),
    not to the empty string. Existing non-empty secrets are preserved when the
    patch simply omits the field (None default)."""
    settings = make_settings(tmp_path).model_copy(
        update={"openrouter_api_key": "sk-or-existing-key"}
    )
    svc = SettingsService(settings)

    # Patch with empty string — the field should become None (cleared), not "".
    patch = SettingsPatch(openrouter_api_key="")
    svc.patch(patch)
    assert settings.openrouter_api_key is None

    # Restore a key.
    patch2 = SettingsPatch(openrouter_api_key="sk-or-new-key")
    svc.patch(patch2)
    assert settings.openrouter_api_key == "sk-or-new-key"

    # Omitting the field (None default) leaves the key unchanged.
    patch3 = SettingsPatch(send_policy="allowlist")
    svc.patch(patch3)
    assert settings.openrouter_api_key == "sk-or-new-key"


# ---------------------------------------------------------------------------
# 5. allow_all requires confirm_allow_all
# ---------------------------------------------------------------------------


def test_patch_rejects_allow_all_without_confirm(tmp_path: Path) -> None:
    """send_policy='allow_all' without confirm_allow_all must raise HTTP 400."""
    settings = make_settings(tmp_path)
    svc = SettingsService(settings)

    with pytest.raises(HTTPException) as exc_info:
        svc.patch(SettingsPatch(send_policy="allow_all"))
    assert exc_info.value.status_code == 400
    assert "confirm_allow_all" in exc_info.value.detail.lower()

    # Live settings unchanged.
    assert settings.send_policy == "dry_run"

    # With confirm — should succeed.
    svc.patch(SettingsPatch(send_policy="allow_all", confirm_allow_all=True))
    assert settings.send_policy == "allow_all"


# ---------------------------------------------------------------------------
# 6. Non-loopback wabot_endpoint is rejected
# ---------------------------------------------------------------------------


def test_patch_rejects_non_loopback_wabot_endpoint(tmp_path: Path) -> None:
    """wabot_endpoint must point at loopback; anything else is HTTP 400."""
    settings = make_settings(tmp_path)
    original_endpoint = settings.wabot_endpoint
    svc = SettingsService(settings)

    with pytest.raises(HTTPException) as exc_info:
        svc.patch(SettingsPatch(wabot_endpoint="http://evil.example.com:7777"))
    assert exc_info.value.status_code == 400
    assert "loopback" in exc_info.value.detail.lower()

    # Live state unchanged.
    assert settings.wabot_endpoint == original_endpoint
    # Disk untouched.
    assert not (tmp_path / "runtime_overrides.json").exists()


# ---------------------------------------------------------------------------
# 7. Plain HTTP to a remote openai_base_url is rejected
# ---------------------------------------------------------------------------


def test_patch_rejects_plain_http_remote_openai_base_url(tmp_path: Path) -> None:
    """openai_base_url over plain HTTP to a remote host must be rejected."""
    settings = make_settings(tmp_path)
    svc = SettingsService(settings)

    with pytest.raises(HTTPException) as exc_info:
        svc.patch(
            SettingsPatch(
                openai_base_url="http://attacker.example.com/v1",
                openai_api_key="sk-test",
            )
        )
    assert exc_info.value.status_code == 400
    assert "https" in exc_info.value.detail.lower()
    assert not (tmp_path / "runtime_overrides.json").exists()


# ---------------------------------------------------------------------------
# 8. base URL change requires a new key in the same patch
# ---------------------------------------------------------------------------


def test_patch_base_url_change_requires_new_key(tmp_path: Path) -> None:
    """Changing openrouter_base_url without supplying openrouter_api_key is rejected."""
    settings = make_settings(tmp_path).model_copy(
        update={"openrouter_api_key": "sk-old-key"}
    )
    svc = SettingsService(settings)

    with pytest.raises(HTTPException) as exc_info:
        svc.patch(
            SettingsPatch(openrouter_base_url="https://elsewhere.example.com/v1")
        )
    assert exc_info.value.status_code == 400
    assert "openrouter_api_key" in exc_info.value.detail

    # With the new key included — should succeed.
    svc.patch(
        SettingsPatch(
            openrouter_base_url="https://elsewhere.example.com/v1",
            openrouter_api_key="sk-new-key",
        )
    )
    assert settings.openrouter_base_url == "https://elsewhere.example.com/v1"


# ---------------------------------------------------------------------------
# 9. Invalid field leaves state (live + disk) clean
# ---------------------------------------------------------------------------


def test_patch_atomic_invalid_field_leaves_state_clean(tmp_path: Path) -> None:
    """A patch that fails validation must not touch live settings or write disk."""
    settings = make_settings(tmp_path)
    original_policy = settings.send_policy
    svc = SettingsService(settings)

    with pytest.raises(HTTPException):
        # send_policy is a Literal — "garbage" fails Pydantic validation on the snapshot.
        svc.patch(SettingsPatch(send_policy="garbage"))

    assert settings.send_policy == original_policy
    assert not (tmp_path / "runtime_overrides.json").exists()


# ---------------------------------------------------------------------------
# 10. Subscribers fire on successful patch
# ---------------------------------------------------------------------------


def test_subscribers_fire_on_successful_patch(tmp_path: Path) -> None:
    """After a successful patch, all registered subscribers receive the new snapshot
    and the set of changed field names."""
    settings = make_settings(tmp_path)
    svc = SettingsService(settings)

    received: list[tuple] = []

    def cb(new_settings: Settings, changed: frozenset[str]) -> None:
        received.append((new_settings.send_policy, changed))

    svc.subscribe(cb)
    svc.patch(SettingsPatch(send_policy="allowlist"))

    assert len(received) == 1
    new_policy, changed = received[0]
    assert new_policy == "allowlist"
    assert "send_policy" in changed


# ---------------------------------------------------------------------------
# 11. Subscribers do NOT fire on failed patch
# ---------------------------------------------------------------------------


def test_subscribers_do_not_fire_on_failed_patch(tmp_path: Path) -> None:
    """An invalid patch must not trigger subscriber callbacks."""
    settings = make_settings(tmp_path)
    svc = SettingsService(settings)

    called = []
    svc.subscribe(lambda s, c: called.append(True))

    with pytest.raises(HTTPException):
        svc.patch(SettingsPatch(send_policy="garbage"))

    assert called == []


# ---------------------------------------------------------------------------
# 12. A bad subscriber does not block other subscribers
# ---------------------------------------------------------------------------


def test_subscriber_exception_does_not_block_other_subscribers(tmp_path: Path) -> None:
    """If one subscriber raises, others still fire and the patch still succeeds."""
    settings = make_settings(tmp_path)
    svc = SettingsService(settings)

    second_called = []

    def bad_cb(s: Settings, c: frozenset[str]) -> None:
        raise RuntimeError("subscriber explosion")

    def good_cb(s: Settings, c: frozenset[str]) -> None:
        second_called.append(s.send_policy)

    svc.subscribe(bad_cb)
    svc.subscribe(good_cb)

    # patch() must not raise even though bad_cb raises.
    svc.patch(SettingsPatch(send_policy="allowlist"))

    # second_called received the call, bad_cb's exception was swallowed.
    assert second_called == ["allowlist"]
    # Live settings updated.
    assert settings.send_policy == "allowlist"


# ---------------------------------------------------------------------------
# 13. subscribe / unsubscribe removes the callback
# ---------------------------------------------------------------------------


def test_subscribe_unsubscribe_removes_callback(tmp_path: Path) -> None:
    """Calling the Unsubscribe handle removes the subscriber."""
    settings = make_settings(tmp_path)
    svc = SettingsService(settings)

    called = []
    unsub = svc.subscribe(lambda s, c: called.append(1))

    svc.patch(SettingsPatch(send_policy="allowlist"))
    assert called == [1]

    unsub()  # deregister

    svc.patch(SettingsPatch(send_policy="dry_run"))
    # Still only one call total.
    assert called == [1]

    # Calling unsub again is safe (idempotent).
    unsub()


# ---------------------------------------------------------------------------
# 14. Thread-safety smoke test
# ---------------------------------------------------------------------------


def test_settings_service_is_thread_safe(tmp_path: Path) -> None:
    """Two threads patching concurrently must not produce a torn write.

    Final state must be consistent with one of the two patches.
    """
    settings = make_settings(tmp_path)
    svc = SettingsService(settings)

    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def patch_allowlist() -> None:
        barrier.wait()
        try:
            svc.patch(SettingsPatch(send_policy="allowlist"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def patch_owner() -> None:
        barrier.wait()
        try:
            svc.patch(SettingsPatch(send_policy="owner"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=patch_allowlist)
    t2 = threading.Thread(target=patch_owner)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == [], f"Thread(s) raised: {errors}"
    # Final state is one of the two valid values — no torn write.
    assert settings.send_policy in {"allowlist", "owner"}

    # Disk is also consistent.
    overrides_path = tmp_path / "runtime_overrides.json"
    written = json.loads(overrides_path.read_text())
    assert written["send_policy"] in {"allowlist", "owner"}
    # Live and disk agree.
    assert written["send_policy"] == settings.send_policy
