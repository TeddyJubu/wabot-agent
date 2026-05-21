from __future__ import annotations

from agents.tool import ToolContext

from wabot_agent.config import Settings
from wabot_agent.events import EventLog
from wabot_agent.memory import InboundMessage, MemoryStore
from wabot_agent.task_progress import (
    format_step_complete,
    format_task_plan,
    looks_like_multi_step_task,
)
from wabot_agent.tools import (
    RuntimeContext,
    maybe_send_task_started_ack,
    report_task_step_complete,
    send_task_plan,
)
from wabot_agent.wabot import FakeWabotClient


def test_looks_like_multi_step_task_long_request() -> None:
    text = (
        "Research every coffee shop in Brooklyn, compile a spreadsheet, "
        "and then message each owner with our intro. Start with Google Maps."
    )
    assert looks_like_multi_step_task(text)


def test_looks_like_multi_step_task_short_request() -> None:
    assert not looks_like_multi_step_task("What time is it in Singapore?")


def test_format_task_plan_numbered() -> None:
    body = format_task_plan("Lead scrape", ["Search web", "Save CSV", "Send summary"])
    assert "📋 Lead scrape" in body
    assert "1. Search web" in body
    assert "2. Save CSV" in body


def test_format_step_complete_includes_total() -> None:
    body = format_step_complete(2, "Scrape", "Found 40 rows", total_steps=4)
    assert "Step 2/4" in body
    assert "Scrape" in body


async def test_send_task_plan_does_not_block_final_auto_reply(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(
        update={
            "send_policy": "allow_all",
            "task_progress_updates_enabled": True,
            "owner_numbers": {"+15550009999@s.whatsapp.net"},
        }
    )
    inbound = InboundMessage(
        id="m1",
        sender="+15550009999@s.whatsapp.net",
        chat="+15550009999@s.whatsapp.net",
        text="long task",
    )
    ctx = ToolContext(
        RuntimeContext(live, memory, fake_wabot, event_log, run_id="run-tp", inbound=inbound),
        tool_name="send_task_plan",
        tool_call_id="call-tp",
        tool_arguments="{}",
    )
    result = await send_task_plan.on_invoke_tool(
        ctx,
        '{"steps":["A","B"],"title":"Plan"}',
    )
    assert result["sent"] is True
    assert fake_wabot.sent
    runtime = ctx.context
    assert runtime.sent_destinations is not None
    assert not runtime.sent_destinations


async def test_maybe_send_task_started_ack_for_complex_inbound(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(
        update={
            "send_policy": "allow_all",
            "owner_numbers": {"+15550009999@s.whatsapp.net"},
        }
    )
    inbound = InboundMessage(
        id="m2",
        sender="+15550009999@s.whatsapp.net",
        chat="+15550009999@s.whatsapp.net",
        text=(
            "First find ten articles about AI agents, then summarize each one, "
            "and then email me a bullet list with links."
        ),
    )
    runtime = RuntimeContext(
        live, memory, fake_wabot, event_log, run_id="run-ack", inbound=inbound
    )
    sent = await maybe_send_task_started_ack(runtime, inbound.text)
    assert sent is not None
    assert sent["sent"] is True
    assert len(fake_wabot.sent) == 1


async def test_maybe_send_task_started_ack_skips_non_owner_inbound(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(
        update={
            "send_policy": "allow_all",
            "owner_numbers": {"+15550001111@s.whatsapp.net"},
        }
    )
    inbound = InboundMessage(
        id="m2b",
        sender="+15550009999@s.whatsapp.net",
        chat="+15550009999@s.whatsapp.net",
        text=(
            "First find ten articles about AI agents, then summarize each one, "
            "and then email me a bullet list with links."
        ),
    )
    runtime = RuntimeContext(
        live, memory, fake_wabot, event_log, run_id="run-ack-non-owner", inbound=inbound
    )
    sent = await maybe_send_task_started_ack(runtime, inbound.text)
    assert sent is None
    assert fake_wabot.sent == []


async def test_report_task_step_complete(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(
        update={
            "send_policy": "allow_all",
            "owner_numbers": {"+15550009999@s.whatsapp.net"},
        }
    )
    inbound = InboundMessage(
        id="m3",
        sender="+15550009999@s.whatsapp.net",
        chat="+15550009999@s.whatsapp.net",
        text="task",
    )
    ctx = ToolContext(
        RuntimeContext(live, memory, fake_wabot, event_log, run_id="run-step", inbound=inbound),
        tool_name="report_task_step_complete",
        tool_call_id="call-step",
        tool_arguments="{}",
    )
    result = await report_task_step_complete.on_invoke_tool(
        ctx,
        '{"step_number":1,"step_title":"Search","status_summary":"Done","total_steps":3}',
    )
    assert result["sent"] is True
    assert "Step 1/3" in fake_wabot.sent[-1]["text"]


async def test_report_task_step_complete_skips_non_owner_inbound(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(
        update={
            "send_policy": "allow_all",
            "owner_numbers": {"+15550001111@s.whatsapp.net"},
        }
    )
    inbound = InboundMessage(
        id="m4",
        sender="+15550009999@s.whatsapp.net",
        chat="+15550009999@s.whatsapp.net",
        text="task",
    )
    ctx = ToolContext(
        RuntimeContext(
            live,
            memory,
            fake_wabot,
            event_log,
            run_id="run-step-non-owner",
            inbound=inbound,
        ),
        tool_name="report_task_step_complete",
        tool_call_id="call-step-non-owner",
        tool_arguments="{}",
    )
    result = await report_task_step_complete.on_invoke_tool(
        ctx,
        '{"step_number":1,"step_title":"Search","status_summary":"Done","total_steps":3}',
    )
    assert result["sent"] is False
    assert result["reason"] == "owner_progress_only"
    assert fake_wabot.sent == []
