"""tools_service — read and manage the tools catalog table.

Phase 3a service layer.  Module-level functions, each taking a MemoryStore as
the first argument.

Three public functions:
- list_tools(store): all rows grouped by kind, each with is_assigned_to: [slug].
- refresh_catalog(store, settings): re-seed native tools; composio if enabled.
- toggle_tool(store, tool_id, is_enabled): flip is_enabled on one row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Settings
    from .memory import MemoryStore


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------


def list_tools(store: MemoryStore) -> dict[str, list[dict]]:
    """Return all tool rows grouped by kind, each with an is_assigned_to slug list.

    Return shape::

        {
          "native": [...],
          "mcp": [...],
          "composio": [...],
          "skill_action": [...],
        }

    Each item includes the standard tool columns plus ``is_assigned_to``
    (list of subagent slugs that have this tool in subagent_tools).
    """
    with store.connect() as conn:
        tool_rows = conn.execute(
            """
            select
                t.id,
                t.kind,
                t.source_ref,
                t.name,
                t.description,
                t.is_enabled
            from tools t
            order by t.kind asc, t.name asc
            """
        ).fetchall()

        # Fetch assignment mapping: tool_id -> list of slugs
        assignment_rows = conn.execute(
            """
            select st.tool_id, s.slug
            from subagent_tools st
            inner join subagents s on s.id = st.subagent_id
            order by st.tool_id, s.slug
            """
        ).fetchall()

    assignments: dict[int, list[str]] = {}
    for ar in assignment_rows:
        try:
            tid = ar["tool_id"]
            slug = ar["slug"]
        except (TypeError, KeyError):
            tid, slug = ar[0], ar[1]
        assignments.setdefault(tid, []).append(slug)

    grouped: dict[str, list[dict]] = {
        "native": [],
        "mcp": [],
        "composio": [],
        "skill_action": [],
    }

    for row in tool_rows:
        try:
            rid = row["id"]
            kind = row["kind"]
            source_ref = row["source_ref"]
            name = row["name"]
            description = row["description"]
            is_enabled = bool(row["is_enabled"])
        except (TypeError, KeyError):
            rid, kind, source_ref, name, description, is_enabled = (
                row[0], row[1], row[2], row[3], row[4], bool(row[5])
            )

        entry = {
            "id": rid,
            "kind": kind,
            "source_ref": source_ref,
            "name": name,
            "description": description,
            "is_enabled": is_enabled,
            "is_assigned_to": assignments.get(rid, []),
        }
        bucket = grouped.get(kind)
        if bucket is not None:
            bucket.append(entry)
        else:
            grouped.setdefault(kind, []).append(entry)

    return grouped


# ---------------------------------------------------------------------------
# refresh_catalog
# ---------------------------------------------------------------------------


def refresh_catalog(store: MemoryStore, settings: Settings) -> dict[str, int]:
    """Re-seed the tools catalog from native + composio sources.

    Native tools: calls memory._seed.seed_tools_catalog via a raw connection.
    Composio: if settings.composio_enabled and API key is present, loads tools
              via composio_tools.load_composio_tools and upserts each as kind='composio'.
    MCP: no-op in v1 (per plan §1.2 we don't per-tool list MCP servers).

    Returns::

        {"native_added": int, "composio_added": int, "mcp_added": int}
    """
    from .memory._seed import seed_tools_catalog  # noqa: PLC0415

    native_before = 0
    native_after = 0
    composio_added = 0

    with store.connect() as conn:
        native_before = conn.execute(
            "select count(*) from tools where kind='native'"
        ).fetchone()[0]
        seed_tools_catalog(conn)
        native_after = conn.execute(
            "select count(*) from tools where kind='native'"
        ).fetchone()[0]

    # Composio: attempt only if enabled
    composio_enabled_flag = getattr(settings, "composio_enabled", False)
    composio_api_key = getattr(settings, "composio_api_key", None)
    if composio_enabled_flag and composio_api_key:
        try:
            from .composio_tools import load_composio_tools  # noqa: PLC0415

            tools = load_composio_tools(settings, store, contact="__refresh__")
            with store.connect() as conn:
                composio_before = conn.execute(
                    "select count(*) from tools where kind='composio'"
                ).fetchone()[0]
                for t in tools:
                    name: str = getattr(t, "name", "")
                    raw_desc: str = getattr(t, "description", "") or ""
                    description = raw_desc[:500]
                    conn.execute(
                        """
                        insert or ignore into tools
                            (kind, source_ref, name, description, is_enabled)
                        values ('composio', ?, ?, ?, 1)
                        """,
                        (name, name, description),
                    )
                composio_after = conn.execute(
                    "select count(*) from tools where kind='composio'"
                ).fetchone()[0]
                composio_added = composio_after - composio_before
        except Exception:  # noqa: BLE001
            # Composio unavailable — not a hard failure for CI
            composio_added = 0

    # TODO(v1.1): enumerate enabled+healthy mcp_servers rows; for each server
    # call connected_mcp_servers() and upsert one row per discovered tool.
    # Per plan §1.2 this is out of scope for v1.

    return {
        "native_added": max(0, native_after - native_before),
        "composio_added": composio_added,
        "mcp_added": 0,
    }


# ---------------------------------------------------------------------------
# toggle_tool
# ---------------------------------------------------------------------------


def toggle_tool(store: MemoryStore, tool_id: int, is_enabled: bool) -> dict | None:
    """Flip is_enabled on one tool row.  Returns updated row dict or None if not found."""
    with store.connect() as conn:
        row = conn.execute("select * from tools where id = ?", (tool_id,)).fetchone()
        if row is None:
            return None
        conn.execute(
            "update tools set is_enabled = ? where id = ?",
            (1 if is_enabled else 0, tool_id),
        )
        updated = conn.execute("select * from tools where id = ?", (tool_id,)).fetchone()
        try:
            return {
                "id": updated["id"],
                "kind": updated["kind"],
                "source_ref": updated["source_ref"],
                "name": updated["name"],
                "description": updated["description"],
                "is_enabled": bool(updated["is_enabled"]),
            }
        except (TypeError, KeyError):
            return {
                "id": updated[0],
                "kind": updated[1],
                "source_ref": updated[2],
                "name": updated[3],
                "description": updated[4],
                "is_enabled": bool(updated[5]),
            }
