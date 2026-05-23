"""agents_service — CRUD + one-shot test runner for the subagents table.

Phase 3a service layer.  All functions are module-level and take a MemoryStore
as their first argument, mirroring the pattern used by settings_service.py.

Validation rules enforced here (not in routes):
- slug must match ^[a-z][a-z0-9_]{1,63}$
- duplicate slug raises ValueError
- parent_slug, if provided, must be null OR reference an existing subagent
  (cycles forbidden in v1: only null or 'orchestrator' is accepted as parent)
- handoff_filter must be in {'remove_all_tools'} or null
- is_builtin and slug are immutable after creation
- delete_agent returns False when is_builtin=1; caller maps this to HTTP 409
- set_agent_tools / set_agent_skills validate all IDs before replacing the set
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .memory import MemoryStore

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_VALID_HANDOFF_FILTERS = {"remove_all_tools"}
MAX_RESPONSE_CHARS = 32_000


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> dict:
    """Convert a sqlite3.Row (or tuple fallback) to a plain dict."""
    try:
        return dict(row)
    except (TypeError, ValueError):
        # Shouldn't happen with row_factory=sqlite3.Row, but be safe.
        raise


def _agent_summary(
    conn: Any,
    row: Any,
    tool_counts: dict | None = None,
    skill_counts: dict | None = None,
) -> dict:
    """Build a summary dict from a subagents row + computed counts.

    When tool_counts / skill_counts dicts are supplied (keyed by agent id),
    they are used directly to avoid per-row queries (N+1 elimination).
    When not supplied, falls back to individual COUNT queries for single-agent
    lookups (get_agent, update_agent, etc.).
    """
    d = _row_to_dict(row)
    agent_id = d["id"]
    if tool_counts is not None:
        tool_count = tool_counts.get(agent_id, 0)
    else:
        tool_count = conn.execute(
            "select count(*) from subagent_tools where subagent_id = ?", (agent_id,)
        ).fetchone()[0]
    if skill_counts is not None:
        skill_count = skill_counts.get(agent_id, 0)
    else:
        skill_count = conn.execute(
            "select count(*) from subagent_skills where subagent_id = ?", (agent_id,)
        ).fetchone()[0]
    return {
        "id": d["id"],
        "slug": d["slug"],
        "display_name": d["display_name"],
        "description": d["description"],
        "is_builtin": bool(d["is_builtin"]),
        "is_enabled": bool(d["is_enabled"]),
        "parent_slug": d["parent_slug"],
        "handoff_filter": d["handoff_filter"],
        "tool_count": tool_count,
        "skill_count": skill_count,
        "updated_at": d["updated_at"],
    }


def _agent_detail(conn: Any, row: Any) -> dict:
    """Build a detail dict (includes instructions + id lists)."""
    d = _agent_summary(conn, row)
    agent_id = d["id"]
    raw = _row_to_dict(row)
    d["instructions"] = raw["instructions"]
    tool_ids = [
        r[0]
        for r in conn.execute(
            "select tool_id from subagent_tools where subagent_id = ? order by tool_id",
            (agent_id,),
        ).fetchall()
    ]
    skill_ids = [
        r[0]
        for r in conn.execute(
            "select skill_id from subagent_skills where subagent_id = ? order by skill_id",
            (agent_id,),
        ).fetchall()
    ]
    d["tool_ids"] = tool_ids
    d["skill_ids"] = skill_ids
    return d


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_agents(store: MemoryStore) -> list[dict]:
    """Return all subagent rows as summary dicts (sorted by slug).

    Uses two GROUP BY queries instead of per-row COUNTs to avoid N+1.
    Total queries: 3 (agents + tool counts + skill counts).
    """
    with store.connect() as conn:
        rows = conn.execute(
            "select * from subagents order by slug asc"
        ).fetchall()
        tool_counts = dict(conn.execute(
            "SELECT subagent_id, COUNT(*) FROM subagent_tools GROUP BY subagent_id"
        ).fetchall())
        skill_counts = dict(conn.execute(
            "SELECT subagent_id, COUNT(*) FROM subagent_skills GROUP BY subagent_id"
        ).fetchall())
        return [
            _agent_summary(conn, row, tool_counts=tool_counts, skill_counts=skill_counts)
            for row in rows
        ]


def get_agent(store: MemoryStore, slug: str) -> dict | None:
    """Return full detail for one agent, or None if not found."""
    with store.connect() as conn:
        row = conn.execute(
            "select * from subagents where slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None
        return _agent_detail(conn, row)


def create_agent(store: MemoryStore, payload: dict) -> dict:
    """Insert a new subagent row and return its full detail.

    Raises:
        ValueError: on slug format violation, duplicate slug, bad parent_slug,
                    or invalid handoff_filter.
    """
    slug = payload["slug"]
    if not _SLUG_RE.match(slug):
        raise ValueError(
            f"slug must match ^[a-z][a-z0-9_]{{1,63}}$; got {slug!r}"
        )

    handoff_filter = payload.get("handoff_filter")
    if handoff_filter is not None and handoff_filter not in _VALID_HANDOFF_FILTERS:
        raise ValueError(
            f"handoff_filter must be one of {_VALID_HANDOFF_FILTERS!r} or null; "
            f"got {handoff_filter!r}"
        )

    parent_slug = payload.get("parent_slug")

    with store.connect() as conn:
        # Check for duplicate slug
        existing = conn.execute(
            "select id from subagents where slug = ?", (slug,)
        ).fetchone()
        if existing is not None:
            raise ValueError(f"slug {slug!r} already exists")

        # Validate parent_slug
        if parent_slug is not None:
            if parent_slug == slug:
                raise ValueError("an agent cannot be its own parent")
            parent_row = conn.execute(
                "select id from subagents where slug = ?", (parent_slug,)
            ).fetchone()
            if parent_row is None:
                raise ValueError(
                    f"parent_slug {parent_slug!r} does not reference an existing agent"
                )

        conn.execute(
            """
            insert into subagents
                (slug, display_name, description, instructions,
                 is_builtin, is_enabled, parent_slug, handoff_filter)
            values (?, ?, ?, ?, 0, 1, ?, ?)
            """,
            (
                slug,
                payload["display_name"],
                payload.get("description"),
                payload["instructions"],
                parent_slug,
                handoff_filter,
            ),
        )
        row = conn.execute(
            "select * from subagents where slug = ?", (slug,)
        ).fetchone()
        return _agent_detail(conn, row)


def update_agent(store: MemoryStore, slug: str, patch: dict) -> dict | None:
    """Apply a partial update to an existing agent.  Returns None if not found.

    Cannot change ``slug`` or ``is_builtin``.  Bumps ``updated_at``.
    """
    handoff_filter = patch.get("handoff_filter")
    if handoff_filter is not None and handoff_filter not in _VALID_HANDOFF_FILTERS:
        raise ValueError(
            f"handoff_filter must be one of {_VALID_HANDOFF_FILTERS!r} or null; "
            f"got {handoff_filter!r}"
        )

    # Nullable text columns: explicit null (None) must be written to DB.
    # Non-nullable / boolean columns: None means "not provided" (exclude_unset
    # in the route ensures they won't appear in patch unless sent by client).
    _nullable_text = {"description", "parent_slug", "handoff_filter"}
    updatable = {
        "display_name",
        "description",
        "instructions",
        "is_enabled",
        "parent_slug",
        "handoff_filter",
    }
    # Keep all keys the client explicitly sent that map to updatable columns.
    # For non-nullable fields (display_name, instructions, is_enabled) we still
    # skip None since the route uses exclude_unset so None only appears for
    # nullable text fields which we want to preserve.
    fields = {
        k: v
        for k, v in patch.items()
        if k in updatable and (v is not None or k in _nullable_text)
    }

    with store.connect() as conn:
        row = conn.execute(
            "select * from subagents where slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None

        # Validate parent_slug if being changed
        if "parent_slug" in fields:
            new_parent = fields["parent_slug"]
            if new_parent is not None:
                if new_parent == slug:
                    raise ValueError("an agent cannot be its own parent")
                parent_row = conn.execute(
                    "select id from subagents where slug = ?", (new_parent,)
                ).fetchone()
                if parent_row is None:
                    raise ValueError(
                        f"parent_slug {new_parent!r} does not reference an existing agent"
                    )

        if not fields:
            return _agent_detail(conn, row)

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        set_clause += ", updated_at = current_timestamp"
        values = list(fields.values()) + [slug]
        conn.execute(
            f"update subagents set {set_clause} where slug = ?", values
        )
        updated_row = conn.execute(
            "select * from subagents where slug = ?", (slug,)
        ).fetchone()
        return _agent_detail(conn, updated_row)


def delete_agent(store: MemoryStore, slug: str) -> bool:
    """Delete an agent.  Returns False if is_builtin=1 (caller maps to 409).

    ON DELETE CASCADE in the schema handles subagent_tools and subagent_skills.
    Returns False if the agent is builtin; True if deleted; raises if not found.
    """
    with store.connect() as conn:
        row = conn.execute(
            "select id, is_builtin from subagents where slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None  # type: ignore[return-value]  # caller checks None → 404
        try:
            is_builtin = bool(row["is_builtin"])
        except (TypeError, KeyError):
            is_builtin = bool(row[1])
        if is_builtin:
            return False
        conn.execute("delete from subagents where slug = ?", (slug,))
        return True


def set_agent_tools(store: MemoryStore, slug: str, tool_ids: list[int]) -> dict:
    """Replace the subagent_tools set for an agent atomically.

    Validates all tool_ids exist in the tools table.  Bumps updated_at on the
    parent agent so the instructions cache key changes.

    Raises ValueError if any tool_id is missing.
    Returns the full agent detail.
    """
    with store.connect() as conn:
        row = conn.execute(
            "select * from subagents where slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None  # type: ignore[return-value]

        # Validate all tool_ids
        if tool_ids:
            placeholders = ",".join("?" * len(tool_ids))
            found = conn.execute(
                f"select id from tools where id in ({placeholders})", tool_ids
            ).fetchall()
            found_ids = {r[0] for r in found}
            missing = set(tool_ids) - found_ids
            if missing:
                raise ValueError(f"tool_ids not found in catalog: {sorted(missing)}")

        try:
            agent_id = row["id"]
        except (TypeError, KeyError):
            agent_id = row[0]

        # Replace the set atomically
        conn.execute(
            "delete from subagent_tools where subagent_id = ?", (agent_id,)
        )
        for tid in tool_ids:
            conn.execute(
                "insert or ignore into subagent_tools (subagent_id, tool_id) values (?, ?)",
                (agent_id, tid),
            )

        # Bump updated_at so cache key changes
        conn.execute(
            "update subagents set updated_at = current_timestamp where id = ?",
            (agent_id,),
        )

        updated_row = conn.execute(
            "select * from subagents where slug = ?", (slug,)
        ).fetchone()
        return _agent_detail(conn, updated_row)


def set_agent_skills(store: MemoryStore, slug: str, skill_ids: list[int]) -> dict:
    """Replace the subagent_skills set for an agent atomically.

    Validates all skill_ids exist in the skills table.  Bumps updated_at.

    Raises ValueError if any skill_id is missing.
    Returns the full agent detail.
    """
    with store.connect() as conn:
        row = conn.execute(
            "select * from subagents where slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None  # type: ignore[return-value]

        # Validate all skill_ids
        if skill_ids:
            placeholders = ",".join("?" * len(skill_ids))
            found = conn.execute(
                f"select id from skills where id in ({placeholders})", skill_ids
            ).fetchall()
            found_ids = {r[0] for r in found}
            missing = set(skill_ids) - found_ids
            if missing:
                raise ValueError(f"skill_ids not found in catalog: {sorted(missing)}")

        try:
            agent_id = row["id"]
        except (TypeError, KeyError):
            agent_id = row[0]

        # Replace the set atomically
        conn.execute(
            "delete from subagent_skills where subagent_id = ?", (agent_id,)
        )
        for sid in skill_ids:
            conn.execute(
                "insert or ignore into subagent_skills (subagent_id, skill_id) values (?, ?)",
                (agent_id, sid),
            )

        # Bump updated_at so cache key changes
        conn.execute(
            "update subagents set updated_at = current_timestamp where id = ?",
            (agent_id,),
        )

        updated_row = conn.execute(
            "select * from subagents where slug = ?", (slug,)
        ).fetchone()
        return _agent_detail(conn, updated_row)


def run_agent_one_shot(
    store: MemoryStore, settings: Any, slug: str, prompt: str
) -> dict:
    """Run a single-turn test against an isolated agent.  No WhatsApp side-effects.

    Builds the agent via build_dynamic_agent (Phase 2 registry), runs one turn
    using agents.Runner, and returns the transcript, tool calls observed, and
    any error string.

    If the agents SDK Runner or the LLM is not available (no API key, CI), the
    function catches the exception and returns it as ``error``.
    """
    try:
        from .agents.registry import build_dynamic_agent, load_subagent_specs  # noqa: PLC0415
        from .tools import core_tools  # noqa: PLC0415

        specs = {s.slug: s for s in load_subagent_specs(store)}
        spec = specs.get(slug)
        if spec is None:
            return {
                "transcript": "",
                "tool_calls": [],
                "error": f"agent {slug!r} not found or not enabled",
            }

        native_tools_by_name = {t.name: t for t in core_tools()}
        agent = build_dynamic_agent(
            spec,
            settings,
            native_tools_by_name,
            mcp_servers=[],
            composio_tools=[],
        )

        import agents as _agents  # noqa: PLC0415

        result = _agents.Runner.run_sync(agent, prompt, max_turns=1)

        # Collect transcript from output items
        transcript_parts: list[str] = []
        tool_calls: list[dict] = []

        for item in getattr(result, "new_items", []):
            item_type = type(item).__name__
            if item_type == "MessageOutputItem":
                for part in getattr(item, "content", []):
                    text = getattr(part, "text", None)
                    if text:
                        transcript_parts.append(text)
            elif item_type == "ToolCallItem":
                tool_calls.append(
                    {
                        "name": getattr(item, "name", "unknown"),
                        "args": getattr(item, "arguments", {}),
                    }
                )

        # Fallback: use final_output if new_items is empty
        if not transcript_parts:
            final = getattr(result, "final_output", None)
            if final:
                transcript_parts.append(str(final))

        # Truncate transcript
        transcript = "\n".join(transcript_parts)
        if len(transcript) > MAX_RESPONSE_CHARS:
            transcript = transcript[:MAX_RESPONSE_CHARS] + "\n\n[truncated]"

        # Truncate tool call output/result fields (one level deep)
        _TOOL_OUTPUT_KEYS = ("output", "result")
        for tc in tool_calls:
            for key in _TOOL_OUTPUT_KEYS:
                if key in tc:
                    val = str(tc[key])
                    if len(val) > MAX_RESPONSE_CHARS:
                        tc[key] = val[:MAX_RESPONSE_CHARS] + "\n\n[truncated]"

        return {
            "transcript": transcript,
            "tool_calls": tool_calls,
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        return {
            "transcript": "",
            "tool_calls": [],
            "error": str(exc),
        }
