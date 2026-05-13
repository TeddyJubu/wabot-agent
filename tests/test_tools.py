from __future__ import annotations

from agents.tool import ToolContext

from vignesh_agent.config import Settings
from vignesh_agent.events import EventLog
from vignesh_agent.memory import MemoryStore
from vignesh_agent.tools import (
    RuntimeContext,
    send_whatsapp_image,
    send_whatsapp_text,
    wabot_health,
)
from vignesh_agent.wabot import FakeWabotClient


async def test_send_tool_blocks_by_default(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    ctx = ToolContext(
        RuntimeContext(settings, memory, fake_wabot, event_log, run_id="run-1"),
        tool_name="send_whatsapp_text",
        tool_call_id="call-1",
        tool_arguments='{"to":"+15550001111","text":"hello"}',
    )

    result = await send_whatsapp_text.on_invoke_tool(
        ctx, '{"to":"+15550001111","text":"hello"}'
    )

    assert result["sent"] is False
    assert result["reason"] == "dry_run"
    assert fake_wabot.sent == []


async def test_send_tool_allows_allowlisted_recipient(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live_settings = settings.model_copy(
        update={"send_policy": "allowlist", "allowed_recipients": {"+15550001111"}}
    )
    ctx = ToolContext(
        RuntimeContext(live_settings, memory, fake_wabot, event_log, run_id="run-2"),
        tool_name="send_whatsapp_text",
        tool_call_id="call-2",
        tool_arguments='{"to":"+15550001111","text":"hello"}',
    )

    result = await send_whatsapp_text.on_invoke_tool(
        ctx, '{"to":"+15550001111","text":"hello"}'
    )

    assert result["sent"] is True
    assert fake_wabot.sent[0]["to"] == "+15550001111"


async def test_wabot_health_tool_uses_client(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    ctx = ToolContext(
        RuntimeContext(settings, memory, fake_wabot, event_log, run_id="run-3"),
        tool_name="wabot_health",
        tool_call_id="call-3",
        tool_arguments="{}",
    )

    result = await wabot_health.on_invoke_tool(ctx, "{}")

    assert result["ready"] is True


async def test_image_send_rejects_paths_outside_media_dir(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live_settings = settings.model_copy(
        update={"send_policy": "allowlist", "allowed_recipients": {"+15550001111"}}
    )
    ctx = ToolContext(
        RuntimeContext(live_settings, memory, fake_wabot, event_log, run_id="run-4"),
        tool_name="send_whatsapp_image",
        tool_call_id="call-4",
        tool_arguments='{"to":"+15550001111","path":"/etc/passwd"}',
    )

    result = await send_whatsapp_image.on_invoke_tool(
        ctx, '{"to":"+15550001111","path":"/etc/passwd"}'
    )

    assert result["sent"] is False
    assert result["reason"] == "image_path_not_allowed"
    assert fake_wabot.sent == []
