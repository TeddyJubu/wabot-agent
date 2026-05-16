from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from wabot_agent.agent import run_agent
from wabot_agent.config import Settings
from wabot_agent.events import EventLog
from wabot_agent.logging_config import (
    ContextVarsFilter,
    JsonFormatter,
    run_id_var,
)
from wabot_agent.memory import MemoryStore
from wabot_agent.wabot import FakeWabotClient


async def test_run_agent_offline_does_not_need_openrouter(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    result = await run_agent(
        "Check wabot and tell me what you can do.",
        settings=settings,
        memory=memory,
        event_log=event_log,
        wabot=fake_wabot,
        session_id="test",
    )

    assert result.live_model is False
    assert "Offline mode is active" in result.final_output
    assert memory.stats()["runs"] == 1


@pytest.fixture()
def capture_agent_logs():
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextVarsFilter())
    logger = logging.getLogger("wabot_agent.agent")
    saved = list(logger.handlers)
    saved_level = logger.level
    saved_propagate = logger.propagate
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield buf
    logger.handlers.clear()
    for h in saved:
        logger.addHandler(h)
    logger.setLevel(saved_level)
    logger.propagate = saved_propagate


async def test_run_agent_emits_correlated_log_records(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
    capture_agent_logs: StringIO,
) -> None:
    """`run_agent` emits agent_run_start and agent_run_end with the same run_id,
    and clears the contextvar after."""
    result = await run_agent(
        "hi",
        settings=settings,
        memory=memory,
        event_log=event_log,
        wabot=fake_wabot,
        session_id="logtest",
    )

    lines = [
        json.loads(line)
        for line in capture_agent_logs.getvalue().strip().splitlines()
        if line
    ]
    starts = [r for r in lines if r["event"] == "agent_run_start"]
    ends = [r for r in lines if r["event"] == "agent_run_end"]
    assert len(starts) == 1, f"expected exactly one agent_run_start, got {starts}"
    assert len(ends) == 1
    # request_id is None here (no FastAPI middleware), but run_id is bound and
    # stamped onto every record in the run.
    assert starts[0]["run_id"] == result.run_id
    assert ends[0]["run_id"] == result.run_id
    assert ends[0]["session_id"] == "logtest"
    assert isinstance(ends[0]["latency_ms"], int)
    # ContextVar restored.
    assert run_id_var.get() is None
