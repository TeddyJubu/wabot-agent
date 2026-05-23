from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wabot_agent.config import Settings
from wabot_agent.memory import MemoryStore
from wabot_agent.thread_summary import (
    history_items_to_transcript,
    should_summarize_dropped,
    summarize_thread,
)


def _settings(tmp_path: Path, **kwargs: object) -> Settings:
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        OPENROUTER_MODEL="openai/gpt-5.2",
        OPENROUTER_API_KEY=None,
        _env_file=None,
        **kwargs,
    )


def test_history_items_to_transcript() -> None:
    text = history_items_to_transcript(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
    )
    assert "user:" in text
    assert "assistant:" in text
    assert "hello" in text


def test_should_summarize_dropped_respects_threshold(tmp_path: Path) -> None:
    settings = _settings(tmp_path, WABOT_AGENT_SESSION_SUMMARY_MIN_DROPPED_TOKENS=100)
    small = [{"role": "user", "content": "hi"}]
    large = [{"role": "user", "content": "x" * 500}]
    assert should_summarize_dropped(settings, small) is False
    assert should_summarize_dropped(settings, large) is True


@pytest.mark.asyncio
async def test_summarize_thread_offline_fallback(tmp_path: Path) -> None:
    settings = _settings(tmp_path, WABOT_AGENT_SESSION_SUMMARY_ENABLED=True)
    summary = await summarize_thread(
        settings,
        [{"role": "user", "content": "We agreed to ship Friday."}],
        prior_summary="User prefers concise replies.",
    )
    assert "Friday" in summary or "concise" in summary


@pytest.mark.asyncio
async def test_summarize_thread_live_calls_llm(tmp_path: Path) -> None:
    settings = Settings(
        WABOT_AGENT_OFFLINE_MODE=False,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_MODEL_PROVIDER="openrouter",
        OPENROUTER_MODEL="openai/gpt-4.1-mini",
        OPENROUTER_API_KEY="test-key",
        WABOT_AGENT_SESSION_SUMMARY_ENABLED=True,
        _env_file=None,
    )
    mock_choice = MagicMock()
    mock_choice.message.content = "User asked about pricing. Assistant quoted $99."
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("wabot_agent.thread_summary.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        summary = await summarize_thread(
            settings,
            [{"role": "user", "content": "What is the price?"}],
        )

    assert "pricing" in summary.lower() or "$99" in summary
    mock_client.chat.completions.create.assert_awaited_once()


def test_memory_session_summary_roundtrip(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "agent.db")
    assert memory.get_session_summary("contact-1") is None
    memory.save_session_summary("contact-1", "User likes short answers.")
    assert memory.get_session_summary("contact-1") == "User likes short answers."
