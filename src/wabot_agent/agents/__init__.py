"""wabot_agent.agents — orchestrator + 5 specialist subagents (Phase 5).

This package implements the multi-agent architecture from Phase 5 of the
simplification roadmap. It is opt-in via the `subagents_enabled` feature flag
in Settings (default: False). When the flag is off, the legacy monolithic
agent in `agent.py` is used unchanged.

Public surface:
    build_orchestrator(settings, *, mcp_servers, composio_tools) — builds the
        orchestrator Agent with all five specialist subagents wired as handoffs.
        MCP servers and Composio tools loaded by _prepare_agent_turn are
        threaded through here so they are attached to the orchestrator rather
        than dropped on the floor when subagents_enabled=True.
    SUBAGENT_NAMES — frozenset of the five specialist names (for tests and
        introspection).

Specialist build functions are also re-exported for testing:
    build_scraper, build_memory_keeper, build_comms, build_scheduler,
    build_inboxer
"""

from __future__ import annotations

from .comms import build_comms
from .inboxer import build_inboxer
from .memory_keeper import build_memory_keeper
from .orchestrator import build_orchestrator
from .scheduler import build_scheduler
from .scraper import build_scraper

SUBAGENT_NAMES: frozenset[str] = frozenset(
    {"scraper", "memory_keeper", "comms", "scheduler", "inboxer"}
)

__all__ = [
    "build_orchestrator",
    "build_scraper",
    "build_memory_keeper",
    "build_comms",
    "build_scheduler",
    "build_inboxer",
    "SUBAGENT_NAMES",
]
