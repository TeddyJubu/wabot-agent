from __future__ import annotations

from vignesh_agent.agent import run_agent
from vignesh_agent.config import Settings
from vignesh_agent.events import EventLog
from vignesh_agent.memory import MemoryStore
from vignesh_agent.wabot import FakeWabotClient


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

