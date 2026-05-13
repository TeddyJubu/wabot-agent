from __future__ import annotations

from wabot_agent.agent import run_agent
from wabot_agent.config import Settings
from wabot_agent.events import EventLog
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
