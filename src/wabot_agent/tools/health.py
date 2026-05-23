from __future__ import annotations

from typing import Any

from agents import RunContextWrapper, function_tool

from ._common import RuntimeContext


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
