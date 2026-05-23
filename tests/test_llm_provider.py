from __future__ import annotations

from wabot_agent.config import Settings
from wabot_agent.llm_provider import (
    active_model_id,
    resolved_llm_api_key,
    resolved_llm_base_url,
    vision_supported,
)


def test_codex_live_requires_credentials(tmp_path) -> None:
    settings = Settings(
        WABOT_AGENT_MODEL_PROVIDER="codex",
        CODEX_AUTH_PATH=str(tmp_path / "missing.json"),
        WABOT_AGENT_OFFLINE_MODE=False,
        _env_file=None,
    )
    assert not settings.live_model_enabled

    settings = Settings(
        WABOT_AGENT_MODEL_PROVIDER="codex",
        CODEX_ACCESS_TOKEN="test-token",
        WABOT_AGENT_OFFLINE_MODE=False,
        _env_file=None,
    )
    assert settings.live_model_enabled
    assert active_model_id(settings) == settings.codex_model
    assert resolved_llm_base_url(settings) == "https://chatgpt.com/backend-api/codex"


def test_codex_reasoning_omitted_for_store_false_subscription() -> None:
    from wabot_agent.llm_provider import reasoning_for_model

    settings = Settings(
        model_provider="codex",
        codex_reasoning_effort="high",
        offline_mode=False,
        _env_file=None,
    )
    assert reasoning_for_model(settings) is None


def test_codex_reasoning_default_omits_block() -> None:
    from wabot_agent.llm_provider import reasoning_for_model

    settings = Settings(
        model_provider="codex",
        codex_reasoning_effort="default",
        offline_mode=False,
        _env_file=None,
    )
    assert reasoning_for_model(settings) is None


def test_codex_spark_is_not_marked_vision_capable() -> None:
    settings = Settings(
        model_provider="codex",
        codex_model="gpt-5.3-codex-spark",
        codex_access_token="test-token",
        offline_mode=False,
        _env_file=None,
    )

    assert not vision_supported(settings)


def test_openai_live_requires_key() -> None:
    settings = Settings(
        WABOT_AGENT_MODEL_PROVIDER="openai",
        WABOT_AGENT_OFFLINE_MODE=False,
        _env_file=None,
    )
    assert not settings.live_model_enabled

    settings = Settings(
        WABOT_AGENT_MODEL_PROVIDER="openai",
        OPENAI_API_KEY="sk-test",
        OPENAI_MODEL="gpt-4.1-mini",
        WABOT_AGENT_OFFLINE_MODE=False,
        _env_file=None,
    )
    assert settings.live_model_enabled
    assert active_model_id(settings) == "gpt-4.1-mini"
    assert resolved_llm_base_url(settings) == "https://api.openai.com/v1"
    assert resolved_llm_api_key(settings) == "sk-test"


def test_openrouter_live_requires_key() -> None:
    settings = Settings(
        WABOT_AGENT_MODEL_PROVIDER="openrouter",
        WABOT_AGENT_OFFLINE_MODE=False,
        _env_file=None,
    )
    assert not settings.live_model_enabled

    settings = Settings(
        WABOT_AGENT_MODEL_PROVIDER="openrouter",
        OPENROUTER_API_KEY="sk-test",
        WABOT_AGENT_OFFLINE_MODE=False,
        _env_file=None,
    )
    assert settings.live_model_enabled
    assert active_model_id(settings) == settings.openrouter_model
    assert "openrouter.ai" in resolved_llm_base_url(settings)


def test_ollama_local_live_without_key() -> None:
    settings = Settings(
        WABOT_AGENT_MODEL_PROVIDER="ollama",
        OLLAMA_MODEL="llama3.2",
        WABOT_AGENT_OFFLINE_MODE=False,
        _env_file=None,
    )
    assert settings.live_model_enabled
    assert active_model_id(settings) == "llama3.2"
    assert resolved_llm_base_url(settings) == "http://127.0.0.1:11434/v1"
    assert resolved_llm_api_key(settings) == "ollama"


def test_ollama_cloud_strips_cloud_suffix_from_model_id() -> None:
    settings = Settings(
        model_provider="ollama_cloud",
        ollama_model="gemma4:31b-cloud",
        ollama_api_key="ollama-test",
        offline_mode=False,
        _env_file=None,
    )
    assert active_model_id(settings) == "gemma4:31b"


def test_ollama_cloud_strips_colon_cloud_suffix() -> None:
    settings = Settings(
        model_provider="ollama_cloud",
        ollama_model="minimax-m2.7:cloud",
        ollama_api_key="ollama-test",
        offline_mode=False,
        _env_file=None,
    )
    assert active_model_id(settings) == "minimax-m2.7"


def test_ollama_cloud_live_requires_key() -> None:
    settings = Settings(
        WABOT_AGENT_MODEL_PROVIDER="ollama_cloud",
        OLLAMA_MODEL="minimax-m2.7",
        WABOT_AGENT_OFFLINE_MODE=False,
        _env_file=None,
    )
    assert not settings.live_model_enabled

    settings = Settings(
        WABOT_AGENT_MODEL_PROVIDER="ollama_cloud",
        OLLAMA_MODEL="minimax-m2.7",
        OLLAMA_API_KEY="ollama-test",
        WABOT_AGENT_OFFLINE_MODE=False,
        _env_file=None,
    )
    assert settings.live_model_enabled
    assert resolved_llm_base_url(settings) == "https://ollama.com/v1"
    assert resolved_llm_api_key(settings) == "ollama-test"
