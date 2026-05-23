from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agents import RunContextWrapper, function_tool

from ..redaction import redact
from ._common import RuntimeContext, _is_owner_session, _requester_jid


def _parse_due_at_iso(due_at: str) -> str | None:
    text = due_at.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    except ValueError:
        return None


@function_tool
async def create_reminder(
    ctx: RunContextWrapper[RuntimeContext],
    message: str,
    due_at: str,
    target_jid: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Schedule a WhatsApp reminder at due_at (ISO-8601 UTC, e.g. 2026-05-19T14:00:00+00:00)."""
    requester = _requester_jid(ctx)
    if requester is None:
        payload = {"created": False, "reason": "no_inbound_requester"}
        ctx.context.memory.record_tool_event(ctx.context.run_id, "create_reminder", payload)
        return payload

    if not ctx.context.settings.reminders_enabled:
        payload = {"created": False, "reason": "reminders_disabled"}
        ctx.context.memory.record_tool_event(ctx.context.run_id, "create_reminder", payload)
        return payload

    due_iso = _parse_due_at_iso(due_at)
    if due_iso is None:
        payload = {"created": False, "reason": "invalid_due_at", "due_at": due_at}
        ctx.context.memory.record_tool_event(ctx.context.run_id, "create_reminder", payload)
        return payload

    pending = ctx.context.memory.count_pending_reminders(requester)
    cap = ctx.context.settings.reminder_max_pending_per_contact
    if pending >= cap:
        payload = {
            "created": False,
            "reason": "pending_limit",
            "pending": pending,
            "limit": cap,
        }
        ctx.context.memory.record_tool_event(ctx.context.run_id, "create_reminder", payload)
        return payload

    payload = ctx.context.memory.create_reminder(
        requester_jid=requester,
        message=message,
        due_at=due_iso,
        target_jid=target_jid,
        idempotency_key=idempotency_key,
    )
    ctx.context.memory.record_tool_event(ctx.context.run_id, "create_reminder", payload)
    ctx.context.event_log.write("reminder_created", redact(payload))
    return redact(payload)


@function_tool
async def list_reminders(
    ctx: RunContextWrapper[RuntimeContext],
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List scheduled reminders for the current requester (or all when no inbound)."""
    requester = _requester_jid(ctx)
    rows = ctx.context.memory.list_reminders(
        requester_jid=requester,
        status=status,
        limit=limit,
    )
    payload = {"count": len(rows), "reminders": rows}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "list_reminders", payload)
    return redact(payload)


@function_tool
async def cancel_reminder(
    ctx: RunContextWrapper[RuntimeContext],
    reminder_id: str,
) -> dict[str, Any]:
    """Cancel a pending reminder by id."""
    requester = _requester_jid(ctx)
    payload = ctx.context.memory.cancel_reminder(
        reminder_id, requester_jid=requester
    )
    ctx.context.memory.record_tool_event(ctx.context.run_id, "cancel_reminder", payload)
    return redact(payload)


@function_tool
async def track_outbound_conversation(
    ctx: RunContextWrapper[RuntimeContext],
    target_jid: str,
    chat_jid: str | None = None,
    prompt_summary: str | None = None,
    notify_owner: bool = True,
) -> dict[str, Any]:
    """Track an outbound message and notify the owner when the target replies."""
    inbound = ctx.context.inbound
    if inbound is None or not _is_owner_session(ctx.context.settings, inbound):
        payload = {"created": False, "reason": "owner_session_required"}
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "track_outbound_conversation", payload
        )
        return payload

    chat = (chat_jid or target_jid).strip()
    expires_at = ctx.context.memory.outbound_expires_at(
        days=ctx.context.settings.outbound_task_expiry_days
    )
    payload = ctx.context.memory.create_outbound_task(
        owner_jid=inbound.sender,
        target_jid=target_jid.strip(),
        chat_jid=chat,
        prompt_summary=prompt_summary,
        notify_owner=notify_owner,
        expires_at=expires_at,
    )
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "track_outbound_conversation", payload
    )
    return redact(payload)


@function_tool
async def get_outbound_task_status(
    ctx: RunContextWrapper[RuntimeContext],
    task_id: str,
) -> dict[str, Any]:
    """Return status and reply details for a tracked outbound conversation."""
    task = ctx.context.memory.get_outbound_task(task_id)
    if task is None:
        payload = {"found": False, "id": task_id}
    else:
        payload = {"found": True, **task}
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "get_outbound_task_status", {"id": task_id, "found": task is not None}
    )
    return redact(payload)


@function_tool
async def list_outbound_tasks(
    ctx: RunContextWrapper[RuntimeContext],
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List outbound conversation tasks for the owner (awaiting_reply, completed, expired)."""
    owner = _requester_jid(ctx)
    rows = ctx.context.memory.list_outbound_tasks(
        owner_jid=owner,
        status=status,
        limit=limit,
    )
    payload = {"count": len(rows), "tasks": rows}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "list_outbound_tasks", payload)
    return redact(payload)
