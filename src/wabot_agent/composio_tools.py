from __future__ import annotations

import logging
import os
from typing import Any

from .config import Settings
from .memory import MemoryStore

logger = logging.getLogger(__name__)

_COMPOSIO_SESSION_FACT_KEY = "composio_session_id"
_composio_client: Any | None = None


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


def load_composio_tools(
    settings: Settings,
    *,
    user_id: str,
    memory: MemoryStore,
) -> list[Any]:
    """Return OpenAI Agents–ready Composio tool router tools for this user."""
    if not composio_enabled(settings):
        return []

    _ensure_composio_api_key(settings)
    try:
        composio = _get_composio_client()
        session_id = _stored_session_id(memory, user_id)
        if session_id:
            session = composio.use(session_id)
        else:
            session = composio.create(user_id=user_id)
            sid = str(getattr(session, "session_id", "") or session)
            memory.remember_contact_fact(
                user_id,
                _COMPOSIO_SESSION_FACT_KEY,
                sid,
                source="composio",
            )
        tools = session.tools()
        return list(tools) if tools else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("composio tools unavailable for %s: %s", user_id, exc)
        return []


def build_composio_prompt_context(*, tools_loaded: bool) -> str:
    """Per-turn reminder when Composio tools are attached (anti-hallucination for mail/calendar)."""
    if not tools_loaded:
        return ""
    return (
        "\n\n[Composio: Gmail & Google Calendar are connected. For this message, if it "
        "mentions email, inbox, Gmail, calendar, meetings, schedule, or availability — "
        "call COMPOSIO_SEARCH_TOOLS and COMPOSIO_MULTI_EXECUTE_TOOL before answering. "
        "State only what those tools return in this turn; never invent messages or events.]\n"
    )


def reset_composio_client_for_tests() -> None:
    global _composio_client
    _composio_client = None
