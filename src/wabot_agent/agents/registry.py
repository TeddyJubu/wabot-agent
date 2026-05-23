"""Phase 2 — DB-driven subagent registry.

Three public functions plus a frozen dataclass:

- SubagentSpec: lightweight value object loaded from the DB.
- load_subagent_specs(store): read all enabled subagents + their tool joins.
- build_dynamic_agent(spec, settings, native_tools_by_name, mcp_servers, composio_tools):
    resolve tool IDs to callables and return an agents.Agent.
- build_orchestrator_from_db(settings, store, mcp_servers, composio_tools):
    full DB-driven replacement for agents.orchestrator.build_orchestrator().

Convention: do NOT call this module from the hardcoded builder files.  Only
agent.py calls build_orchestrator_from_db when settings.subagents_db_enabled
is True and a row for slug='orchestrator' exists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config import Settings
    from ..memory import MemoryStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubagentSpec:
    id: int
    slug: str
    display_name: str
    description: str | None
    instructions: str
    is_builtin: bool
    is_enabled: bool
    parent_slug: str | None
    handoff_filter: str | None
    tool_ids: tuple[int, ...]
    # skill_ids omitted — skills remain prompt-injected in v1 per plan §1.2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HANDOFF_FILTER_MAP: dict[str, Any] = {}
_unknown_handoff_filter_warned: set[str] = set()


def _resolve_handoff_filter(name: str | None) -> Any:
    """Convert a DB string value to the real callable (or None).

    Currently only 'remove_all_tools' is supported.  Unknown non-empty values
    emit a one-per-value warning and are treated as None to avoid hard failures
    on forward-compat strings.
    """
    if not name:
        return None
    # Lazy-populate the map once to avoid importing at module load time.
    if not _HANDOFF_FILTER_MAP:
        from agents.extensions.handoff_filters import remove_all_tools  # noqa: PLC0415

        _HANDOFF_FILTER_MAP["remove_all_tools"] = remove_all_tools
    result = _HANDOFF_FILTER_MAP.get(name)
    if result is None and name not in _unknown_handoff_filter_warned:
        _unknown_handoff_filter_warned.add(name)
        logger.warning(
            "_resolve_handoff_filter: unknown handoff_filter value %r; "
            "treating as None (no filter).  Add it to _HANDOFF_FILTER_MAP when "
            "the corresponding callable becomes available.",
            name,
        )
    return result


# ---------------------------------------------------------------------------
# load_subagent_specs
# ---------------------------------------------------------------------------


def load_subagent_specs(store: MemoryStore) -> list[SubagentSpec]:
    """Read every *enabled* subagent row joined with subagent_tools.

    Returns specs in deterministic order (slug ASC).
    Pure DB read — no side effects.
    """
    with store.connect() as conn:
        rows = conn.execute(
            """
            select
                s.id,
                s.slug,
                s.display_name,
                s.description,
                s.instructions,
                s.is_builtin,
                s.is_enabled,
                s.parent_slug,
                s.handoff_filter
            from subagents s
            where s.is_enabled = 1
            order by s.slug asc
            """
        ).fetchall()

        # Collect tool_ids per subagent in a single extra query for efficiency.
        tool_rows = conn.execute(
            """
            select st.subagent_id, st.tool_id
            from subagent_tools st
            inner join subagents s on s.id = st.subagent_id
            where s.is_enabled = 1
            order by st.subagent_id, st.tool_id
            """
        ).fetchall()

    # Build tool_ids mapping: {subagent_id: [tool_id, ...]}
    tool_ids_by_agent: dict[int, list[int]] = {}
    for tr in tool_rows:
        # Support both dict-like (sqlite3.Row) and tuple-like access
        try:
            sub_id = tr["subagent_id"]
            t_id = tr["tool_id"]
        except (TypeError, IndexError):
            sub_id, t_id = tr[0], tr[1]
        tool_ids_by_agent.setdefault(sub_id, []).append(t_id)

    specs: list[SubagentSpec] = []
    for row in rows:
        try:
            r_id = row["id"]
            r_slug = row["slug"]
            r_display_name = row["display_name"]
            r_description = row["description"]
            r_instructions = row["instructions"]
            r_is_builtin = bool(row["is_builtin"])
            r_is_enabled = bool(row["is_enabled"])
            r_parent_slug = row["parent_slug"]
            r_handoff_filter = row["handoff_filter"]
        except (TypeError, IndexError):
            (
                r_id,
                r_slug,
                r_display_name,
                r_description,
                r_instructions,
                r_is_builtin,
                r_is_enabled,
                r_parent_slug,
                r_handoff_filter,
            ) = row

            r_is_builtin = bool(r_is_builtin)
            r_is_enabled = bool(r_is_enabled)

        specs.append(
            SubagentSpec(
                id=r_id,
                slug=r_slug,
                display_name=r_display_name,
                description=r_description,
                instructions=r_instructions,
                is_builtin=r_is_builtin,
                is_enabled=r_is_enabled,
                parent_slug=r_parent_slug,
                handoff_filter=r_handoff_filter,
                tool_ids=tuple(tool_ids_by_agent.get(r_id, [])),
            )
        )

    return specs


# ---------------------------------------------------------------------------
# build_dynamic_agent
# ---------------------------------------------------------------------------


def build_dynamic_agent(
    spec: SubagentSpec,
    settings: Settings,
    native_tools_by_name: dict[str, Any],
    mcp_servers,
    composio_tools,
    *,
    _tool_catalog: dict[int, dict] | None = None,
) -> Any:
    """Build an agents.Agent from a spec, resolving spec.tool_ids to callables.

    Tool resolution strategy (v1):
    - native: look up name in native_tools_by_name; warn-log + skip missing.
    - mcp: ignored at per-tool level in v1 (whole servers pass through via
      mcp_servers arg).
    - composio: filter composio_tools by matching tool.name to source_ref.
    - skill_action: ignored in v1 (skills remain prompt-injected).

    _tool_catalog is an optional pre-loaded dict[tool_id -> row] that
    build_orchestrator_from_db passes in to avoid per-agent DB hits.  When
    None and spec.tool_ids is non-empty, tool resolution is skipped gracefully
    (safe — the agent still works, just with no resolved tools).
    """
    import logging as _logging  # noqa: PLC0415

    import agents as _agents  # noqa: PLC0415

    from ..model_routing import ModelPurpose  # noqa: PLC0415
    from ..models import build_model, model_settings  # noqa: PLC0415

    _log = _logging.getLogger(__name__)
    resolved_tools: list[Any] = []

    if spec.tool_ids and _tool_catalog is not None:
        for tid in spec.tool_ids:
            tool_row = _tool_catalog.get(tid)
            if tool_row is None:
                continue
            kind = tool_row["kind"]
            source_ref = tool_row["source_ref"]
            name = tool_row["name"]

            if kind == "native":
                if name in native_tools_by_name:
                    resolved_tools.append(native_tools_by_name[name])
                else:
                    _log.warning(
                        "build_dynamic_agent: native tool %r (id=%d) not found in "
                        "native_tools_by_name for spec %r; skipping",
                        name,
                        tid,
                        spec.slug,
                    )
            elif kind == "composio":
                slug = source_ref
                for ct in composio_tools:
                    if getattr(ct, "name", None) == slug:
                        resolved_tools.append(ct)
                        break
            # mcp and skill_action: handled at orchestrator level in v1

    return _agents.Agent(
        # Use slug (not display_name) for the Agents SDK name field so it
        # matches the hardcoded builders (which use name="scraper" etc.) and
        # produces valid handoff tool names like "transfer_to_scraper".
        # display_name is for UI surfaces only.
        name=spec.slug,
        instructions=spec.instructions,
        model=build_model(settings, purpose=ModelPurpose.CHAT),
        model_settings=model_settings(settings, purpose=ModelPurpose.CHAT),
        tools=resolved_tools,
        mcp_servers=list(mcp_servers) if mcp_servers else [],
    )


# ---------------------------------------------------------------------------
# build_orchestrator_from_db
# ---------------------------------------------------------------------------


def build_orchestrator_from_db(
    settings: Settings,
    store: MemoryStore,
    mcp_servers: list[Any],
    composio_tools: list[Any],
) -> Any:
    """DB-driven replacement for agents.orchestrator.build_orchestrator.

    Algorithm:
    1. Load all enabled specs.
    2. Find root spec (slug='orchestrator').
    3. Load tool catalog for all tool_ids referenced in any spec.
    4. For each spec with parent_slug='orchestrator', build the specialist
       via _build_dynamic_agent_with_tools, then wrap in agents.handoff(...)
       using the handoff_filter resolved from its string value.
    5. Build the orchestrator agent with:
         - instructions from build_orchestrator_instructions(settings)
           (same composition as the hardcoded builder)
         - tools = composio_tools (same as hardcoded)
         - mcp_servers = mcp_servers (same as hardcoded)
         - handoffs in the order: scraper, memory_keeper, comms, scheduler,
           inboxer — matching the hardcoded order in orchestrator.py lines
           144-154.

    Snapshot equivalence: when called with the default Phase 1 seed, the
    returned Agent has identical name, instructions, and handoff structure
    to build_orchestrator(settings, mcp_servers=..., composio_tools=...).
    """
    import agents as _agents  # noqa: PLC0415

    from ..model_routing import ModelPurpose  # noqa: PLC0415
    from ..models import build_model, model_settings  # noqa: PLC0415

    # 1. Load specs
    specs = load_subagent_specs(store)
    specs_by_slug = {s.slug: s for s in specs}

    # 2. Validate root
    root_spec = specs_by_slug.get("orchestrator")
    if root_spec is None:
        raise RuntimeError(
            "build_orchestrator_from_db: no enabled 'orchestrator' row in subagents table"
        )

    # 3. Load tool catalog for all referenced tool_ids
    all_tool_ids: set[int] = set()
    for s in specs:
        all_tool_ids.update(s.tool_ids)

    tool_catalog: dict[int, dict] = {}
    if all_tool_ids:
        with store.connect() as conn:
            placeholders = ",".join("?" * len(all_tool_ids))
            rows = conn.execute(
                f"select id, kind, source_ref, name from tools where id in ({placeholders})",
                tuple(all_tool_ids),
            ).fetchall()
        for row in rows:
            try:
                tool_catalog[row["id"]] = {
                    "kind": row["kind"],
                    "source_ref": row["source_ref"],
                    "name": row["name"],
                }
            except (TypeError, IndexError):
                tool_catalog[row[0]] = {
                    "kind": row[1],
                    "source_ref": row[2],
                    "name": row[3],
                }

    # Build native_tools_by_name once
    from ..tools import core_tools  # noqa: PLC0415

    native_tools_by_name: dict[str, Any] = {t.name: t for t in core_tools()}

    # 4. Build specialist agents in the canonical order
    # Canonical handoff order mirrors orchestrator.py lines 144-154.
    _CANONICAL_ORDER = ["scraper", "memory_keeper", "comms", "scheduler", "inboxer"]

    handoffs: list[Any] = []
    for slug in _CANONICAL_ORDER:
        spec = specs_by_slug.get(slug)
        if spec is None or spec.parent_slug != "orchestrator":
            continue
        specialist_agent = build_dynamic_agent(
            spec,
            settings,
            native_tools_by_name,
            mcp_servers=[],  # specialists don't get MCP in v1
            composio_tools=composio_tools,
            _tool_catalog=tool_catalog,
        )
        hf_callable = _resolve_handoff_filter(spec.handoff_filter)
        if hf_callable is not None:
            h = _agents.handoff(agent=specialist_agent, input_filter=hf_callable)
        else:
            h = _agents.handoff(agent=specialist_agent)
        handoffs.append(h)

    # Also include any non-canonical specialists in slug order so we don't
    # silently drop custom agents added via UI.
    canonical_set = set(_CANONICAL_ORDER)
    for spec in sorted(specs, key=lambda s: s.slug):
        if spec.slug in canonical_set or spec.slug == "orchestrator":
            continue
        if spec.parent_slug != "orchestrator":
            continue
        specialist_agent = build_dynamic_agent(
            spec,
            settings,
            native_tools_by_name,
            mcp_servers=[],
            composio_tools=composio_tools,
            _tool_catalog=tool_catalog,
        )
        hf_callable = _resolve_handoff_filter(spec.handoff_filter)
        if hf_callable is not None:
            h = _agents.handoff(agent=specialist_agent, input_filter=hf_callable)
        else:
            h = _agents.handoff(agent=specialist_agent)
        handoffs.append(h)

    # 5. Build orchestrator instructions using the same composer as the
    #    hardcoded builder so the string is byte-identical.
    from ..agents.orchestrator import build_orchestrator_instructions  # noqa: PLC0415

    instructions = build_orchestrator_instructions(settings)

    return _agents.Agent(
        name="orchestrator",
        instructions=instructions,
        model=build_model(settings, purpose=ModelPurpose.CHAT),
        model_settings=model_settings(settings, purpose=ModelPurpose.CHAT),
        tools=composio_tools or [],
        mcp_servers=mcp_servers or [],
        handoffs=handoffs,
    )
