from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from agents import FunctionTool

from .config import Settings
from .memory import MemoryStore

logger = logging.getLogger(__name__)

_COMPOSIO_SESSION_FACT_KEY = "composio_session_id"
_COMPOSIO_TOOLS_TTL_SEC = 300.0
_composio_client: Any | None = None
_composio_tools_cache: dict[str, tuple[float, list[Any]]] = {}
_COMPOSIO_WHATSAPP_TOOL_NAMES = {
    "COMPOSIO_MANAGE_CONNECTIONS",
    "COMPOSIO_SEARCH_TOOLS",
    "COMPOSIO_MULTI_EXECUTE_TOOL",
}
_COMPOSIO_WHATSAPP_PATTERN = re.compile(
    r"WHATSAPP_|"
    r"['\"]toolkits?['\"]\s*:\s*\[[^\]]*['\"]whatsapp['\"]|"
    r"\b(?:lookup|look up|send|message|contact|phone|number|group|media|"
    r"ready|readiness|connect|connection|auth|authenticate|activate|toolkit)"
    r"\b.{0,100}\bwhatsapp\b|"
    r"\bwhatsapp\b.{0,100}\b(?:lookup|look up|send|message|contact|phone|"
    r"number|group|media|ready|readiness|connect|connection|auth|authenticate|"
    r"activate|toolkit)\b",
    re.IGNORECASE | re.DOTALL,
)


def composio_enabled(settings: Settings) -> bool:
    if not settings.composio_enabled:
        return False
    return bool(settings.composio_api_key)


def _ensure_composio_api_key(settings: Settings) -> None:
    cache_dir = settings.data_dir / "composio"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("COMPOSIO_CACHE_DIR", str(cache_dir.resolve()))
    if settings.composio_api_key:
        os.environ.setdefault("COMPOSIO_API_KEY", settings.composio_api_key)


def _get_composio_client():
    global _composio_client
    if _composio_client is None:
        from composio import Composio
        from composio_openai_agents import OpenAIAgentsProvider

        _composio_client = Composio(provider=OpenAIAgentsProvider())
    return _composio_client


def _stored_session_id(memory: MemoryStore, user_id: str) -> str | None:
    return memory.get_contact_fact(user_id, _COMPOSIO_SESSION_FACT_KEY)


def composio_session_user_id(settings: Settings, user_id: str) -> str:
    """Session owner for Composio OAuth apps.

    By default this is per-contact. Production can set WABOT_AGENT_COMPOSIO_USER_ID
    to reuse the owner's already-connected Gmail/Calendar session for all booking
    turns, instead of asking each WhatsApp contact to connect Google Calendar.
    """
    configured = (settings.composio_user_id or "").strip()
    return configured or user_id


def _cached_composio_tools(user_id: str) -> list[Any] | None:
    entry = _composio_tools_cache.get(user_id)
    if entry is None:
        return None
    cached_at, tools = entry
    if time.monotonic() - cached_at > _COMPOSIO_TOOLS_TTL_SEC:
        _composio_tools_cache.pop(user_id, None)
        return None
    return tools


def _is_composio_whatsapp_request(raw_input: str) -> bool:
    return bool(_COMPOSIO_WHATSAPP_PATTERN.search(raw_input or ""))


def _blocked_whatsapp_result(tool_name: str) -> dict[str, Any]:
    return {
        "ok": False,
        "blocked": True,
        "reason": "whatsapp_is_native_wabot",
        "tool": tool_name,
        "message": (
            "WhatsApp is not connected through Composio in wabot-agent. "
            "Use native wabot tools such as lookup_whatsapp_contacts, "
            "send_whatsapp_text, WhatsApp group/media tools, and wabot_health."
        ),
    }


def _guard_composio_tool(tool: Any) -> Any:
    if not isinstance(tool, FunctionTool):
        return tool
    if tool.name not in _COMPOSIO_WHATSAPP_TOOL_NAMES:
        return tool

    original_invoke = tool.on_invoke_tool

    async def guarded_invoke(ctx: Any, raw_input: str) -> Any:
        if _is_composio_whatsapp_request(raw_input):
            return _blocked_whatsapp_result(tool.name)
        return await original_invoke(ctx, raw_input)

    return FunctionTool(
        name=tool.name,
        description=tool.description,
        params_json_schema=tool.params_json_schema,
        on_invoke_tool=guarded_invoke,
        strict_json_schema=tool.strict_json_schema,
        is_enabled=tool.is_enabled,
        tool_input_guardrails=tool.tool_input_guardrails,
        tool_output_guardrails=tool.tool_output_guardrails,
        needs_approval=tool.needs_approval,
        timeout_seconds=tool.timeout_seconds,
        timeout_behavior=tool.timeout_behavior,
        timeout_error_function=tool.timeout_error_function,
        defer_loading=tool.defer_loading,
        _failure_error_function=tool._failure_error_function,
        _use_default_failure_error_function=tool._use_default_failure_error_function,
        _is_agent_tool=tool._is_agent_tool,
        _is_codex_tool=tool._is_codex_tool,
        _agent_instance=tool._agent_instance,
        _tool_namespace=tool._tool_namespace,
        _tool_namespace_description=tool._tool_namespace_description,
        _mcp_title=tool._mcp_title,
        _tool_origin=tool._tool_origin,
        _emit_tool_origin=tool._emit_tool_origin,
    )


def guard_composio_tools(tools: list[Any]) -> list[Any]:
    return [_guard_composio_tool(tool) for tool in tools]


def load_composio_tools(
    settings: Settings,
    *,
    user_id: str,
    memory: MemoryStore,
) -> list[Any]:
    """Return OpenAI Agents–ready Composio tool router tools for this user."""
    if not composio_enabled(settings):
        return []
    session_user_id = composio_session_user_id(settings, user_id=user_id)

    cached = _cached_composio_tools(session_user_id)
    if cached is not None:
        return cached

    _ensure_composio_api_key(settings)
    try:
        composio = _get_composio_client()
        session_id = _stored_session_id(memory, session_user_id)
        if session_id:
            session = composio.use(session_id)
        else:
            session = composio.create(user_id=session_user_id)
            sid = str(getattr(session, "session_id", "") or session)
            memory.remember_contact_fact(
                session_user_id,
                _COMPOSIO_SESSION_FACT_KEY,
                sid,
                source="composio",
            )
        tools = guard_composio_tools(list(session.tools() or []))
        _composio_tools_cache[session_user_id] = (time.monotonic(), tools)
        return tools
    except Exception as exc:  # noqa: BLE001
        logger.warning("composio tools unavailable for %s: %s", user_id, exc)
        return []


def build_composio_prompt_context(*, tools_loaded: bool) -> str:
    """Per-turn reminder when Composio tools are attached (anti-hallucination for mail/calendar)."""
    if not tools_loaded:
        return ""
    return (
        "\n\n[Composio boundary: Gmail & Google Calendar are connected through Composio. "
        "WhatsApp is not: it is native wabot only. Never search for, execute, or manage "
        "a Composio whatsapp toolkit; never ask for a Composio WhatsApp connection link. "
        "For email, inbox, Gmail, calendar, meetings, schedule, appointment booking calendar "
        "checks, free/busy, or availability, call COMPOSIO_SEARCH_TOOLS and "
        "COMPOSIO_MULTI_EXECUTE_TOOL before answering. Use native wabot tools for WhatsApp "
        "contacts/messages. State only what live tools return; never invent messages or events.]\n"
    )


def reset_composio_client_for_tests() -> None:
    global _composio_client
    _composio_client = None
    _composio_tools_cache.clear()
