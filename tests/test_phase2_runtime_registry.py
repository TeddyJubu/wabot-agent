"""Phase 2 — Runtime registry tests.

Covers:
1. load_subagent_specs returns exactly 6 specs on a freshly-seeded DB, slugs sorted.
2. tool_ids is empty for builtins (Phase 1 seed doesn't insert subagent_tools rows);
   a fake join row appears correctly via the JOIN.
3. build_dynamic_agent builds an agents.Agent with the right name and instructions
   for a spec with empty tool_ids.
4. build_orchestrator_from_db produces an agents.Agent whose name, instructions,
   handoff count (5), and target names match build_orchestrator(settings).
5. Snapshot equivalence: same name, same instructions string, same handoff count /
   order, same handoff_filter per handoff.
6. subagents_updated_at returns a non-empty string after seed.
7. Flag default: settings.subagents_db_enabled is False unless env var is set.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from wabot_agent.agents.registry import (
    SubagentSpec,
    build_dynamic_agent,
    build_orchestrator_from_db,
    load_subagent_specs,
)
from wabot_agent.instructions_cache import subagents_updated_at
from wabot_agent.memory._migrations import init_schema
from wabot_agent.memory._seed import seed_builtin_subagents, seed_tools_catalog

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


class _FakeStore:
    """Minimal MemoryStore stand-in that wraps a raw sqlite3 connection.

    Only implements the `connect()` context manager that the registry
    functions use.
    """

    def __init__(self, db_path: Path) -> None:
        self.path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    class _CM:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn

        def __enter__(self) -> sqlite3.Connection:
            return self._conn

        def __exit__(self, *_: Any) -> None:
            try:
                self._conn.commit()
            except Exception:
                pass

    def connect(self):  # type: ignore[return]
        return self._CM(self._get_conn())


def _seeded_store(tmp_path: Path) -> _FakeStore:
    db = tmp_path / "test.db"
    conn = _make_conn(db)
    init_schema(conn)
    seed_builtin_subagents(conn)
    seed_tools_catalog(conn)
    conn.commit()
    conn.close()
    return _FakeStore(db)


def _minimal_settings() -> Any:
    """Return a real Settings instance with no live-model keys set."""
    # Use environment isolation so we don't need an actual .env on disk.
    from wabot_agent.config import Settings

    return Settings(
        _env_file=None,  # type: ignore[call-arg]
    )


# ---------------------------------------------------------------------------
# 1. load_subagent_specs returns 6 specs, slugs sorted
# ---------------------------------------------------------------------------


def test_load_subagent_specs_returns_six_specs(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    specs = load_subagent_specs(store)
    assert len(specs) == 6, f"Expected 6, got {len(specs)}: {[s.slug for s in specs]}"


def test_load_subagent_specs_slugs_are_sorted(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    specs = load_subagent_specs(store)
    slugs = [s.slug for s in specs]
    assert slugs == sorted(slugs), f"Slugs not sorted: {slugs}"


def test_load_subagent_specs_all_are_builtin(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    specs = load_subagent_specs(store)
    for s in specs:
        assert s.is_builtin, f"Spec {s.slug} is not marked builtin"


def test_load_subagent_specs_returns_subagentspec_instances(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    specs = load_subagent_specs(store)
    for s in specs:
        assert isinstance(s, SubagentSpec)


# ---------------------------------------------------------------------------
# 2. tool_ids is empty for builtins; fake join row appears
# ---------------------------------------------------------------------------


def test_load_subagent_specs_tool_ids_empty_for_builtins(tmp_path: Path) -> None:
    """Phase 1 seed doesn't populate subagent_tools.  All builtins should have
    empty tool_ids for now; Phase 3 UI will fill the join table."""
    store = _seeded_store(tmp_path)
    specs = load_subagent_specs(store)
    for s in specs:
        assert s.tool_ids == (), (
            f"Spec {s.slug} should have empty tool_ids; got {s.tool_ids}"
        )


def test_load_subagent_specs_fake_join_row_appears(tmp_path: Path) -> None:
    """Inserting a row into subagent_tools should make it appear in tool_ids."""
    store = _seeded_store(tmp_path)

    # Get the scraper subagent id and first tool id
    with store.connect() as conn:
        scraper_id = conn.execute(
            "select id from subagents where slug='scraper'"
        ).fetchone()[0]
        tool_id = conn.execute("select id from tools limit 1").fetchone()[0]

        conn.execute(
            "insert or ignore into subagent_tools (subagent_id, tool_id) values (?, ?)",
            (scraper_id, tool_id),
        )
        conn.commit()

    specs = load_subagent_specs(store)
    scraper_spec = next(s for s in specs if s.slug == "scraper")
    assert tool_id in scraper_spec.tool_ids, (
        f"Expected tool_id {tool_id} in scraper.tool_ids {scraper_spec.tool_ids}"
    )


# ---------------------------------------------------------------------------
# 3. build_dynamic_agent builds an Agent with the right name and instructions
# ---------------------------------------------------------------------------


def test_build_dynamic_agent_returns_agent_with_correct_name_and_instructions(
    tmp_path: Path,
) -> None:
    import agents as _agents

    store = _seeded_store(tmp_path)
    specs = load_subagent_specs(store)
    scraper_spec = next(s for s in specs if s.slug == "scraper")

    settings = _minimal_settings()
    agent = build_dynamic_agent(
        scraper_spec,
        settings,
        native_tools_by_name={},
        mcp_servers=[],
        composio_tools=[],
    )

    assert isinstance(agent, _agents.Agent)
    # name uses spec.slug (not display_name) so Agents SDK handoff tool
    # names like "transfer_to_scraper" stay valid identifiers; display_name
    # is a UI concern and may contain spaces/capitals.
    assert agent.name == scraper_spec.slug
    assert agent.instructions == scraper_spec.instructions


def test_build_dynamic_agent_empty_tool_ids_gives_no_tools(tmp_path: Path) -> None:
    import agents as _agents

    store = _seeded_store(tmp_path)
    specs = load_subagent_specs(store)
    scraper_spec = next(s for s in specs if s.slug == "scraper")
    assert scraper_spec.tool_ids == ()

    settings = _minimal_settings()
    agent = build_dynamic_agent(
        scraper_spec,
        settings,
        native_tools_by_name={},
        mcp_servers=[],
        composio_tools=[],
    )

    assert isinstance(agent, _agents.Agent)
    # With empty tool_ids the agent should have no resolved tools
    assert agent.tools == [] or agent.tools is None or list(agent.tools) == []


# ---------------------------------------------------------------------------
# 4. build_orchestrator_from_db produces matching structure
# ---------------------------------------------------------------------------


def test_build_orchestrator_from_db_produces_five_handoffs(tmp_path: Path) -> None:
    import agents as _agents

    store = _seeded_store(tmp_path)
    settings = _minimal_settings()
    orch = build_orchestrator_from_db(settings, store, mcp_servers=[], composio_tools=[])

    assert isinstance(orch, _agents.Agent)
    assert orch.name == "orchestrator"
    assert len(orch.handoffs) == 5, (
        f"Expected 5 handoffs, got {len(orch.handoffs)}"
    )


def test_build_orchestrator_from_db_handoff_target_names_match_hardcoded(
    tmp_path: Path,
) -> None:
    """The DB-built orchestrator's handoff target names must match those
    produced by the hardcoded build_orchestrator."""
    from wabot_agent.agents.orchestrator import build_orchestrator

    store = _seeded_store(tmp_path)
    settings = _minimal_settings()

    db_orch = build_orchestrator_from_db(settings, store, mcp_servers=[], composio_tools=[])
    hc_orch = build_orchestrator(settings, mcp_servers=[], composio_tools=[])

    def _handoff_target_name(h: Any) -> str:
        # agents.Handoff exposes the target via .agent or .agent_name
        if hasattr(h, "agent_name"):
            return h.agent_name
        if hasattr(h, "agent") and h.agent is not None:
            return h.agent.name
        return str(h)

    db_names = [_handoff_target_name(h) for h in db_orch.handoffs]
    hc_names = [_handoff_target_name(h) for h in hc_orch.handoffs]

    assert db_names == hc_names, (
        f"DB handoff names: {db_names}\nHardcoded: {hc_names}"
    )


# ---------------------------------------------------------------------------
# 5. Snapshot equivalence: name, instructions, handoff count/order, filters
# ---------------------------------------------------------------------------


def test_snapshot_equivalence_name(tmp_path: Path) -> None:
    from wabot_agent.agents.orchestrator import build_orchestrator

    store = _seeded_store(tmp_path)
    settings = _minimal_settings()

    db_orch = build_orchestrator_from_db(settings, store, mcp_servers=[], composio_tools=[])
    hc_orch = build_orchestrator(settings, mcp_servers=[], composio_tools=[])

    assert db_orch.name == hc_orch.name


def test_snapshot_equivalence_instructions(tmp_path: Path) -> None:
    from wabot_agent.agents.orchestrator import build_orchestrator

    store = _seeded_store(tmp_path)
    settings = _minimal_settings()

    db_orch = build_orchestrator_from_db(settings, store, mcp_servers=[], composio_tools=[])
    hc_orch = build_orchestrator(settings, mcp_servers=[], composio_tools=[])

    assert db_orch.instructions == hc_orch.instructions, (
        "instructions mismatch between DB-built and hardcoded orchestrator"
    )


def test_snapshot_equivalence_handoff_count_and_order(tmp_path: Path) -> None:
    from wabot_agent.agents.orchestrator import build_orchestrator

    store = _seeded_store(tmp_path)
    settings = _minimal_settings()

    db_orch = build_orchestrator_from_db(settings, store, mcp_servers=[], composio_tools=[])
    hc_orch = build_orchestrator(settings, mcp_servers=[], composio_tools=[])

    assert len(db_orch.handoffs) == len(hc_orch.handoffs), (
        f"handoff count: DB={len(db_orch.handoffs)}, hardcoded={len(hc_orch.handoffs)}"
    )

    def _handoff_target_name(h: Any) -> str:
        if hasattr(h, "agent_name"):
            return h.agent_name
        if hasattr(h, "agent") and h.agent is not None:
            return h.agent.name
        return str(h)

    db_names = [_handoff_target_name(h) for h in db_orch.handoffs]
    hc_names = [_handoff_target_name(h) for h in hc_orch.handoffs]
    assert db_names == hc_names


def test_snapshot_equivalence_handoff_filters(tmp_path: Path) -> None:
    """Verify that handoff filters match: scraper and inboxer get
    remove_all_tools; the others get None."""
    from agents.extensions.handoff_filters import remove_all_tools

    from wabot_agent.agents.orchestrator import build_orchestrator

    store = _seeded_store(tmp_path)
    settings = _minimal_settings()

    db_orch = build_orchestrator_from_db(settings, store, mcp_servers=[], composio_tools=[])
    hc_orch = build_orchestrator(settings, mcp_servers=[], composio_tools=[])

    def _filter_name(h: Any) -> str | None:
        # Handoff stores the filter as input_filter attribute
        f = getattr(h, "input_filter", None)
        if f is None:
            return None
        if f is remove_all_tools:
            return "remove_all_tools"
        # Compare by name for forward compat
        return getattr(f, "__name__", None) or str(f)

    db_filters = [_filter_name(h) for h in db_orch.handoffs]
    hc_filters = [_filter_name(h) for h in hc_orch.handoffs]

    assert db_filters == hc_filters, (
        f"filter mismatch:\n  DB:  {db_filters}\n  HC:  {hc_filters}"
    )


# ---------------------------------------------------------------------------
# 6. subagents_updated_at returns a non-empty string after seed
# ---------------------------------------------------------------------------


def test_subagents_updated_at_non_empty_after_seed(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    result = subagents_updated_at(store)
    assert result != "", "Expected non-empty updated_at after seed"


def test_subagents_updated_at_none_store_returns_empty() -> None:
    result = subagents_updated_at(None)
    assert result == ""


# ---------------------------------------------------------------------------
# 7. Flag default: subagents_db_enabled is False unless env var is set
# ---------------------------------------------------------------------------


def test_subagents_db_enabled_default_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure neither env var is set
    monkeypatch.delenv("WABOT_AGENT_SUBAGENTS_DB_ENABLED", raising=False)
    monkeypatch.delenv("SUBAGENTS_DB_ENABLED", raising=False)

    from wabot_agent.config import Settings

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.subagents_db_enabled is False


def test_subagents_db_enabled_true_via_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WABOT_AGENT_SUBAGENTS_DB_ENABLED", "true")

    from wabot_agent.config import Settings

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.subagents_db_enabled is True


def test_subagents_db_enabled_true_via_short_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WABOT_AGENT_SUBAGENTS_DB_ENABLED", raising=False)
    monkeypatch.setenv("SUBAGENTS_DB_ENABLED", "1")

    from wabot_agent.config import Settings

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.subagents_db_enabled is True


# ---------------------------------------------------------------------------
# 8. build_dynamic_agent resolves native tools from tool_ids (BLOCKER 2)
# ---------------------------------------------------------------------------


def test_build_dynamic_agent_resolves_native_tools_from_tool_ids(tmp_path: Path) -> None:
    """build_dynamic_agent with a _tool_catalog must resolve native tool_ids to
    real callables from native_tools_by_name."""
    import agents as _agents

    from wabot_agent.tools import core_tools

    settings = _minimal_settings()

    # Pick the first tool in core_tools() to use as the target.
    all_native = core_tools()
    assert all_native, "core_tools() must return at least one tool"
    target_tool = all_native[0]
    native_tools_by_name = {t.name: t for t in all_native}

    # Build a spec that references a fake tool_id=999 pointing at target_tool.
    fake_catalog: dict[int, dict] = {
        999: {
            "kind": "native",
            "source_ref": f"tools.{target_tool.name}",
            "name": target_tool.name,
        },
    }
    spec = SubagentSpec(
        id=1,
        slug="test_agent",
        display_name="Test Agent",
        description=None,
        instructions="Do stuff.",
        is_builtin=False,
        is_enabled=True,
        parent_slug="orchestrator",
        handoff_filter=None,
        tool_ids=(999,),
    )

    agent = build_dynamic_agent(
        spec,
        settings,
        native_tools_by_name=native_tools_by_name,
        mcp_servers=[],
        composio_tools=[],
        _tool_catalog=fake_catalog,
    )

    assert isinstance(agent, _agents.Agent)
    resolved_names = [getattr(t, "name", None) for t in (agent.tools or [])]
    assert target_tool.name in resolved_names, (
        f"Expected {target_tool.name!r} in resolved tools {resolved_names}"
    )
    assert len(agent.tools) == 1, (
        f"Expected exactly 1 tool, got {len(agent.tools)}: {resolved_names}"
    )


# ---------------------------------------------------------------------------
# 9. Snapshot equivalence — specialist instructions must match (SHOULD FIX 3)
# ---------------------------------------------------------------------------


def test_snapshot_equivalence_specialist_instructions(tmp_path: Path) -> None:
    """Each specialist built from DB must have byte-identical instructions to
    its hardcoded counterpart, matched by slug."""
    from wabot_agent.agents.comms import build_comms
    from wabot_agent.agents.inboxer import build_inboxer
    from wabot_agent.agents.memory_keeper import build_memory_keeper
    from wabot_agent.agents.scheduler import build_scheduler
    from wabot_agent.agents.scraper import build_scraper

    store = _seeded_store(tmp_path)
    settings = _minimal_settings()

    # Hardcoded specialists, keyed on their Agent.name (which is the slug).
    hc_builders = {
        "scraper": build_scraper,
        "memory_keeper": build_memory_keeper,
        "comms": build_comms,
        "scheduler": build_scheduler,
        "inboxer": build_inboxer,
    }
    hc_by_slug = {slug: builder(settings) for slug, builder in hc_builders.items()}

    # DB-built specialists via the same build_dynamic_agent path the
    # orchestrator uses. Empty tool catalogs are fine for instruction
    # equivalence — instructions don't depend on tools.
    specs = load_subagent_specs(store)
    db_by_slug = {
        spec.slug: build_dynamic_agent(
            spec,
            settings,
            native_tools_by_name={},
            mcp_servers=[],
            composio_tools=[],
        )
        for spec in specs
        if spec.slug in hc_builders
    }

    assert set(db_by_slug) == set(hc_by_slug), (
        f"Specialist sets differ: db={set(db_by_slug)} hardcoded={set(hc_by_slug)}"
    )

    for slug in hc_by_slug:
        assert db_by_slug[slug].instructions == hc_by_slug[slug].instructions, (
            f"Specialist {slug!r} instructions diverge between DB and hardcoded path"
        )
        assert db_by_slug[slug].name == hc_by_slug[slug].name, (
            f"Specialist {slug!r} Agent.name differs: "
            f"db={db_by_slug[slug].name!r} hc={hc_by_slug[slug].name!r}"
        )
