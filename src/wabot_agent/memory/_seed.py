"""Seed functions for the Phase 1 dynamic-subagent data model.

All three functions are safe to call on every startup:
- seed_builtin_subagents / seed_tools_catalog use INSERT OR IGNORE so
  re-runs are no-ops.
- import_mcp_config_file checks whether the mcp_servers table is empty
  before inserting, so it only runs once.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Settings


# ---------------------------------------------------------------------------
# Builtin subagent manifest
# ---------------------------------------------------------------------------

# Maps slug -> (module_attr, display_name, description, parent_slug, handoff_filter)
# parent_slug=None means top-level (orchestrator itself).
# handoff_filter mirrors the wiring in agents/orchestrator.py lines ~144-154:
#   scraper  -> remove_all_tools
#   inboxer  -> remove_all_tools
#   the other three -> None
_BUILTIN_MANIFEST: list[dict] = [
    {
        "slug": "orchestrator",
        "module": "wabot_agent.agents.orchestrator",
        "attr": "ORCHESTRATOR_INSTRUCTIONS",
        "display_name": "Orchestrator",
        "description": "Routes inbound WhatsApp messages to specialist subagents.",
        "parent_slug": None,
        "handoff_filter": None,
    },
    {
        "slug": "scraper",
        "module": "wabot_agent.agents.scraper",
        "attr": "SCRAPER_INSTRUCTIONS",
        "display_name": "Scraper",
        "description": "Web search, URL fetch, image search, and file processing.",
        "parent_slug": "orchestrator",
        "handoff_filter": "remove_all_tools",
    },
    {
        "slug": "memory_keeper",
        "module": "wabot_agent.agents.memory_keeper",
        "attr": "MEMORY_KEEPER_INSTRUCTIONS",
        "display_name": "Memory Keeper",
        "description": "Recalls and stores per-contact and global agent memory.",
        "parent_slug": "orchestrator",
        "handoff_filter": None,
    },
    {
        "slug": "comms",
        "module": "wabot_agent.agents.comms",
        "attr": "COMMS_INSTRUCTIONS",
        "display_name": "Comms",
        "description": "Sends WhatsApp messages and manages groups.",
        "parent_slug": "orchestrator",
        "handoff_filter": None,
    },
    {
        "slug": "scheduler",
        "module": "wabot_agent.agents.scheduler",
        "attr": "SCHEDULER_INSTRUCTIONS",
        "display_name": "Scheduler",
        "description": "Creates reminders and tracks outbound conversations.",
        "parent_slug": "orchestrator",
        "handoff_filter": None,
    },
    {
        "slug": "inboxer",
        "module": "wabot_agent.agents.inboxer",
        "attr": "INBOXER_INSTRUCTIONS",
        "display_name": "Inboxer",
        "description": "Reads inbox, looks up contacts, lists skills, checks wabot health.",
        "parent_slug": "orchestrator",
        "handoff_filter": "remove_all_tools",
    },
]


def seed_builtin_subagents(conn: sqlite3.Connection) -> None:
    """Insert the 6 builtin subagents.

    Reads each agent module and extracts the *_INSTRUCTIONS constant by
    importing it — no regex. Uses INSERT OR IGNORE keyed on the unique slug
    so re-runs are no-ops.
    """
    import importlib

    for spec in _BUILTIN_MANIFEST:
        mod = importlib.import_module(spec["module"])
        instructions: str = getattr(mod, spec["attr"])

        conn.execute(
            """
            insert or ignore into subagents
                (slug, display_name, description, instructions,
                 is_builtin, is_enabled, parent_slug, handoff_filter)
            values (?, ?, ?, ?, 1, 1, ?, ?)
            """,
            (
                spec["slug"],
                spec["display_name"],
                spec["description"],
                instructions,
                spec["parent_slug"],
                spec["handoff_filter"],
            ),
        )


def seed_tools_catalog(conn: sqlite3.Connection) -> None:
    """Upsert native tool rows from core_tools().

    Uses INSERT OR IGNORE on the (kind, source_ref) unique index so
    re-runs are no-ops.
    """
    from ..tools import core_tools  # local import to avoid circular at module load

    for tool in core_tools():
        name: str = tool.name
        raw_desc: str = getattr(tool, "description", "") or ""
        description = raw_desc[:500] if len(raw_desc) > 500 else raw_desc
        source_ref = f"tools.{name}"

        conn.execute(
            """
            insert or ignore into tools (kind, source_ref, name, description, is_enabled)
            values ('native', ?, ?, ?, 1)
            """,
            (source_ref, name, description),
        )


def import_mcp_config_file(conn: sqlite3.Connection, settings: Settings) -> None:
    """One-time import of settings.mcp_config into the mcp_servers table.

    Skips silently if:
    - settings.mcp_config is None
    - the file does not exist or is not readable JSON
    - the mcp_servers table already contains rows (import already done)
    """
    mcp_config: Path | None = getattr(settings, "mcp_config", None)
    if mcp_config is None:
        return

    mcp_path = Path(mcp_config)
    if not mcp_path.exists():
        return

    try:
        raw = mcp_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        return

    if not isinstance(data, dict):
        return

    # Only import if the table is currently empty
    count = conn.execute("select count(*) from mcp_servers").fetchone()[0]
    if count > 0:
        return

    for name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        # Infer transport from the entry structure
        if "command" in entry:
            transport = "stdio"
        elif "url" in entry:
            transport = "http"
        else:
            transport = "stdio"

        config_json = json.dumps(entry)
        conn.execute(
            """
            insert or ignore into mcp_servers
                (name, transport, config_json, is_enabled, health_status)
            values (?, ?, ?, 1, 'unknown')
            """,
            (name, transport, config_json),
        )
