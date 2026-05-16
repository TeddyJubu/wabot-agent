from __future__ import annotations

from agents.tool import ToolContext

from wabot_agent.config import Settings
from wabot_agent.events import EventLog
from wabot_agent.memory import MemoryStore
from wabot_agent.tools import RuntimeContext, archive_whatsapp_chat, mute_whatsapp_chat
from wabot_agent.wabot import FakeWabotClient


async def test_mute_chat_blocked_dry_run(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    dry = settings.model_copy(update={"send_policy": "dry_run"})
    ctx = ToolContext(
        RuntimeContext(dry, memory, fake_wabot, event_log, run_id="run-mute"),
        tool_name="mute_whatsapp_chat",
        tool_call_id="call-mute",
        tool_arguments="{}",
    )
    result = await mute_whatsapp_chat.on_invoke_tool(
        ctx, '{"chat":"+15550001111","mute":true}'
    )
    assert result["ok"] is False
    assert result["reason"] == "dry_run"


async def test_archive_chat_when_ready(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(update={"send_policy": "allowlist", "allowed_recipients": set()})
    ctx = ToolContext(
        RuntimeContext(live, memory, fake_wabot, event_log, run_id="run-arch"),
        tool_name="archive_whatsapp_chat",
        tool_call_id="call-arch",
        tool_arguments="{}",
    )
    result = await archive_whatsapp_chat.on_invoke_tool(
        ctx, '{"chat":"+15550001111","archive":true}'
    )
    assert result["ok"] is True
