from __future__ import annotations

from agents.tool import ToolContext

from wabot_agent.config import Settings
from wabot_agent.events import EventLog
from wabot_agent.memory import MemoryStore
from wabot_agent.tools import (
    RuntimeContext,
    create_whatsapp_group,
    get_whatsapp_group,
    leave_whatsapp_group,
    set_whatsapp_group_picture,
    react_whatsapp_message,
    revoke_whatsapp_message,
    update_whatsapp_group,
    update_whatsapp_group_participants,
)
from wabot_agent.wabot import FakeWabotClient


async def test_react_blocked_in_dry_run(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    ctx = ToolContext(
        RuntimeContext(settings, memory, fake_wabot, event_log, run_id="run-react"),
        tool_name="react_whatsapp_message",
        tool_call_id="call-react",
        tool_arguments="{}",
    )
    result = await react_whatsapp_message.on_invoke_tool(
        ctx,
        '{"chat":"+15550001111","message_id":"m1","reaction":"👍"}',
    )
    assert result["sent"] is False
    assert result["reason"] == "dry_run"


async def test_react_allowlisted(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(
        update={"send_policy": "allowlist", "allowed_recipients": {"+15550001111"}}
    )
    ctx = ToolContext(
        RuntimeContext(live, memory, fake_wabot, event_log, run_id="run-react2"),
        tool_name="react_whatsapp_message",
        tool_call_id="call-react2",
        tool_arguments="{}",
    )
    result = await react_whatsapp_message.on_invoke_tool(
        ctx,
        '{"chat":"+15550001111","message_id":"m1","reaction":"👍"}',
    )
    assert result["ok"] is True


async def test_get_whatsapp_group_when_ready(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    ctx = ToolContext(
        RuntimeContext(settings, memory, fake_wabot, event_log, run_id="run-grp"),
        tool_name="get_whatsapp_group",
        tool_call_id="call-grp",
        tool_arguments="{}",
    )
    result = await get_whatsapp_group.on_invoke_tool(
        ctx, '{"group_jid":"120363123456789012@g.us"}'
    )
    assert result["ok"] is True


async def test_create_group_blocked_dry_run(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    ctx = ToolContext(
        RuntimeContext(settings, memory, fake_wabot, event_log, run_id="run-create"),
        tool_name="create_whatsapp_group",
        tool_call_id="call-create",
        tool_arguments="{}",
    )
    result = await create_whatsapp_group.on_invoke_tool(
        ctx, '{"name":"Ops","participants":["+15550001111"]}'
    )
    assert result["ok"] is False
    assert result["reason"] == "dry_run"


async def test_update_group_blocked_dry_run(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    ctx = ToolContext(
        RuntimeContext(settings, memory, fake_wabot, event_log, run_id="run-update"),
        tool_name="update_whatsapp_group",
        tool_call_id="call-update",
        tool_arguments="{}",
    )
    result = await update_whatsapp_group.on_invoke_tool(
        ctx, '{"group_jid":"120363123456789012@g.us","name":"New Name"}'
    )
    assert result["ok"] is False
    assert result["reason"] == "dry_run"


async def test_update_group_participants_add(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(update={"send_policy": "allow_all"})
    ctx = ToolContext(
        RuntimeContext(live, memory, fake_wabot, event_log, run_id="run-parts"),
        tool_name="update_whatsapp_group_participants",
        tool_call_id="call-parts",
        tool_arguments="{}",
    )
    result = await update_whatsapp_group_participants.on_invoke_tool(
        ctx,
        '{"group_jid":"120363123456789012@g.us","participants":["+15550001111"],"action":"add"}',
    )
    assert result["ok"] is True


async def test_leave_group_when_ready(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(update={"send_policy": "allow_all"})
    ctx = ToolContext(
        RuntimeContext(live, memory, fake_wabot, event_log, run_id="run-leave"),
        tool_name="leave_whatsapp_group",
        tool_call_id="call-leave",
        tool_arguments="{}",
    )
    result = await leave_whatsapp_group.on_invoke_tool(
        ctx, '{"group_jid":"120363123456789012@g.us"}'
    )
    assert result["ok"] is True


async def test_set_group_picture_remove(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(update={"send_policy": "allow_all"})
    ctx = ToolContext(
        RuntimeContext(live, memory, fake_wabot, event_log, run_id="run-gpic"),
        tool_name="set_whatsapp_group_picture",
        tool_call_id="call-gpic-rm",
        tool_arguments="{}",
    )
    result = await set_whatsapp_group_picture.on_invoke_tool(
        ctx, '{"group_jid":"120363123456789012@g.us","remove":true}'
    )
    assert result["ok"] is True


async def test_set_group_picture_blocked_dry_run(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    ctx = ToolContext(
        RuntimeContext(settings, memory, fake_wabot, event_log, run_id="run-gpic-dry"),
        tool_name="set_whatsapp_group_picture",
        tool_call_id="call-gpic-dry",
        tool_arguments="{}",
    )
    result = await set_whatsapp_group_picture.on_invoke_tool(
        ctx,
        '{"group_jid":"120363123456789012@g.us","image_path":"avatar.jpg","remove":false}',
    )
    assert result["ok"] is False
    assert result["reason"] == "dry_run"


async def test_revoke_returns_payload(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(update={"send_policy": "allow_all"})
    ctx = ToolContext(
        RuntimeContext(live, memory, fake_wabot, event_log, run_id="run-revoke"),
        tool_name="revoke_whatsapp_message",
        tool_call_id="call-revoke",
        tool_arguments="{}",
    )
    result = await revoke_whatsapp_message.on_invoke_tool(
        ctx, '{"chat":"+15550001111","message_id":"m9"}'
    )
    assert result["ok"] is True
