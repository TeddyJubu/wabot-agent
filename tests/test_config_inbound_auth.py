from __future__ import annotations

from wabot_agent.config import Settings


def test_requires_inbound_token_local_loopback() -> None:
    settings = Settings(env="local", host="127.0.0.1", _env_file=None)
    assert settings.requires_inbound_token() is False


def test_requires_inbound_token_production_env() -> None:
    settings = Settings(env="production", host="127.0.0.1", _env_file=None)
    assert settings.requires_inbound_token() is True


def test_requires_inbound_token_non_loopback_host() -> None:
    settings = Settings(env="local", host="0.0.0.0", _env_file=None)
    assert settings.requires_inbound_token() is True


def test_requires_inbound_token_explicit_flag() -> None:
    settings = Settings(
        env="local",
        host="127.0.0.1",
        wabot_inbound_token_required=True,
        _env_file=None,
    )
    assert settings.requires_inbound_token() is True
