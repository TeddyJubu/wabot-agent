from __future__ import annotations

from typing import Any

from agents import RunContextWrapper, function_tool

from ..file_processing import whatsapp_send_kind_for_path
from ..redaction import mask_phone, redact
from ._common import (
    RuntimeContext,
    _apply_send_policy_gate,
    _invoke_chat_message_action,
    _invoke_chat_state_action,
    _maybe_auto_track_outbound,
    _media_path_allowed,
    _send_whatsapp_media,
)


@function_tool
async def send_whatsapp_text(
    ctx: RunContextWrapper[RuntimeContext], to: str, text: str
) -> dict[str, Any]:
    """Send a WhatsApp text message through wabot when the send policy allows it."""
    _, reason, block = await _apply_send_policy_gate(ctx, "send_whatsapp_text", to)
    if block is not None:
        return block

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
    safe_path, reason, block = await _apply_send_policy_gate(
        ctx, "send_whatsapp_image", to, media_path=path
    )
    if block is not None:
        return block
    assert safe_path is not None  # gate guarantees this when block is None

    result = await ctx.context.wabot.send_image(to=to, path=str(safe_path), caption=caption)
    ctx.context.record_sent(to)
    payload = {"sent": True, "policy": reason, "to": mask_phone(to), "result": redact(result)}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "send_whatsapp_image", payload)
    ctx.context.event_log.write("send_image", payload)
    return payload


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
