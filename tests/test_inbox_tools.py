from __future__ import annotations

from agents.tool import ToolContext

from wabot_agent.config import Settings
from wabot_agent.events import EventLog
from wabot_agent.memory import InboundMessage, MemoryStore
from wabot_agent.tools import (
    RuntimeContext,
    get_last_whatsapp_inbound_message,
    list_whatsapp_inbound_messages,
)
from wabot_agent.wabot import FakeWabotClient


async def test_inbox_tools_prefer_wabot_daemon(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    ctx = ToolContext(
        RuntimeContext(settings, memory, fake_wabot, event_log, run_id="run-inbox"),
        tool_name="list_whatsapp_inbound_messages",
        tool_call_id="call-inbox",
        tool_arguments="{}",
    )

    result = await list_whatsapp_inbound_messages.on_invoke_tool(ctx, '{"limit": 5}')

    assert result["source"] == "wabot_daemon"
    assert result["count"] == 1


async def test_inbox_tools_fall_back_to_memory(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
) -> None:
    class EmptyInboxClient(FakeWabotClient):
        async def inbox_recent(self, limit: int = 20) -> dict:
            return {"reachable": True, "messages": [], "count": 0}

    memory.record_inbound(
        InboundMessage(
            id="m-1",
            sender="+15550009999",
            chat="+15550009999",
            text="stored inbound",
        )
    )
    ctx = ToolContext(
        RuntimeContext(settings, memory, EmptyInboxClient(), event_log, run_id="run-mem"),
        tool_name="get_last_whatsapp_inbound_message",
        tool_call_id="call-last",
        tool_arguments="{}",
    )

    result = await get_last_whatsapp_inbound_message.on_invoke_tool(ctx, "{}")

    assert result["found"] is True
    assert result["message"]["text"] == "stored inbound"
