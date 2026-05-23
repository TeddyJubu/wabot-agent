from __future__ import annotations

from agents import RunContextWrapper, function_tool

from ..skills import list_skills, read_skill
from ._common import RuntimeContext


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
