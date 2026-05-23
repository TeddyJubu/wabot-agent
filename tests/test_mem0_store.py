from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wabot_agent.config import Settings
from wabot_agent.mem0_store import (
    build_mem0_config,
    format_memories_for_prompt,
    mem0_enabled,
    mem0_health,
    reset_mem0_memory_for_tests,
    search_memories_sync,
)


@pytest.fixture(autouse=True)
def _reset_mem0() -> None:
    reset_mem0_memory_for_tests()
    yield
    reset_mem0_memory_for_tests()


def test_mem0_disabled_without_flag() -> None:
    settings = Settings(mem0_enabled=False, openrouter_api_key="sk-test")
    assert mem0_enabled(settings) is False


def test_mem0_enabled_with_openrouter() -> None:
    settings = Settings(
        model_provider="openrouter",
        mem0_enabled=True,
        openrouter_api_key="sk-test",
    )
    assert mem0_enabled(settings) is True


def test_mem0_enabled_with_openai() -> None:
    settings = Settings(
        model_provider="openai",
        mem0_enabled=True,
        openai_api_key="sk-test",
    )
    assert mem0_enabled(settings) is True
    config = build_mem0_config(settings)
    assert config["llm"]["config"]["openai_base_url"] == settings.openai_base_url
    assert config["embedder"]["config"]["openai_base_url"] == settings.openai_base_url


def test_mem0_codex_requires_explicit_llm_provider() -> None:
    settings = Settings(
        model_provider="codex",
        mem0_enabled=True,
        openrouter_api_key="sk-test",
        offline_mode=False,
    )
    assert mem0_enabled(settings) is False
    health = mem0_health(settings)
    assert health["enabled"] is False
    assert health["reason"] == "mem0_llm_provider_required_for_codex"


def test_mem0_codex_can_use_explicit_openrouter_provider() -> None:
    settings = Settings(
        model_provider="codex",
        mem0_enabled=True,
        mem0_llm_provider="openrouter",
        openrouter_api_key="sk-test",
        offline_mode=False,
    )
    assert mem0_enabled(settings) is True
    config = build_mem0_config(settings)
    assert config["llm"]["config"]["openai_base_url"] == settings.openrouter_base_url


def test_build_mem0_config_uses_local_qdrant() -> None:
    settings = Settings(
        model_provider="openrouter",
        mem0_enabled=True,
        openrouter_api_key="sk-test",
        mem0_path="./data/mem0_qdrant",
    )
    config = build_mem0_config(settings)
    assert config["vector_store"]["provider"] == "qdrant"
    assert config["vector_store"]["config"]["on_disk"] is True
    assert config["llm"]["config"]["openai_base_url"] == settings.openrouter_base_url


def test_format_memories_for_prompt() -> None:
    text = format_memories_for_prompt(
        [{"memory": "Prefers morning appointments"}],
        max_chars=500,
    )
    assert "Mem0" in text
    assert "morning" in text


def test_search_memories_sync_mocked(tmp_path) -> None:
    settings = Settings(
        model_provider="openrouter",
        mem0_enabled=True,
        openrouter_api_key="sk-test",
        mem0_path=tmp_path / "mem0",
    )
    mock_memory = MagicMock()
    mock_memory.search.return_value = {
        "results": [{"memory": "Likes TCM clinics", "id": "1", "score": 0.9}]
    }

    with patch("wabot_agent.mem0_store.get_mem0_memory", return_value=mock_memory):
        payload = search_memories_sync(
            settings,
            user_id="user@s.whatsapp.net",
            query="clinic preferences",
        )

    assert payload["ok"] is True
    assert payload["count"] == 1
    mock_memory.search.assert_called_once()


def test_mem0_quota_failure_degrades_temporarily() -> None:
    settings = Settings(
        model_provider="openrouter",
        mem0_enabled=True,
        openrouter_api_key="sk-test",
        mem0_path="./data/mem0_qdrant",
    )
    mock_memory = MagicMock()
    mock_memory.search.side_effect = RuntimeError("Error code: 403 - Key limit exceeded")

    with patch("wabot_agent.mem0_store.get_mem0_memory", return_value=mock_memory):
        payload = search_memories_sync(
            settings,
            user_id="user@s.whatsapp.net",
            query="clinic preferences",
        )

    assert payload["ok"] is False
    health = mem0_health(settings)
    assert health["enabled"] is False
    assert health["degraded"] is True
    assert "Key limit exceeded" in str(health["reason"])
