from __future__ import annotations

from wabot_agent.agent import run_agent
from wabot_agent.config import Settings
from wabot_agent.events import EventLog
from wabot_agent.memory import InboundMessage, MemoryStore
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


async def test_run_agent_returns_partial_when_runner_fails_after_whatsapp_send(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
    monkeypatch,
) -> None:
    live_settings = settings.model_copy(
        update={
            "send_policy": "allowlist",
            "allowed_recipients": {"+15550001111"},
        }
    )
    inbound = InboundMessage(
        id="partial-1",
        sender="+15550001111",
        text="hello",
        chat="+15550001111",
    )

    async def fake_run(*args, **kwargs):
        kwargs["context"].record_sent("+15550001111")
        raise RuntimeError("Max turns (15) exceeded")

    monkeypatch.setattr("wabot_agent.agent.Runner.run", fake_run)

    result = await run_agent(
        "hello",
        settings=live_settings,
        memory=memory,
        event_log=event_log,
        wabot=fake_wabot,
        inbound=inbound,
        session_id="+15550001111",
    )

    assert result.final_output == ""
    assert result.sent_destinations == frozenset({"+15550001111"})
    assert memory.stats()["runs"] == 1
    assert "agent_run_partial" in live_settings.log_path.read_text()
