from __future__ import annotations

import pytest

from wabot_agent.config import Settings


@pytest.mark.offline
def test_empty_allowed_recipients_env_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WABOT_AGENT_ALLOWED_RECIPIENTS", "")
    monkeypatch.setenv("WABOT_AGENT_OFFLINE_MODE", "true")

    settings = Settings(_env_file=None)

    assert settings.allowed_recipients == set()


@pytest.mark.offline
def test_comma_separated_allowed_recipients_env_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "WABOT_AGENT_ALLOWED_RECIPIENTS",
        "+15551234567, +15557654321 , +15550000000",
    )
    monkeypatch.setenv("WABOT_AGENT_OFFLINE_MODE", "true")

    settings = Settings(_env_file=None)

    assert settings.allowed_recipients == {"+15551234567", "+15557654321", "+15550000000"}


@pytest.mark.offline
def test_empty_legacy_allowed_recipients_env_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIGNESH_ALLOWED_RECIPIENTS", "")
    monkeypatch.setenv("WABOT_AGENT_OFFLINE_MODE", "true")

    settings = Settings(_env_file=None)

    assert settings.allowed_recipients == set()
