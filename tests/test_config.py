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


@pytest.mark.offline
def test_cf_access_settings_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WABOT_AGENT_OFFLINE_MODE", "true")
    settings = Settings(_env_file=None)
    assert settings.cf_access_required is False
    assert settings.cf_access_team_domain is None
    assert settings.cf_access_aud is None


@pytest.mark.offline
def test_cf_access_settings_can_be_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WABOT_AGENT_OFFLINE_MODE", "true")
    monkeypatch.setenv(
        "WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN", "example.cloudflareaccess.com"
    )
    monkeypatch.setenv("WABOT_AGENT_CF_ACCESS_AUD", "abc123def456")
    monkeypatch.setenv("WABOT_AGENT_CF_ACCESS_REQUIRED", "true")

    settings = Settings(_env_file=None)

    assert settings.cf_access_required is True
    assert settings.cf_access_team_domain == "example.cloudflareaccess.com"
    assert settings.cf_access_aud == "abc123def456"


@pytest.mark.offline
def test_cf_access_settings_accept_vignesh_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WABOT_AGENT_OFFLINE_MODE", "true")
    monkeypatch.delenv("WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.delenv("WABOT_AGENT_CF_ACCESS_AUD", raising=False)
    monkeypatch.delenv("WABOT_AGENT_CF_ACCESS_REQUIRED", raising=False)
    monkeypatch.setenv(
        "VIGNESH_CF_ACCESS_TEAM_DOMAIN", "legacy.cloudflareaccess.com"
    )
    monkeypatch.setenv("VIGNESH_CF_ACCESS_AUD", "legacy-aud")
    monkeypatch.setenv("VIGNESH_CF_ACCESS_REQUIRED", "true")

    settings = Settings(_env_file=None)

    assert settings.cf_access_team_domain == "legacy.cloudflareaccess.com"
    assert settings.cf_access_aud == "legacy-aud"
    assert settings.cf_access_required is True


@pytest.mark.offline
def test_get_settings_respects_env_file_model_provider(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wabot_agent.config import get_settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WABOT_AGENT_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("VIGNESH_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "WABOT_AGENT_MODEL_PROVIDER=codex",
                "OPENROUTER_API_KEY=sk-or-test",
                "WABOT_AGENT_OFFLINE_MODE=true",
            ]
        ),
        encoding="utf-8",
    )

    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.model_provider == "codex"
    finally:
        get_settings.cache_clear()
