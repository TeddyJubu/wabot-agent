from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents import RunContextWrapper, function_tool

from .config import Settings
from .events import EventLog
from .memory import InboundMessage, MemoryStore
from .redaction import mask_phone, redact
from .skills import list_skills, read_skill
from .wabot import WabotClient


@dataclass
class RuntimeContext:
    settings: Settings
    memory: MemoryStore
    wabot: WabotClient
    event_log: EventLog
    run_id: str
    inbound: InboundMessage | None = None


def _is_send_allowed(settings: Settings, to: str) -> tuple[bool, str]:
    if settings.send_policy == "dry_run":
        return False, "dry_run"
    if settings.send_policy == "allow_all":
        return True, "allow_all"
    if to in settings.allowed_recipients:
        return True, "allowlist"
    return False, "recipient_not_allowlisted"


def _media_path_allowed(settings: Settings, path: str) -> tuple[bool, Path | None, str | None]:
    try:
        media_root = settings.media_dir.resolve()
        candidate = Path(path).expanduser().resolve()
    except OSError as exc:
        return False, None, str(exc)
    if media_root not in candidate.parents and candidate != media_root:
        return False, None, f"Media files must live under {settings.media_dir}."
    if not candidate.exists() or not candidate.is_file():
        return False, None, "Media file does not exist."
    return True, candidate, None


def _safe_media_segment(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._@-" else "_" for ch in value)
    return cleaned[:120] or "unknown"


def _filename_from_content_disposition(header: str) -> str | None:
    if not header:
        return None
    marker = 'filename="'
    if marker in header:
        start = header.index(marker) + len(marker)
        end = header.find('"', start)
        if end > start:
            return header[start:end]
    return None


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


@function_tool
async def send_whatsapp_text(
    ctx: RunContextWrapper[RuntimeContext], to: str, text: str
) -> dict[str, Any]:
    """Send a WhatsApp text message through wabot when the send policy allows it."""
    allowed, reason = _is_send_allowed(ctx.context.settings, to)
    if not allowed:
        payload = {
            "sent": False,
            "reason": reason,
            "to": mask_phone(to),
            "operator_action": (
                "Set WABOT_AGENT_SEND_POLICY=allowlist and add the number to "
                "WABOT_AGENT_ALLOWED_RECIPIENTS, or deliberately use allow_all."
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
    payload = {"sent": True, "policy": reason, "to": mask_phone(to), "result": redact(result)}
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

    allowed, reason = _is_send_allowed(ctx.context.settings, to)
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

    allowed, reason = _is_send_allowed(ctx.context.settings, to)
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
    allowed, reason = _is_send_allowed(ctx.context.settings, chat)
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
async def download_whatsapp_media(
    ctx: RunContextWrapper[RuntimeContext],
    chat: str,
    message_id: str,
    filename: str | None = None,
) -> dict[str, Any]:
    """Download inbound WhatsApp media to WABOT_AGENT_MEDIA_DIR (recent messages only)."""
    try:
        resp = await ctx.context.wabot.download_media(chat=chat, message_id=message_id)
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "download_whatsapp_media", payload
        )
        return payload

    if resp.status_code == 404:
        payload = {
            "ok": False,
            "detail": (
                "Media not in wabot cache. Only recent inbound media can be downloaded; "
                "ensure the message was received while wabot was running."
            ),
        }
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "download_whatsapp_media", payload
        )
        return payload
    if resp.status_code >= 400:
        payload = {
            "ok": False,
            "detail": f"wabot returned HTTP {resp.status_code}: {resp.text[:200]}",
        }
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "download_whatsapp_media", payload
        )
        return payload

    media_kind = resp.headers.get("X-Media-Kind", "media")
    suggested = filename or _filename_from_content_disposition(
        resp.headers.get("Content-Disposition", "")
    )
    if not suggested:
        ext = ".bin"
        mime = resp.headers.get("Content-Type", "")
        if "image/png" in mime:
            ext = ".png"
        elif "image/" in mime:
            ext = ".jpg"
        elif "video/" in mime:
            ext = ".mp4"
        elif "audio/" in mime:
            ext = ".ogg"
        elif "pdf" in mime:
            ext = ".pdf"
        suggested = f"{_safe_media_segment(message_id)}{ext}"

    dest_dir = (
        ctx.context.settings.media_dir.resolve()
        / "inbound"
        / _safe_media_segment(chat)
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / _safe_media_segment(suggested)
    dest_path.write_bytes(resp.content)

    payload = {
        "ok": True,
        "path": str(dest_path),
        "bytes": len(resp.content),
        "media_kind": media_kind,
        "chat": chat,
        "message_id": message_id,
    }
    ctx.context.memory.record_tool_event(ctx.context.run_id, "download_whatsapp_media", payload)
    redacted = redact({k: v for k, v in payload.items() if k != "path"})
    redacted["path"] = payload["path"]
    return redacted


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
    """Recall durable non-secret memory for a WhatsApp contact."""
    payload = ctx.context.memory.recall_contact(contact)
    ctx.context.memory.record_tool_event(ctx.context.run_id, "recall_contact_memory", payload)
    return redact(payload)


@function_tool
async def remember_contact_fact(
    ctx: RunContextWrapper[RuntimeContext], contact: str, key: str, value: str
) -> dict[str, Any]:
    """Store a durable, non-secret fact about a contact."""
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
        mute_whatsapp_chat,
        archive_whatsapp_chat,
        pin_whatsapp_chat,
        recall_contact_memory,
        remember_contact_fact,
        recall_agent_notes,
        remember_agent_note,
        list_local_skills,
        read_local_skill,
    ]
