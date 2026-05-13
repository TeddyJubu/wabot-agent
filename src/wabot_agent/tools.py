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
        return False, None, f"Images must live under {settings.media_dir}."
    if not candidate.exists() or not candidate.is_file():
        return False, None, "Image file does not exist."
    return True, candidate, None


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
            "reason": "image_path_not_allowed",
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
        send_whatsapp_text,
        send_whatsapp_image,
        recall_contact_memory,
        remember_contact_fact,
        recall_agent_notes,
        remember_agent_note,
        list_local_skills,
        read_local_skill,
    ]
