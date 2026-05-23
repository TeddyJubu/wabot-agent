from __future__ import annotations

from typing import Any

from agents import RunContextWrapper, function_tool

from ..redaction import redact
from ._common import (
    RuntimeContext,
    _dry_run_block,
    _media_path_allowed,
    _wabot_ready_or_block,
)


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
