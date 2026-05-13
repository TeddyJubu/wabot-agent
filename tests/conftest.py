from __future__ import annotations

from pathlib import Path

import pytest

from vignesh_agent.config import Settings
from vignesh_agent.events import EventLog
from vignesh_agent.memory import MemoryStore
from vignesh_agent.wabot import FakeWabotClient


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        VIGNESH_OFFLINE_MODE=True,
        VIGNESH_DATA_DIR=tmp_path,
        VIGNESH_DB_PATH=tmp_path / "agent.db",
        VIGNESH_LOG_PATH=tmp_path / "events.jsonl",
        VIGNESH_MCP_CONFIG=None,
        VIGNESH_SKILLS_DIR=Path("skills"),
        VIGNESH_SEND_POLICY="dry_run",
        OPENROUTER_API_KEY=None,
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

