from __future__ import annotations

from pathlib import Path

import pytest

from wabot_agent.config import Settings
from wabot_agent.events import EventLog
from wabot_agent.memory import MemoryStore
from wabot_agent.wabot import FakeWabotClient


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SKILLS_DIR=Path("skills"),
        WABOT_AGENT_SEND_POLICY="dry_run",
        OPENROUTER_MODEL="openai/gpt-5.2",
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )


@pytest.fixture
def memory(settings: Settings) -> MemoryStore:
    return MemoryStore(settings.db_path)


@pytest.fixture
def event_log(settings: Settings) -> EventLog:
    return EventLog(settings.log_path)


@pytest.fixture
def fake_wabot() -> FakeWabotClient:
    return FakeWabotClient()
