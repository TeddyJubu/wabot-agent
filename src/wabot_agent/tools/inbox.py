from __future__ import annotations

from typing import Any

from agents import RunContextWrapper, function_tool

from ..redaction import redact
from ._common import RuntimeContext


async def _inbox_payload(ctx: RunContextWrapper[RuntimeContext], limit: int = 20) -> dict[str, Any]:
    inbox = await ctx.context.wabot.inbox_recent(limit=limit)
    messages = inbox.get("messages") or []
    if not messages:
        messages = ctx.context.memory.recent_inbound(limit=limit)
        if messages:
            inbox = {
                **inbox,
                "messages": messages,
                "count": len(messages),
                "source": "agent_database",
            }
    else:
        inbox = {**inbox, "source": "wabot_daemon"}
    inbox.setdefault(
        "note",
        "Shows recent inbound WhatsApp messages observed by wabot. "
        "This is not the same as unread counts in the WhatsApp mobile app.",
    )
    return inbox


@function_tool
async def list_whatsapp_inbound_messages(
    ctx: RunContextWrapper[RuntimeContext], limit: int = 20
) -> dict[str, Any]:
    """List recent inbound WhatsApp messages received by wabot (not WhatsApp app unread badges)."""
    payload = await _inbox_payload(ctx, limit=limit)
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "list_whatsapp_inbound_messages", {"count": payload.get("count", 0)}
    )
    return redact(payload)


@function_tool
async def get_last_whatsapp_inbound_message(
    ctx: RunContextWrapper[RuntimeContext], contact: str | None = None
) -> dict[str, Any]:
    """Return the most recent inbound WhatsApp message, optionally filtered by contact/chat JID."""
    inbox = await _inbox_payload(ctx, limit=50)
    messages = inbox.get("messages") or []
    if contact:
        filtered = [
            msg
            for msg in messages
            if msg.get("from") == contact
            or msg.get("chat") == contact
            or msg.get("sender") == contact
        ]
        messages = filtered
    last = messages[-1] if messages else ctx.context.memory.last_inbound(contact)
    payload = {
        "found": last is not None,
        "message": last,
        "note": inbox.get("note"),
        "source": inbox.get("source"),
    }
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "get_last_whatsapp_inbound_message", payload
    )
    return redact(payload)


@function_tool
async def lookup_whatsapp_contacts(
    ctx: RunContextWrapper[RuntimeContext], phones: list[str]
) -> dict[str, Any]:
    """Check whether phone numbers are registered on WhatsApp (whatsmeow IsOnWhatsApp)."""
    try:
        payload = await ctx.context.wabot.contacts_lookup(phones)
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "lookup_whatsapp_contacts", payload)
    return redact(payload)
