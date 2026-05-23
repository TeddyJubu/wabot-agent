from __future__ import annotations

from agents import FunctionTool

from wabot_agent.agent import build_agent_instructions, run_agent
from wabot_agent.composio_tools import build_composio_prompt_context, guard_composio_tools
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


def test_composio_instructions_keep_whatsapp_native() -> None:
    settings = Settings(
        composio_enabled=True,
        composio_api_key="ak-test",
        openai_api_key="sk-test",
        offline_mode=False,
    )

    text = build_agent_instructions(settings, "")

    assert "WhatsApp is never a Composio app/toolkit" in text
    assert "Do not call COMPOSIO_MANAGE_CONNECTIONS" in text
    assert "with `whatsapp`" in text
    assert "native wabot tools" in text


def test_composio_turn_context_blocks_whatsapp_toolkit() -> None:
    text = build_composio_prompt_context(tools_loaded=True)

    assert "WhatsApp is not" in text
    assert "native wabot only" in text
    assert "Never search for, execute, or manage" in text
    assert "Composio WhatsApp connection link" in text


async def test_composio_guard_blocks_whatsapp_connection_toolkit() -> None:
    called = False

    async def fake_invoke(ctx, raw_input):
        nonlocal called
        called = True
        return {"ok": True}

    tool = FunctionTool(
        name="COMPOSIO_MANAGE_CONNECTIONS",
        description="manage",
        params_json_schema={"type": "object", "properties": {}},
        on_invoke_tool=fake_invoke,
    )

    guarded = guard_composio_tools([tool])[0]
    result = await guarded.on_invoke_tool(
        None,
        '{"toolkits":["whatsapp"],"session_id":"unit"}',
    )

    assert called is False
    assert result["blocked"] is True
    assert result["reason"] == "whatsapp_is_native_wabot"


async def test_composio_guard_allows_calendar_search() -> None:
    async def fake_invoke(ctx, raw_input):
        return {"ok": True, "input": raw_input}

    tool = FunctionTool(
        name="COMPOSIO_SEARCH_TOOLS",
        description="search",
        params_json_schema={"type": "object", "properties": {}},
        on_invoke_tool=fake_invoke,
    )

    guarded = guard_composio_tools([tool])[0]
    result = await guarded.on_invoke_tool(
        None,
        '{"queries":[{"use_case":"Check Google Calendar free/busy today"}]}',
    )

    assert result["ok"] is True
