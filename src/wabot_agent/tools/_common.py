from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents import RunContextWrapper

from ..config import Settings
from ..events import EventLog
from ..media_paths import media_path_allowed
from ..memory import (
    InboundMessage,
    MemoryStore,
    inbound_memory_contact_id,
    inbound_memory_user_ids,
)
from ..recipients import is_listed_recipient, is_owner_inbound, recipients_match
from ..redaction import mask_phone, redact
from ..wabot import WabotClient


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
    return is_owner_inbound(settings, inbound)


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


def _media_path_allowed(settings: Settings, path: str) -> tuple[bool, Path | None, str | None]:
    return media_path_allowed(settings, path)


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


async def _apply_send_policy_gate(
    ctx: RunContextWrapper[RuntimeContext],
    tool_name: str,
    to: str,
    *,
    media_path: str | None = None,
) -> tuple[Path | None, str, dict[str, Any] | None]:
    """Single fail-closed gate for every WhatsApp send tool.

    Runs the policy/health sequence in this order:
      1. ``_media_path_allowed`` — only when ``media_path`` is supplied.
      2. ``_is_send_allowed`` (send-policy chokepoint per CLAUDE.md / MASTER §3).
      3. ``wabot.health()`` readiness.

    Returns ``(safe_path, allow_reason, None)`` when every gate passes. The
    caller dispatches to the appropriate ``wabot.send_*`` method and builds
    its own success payload (text vs media payloads diverge intentionally).

    Returns ``(None, "", block_payload)`` when any gate blocks. The helper has
    already recorded the tool event (and the ``send_blocked`` log entry for
    the text branch); the caller MUST return ``block_payload`` directly.

    Centralising this boundary means new send tools cannot accidentally skip
    a gate by copying boilerplate that drifts. See QW-3 in
    ``MASTER-architecture-debt-testing.md``.
    """
    safe_path: Path | None = None
    is_text = media_path is None

    if media_path is not None:
        path_allowed, safe_path, path_reason = _media_path_allowed(
            ctx.context.settings, media_path
        )
        if not path_allowed or safe_path is None:
            payload = {
                "sent": False,
                "reason": "media_path_not_allowed",
                "detail": path_reason,
            }
            ctx.context.memory.record_tool_event(
                ctx.context.run_id, f"{tool_name}.blocked", payload
            )
            return None, "", payload

    allowed, reason = _is_send_allowed(
        ctx.context.settings, to, inbound=ctx.context.inbound
    )
    if not allowed:
        payload: dict[str, Any] = {
            "sent": False,
            "reason": reason,
            "to": mask_phone(to),
        }
        if safe_path is not None:
            payload["path"] = str(
                safe_path.relative_to(ctx.context.settings.media_dir.resolve())
            )
        if is_text:
            payload["operator_action"] = (
                "Owner policy: only the configured owner (dashboard or owner WhatsApp) "
                "may message arbitrary numbers; others may only reply to their own chat."
            )
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, f"{tool_name}.blocked", payload
        )
        if is_text:
            ctx.context.event_log.write("send_blocked", payload)
        return None, "", payload

    health = await ctx.context.wabot.health()
    if not health.ready:
        if is_text:
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
        else:
            payload = {
                "sent": False,
                "reason": "wabot_not_ready",
                "ready": health.ready,
            }
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, f"{tool_name}.blocked", payload
        )
        return None, "", payload

    return safe_path, reason, None


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
    """Shared fail-closed media send gate (QW-3 single implementation)."""
    safe_path, reason, block = await _apply_send_policy_gate(
        ctx, tool_name, to, media_path=path
    )
    if block is not None:
        return block
    assert safe_path is not None

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


def _owner_progress_allowed(ctx: RuntimeContext) -> bool:
    return _is_owner_session(ctx.settings, ctx.inbound)


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
