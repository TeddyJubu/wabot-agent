from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents import RunContextWrapper, function_tool

from .config import Settings
from .events import EventLog
from .file_processing import process_file_at_path, whatsapp_send_kind_for_path
from .media_download import download_media_message
from .media_paths import media_path_allowed, workspace_path_allowed
from .mem0_store import (
    add_memory_sync,
    mem0_enabled,
    search_memories_sync,
)
from .memory import (
    InboundMessage,
    MemoryStore,
    inbound_memory_contact_id,
    inbound_memory_user_ids,
)
from .recipients import is_listed_recipient, recipients_match
from .redaction import looks_sensitive, mask_phone, redact
from .skills import list_skills, read_skill
from .task_progress import (
    TASK_STARTED_ACK,
    format_step_complete,
    format_task_plan,
    looks_like_multi_step_task,
)
from .wabot import WabotClient
from .web_agent import web_agent_health
from .web_fetch import fetch_url_to_media as download_url_to_media
from .web_search import search_web as duckduckgo_search


@dataclass
class RuntimeContext:
    settings: Settings
    memory: MemoryStore
    wabot: WabotClient
    event_log: EventLog
    run_id: str
    inbound: InboundMessage | None = None
    sent_destinations: set[str] | None = None

    def __post_init__(self) -> None:
        if self.sent_destinations is None:
            self.sent_destinations = set()

    def record_sent(self, to: str, *, substantive: bool = True) -> None:
        """Track WhatsApp sends. Progress pings do not block the final auto-reply."""
        if self.sent_destinations is not None and substantive:
            self.sent_destinations.add(to.strip())


def _is_owner_session(settings: Settings, inbound: InboundMessage | None) -> bool:
    """Dashboard operator, or an inbound WhatsApp message from a configured owner."""
    if inbound is None:
        return True
    return is_listed_recipient(inbound.sender, settings.owner_numbers)


def _is_send_allowed(
    settings: Settings,
    to: str,
    *,
    inbound: InboundMessage | None = None,
) -> tuple[bool, str]:
    if settings.send_policy == "dry_run":
        return False, "dry_run"
    if settings.send_policy == "allow_all":
        return True, "allow_all"
    if is_listed_recipient(to, settings.allowed_recipients):
        return True, "allowlist"
    if settings.send_policy == "owner":
        if _is_owner_session(settings, inbound):
            return True, "owner"
        if inbound is not None and recipients_match(inbound.sender, to):
            return True, "reply_to_sender"
        if (
            inbound is not None
            and inbound.is_group
            and inbound.chat
            and recipients_match(inbound.chat, to)
        ):
            return True, "reply_to_group_chat"
        return False, "recipient_not_allowed_for_non_owner"
    return False, "recipient_not_allowlisted"


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


def _requester_jid(ctx: RunContextWrapper[RuntimeContext]) -> str | None:
    inbound = ctx.context.inbound
    if inbound is None:
        return None
    sender = inbound.sender.strip()
    return sender or None


def _mem0_user_id(ctx: RunContextWrapper[RuntimeContext]) -> str | None:
    """Default Mem0 user id: sender (person), not group chat JID."""
    inbound = ctx.context.inbound
    if inbound is None:
        return None
    uid = inbound_memory_contact_id(inbound).strip()
    return uid or None


def _mem0_user_ids(ctx: RunContextWrapper[RuntimeContext]) -> list[str]:
    inbound = ctx.context.inbound
    if inbound is None:
        return []
    return inbound_memory_user_ids(inbound)


def _maybe_auto_track_outbound(
    ctx: RunContextWrapper[RuntimeContext], *, to: str, send_result: dict[str, Any]
) -> None:
    inbound = ctx.context.inbound
    if inbound is None or not _is_owner_session(ctx.context.settings, inbound):
        return
    destination = to.strip()
    if not destination or recipients_match(inbound.sender, destination):
        return
    chat_jid = destination
    if inbound.is_group and inbound.chat and recipients_match(inbound.chat, destination):
        chat_jid = inbound.chat.strip()
    expires_at = ctx.context.memory.outbound_expires_at(
        days=ctx.context.settings.outbound_task_expiry_days
    )
    sent_message_id: str | None = None
    raw = send_result.get("result") if isinstance(send_result.get("result"), dict) else None
    if raw:
        sent_message_id = raw.get("message_id") or raw.get("id")
    ctx.context.memory.create_outbound_task(
        owner_jid=inbound.sender,
        target_jid=destination,
        chat_jid=chat_jid,
        prompt_summary=None,
        sent_message_id=str(sent_message_id) if sent_message_id else None,
        notify_owner=True,
        expires_at=expires_at,
    )


def _media_path_allowed(settings: Settings, path: str) -> tuple[bool, Path | None, str | None]:
    return media_path_allowed(settings, path)


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


@function_tool
async def list_whatsapp_groups(ctx: RunContextWrapper[RuntimeContext]) -> dict[str, Any]:
    """List WhatsApp groups this linked device has joined."""
    try:
        payload = await ctx.context.wabot.list_groups()
    except Exception as exc:
        payload = {"ok": False, "groups": [], "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "list_whatsapp_groups", payload)
    return redact(payload)


@function_tool
async def mark_whatsapp_read(
    ctx: RunContextWrapper[RuntimeContext],
    chat: str,
    message_ids: list[str],
    sender: str | None = None,
) -> dict[str, Any]:
    """Send read receipts for one or more messages (same sender per call)."""
    try:
        payload = await ctx.context.wabot.mark_read(chat, message_ids, sender=sender)
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "mark_whatsapp_read", payload)
    return redact(payload)


@function_tool
async def send_whatsapp_typing(
    ctx: RunContextWrapper[RuntimeContext], to: str, state: str = "composing"
) -> dict[str, Any]:
    """Send typing/composing presence to a chat."""
    try:
        payload = await ctx.context.wabot.send_typing(to, state=state)
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "send_whatsapp_typing", payload)
    return redact(payload)


@function_tool
async def wabot_health(ctx: RunContextWrapper[RuntimeContext]) -> dict[str, Any]:
    """Check whether the local wabot daemon and WhatsApp session are ready."""
    health = await ctx.context.wabot.health()
    payload = {
        "reachable": health.reachable,
        "logged_in": health.logged_in,
        "connected": health.connected,
        "ready": health.ready,
        "detail": health.detail,
    }
    ctx.context.memory.record_tool_event(ctx.context.run_id, "wabot_health", payload)
    return payload


def _inbound_reply_destination(inbound: InboundMessage) -> str:
    return (inbound.chat or inbound.sender).strip()


def _resolve_progress_destination(
    ctx: RuntimeContext, to: str | None
) -> tuple[str | None, str | None]:
    if to and to.strip():
        return to.strip(), None
    inbound = ctx.inbound
    if inbound is None:
        return None, "no_inbound_chat_set_to_parameter"
    destination = _inbound_reply_destination(inbound)
    if not destination:
        return None, "no_destination"
    return destination, None


async def _send_progress_whatsapp(
    ctx: RuntimeContext,
    text: str,
    *,
    to: str | None = None,
    event_kind: str,
) -> dict[str, Any]:
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
    """Post a numbered plan to WhatsApp before starting multi-step work.

    Call this at the start of any task that needs 3+ tool calls or several minutes.
    `to` defaults to the inbound chat (or sender). On the dashboard, pass `to` explicitly.
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
    """Notify the user on WhatsApp that one plan step finished.

    Call after each step in a multi-step task, before starting the next step.
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
    """Send a short in-progress update on WhatsApp during long-running work.

    Use when a single step will take a while and you have no other tool output yet
    (e.g. "Still scraping page 3 of 10…").
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


@function_tool
async def send_whatsapp_text(
    ctx: RunContextWrapper[RuntimeContext], to: str, text: str
) -> dict[str, Any]:
    """Send a WhatsApp text message through wabot when the send policy allows it."""
    allowed, reason = _is_send_allowed(
        ctx.context.settings, to, inbound=ctx.context.inbound
    )
    if not allowed:
        payload = {
            "sent": False,
            "reason": reason,
            "to": mask_phone(to),
            "operator_action": (
                "Owner policy: only the configured owner (dashboard or owner WhatsApp) "
                "may message arbitrary numbers; others may only reply to their own chat."
            ),
        }
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "send_whatsapp_text.blocked", payload
        )
        ctx.context.event_log.write("send_blocked", payload)
        return payload

    health = await ctx.context.wabot.health()
    if not health.ready:
        payload = {
            "sent": False,
            "reason": "wabot_not_ready",
            "health": {
                "reachable": health.reachable,
                "logged_in": health.logged_in,
                "connected": health.connected,
                "detail": health.detail,
            },
        }
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "send_whatsapp_text.blocked", payload
        )
        return payload

    result = await ctx.context.wabot.send_text(to=to, text=text)
    ctx.context.record_sent(to)
    payload = {"sent": True, "policy": reason, "to": mask_phone(to), "result": redact(result)}
    _maybe_auto_track_outbound(ctx, to=to, send_result={"result": result})
    ctx.context.memory.record_tool_event(ctx.context.run_id, "send_whatsapp_text", payload)
    ctx.context.event_log.write("send_text", payload)
    return payload


@function_tool
async def send_whatsapp_image(
    ctx: RunContextWrapper[RuntimeContext], to: str, path: str, caption: str | None = None
) -> dict[str, Any]:
    """Send a WhatsApp image message through wabot when the send policy allows it."""
    path_allowed, safe_path, path_reason = _media_path_allowed(ctx.context.settings, path)
    if not path_allowed or safe_path is None:
        payload = {
            "sent": False,
            "reason": "media_path_not_allowed",
            "detail": path_reason,
        }
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "send_whatsapp_image.blocked", payload
        )
        return payload

    allowed, reason = _is_send_allowed(
        ctx.context.settings, to, inbound=ctx.context.inbound
    )
    if not allowed:
        payload = {
            "sent": False,
            "reason": reason,
            "to": mask_phone(to),
            "path": str(safe_path.relative_to(ctx.context.settings.media_dir.resolve())),
        }
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "send_whatsapp_image.blocked", payload
        )
        return payload

    health = await ctx.context.wabot.health()
    if not health.ready:
        payload = {"sent": False, "reason": "wabot_not_ready", "ready": health.ready}
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "send_whatsapp_image.blocked", payload
        )
        return payload

    result = await ctx.context.wabot.send_image(to=to, path=str(safe_path), caption=caption)
    ctx.context.record_sent(to)
    payload = {"sent": True, "policy": reason, "to": mask_phone(to), "result": redact(result)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "send_whatsapp_image", payload)
    ctx.context.event_log.write("send_image", payload)
    return payload


async def _send_whatsapp_media(
    ctx: RunContextWrapper[RuntimeContext],
    *,
    tool_name: str,
    to: str,
    path: str,
    kind: str,
    caption: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    path_allowed, safe_path, path_reason = _media_path_allowed(ctx.context.settings, path)
    if not path_allowed or safe_path is None:
        payload = {"sent": False, "reason": "media_path_not_allowed", "detail": path_reason}
        ctx.context.memory.record_tool_event(ctx.context.run_id, f"{tool_name}.blocked", payload)
        return payload

    allowed, reason = _is_send_allowed(
        ctx.context.settings, to, inbound=ctx.context.inbound
    )
    if not allowed:
        payload = {
            "sent": False,
            "reason": reason,
            "to": mask_phone(to),
            "path": str(safe_path.relative_to(ctx.context.settings.media_dir.resolve())),
        }
        ctx.context.memory.record_tool_event(ctx.context.run_id, f"{tool_name}.blocked", payload)
        return payload

    health = await ctx.context.wabot.health()
    if not health.ready:
        payload = {"sent": False, "reason": "wabot_not_ready", "ready": health.ready}
        ctx.context.memory.record_tool_event(ctx.context.run_id, f"{tool_name}.blocked", payload)
        return payload

    result = await ctx.context.wabot.send_media(
        to=to,
        kind=kind,
        path=str(safe_path),
        caption=caption,
        filename=filename,
    )
    ctx.context.record_sent(to)
    payload = {
        "sent": True,
        "policy": reason,
        "to": mask_phone(to),
        "kind": kind,
        "result": redact(result),
    }
    ctx.context.memory.record_tool_event(ctx.context.run_id, tool_name, payload)
    ctx.context.event_log.write(tool_name, payload)
    return payload


async def _wabot_ready_or_block(
    ctx: RunContextWrapper[RuntimeContext], tool_name: str
) -> dict[str, Any] | None:
    health = await ctx.context.wabot.health()
    if health.ready:
        return None
    payload = {
        "ok": False,
        "reason": "wabot_not_ready",
        "ready": health.ready,
        "detail": health.detail,
    }
    ctx.context.memory.record_tool_event(ctx.context.run_id, f"{tool_name}.blocked", payload)
    return payload


async def _dry_run_block(
    ctx: RunContextWrapper[RuntimeContext], tool_name: str
) -> dict[str, Any] | None:
    if ctx.context.settings.send_policy != "dry_run":
        return None
    payload = {"ok": False, "reason": "dry_run"}
    ctx.context.memory.record_tool_event(ctx.context.run_id, f"{tool_name}.blocked", payload)
    return payload


async def _invoke_chat_state_action(
    ctx: RunContextWrapper[RuntimeContext],
    tool_name: str,
    chat: str,
    invoke: Any,
) -> dict[str, Any]:
    if blocked := await _dry_run_block(ctx, tool_name):
        return blocked
    if blocked := await _wabot_ready_or_block(ctx, tool_name):
        return blocked
    try:
        result = await invoke()
        payload = {"ok": True, "chat": mask_phone(chat), "result": redact(result)}
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, tool_name, payload)
    return payload


async def _invoke_chat_message_action(
    ctx: RunContextWrapper[RuntimeContext],
    tool_name: str,
    chat: str,
    invoke: Any,
) -> dict[str, Any]:
    ok, _, blocked = await _chat_send_or_block(ctx, tool_name, chat)
    if not ok:
        return blocked or {"ok": False}
    try:
        result = await invoke()
        payload = {"ok": True, "chat": mask_phone(chat), "result": redact(result)}
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, tool_name, payload)
    return payload


async def _chat_send_or_block(
    ctx: RunContextWrapper[RuntimeContext], tool_name: str, chat: str
) -> tuple[bool, str, dict[str, Any] | None]:
    allowed, reason = _is_send_allowed(
        ctx.context.settings, chat, inbound=ctx.context.inbound
    )
    if not allowed:
        payload = {
            "ok": False,
            "sent": False,
            "reason": reason,
            "chat": mask_phone(chat),
        }
        ctx.context.memory.record_tool_event(ctx.context.run_id, f"{tool_name}.blocked", payload)
        return False, reason, payload
    blocked = await _wabot_ready_or_block(ctx, tool_name)
    if blocked is not None:
        return False, reason, blocked
    return True, reason, None


@function_tool
async def react_whatsapp_message(
    ctx: RunContextWrapper[RuntimeContext],
    chat: str,
    message_id: str,
    reaction: str,
    sender: str | None = None,
) -> dict[str, Any]:
    """React to a WhatsApp message (emoji). Pass empty reaction to remove."""
    return await _invoke_chat_message_action(
        ctx,
        "react_whatsapp_message",
        chat,
        lambda: ctx.context.wabot.react_message(chat, message_id, reaction, sender=sender),
    )


@function_tool
async def edit_whatsapp_message(
    ctx: RunContextWrapper[RuntimeContext], chat: str, message_id: str, text: str
) -> dict[str, Any]:
    """Edit a message you sent (within WhatsApp edit window)."""
    return await _invoke_chat_message_action(
        ctx,
        "edit_whatsapp_message",
        chat,
        lambda: ctx.context.wabot.edit_message(chat, message_id, text),
    )


@function_tool
async def revoke_whatsapp_message(
    ctx: RunContextWrapper[RuntimeContext],
    chat: str,
    message_id: str,
    sender: str | None = None,
) -> dict[str, Any]:
    """Revoke (delete for everyone) a message. For others' messages in groups, pass sender."""
    return await _invoke_chat_message_action(
        ctx,
        "revoke_whatsapp_message",
        chat,
        lambda: ctx.context.wabot.revoke_message(chat, message_id, sender=sender),
    )


@function_tool
async def create_whatsapp_group(
    ctx: RunContextWrapper[RuntimeContext], name: str, participants: list[str]
) -> dict[str, Any]:
    """Create a WhatsApp group with the given name and participant phone numbers."""
    if blocked := await _dry_run_block(ctx, "create_whatsapp_group"):
        return blocked
    blocked = await _wabot_ready_or_block(ctx, "create_whatsapp_group")
    if blocked is not None:
        return blocked
    try:
        payload = await ctx.context.wabot.create_group(name, participants)
        payload = {"ok": True, "result": redact(payload)}
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "create_whatsapp_group", payload)
    return payload


@function_tool
async def get_whatsapp_group(
    ctx: RunContextWrapper[RuntimeContext], group_jid: str
) -> dict[str, Any]:
    """Get metadata and participants for a group by JID."""
    blocked = await _wabot_ready_or_block(ctx, "get_whatsapp_group")
    if blocked is not None:
        return blocked
    try:
        payload = await ctx.context.wabot.get_group(group_jid)
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "get_whatsapp_group", payload)
    return redact(payload)


@function_tool
async def get_whatsapp_group_invite(
    ctx: RunContextWrapper[RuntimeContext], group_jid: str, reset: bool = False
) -> dict[str, Any]:
    """Get (or reset) the invite link for a group you administer."""
    if blocked := await _dry_run_block(ctx, "get_whatsapp_group_invite"):
        return blocked
    blocked = await _wabot_ready_or_block(ctx, "get_whatsapp_group_invite")
    if blocked is not None:
        return blocked
    try:
        payload = await ctx.context.wabot.get_group_invite(group_jid, reset=reset)
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "get_whatsapp_group_invite", payload)
    return redact(payload)


@function_tool
async def mute_whatsapp_chat(
    ctx: RunContextWrapper[RuntimeContext],
    chat: str,
    mute: bool,
    duration_hours: int = 0,
) -> dict[str, Any]:
    """Mute or unmute a chat. duration_hours applies when mute is true (0 = forever)."""
    return await _invoke_chat_state_action(
        ctx,
        "mute_whatsapp_chat",
        chat,
        lambda: ctx.context.wabot.mute_chat(chat, mute, duration_hours=duration_hours),
    )


@function_tool
async def archive_whatsapp_chat(
    ctx: RunContextWrapper[RuntimeContext], chat: str, archive: bool
) -> dict[str, Any]:
    """Archive or unarchive a chat in WhatsApp."""
    return await _invoke_chat_state_action(
        ctx,
        "archive_whatsapp_chat",
        chat,
        lambda: ctx.context.wabot.archive_chat(chat, archive),
    )


@function_tool
async def pin_whatsapp_chat(
    ctx: RunContextWrapper[RuntimeContext], chat: str, pin: bool
) -> dict[str, Any]:
    """Pin or unpin a chat in WhatsApp."""
    return await _invoke_chat_state_action(
        ctx,
        "pin_whatsapp_chat",
        chat,
        lambda: ctx.context.wabot.pin_chat(chat, pin),
    )


@function_tool
async def join_whatsapp_group(
    ctx: RunContextWrapper[RuntimeContext], invite_link: str
) -> dict[str, Any]:
    """Join a group using a chat.whatsapp.com invite link."""
    if blocked := await _dry_run_block(ctx, "join_whatsapp_group"):
        return blocked
    blocked = await _wabot_ready_or_block(ctx, "join_whatsapp_group")
    if blocked is not None:
        return blocked
    try:
        payload = await ctx.context.wabot.join_group(invite_link)
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "join_whatsapp_group", payload)
    return redact(payload)


@function_tool
async def update_whatsapp_group(
    ctx: RunContextWrapper[RuntimeContext],
    group_jid: str,
    name: str | None = None,
    topic: str | None = None,
    announce: bool | None = None,
    locked: bool | None = None,
) -> dict[str, Any]:
    """Update group settings (name/subject, description topic, announce-only, admin-only info)."""
    if blocked := await _dry_run_block(ctx, "update_whatsapp_group"):
        return blocked
    blocked = await _wabot_ready_or_block(ctx, "update_whatsapp_group")
    if blocked is not None:
        return blocked
    if name is None and topic is None and announce is None and locked is None:
        return {"ok": False, "detail": "provide at least one of name, topic, announce, locked"}
    try:
        payload = await ctx.context.wabot.update_group(
            group_jid,
            name=name,
            topic=topic,
            announce=announce,
            locked=locked,
        )
        payload = {"ok": True, "result": redact(payload)}
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "update_whatsapp_group", payload)
    return payload


@function_tool
async def update_whatsapp_group_participants(
    ctx: RunContextWrapper[RuntimeContext],
    group_jid: str,
    participants: list[str],
    action: str = "add",
) -> dict[str, Any]:
    """Add, remove, promote, or demote group members (action: add|remove|promote|demote)."""
    if blocked := await _dry_run_block(ctx, "update_whatsapp_group_participants"):
        return blocked
    blocked = await _wabot_ready_or_block(ctx, "update_whatsapp_group_participants")
    if blocked is not None:
        return blocked
    normalized = action.strip().lower()
    if normalized not in {"add", "remove", "promote", "demote"}:
        return {"ok": False, "detail": "action must be add, remove, promote, or demote"}
    if not participants:
        return {"ok": False, "detail": "participants list is required"}
    try:
        payload = await ctx.context.wabot.update_group_participants(
            group_jid, participants, action=normalized
        )
        payload = {"ok": True, "result": redact(payload)}
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "update_whatsapp_group_participants", payload
    )
    return payload


@function_tool
async def leave_whatsapp_group(
    ctx: RunContextWrapper[RuntimeContext], group_jid: str
) -> dict[str, Any]:
    """Leave a WhatsApp group the linked device has joined."""
    if blocked := await _dry_run_block(ctx, "leave_whatsapp_group"):
        return blocked
    blocked = await _wabot_ready_or_block(ctx, "leave_whatsapp_group")
    if blocked is not None:
        return blocked
    try:
        payload = await ctx.context.wabot.leave_group(group_jid)
        payload = {"ok": True, "result": redact(payload)}
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "leave_whatsapp_group", payload)
    return payload


@function_tool
async def set_whatsapp_group_picture(
    ctx: RunContextWrapper[RuntimeContext],
    group_jid: str,
    image_path: str | None = None,
    remove: bool = False,
) -> dict[str, Any]:
    """Set or remove a WhatsApp group profile photo (JPEG in WABOT_AGENT_MEDIA_DIR)."""
    if blocked := await _dry_run_block(ctx, "set_whatsapp_group_picture"):
        return blocked
    blocked = await _wabot_ready_or_block(ctx, "set_whatsapp_group_picture")
    if blocked is not None:
        return blocked
    if remove:
        try:
            payload = await ctx.context.wabot.remove_group_picture(group_jid)
            payload = {"ok": True, "result": redact(payload)}
        except Exception as exc:
            payload = {"ok": False, "detail": str(exc)}
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "set_whatsapp_group_picture", payload
        )
        return payload
    if not image_path:
        return {"ok": False, "detail": "image_path is required unless remove=true"}
    path_allowed, safe_path, path_reason = _media_path_allowed(ctx.context.settings, image_path)
    if not path_allowed or safe_path is None:
        payload = {"ok": False, "reason": "media_path_not_allowed", "detail": path_reason}
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "set_whatsapp_group_picture.blocked", payload
        )
        return payload
    try:
        payload = await ctx.context.wabot.set_group_picture(group_jid, str(safe_path))
        payload = {"ok": True, "result": redact(payload)}
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "set_whatsapp_group_picture", payload
    )
    return payload


@function_tool
async def get_whatsapp_user_info(
    ctx: RunContextWrapper[RuntimeContext], jid: str
) -> dict[str, Any]:
    """Get WhatsApp profile metadata (status, picture id, verified name) for a JID or phone."""
    blocked = await _wabot_ready_or_block(ctx, "get_whatsapp_user_info")
    if blocked is not None:
        return blocked
    try:
        payload = await ctx.context.wabot.get_user_info(jid)
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "get_whatsapp_user_info", payload)
    return redact(payload)


@function_tool
async def download_whatsapp_profile_picture(
    ctx: RunContextWrapper[RuntimeContext],
    jid: str,
    preview: bool = False,
    filename: str | None = None,
) -> dict[str, Any]:
    """Download a contact or group profile picture to WABOT_AGENT_MEDIA_DIR/avatars/."""
    blocked = await _wabot_ready_or_block(ctx, "download_whatsapp_profile_picture")
    if blocked is not None:
        return blocked
    try:
        resp = await ctx.context.wabot.get_user_picture(jid, preview=preview)
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "download_whatsapp_profile_picture", payload
        )
        return payload

    if resp.status_code == 404:
        payload = {"ok": False, "detail": "no profile picture"}
    elif resp.status_code >= 400:
        payload = {"ok": False, "detail": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    elif "application/json" in (resp.headers.get("content-type") or ""):
        payload = {"ok": True, "unchanged": True, "result": resp.json()}
    else:
        avatars = ctx.context.settings.media_dir / "avatars"
        avatars.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in jid)[:120]
        ext = ".jpg"
        if "png" in (resp.headers.get("content-type") or ""):
            ext = ".png"
        out_name = filename or f"{safe}{ext}"
        out_path = avatars / out_name
        out_path.write_bytes(resp.content)
        payload = {
            "ok": True,
            "path": str(out_path),
            "picture_id": resp.headers.get("X-Picture-ID"),
            "preview": preview,
        }
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "download_whatsapp_profile_picture", payload
    )
    return redact(payload)


@function_tool
async def download_whatsapp_media(
    ctx: RunContextWrapper[RuntimeContext],
    chat: str,
    message_id: str,
    filename: str | None = None,
) -> dict[str, Any]:
    """Download inbound WhatsApp media to WABOT_AGENT_MEDIA_DIR (recent messages only)."""
    downloaded = await download_media_message(
        ctx.context.wabot,
        chat,
        message_id,
        ctx.context.settings,
        filename=filename,
    )
    if not downloaded.ok or downloaded.path is None:
        payload = {"ok": False, "detail": downloaded.detail}
    else:
        payload = {
            "ok": True,
            "path": str(downloaded.path),
            "bytes": downloaded.bytes,
            "media_kind": downloaded.media_kind,
            "mime": downloaded.mime,
            "chat": chat,
            "message_id": message_id,
        }
    ctx.context.memory.record_tool_event(ctx.context.run_id, "download_whatsapp_media", payload)
    if payload.get("ok"):
        redacted = redact({k: v for k, v in payload.items() if k != "path"})
        redacted["path"] = payload["path"]
        return redacted
    return redact(payload)


@function_tool
async def process_vps_file(
    ctx: RunContextWrapper[RuntimeContext], path: str
) -> dict[str, Any]:
    """Read and summarize a file on the VPS (under media/ or data/)."""
    allowed, safe_path, reason = workspace_path_allowed(ctx.context.settings, path)
    if not allowed or safe_path is None:
        payload = {"ok": False, "detail": reason}
    else:
        payload = process_file_at_path(
            safe_path,
            excerpt_limit=ctx.context.settings.file_excerpt_limit,
            max_bytes=ctx.context.settings.file_max_process_bytes,
            settings=ctx.context.settings,
            is_owner=_is_owner_session(ctx.context.settings, ctx.context.inbound),
        )
    ctx.context.memory.record_tool_event(ctx.context.run_id, "process_vps_file", payload)
    return redact(payload)


@function_tool
async def process_whatsapp_attachment(
    ctx: RunContextWrapper[RuntimeContext],
    chat: str,
    message_id: str,
    filename: str | None = None,
) -> dict[str, Any]:
    """Download a WhatsApp attachment and extract text/metadata on the VPS."""
    downloaded = await download_media_message(
        ctx.context.wabot,
        chat,
        message_id,
        ctx.context.settings,
        filename=filename,
    )
    if not downloaded.ok or downloaded.path is None:
        payload = {"ok": False, "detail": downloaded.detail}
    else:
        payload = process_file_at_path(
            downloaded.path,
            mime=downloaded.mime,
            excerpt_limit=ctx.context.settings.file_excerpt_limit,
            max_bytes=ctx.context.settings.file_max_process_bytes,
            settings=ctx.context.settings,
            is_owner=_is_owner_session(ctx.context.settings, ctx.context.inbound),
        )
        payload["download_path"] = str(downloaded.path)
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "process_whatsapp_attachment", payload
    )
    return redact(payload)


@function_tool
async def send_whatsapp_file(
    ctx: RunContextWrapper[RuntimeContext],
    to: str,
    path: str,
    caption: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Send any file from the VPS media dir (image, video, audio, or document)."""
    path_allowed, safe_path, path_reason = _media_path_allowed(ctx.context.settings, path)
    if not path_allowed or safe_path is None:
        payload = {"sent": False, "reason": "media_path_not_allowed", "detail": path_reason}
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "send_whatsapp_file.blocked", payload
        )
        return payload

    kind = whatsapp_send_kind_for_path(safe_path)
    if kind == "image":
        return await send_whatsapp_image(ctx, to=to, path=path, caption=caption)
    if kind == "video":
        return await send_whatsapp_video(ctx, to=to, path=path, caption=caption)
    if kind == "audio":
        return await send_whatsapp_audio(ctx, to=to, path=path)
    return await send_whatsapp_document(
        ctx, to=to, path=path, caption=caption, filename=filename or safe_path.name
    )


@function_tool
async def send_whatsapp_document(
    ctx: RunContextWrapper[RuntimeContext],
    to: str,
    path: str,
    caption: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Send a WhatsApp document through wabot when the send policy allows it."""
    return await _send_whatsapp_media(
        ctx,
        tool_name="send_whatsapp_document",
        to=to,
        path=path,
        kind="document",
        caption=caption,
        filename=filename,
    )


@function_tool
async def send_whatsapp_audio(
    ctx: RunContextWrapper[RuntimeContext], to: str, path: str
) -> dict[str, Any]:
    """Send a WhatsApp voice/audio note through wabot when the send policy allows it."""
    return await _send_whatsapp_media(
        ctx, tool_name="send_whatsapp_audio", to=to, path=path, kind="audio"
    )


@function_tool
async def send_whatsapp_video(
    ctx: RunContextWrapper[RuntimeContext],
    to: str,
    path: str,
    caption: str | None = None,
) -> dict[str, Any]:
    """Send a WhatsApp video through wabot when the send policy allows it."""
    return await _send_whatsapp_media(
        ctx,
        tool_name="send_whatsapp_video",
        to=to,
        path=path,
        kind="video",
        caption=caption,
    )


@function_tool
async def recall_contact_memory(
    ctx: RunContextWrapper[RuntimeContext], contact: str
) -> dict[str, Any]:
    """Recall durable non-secret memory for a WhatsApp contact. Call every inbound turn."""
    payload = ctx.context.memory.recall_contact(contact)
    ctx.context.memory.record_tool_event(ctx.context.run_id, "recall_contact_memory", payload)
    return redact(payload)


@function_tool
async def remember_contact_fact(
    ctx: RunContextWrapper[RuntimeContext], contact: str, key: str, value: str
) -> dict[str, Any]:
    """Store a durable, non-secret key/value fact. Call when the message contains important info."""
    payload = ctx.context.memory.remember_contact_fact(
        contact=contact, key=key, value=value, source=ctx.context.run_id
    )
    ctx.context.memory.record_tool_event(ctx.context.run_id, "remember_contact_fact", payload)
    return redact(payload)


@function_tool
async def recall_agent_notes(ctx: RunContextWrapper[RuntimeContext]) -> list[dict[str, Any]]:
    """Recall durable non-secret operating notes for this agent."""
    payload = ctx.context.memory.agent_notes()
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "recall_agent_notes", {"count": len(payload)}
    )
    return redact(payload)


@function_tool
async def remember_agent_note(
    ctx: RunContextWrapper[RuntimeContext], key: str, value: str
) -> dict[str, Any]:
    """Store a durable, non-secret operating note for this agent."""
    payload = ctx.context.memory.remember_agent_note(key=key, value=value)
    ctx.context.memory.record_tool_event(ctx.context.run_id, "remember_agent_note", payload)
    return redact(payload)


@function_tool
async def list_local_skills(ctx: RunContextWrapper[RuntimeContext]) -> list[dict[str, str]]:
    """List local skill cards the agent can consult for operating guidance."""
    cards = list_skills(ctx.context.settings.skills_dir)
    payload = [
        {"name": card.name, "description": card.description, "path": str(card.path)}
        for card in cards
    ]
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "list_local_skills", {"count": len(payload)}
    )
    return payload


@function_tool
async def read_local_skill(ctx: RunContextWrapper[RuntimeContext], name: str) -> str:
    """Read one local skill by folder name."""
    text = read_skill(ctx.context.settings.skills_dir, name)
    ctx.context.memory.record_tool_event(ctx.context.run_id, "read_local_skill", {"name": name})
    return text[:12000]


@function_tool
async def search_web(
    ctx: RunContextWrapper[RuntimeContext],
    query: str,
    max_results: int = 8,
) -> dict[str, Any]:
    """Search the public web (DuckDuckGo). Use before fetch_url_to_media when you need a URL."""
    results, error = await duckduckgo_search(
        ctx.context.settings,
        query,
        max_results=max_results,
        images=False,
    )
    payload: dict[str, Any] = {
        "ok": error is None,
        "query": query,
        "results": [
            {"title": r.title, "url": r.url, "snippet": r.snippet, "kind": r.kind}
            for r in results
        ],
    }
    if error:
        payload["detail"] = error
    ctx.context.memory.record_tool_event(ctx.context.run_id, "search_web", payload)
    return redact(payload)


@function_tool
async def search_images(
    ctx: RunContextWrapper[RuntimeContext],
    query: str,
    max_results: int = 6,
) -> dict[str, Any]:
    """Search for image URLs on the web. Use for logos/photos, then fetch_url_to_media + send."""
    results, error = await duckduckgo_search(
        ctx.context.settings,
        query,
        max_results=max_results,
        images=True,
    )
    payload: dict[str, Any] = {
        "ok": error is None,
        "query": query,
        "results": [{"title": r.title, "url": r.url, "kind": "image"} for r in results],
    }
    if error:
        payload["detail"] = error
    ctx.context.memory.record_tool_event(ctx.context.run_id, "search_images", payload)
    return redact(payload)


@function_tool
async def fetch_url_to_media(
    ctx: RunContextWrapper[RuntimeContext],
    url: str,
    filename: str | None = None,
    prefer_page_image: bool = False,
) -> dict[str, Any]:
    """Download a public http(s) URL into the VPS media directory; then send_whatsapp_file(path).

    Set prefer_page_image=True for homepages (uses og:image when the URL returns HTML).
    """
    fetched = await download_url_to_media(
        ctx.context.settings,
        url,
        filename=filename,
        prefer_page_image=prefer_page_image,
    )
    if not fetched.ok or fetched.path is None:
        payload = {"ok": False, "detail": fetched.detail, "url": fetched.url}
    else:
        payload = {
            "ok": True,
            "path": str(fetched.path),
            "bytes": fetched.bytes,
            "mime": fetched.mime,
            "url": fetched.url,
            "send_hint": "Call send_whatsapp_file or send_whatsapp_image with this path.",
        }
    ctx.context.memory.record_tool_event(ctx.context.run_id, "fetch_url_to_media", payload)
    if payload.get("ok"):
        redacted = redact({k: v for k, v in payload.items() if k != "path"})
        redacted["path"] = payload["path"]
        return redacted
    return redact(payload)


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


@function_tool
async def web_research_health(
    ctx: RunContextWrapper[RuntimeContext],
) -> dict[str, Any]:
    """Check whether the Firecrawl web-agent sidecar (Express /v1/run) is reachable."""
    payload = await web_agent_health(ctx.context.settings)
    ctx.context.memory.record_tool_event(ctx.context.run_id, "web_research_health", payload)
    return redact(payload)


@function_tool
async def start_web_research(
    ctx: RunContextWrapper[RuntimeContext],
    prompt: str,
    title: str | None = None,
    output_format: str = "csv",
    output_schema_json: str | None = None,
) -> dict[str, Any]:
    """Start a long-running Firecrawl web-agent research job (results sent on WhatsApp when done).

    Use for structured lead lists, multi-page scraping, and deep web research. Pass the full
    research brief in prompt (targets, exclusions, columns, output headers). output_format:
    csv | markdown | json. For json, pass output_schema_json as a JSON Schema string.
    """
    requester = _requester_jid(ctx)
    if requester is None:
        payload = {"created": False, "reason": "no_inbound_requester"}
        ctx.context.memory.record_tool_event(ctx.context.run_id, "start_web_research", payload)
        return payload

    if not ctx.context.settings.web_agent_enabled:
        payload = {"created": False, "reason": "web_agent_disabled"}
        ctx.context.memory.record_tool_event(ctx.context.run_id, "start_web_research", payload)
        return payload

    if ctx.context.settings.web_agent_owner_only and not _is_owner_session(
        ctx.context.settings, ctx.context.inbound
    ):
        payload = {"created": False, "reason": "owner_only"}
        ctx.context.memory.record_tool_event(ctx.context.run_id, "start_web_research", payload)
        return payload

    pending = ctx.context.memory.count_web_research_jobs(
        requester_jid=requester, status="pending"
    )
    running = ctx.context.memory.count_web_research_jobs(
        requester_jid=requester, status="running"
    )
    cap = ctx.context.settings.web_agent_max_pending_per_contact
    if pending + running >= cap:
        payload = {
            "created": False,
            "reason": "pending_limit",
            "pending": pending,
            "running": running,
            "limit": cap,
        }
        ctx.context.memory.record_tool_event(ctx.context.run_id, "start_web_research", payload)
        return payload

    fmt = output_format.strip().lower()
    if fmt not in {"csv", "markdown", "json"}:
        fmt = "markdown"

    payload = ctx.context.memory.create_web_research_job(
        requester_jid=requester,
        prompt=prompt.strip(),
        title=title.strip() if title else None,
        output_format=fmt,
        schema_json=output_schema_json,
    )
    payload["message"] = (
        "Research job queued. You will receive a WhatsApp summary and file when it completes."
    )
    ctx.context.memory.record_tool_event(ctx.context.run_id, "start_web_research", payload)
    ctx.context.event_log.write("web_research_queued", redact(payload))
    return redact(payload)


@function_tool
async def get_web_research_status(
    ctx: RunContextWrapper[RuntimeContext],
    job_id: str,
) -> dict[str, Any]:
    """Get status, preview, and result path for a web research job."""
    job = ctx.context.memory.get_web_research_job(job_id)
    requester = _requester_jid(ctx)
    if job is None:
        payload = {"found": False, "id": job_id}
    elif requester and job.get("requester_jid") != requester:
        payload = {"found": False, "id": job_id, "reason": "not_your_job"}
    else:
        payload = {"found": True, **job}
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "get_web_research_status", {"id": job_id, "found": job is not None}
    )
    return redact(payload)


@function_tool
async def list_web_research_jobs(
    ctx: RunContextWrapper[RuntimeContext],
    status: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """List web research jobs for the current requester."""
    requester = _requester_jid(ctx)
    rows = ctx.context.memory.list_web_research_jobs(
        requester_jid=requester,
        status=status,
        limit=limit,
    )
    payload = {"count": len(rows), "jobs": rows}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "list_web_research_jobs", payload)
    return redact(payload)


@function_tool
async def cancel_web_research(
    ctx: RunContextWrapper[RuntimeContext],
    job_id: str,
) -> dict[str, Any]:
    """Cancel a pending web research job."""
    requester = _requester_jid(ctx)
    payload = ctx.context.memory.cancel_web_research_job(
        job_id, requester_jid=requester
    )
    ctx.context.memory.record_tool_event(ctx.context.run_id, "cancel_web_research", payload)
    return redact(payload)


@function_tool
async def mem0_status(ctx: RunContextWrapper[RuntimeContext]) -> dict[str, Any]:
    """Report whether Mem0 long-term memory is enabled and configured."""
    settings = ctx.context.settings
    payload = {
        "enabled": mem0_enabled(settings),
        "configured": settings.mem0_enabled,
        "use_platform": settings.mem0_use_platform,
        "path": str(settings.mem0_path),
        "collection": settings.mem0_collection,
        "auto_capture": settings.mem0_auto_capture,
        "inject_on_run": settings.mem0_inject_on_run,
    }
    ctx.context.memory.record_tool_event(ctx.context.run_id, "mem0_status", payload)
    return payload


@function_tool
async def search_mem0_memories(
    ctx: RunContextWrapper[RuntimeContext],
    query: str,
    user_id: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Search Mem0 memories. Defaults to sender (searches person + group ids in groups)."""
    if not mem0_enabled(ctx.context.settings):
        payload = {"ok": False, "reason": "mem0_disabled", "results": []}
    else:
        ids = [user_id.strip()] if user_id and user_id.strip() else _mem0_user_ids(ctx)
        if not ids:
            payload = {"ok": False, "reason": "no_user_id", "results": []}
        else:
            merged: list[dict[str, str]] = []
            seen: set[str] = set()
            for uid in ids:
                part = search_memories_sync(
                    ctx.context.settings,
                    user_id=uid,
                    query=query,
                    top_k=top_k,
                )
                if not part.get("ok"):
                    continue
                for row in part.get("results") or []:
                    text = str(row.get("memory") or "").strip()
                    if text and text not in seen:
                        seen.add(text)
                        merged.append(row)
            payload = {"ok": True, "count": len(merged), "results": merged[:top_k]}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "search_mem0_memories", payload)
    return redact(payload)


@function_tool
async def add_mem0_memory(
    ctx: RunContextWrapper[RuntimeContext],
    text: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Store a durable fact in Mem0 before final reply when something important was said."""
    if not mem0_enabled(ctx.context.settings):
        payload = {"ok": False, "reason": "mem0_disabled"}
    else:
        uid = (user_id or _mem0_user_id(ctx) or "").strip()
        if not uid:
            payload = {"ok": False, "reason": "no_user_id"}
        elif looks_sensitive(text):
            payload = {"ok": False, "reason": "sensitive_content"}
        else:
            payload = add_memory_sync(
                ctx.context.settings,
                user_id=uid,
                messages=[{"role": "user", "content": text.strip()}],
                metadata={"source": ctx.context.run_id},
            )
    ctx.context.memory.record_tool_event(ctx.context.run_id, "add_mem0_memory", payload)
    return redact(payload)


def core_tools() -> list[Any]:
    return [
        wabot_health,
        list_whatsapp_inbound_messages,
        get_last_whatsapp_inbound_message,
        lookup_whatsapp_contacts,
        list_whatsapp_groups,
        mark_whatsapp_read,
        send_whatsapp_typing,
        send_whatsapp_text,
        send_whatsapp_image,
        download_whatsapp_media,
        process_vps_file,
        process_whatsapp_attachment,
        search_web,
        search_images,
        fetch_url_to_media,
        send_whatsapp_file,
        send_whatsapp_document,
        send_whatsapp_audio,
        send_whatsapp_video,
        react_whatsapp_message,
        edit_whatsapp_message,
        revoke_whatsapp_message,
        create_whatsapp_group,
        get_whatsapp_group,
        get_whatsapp_group_invite,
        join_whatsapp_group,
        update_whatsapp_group,
        update_whatsapp_group_participants,
        leave_whatsapp_group,
        set_whatsapp_group_picture,
        mute_whatsapp_chat,
        archive_whatsapp_chat,
        pin_whatsapp_chat,
        get_whatsapp_user_info,
        download_whatsapp_profile_picture,
        recall_contact_memory,
        remember_contact_fact,
        recall_agent_notes,
        remember_agent_note,
        list_local_skills,
        read_local_skill,
        create_reminder,
        list_reminders,
        cancel_reminder,
        track_outbound_conversation,
        get_outbound_task_status,
        list_outbound_tasks,
        web_research_health,
        start_web_research,
        get_web_research_status,
        list_web_research_jobs,
        cancel_web_research,
        send_task_plan,
        report_task_step_complete,
        send_task_progress,
        mem0_status,
        search_mem0_memories,
        add_mem0_memory,
    ]
