from __future__ import annotations

from typing import Any

from agents import RunContextWrapper, function_tool

from ..redaction import mask_phone, redact
from ..task_progress import (
    TASK_STARTED_ACK,
    format_step_complete,
    format_task_plan,
    looks_like_multi_step_task,
)
from ._common import (
    RuntimeContext,
    _is_send_allowed,
    _owner_progress_allowed,
    _resolve_progress_destination,
)


async def _send_progress_whatsapp(
    ctx: RuntimeContext,
    text: str,
    *,
    to: str | None = None,
    event_kind: str,
) -> dict[str, Any]:
    if not _owner_progress_allowed(ctx):
        payload = {"sent": False, "reason": "owner_progress_only"}
        ctx.memory.record_tool_event(ctx.run_id, event_kind, payload)
        ctx.event_log.write("task_progress_skipped", payload)
        return payload

    destination, dest_reason = _resolve_progress_destination(ctx, to)
    if destination is None:
        payload = {"sent": False, "reason": dest_reason}
        ctx.memory.record_tool_event(ctx.run_id, event_kind, payload)
        return payload

    allowed, policy = _is_send_allowed(ctx.settings, destination, inbound=ctx.inbound)
    if not allowed:
        payload = {
            "sent": False,
            "reason": policy,
            "to": mask_phone(destination),
        }
        ctx.memory.record_tool_event(ctx.run_id, event_kind, payload)
        ctx.event_log.write("send_blocked", payload)
        return payload

    health = await ctx.wabot.health()
    if not health.ready:
        payload = {
            "sent": False,
            "reason": "wabot_not_ready",
            "to": mask_phone(destination),
        }
        ctx.memory.record_tool_event(ctx.run_id, event_kind, payload)
        return payload

    try:
        result = await ctx.wabot.send_text(to=destination, text=text)
    except Exception as exc:  # noqa: BLE001 — WabotError and transport errors
        payload = {
            "sent": False,
            "reason": "send_failed",
            "to": mask_phone(destination),
            "detail": redact(str(exc)),
        }
        ctx.memory.record_tool_event(ctx.run_id, event_kind, payload)
        return payload

    ctx.record_sent(destination, substantive=False)
    payload = {
        "sent": True,
        "policy": policy,
        "to": mask_phone(destination),
        "result": redact(result),
    }
    ctx.memory.record_tool_event(ctx.run_id, event_kind, payload)
    ctx.event_log.write(event_kind, payload)
    return payload


async def maybe_send_task_started_ack(
    ctx: RuntimeContext,
    prompt: str,
) -> dict[str, Any] | None:
    if not ctx.settings.task_progress_updates_enabled:
        return None
    if ctx.inbound is None:
        return None
    if not _owner_progress_allowed(ctx):
        return None
    if not looks_like_multi_step_task(prompt):
        return None
    return await _send_progress_whatsapp(
        ctx,
        TASK_STARTED_ACK,
        event_kind="task_progress_started",
    )


@function_tool
async def send_task_plan(
    ctx: RunContextWrapper[RuntimeContext],
    steps: list[str],
    title: str = "Plan",
    to: str | None = None,
) -> dict[str, Any]:
    """Post a numbered plan to WhatsApp before starting multi-step owner work.

    Owner/dashboard only. Call this at the start of an owner task that needs 3+ tool calls
    or several minutes. For non-owner inbound chats, do not send step-by-step progress;
    answer naturally in the final reply. `to` defaults to the inbound chat (or sender).
    On the dashboard, pass `to` explicitly.
    """
    if not steps:
        return {"sent": False, "reason": "empty_steps"}
    body = format_task_plan(title, steps)
    result = await _send_progress_whatsapp(
        ctx.context,
        body,
        to=to,
        event_kind="send_task_plan",
    )
    result["step_count"] = len([s for s in steps if s.strip()])
    return result


@function_tool
async def report_task_step_complete(
    ctx: RunContextWrapper[RuntimeContext],
    step_number: int,
    step_title: str,
    status_summary: str,
    total_steps: int | None = None,
    to: str | None = None,
) -> dict[str, Any]:
    """Notify the owner on WhatsApp that one plan step finished.

    Owner/dashboard only. Call after each step in a multi-step owner task, before
    starting the next step. For non-owner inbound chats, do not send progress pings.
    """
    body = format_step_complete(
        step_number,
        step_title,
        status_summary,
        total_steps=total_steps,
    )
    return await _send_progress_whatsapp(
        ctx.context,
        body,
        to=to,
        event_kind="report_task_step_complete",
    )


@function_tool
async def send_task_progress(
    ctx: RunContextWrapper[RuntimeContext],
    message: str,
    to: str | None = None,
) -> dict[str, Any]:
    """Send a short owner-only in-progress update on WhatsApp during long-running work.

    Use for owner/dashboard tasks when a single step will take a while and you have no
    other tool output yet (e.g. "Still scraping page 3 of 10…"). For non-owner inbound
    chats, do not send progress pings; reply naturally at the end.
    """
    text = message.strip()
    if not text:
        return {"sent": False, "reason": "empty_message"}
    return await _send_progress_whatsapp(
        ctx.context,
        text,
        to=to,
        event_kind="send_task_progress",
    )
