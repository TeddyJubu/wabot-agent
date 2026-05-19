from __future__ import annotations

from typing import Any

from .agent import AgentRunResult
from .config import Settings
from .memory import InboundMessage, inbound_chat_session_id
from .output_sanitize import strip_model_thinking
from .recipients import recipients_match
from .redaction import mask_phone, redact
from .tools import _is_send_allowed
from .wabot import WabotClient, WabotError


def inbound_reply_destination(inbound: InboundMessage) -> str:
    return (inbound.chat or inbound.sender).strip()


def inbound_session_id(inbound: InboundMessage) -> str:
    return inbound_chat_session_id(inbound)


def agent_already_replied_to(result: AgentRunResult, destination: str) -> bool:
    return any(recipients_match(destination, sent_to) for sent_to in result.sent_destinations)


async def deliver_auto_reply(
    *,
    settings: Settings,
    wabot: WabotClient,
    inbound: InboundMessage,
    result: AgentRunResult,
) -> dict[str, Any]:
    """Send the agent's final output to the inbound chat when enabled."""
    if not settings.auto_reply_enabled:
        return {"sent": False, "reason": "disabled"}
    if inbound.is_group and not settings.group_auto_reply_enabled:
        return {"sent": False, "reason": "group_auto_reply_disabled"}

    destination = inbound_reply_destination(inbound)
    if not destination:
        return {"sent": False, "reason": "no_destination"}

    text = strip_model_thinking(result.final_output or "")
    if not text:
        return {"sent": False, "reason": "empty_output"}

    if agent_already_replied_to(result, destination):
        return {"sent": False, "reason": "already_sent_by_agent"}

    allowed, policy = _is_send_allowed(settings, destination, inbound=inbound)
    if not allowed:
        return {"sent": False, "reason": policy, "to": mask_phone(destination)}

    health = await wabot.health()
    if not health.ready:
        return {
            "sent": False,
            "reason": "wabot_not_ready",
            "health": {
                "reachable": health.reachable,
                "logged_in": health.logged_in,
                "connected": health.connected,
                "detail": health.detail,
            },
        }

    try:
        send_result = await wabot.send_text(to=destination, text=text)
    except WabotError as exc:
        return {"sent": False, "reason": "send_failed", "detail": redact(str(exc))}

    return {
        "sent": True,
        "policy": policy,
        "to": mask_phone(destination),
        "result": redact(send_result),
    }


async def deliver_inbound_error_reply(
    *,
    settings: Settings,
    wabot: WabotClient,
    inbound: InboundMessage,
    error: str,
) -> dict[str, Any]:
    """Send a short fallback when the agent run fails so the user is not left silent."""
    if not settings.auto_reply_enabled:
        return {"sent": False, "reason": "disabled"}
    if inbound.is_group and not settings.group_auto_reply_enabled:
        return {"sent": False, "reason": "group_auto_reply_disabled"}

    destination = inbound_reply_destination(inbound)
    if not destination:
        return {"sent": False, "reason": "no_destination"}

    allowed, policy = _is_send_allowed(settings, destination, inbound=inbound)
    if not allowed:
        return {"sent": False, "reason": policy, "to": mask_phone(destination)}

    health = await wabot.health()
    if not health.ready:
        return {"sent": False, "reason": "wabot_not_ready"}

    lowered = error.lower()
    if "invalid image" in lowered:
        text = (
            "Sorry — I couldn't process that because an older image in this chat "
            "confused the model. Please send your message again."
        )
    else:
        text = (
            "Sorry — I hit an error while handling your message. "
            "Please try again in a moment."
        )

    try:
        send_result = await wabot.send_text(to=destination, text=text)
    except WabotError as exc:
        return {"sent": False, "reason": "send_failed", "detail": redact(str(exc))}

    return {
        "sent": True,
        "policy": policy,
        "to": mask_phone(destination),
        "reason": "agent_error_fallback",
        "result": redact(send_result),
    }
