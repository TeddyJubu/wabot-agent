# ruff: noqa: I001  (the `from .. import tools as _tools_pkg` line is kept at
# the bottom of the import block on purpose — see the comment above it.)
from __future__ import annotations

from typing import Any

from agents import RunContextWrapper, function_tool

from ..mem0_store import mem0_enabled, mem0_health
from ..redaction import looks_sensitive, redact
from ._common import RuntimeContext, _is_owner_session, _mem0_user_id, _mem0_user_ids

# `add_memory_sync` and `search_memories_sync` are reached via the parent
# `wabot_agent.tools` package (which re-exports them from mem0_store) instead
# of being bound to module-local names here. This preserves the pre-split
# mock.patch contract: tests do `patch("wabot_agent.tools.search_memories_sync")`
# expecting it to intercept the call the tool actually makes. Late attribute
# lookup through the package module makes that work.
from .. import tools as _tools_pkg


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
    """Store a durable, non-secret operating note for this agent.

    Owner-gated: only sessions identified as the operator can write
    agent notes. Non-owner senders get a no-op response that's still
    recorded as a tool event for auditability. This prevents arbitrary
    inbound contacts from poisoning the operator's durable knowledge
    via crafted messages that trick the agent into calling this tool.
    """
    if not _is_owner_session(ctx.context.settings, ctx.context.inbound):
        payload = {"ok": False, "reason": "owner_session_required"}
        ctx.context.memory.record_tool_event(ctx.context.run_id, "remember_agent_note", payload)
        return redact(payload)
    payload = ctx.context.memory.remember_agent_note(key=key, value=value)
    ctx.context.memory.record_tool_event(ctx.context.run_id, "remember_agent_note", payload)
    return redact(payload)


@function_tool
async def mem0_status(ctx: RunContextWrapper[RuntimeContext]) -> dict[str, Any]:
    """Report whether Mem0 long-term memory is enabled and configured."""
    settings = ctx.context.settings
    payload = mem0_health(settings)
    ctx.context.memory.record_tool_event(ctx.context.run_id, "mem0_status", payload)
    return redact(payload)


@function_tool
async def search_mem0_memories(
    ctx: RunContextWrapper[RuntimeContext],
    query: str,
    user_id: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Search Mem0 memories. Defaults to sender (searches person + group ids in groups)."""
    if not mem0_enabled(ctx.context.settings):
        health = mem0_health(ctx.context.settings)
        reason = health.get("reason") or "mem0_disabled"
        if reason == "mem0_config_disabled":
            reason = "mem0_disabled"
        payload = {"ok": False, "reason": reason, "results": []}
    else:
        ids = [user_id.strip()] if user_id and user_id.strip() else _mem0_user_ids(ctx)
        if not ids:
            payload = {"ok": False, "reason": "no_user_id", "results": []}
        else:
            merged: list[dict[str, str]] = []
            seen: set[str] = set()
            for uid in ids:
                part = _tools_pkg.search_memories_sync(
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
        health = mem0_health(ctx.context.settings)
        reason = health.get("reason") or "mem0_disabled"
        if reason == "mem0_config_disabled":
            reason = "mem0_disabled"
        payload = {"ok": False, "reason": reason}
    else:
        uid = (user_id or _mem0_user_id(ctx) or "").strip()
        if not uid:
            payload = {"ok": False, "reason": "no_user_id"}
        elif looks_sensitive(text):
            payload = {"ok": False, "reason": "sensitive_content"}
        else:
            payload = _tools_pkg.add_memory_sync(
                ctx.context.settings,
                user_id=uid,
                messages=[{"role": "user", "content": text.strip()}],
                metadata={"source": ctx.context.run_id},
            )
    ctx.context.memory.record_tool_event(ctx.context.run_id, "add_mem0_memory", payload)
    return redact(payload)
