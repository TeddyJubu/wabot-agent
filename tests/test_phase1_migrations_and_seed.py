"""Phase 1 — Schema migrations and seed determinism tests.

Covers:
1. Fresh DB: init_schema creates all 7 new tables.
2. Idempotency: running init_schema twice on the same connection is error-free
   and doesn't duplicate anything.
3. seed_builtin_subagents inserts exactly 6 rows, all with is_builtin=1.
   Re-running is a no-op.
4. The orchestrator row has parent_slug=NULL; the 5 specialists have
   parent_slug='orchestrator'. The two with remove_all_tools filter are
   correctly marked.
5. seed_tools_catalog inserts >= 30 native tool rows. Re-running is a no-op.
6. import_mcp_config_file with a missing file is a no-op. With a tmp JSON
   of one server, inserts one row with the right transport.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from wabot_agent.memory._migrations import init_schema
from wabot_agent.memory._seed import (
    import_mcp_config_file,
    seed_builtin_subagents,
    seed_tools_catalog,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "select name from sqlite_master where type='table'"
    ).fetchall()
    return {row["name"] for row in rows}


# ---------------------------------------------------------------------------
# 1. Fresh DB: all 7 new tables are created
# ---------------------------------------------------------------------------

_EXPECTED_PHASE1_TABLES = {
    "subagents",
    "tools",
    "subagent_tools",
    "skills",
    "subagent_skills",
    "mcp_servers",
    "composio_connections",
}


def test_fresh_db_creates_phase1_tables(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path / "fresh.db")
    init_schema(conn)
    tables = _table_names(conn)
    for expected in _EXPECTED_PHASE1_TABLES:
        assert expected in tables, f"Missing table: {expected}"
    conn.close()


# ---------------------------------------------------------------------------
# 2. Idempotency: running init_schema twice doesn't error or duplicate
# ---------------------------------------------------------------------------


def test_init_schema_is_idempotent(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path / "idempotent.db")
    init_schema(conn)
    # Second call must not raise
    init_schema(conn)
    tables = _table_names(conn)
    for expected in _EXPECTED_PHASE1_TABLES:
        assert expected in tables
    conn.close()


# ---------------------------------------------------------------------------
# 3. seed_builtin_subagents: exactly 6 rows, all is_builtin=1; re-run no-op
# ---------------------------------------------------------------------------


def test_seed_builtin_subagents_inserts_six_rows(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path / "seed_agents.db")
    init_schema(conn)

    seed_builtin_subagents(conn)
    conn.commit()

    rows = conn.execute("select * from subagents").fetchall()
    assert len(rows) == 6, f"Expected 6, got {len(rows)}"
    for row in rows:
        assert row["is_builtin"] == 1, f"Row {row['slug']} not marked builtin"


def test_seed_builtin_subagents_is_idempotent(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path / "seed_agents_idem.db")
    init_schema(conn)

    seed_builtin_subagents(conn)
    conn.commit()
    seed_builtin_subagents(conn)
    conn.commit()

    count = conn.execute("select count(*) from subagents").fetchone()[0]
    assert count == 6
    conn.close()


# ---------------------------------------------------------------------------
# 4. Orchestrator row has parent_slug=NULL; specialists have parent_slug='orchestrator'.
#    scraper and inboxer have handoff_filter='remove_all_tools'.
# ---------------------------------------------------------------------------


def test_orchestrator_has_null_parent(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path / "parents.db")
    init_schema(conn)
    seed_builtin_subagents(conn)
    conn.commit()

    row = conn.execute(
        "select parent_slug from subagents where slug='orchestrator'"
    ).fetchone()
    assert row is not None
    assert row["parent_slug"] is None


def test_specialists_have_orchestrator_parent(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path / "parents2.db")
    init_schema(conn)
    seed_builtin_subagents(conn)
    conn.commit()

    specialists = conn.execute(
        "select slug, parent_slug from subagents where slug != 'orchestrator'"
    ).fetchall()
    assert len(specialists) == 5
    for row in specialists:
        assert row["parent_slug"] == "orchestrator", (
            f"{row['slug']} has parent_slug={row['parent_slug']!r}"
        )


def test_remove_all_tools_filter_on_scraper_and_inboxer(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path / "filter.db")
    init_schema(conn)
    seed_builtin_subagents(conn)
    conn.commit()

    rows = conn.execute(
        "select slug, handoff_filter from subagents"
    ).fetchall()
    filters = {row["slug"]: row["handoff_filter"] for row in rows}

    # These two must have remove_all_tools
    assert filters["scraper"] == "remove_all_tools"
    assert filters["inboxer"] == "remove_all_tools"

    # The rest must have NULL
    for slug in ("orchestrator", "memory_keeper", "comms", "scheduler"):
        assert filters[slug] is None, (
            f"{slug} should have NULL handoff_filter, got {filters[slug]!r}"
        )


# ---------------------------------------------------------------------------
# 5. seed_tools_catalog: >= 30 rows inserted; re-running is a no-op
# ---------------------------------------------------------------------------


def test_seed_tools_catalog_inserts_at_least_30_rows(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path / "tools.db")
    init_schema(conn)
    seed_tools_catalog(conn)
    conn.commit()

    count = conn.execute("select count(*) from tools").fetchone()[0]
    assert count >= 30, f"Expected >= 30 native tools, got {count}"


def test_seed_tools_catalog_all_native_kind(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path / "tools_kind.db")
    init_schema(conn)
    seed_tools_catalog(conn)
    conn.commit()

    non_native = conn.execute(
        "select count(*) from tools where kind != 'native'"
    ).fetchone()[0]
    assert non_native == 0


def test_seed_tools_catalog_is_idempotent(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path / "tools_idem.db")
    init_schema(conn)
    seed_tools_catalog(conn)
    conn.commit()
    first_count = conn.execute("select count(*) from tools").fetchone()[0]

    seed_tools_catalog(conn)
    conn.commit()
    second_count = conn.execute("select count(*) from tools").fetchone()[0]

    assert first_count == second_count, "Re-running seed_tools_catalog duplicated rows"
    conn.close()


# ---------------------------------------------------------------------------
# 6. import_mcp_config_file: missing file is no-op; single-server JSON imports
# ---------------------------------------------------------------------------


class _FakeSettings:
    """Minimal stand-in for Settings used only in import_mcp_config_file."""

    def __init__(self, mcp_config: Path | None) -> None:
        self.mcp_config = mcp_config


def test_import_mcp_config_missing_file_is_noop(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path / "mcp_noop.db")
    init_schema(conn)
    fake = _FakeSettings(mcp_config=tmp_path / "nonexistent.json")
    import_mcp_config_file(conn, fake)
    conn.commit()

    count = conn.execute("select count(*) from mcp_servers").fetchone()[0]
    assert count == 0


def test_import_mcp_config_none_settings_is_noop(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path / "mcp_none.db")
    init_schema(conn)
    import_mcp_config_file(conn, None)  # type: ignore[arg-type]
    conn.commit()

    count = conn.execute("select count(*) from mcp_servers").fetchone()[0]
    assert count == 0


def test_import_mcp_config_stdio_transport(tmp_path: Path) -> None:
    config = {
        "my-server": {
            "command": "npx",
            "args": ["-y", "@some/mcp-server"],
            "env": {"API_KEY": "test"},
        }
    }
    config_file = tmp_path / "mcp.json"
    config_file.write_text(json.dumps(config))

    conn = _make_conn(tmp_path / "mcp_stdio.db")
    init_schema(conn)
    fake = _FakeSettings(mcp_config=config_file)
    import_mcp_config_file(conn, fake)
    conn.commit()

    rows = conn.execute("select * from mcp_servers").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "my-server"
    assert row["transport"] == "stdio"
    assert row["is_enabled"] == 1
    assert row["health_status"] == "unknown"
    stored = json.loads(row["config_json"])
    assert stored["command"] == "npx"
    conn.close()


def test_import_mcp_config_http_transport(tmp_path: Path) -> None:
    config = {
        "remote-server": {
            "url": "https://mcp.example.com/sse",
            "headers": {"Authorization": "Bearer token"},
        }
    }
    config_file = tmp_path / "mcp_http.json"
    config_file.write_text(json.dumps(config))

    conn = _make_conn(tmp_path / "mcp_http.db")
    init_schema(conn)
    fake = _FakeSettings(mcp_config=config_file)
    import_mcp_config_file(conn, fake)
    conn.commit()

    row = conn.execute("select transport from mcp_servers").fetchone()
    assert row["transport"] == "http"
    conn.close()


def test_import_mcp_config_skips_if_table_nonempty(tmp_path: Path) -> None:
    """If mcp_servers already has rows, the import is skipped (one-time only)."""
    config = {"server-a": {"command": "npx", "args": []}}
    config_file = tmp_path / "mcp.json"
    config_file.write_text(json.dumps(config))

    conn = _make_conn(tmp_path / "mcp_skip.db")
    init_schema(conn)

    # Pre-seed a row
    conn.execute(
        "insert into mcp_servers (name, transport, config_json, is_enabled, health_status)"
        " values ('existing', 'stdio', '{}', 1, 'ok')"
    )
    conn.commit()

    fake = _FakeSettings(mcp_config=config_file)
    import_mcp_config_file(conn, fake)
    conn.commit()

    count = conn.execute("select count(*) from mcp_servers").fetchone()[0]
    assert count == 1, "Should not import when table is non-empty"
    conn.close()


# ---------------------------------------------------------------------------
# BLOCKER 1: source_ref for native tools must use dotted format tools.<name>
# ---------------------------------------------------------------------------


def test_seed_tools_catalog_source_ref_format(tmp_path: Path) -> None:
    """Every native tool row must have source_ref = 'tools.<name>' (not 'native:<name>')."""
    conn = _make_conn(tmp_path / "tools_source_ref.db")
    init_schema(conn)
    seed_tools_catalog(conn)
    conn.commit()

    rows = conn.execute("select name, source_ref from tools").fetchall()
    assert len(rows) > 0, "Expected at least one tool row"
    for row in rows:
        expected = f"tools.{row['name']}"
        assert row["source_ref"] == expected, (
            f"Tool {row['name']!r}: expected source_ref={expected!r}, got {row['source_ref']!r}"
        )
    conn.close()


# ---------------------------------------------------------------------------
# BLOCKER 2: Upgrade from pre-Phase-1 DB preserves data and adds tables
# ---------------------------------------------------------------------------

_PRE_PHASE1_TABLES_DDL = """
    create table if not exists contact_facts (
        contact text not null,
        key text not null,
        value text not null,
        source text not null,
        updated_at text not null,
        primary key (contact, key)
    );
    create table if not exists agent_notes (
        key text primary key,
        value text not null,
        updated_at text not null
    );
    create table if not exists processed_messages (
        message_id text primary key,
        sender text,
        processed_at text not null,
        status text not null default 'done',
        run_id text,
        error text,
        retry_count integer not null default 0
    );
    create table if not exists runs (
        run_id text primary key,
        sender text,
        user_input text not null,
        final_output text not null,
        created_at text not null
    );
    create table if not exists tool_events (
        id integer primary key autoincrement,
        run_id text not null,
        name text not null,
        payload text not null,
        created_at text not null
    );
    create table if not exists inbound_messages (
        id text primary key,
        sender text not null,
        chat text,
        text text not null,
        timestamp text,
        push_name text,
        is_group integer not null default 0,
        media_kind text,
        media_mime text,
        media_filename text,
        has_media integer not null default 0,
        recorded_at text not null
    );
    create table if not exists session_summaries (
        session_id text primary key,
        summary text not null,
        updated_at text not null
    );
    create table if not exists scheduled_reminders (
        reminder_id text primary key,
        requester_jid text not null,
        target_jid text,
        message text not null,
        due_at text not null,
        status text not null default 'pending',
        idempotency_key text unique,
        created_at text not null,
        claimed_at text,
        fired_at text,
        error text
    );
    create table if not exists outbound_tasks (
        task_id text primary key,
        owner_jid text not null,
        target_jid text not null,
        chat_jid text not null,
        prompt_summary text,
        sent_message_id text,
        notify_owner integer not null default 1,
        status text not null default 'pending',
        created_at text not null,
        expires_at text not null,
        completed_at text,
        reply_text text,
        reply_message_id text
    );
    create table if not exists web_research_jobs (
        job_id text primary key,
        requester_jid text not null,
        prompt text not null,
        title text,
        output_format text not null default 'markdown',
        schema_json text,
        status text not null default 'pending',
        created_at text not null,
        claimed_at text,
        completed_at text,
        error text,
        result_path text,
        preview text,
        duration_ms integer,
        steps integer
    );
"""

_ALL_17_TABLES = {
    # original 10
    "contact_facts",
    "agent_notes",
    "processed_messages",
    "runs",
    "tool_events",
    "inbound_messages",
    "session_summaries",
    "scheduled_reminders",
    "outbound_tasks",
    "web_research_jobs",
    # Phase 1 additions
    "subagents",
    "tools",
    "subagent_tools",
    "skills",
    "subagent_skills",
    "mcp_servers",
    "composio_connections",
}


def test_upgrade_from_pre_phase1_db_preserves_data_and_adds_tables(tmp_path: Path) -> None:
    """Simulates upgrading an existing pre-Phase-1 database.

    Steps:
    1. Create the original 10 tables and insert a sentinel row in contact_facts.
    2. Run init_schema (must add 7 new tables without touching existing data).
    3. Run all seeds.
    4. Assert all 17 tables exist, sentinel row is intact, 6 builtin subagents
       are present, and the native tools catalog is populated.
    """
    conn = _make_conn(tmp_path / "upgrade.db")

    # Step 1: simulate a pre-Phase-1 install
    conn.executescript(_PRE_PHASE1_TABLES_DDL)
    conn.execute(
        "insert into contact_facts (contact, key, value, source, updated_at)"
        " values ('+1sentinel@s.whatsapp.net', 'test_key', 'test_value',"
        " 'test', '2024-01-01T00:00:00')"
    )
    conn.commit()

    # Step 2: run init_schema — should add the 7 Phase 1 tables
    init_schema(conn)
    conn.commit()

    # Step 3: run seeds
    seed_builtin_subagents(conn)
    conn.commit()
    seed_tools_catalog(conn)
    conn.commit()

    # Step 4a: all 17 tables exist
    tables = _table_names(conn)
    for expected in _ALL_17_TABLES:
        assert expected in tables, f"Missing table after upgrade: {expected}"

    # Step 4b: sentinel row is still there (user data was not destroyed)
    row = conn.execute(
        "select value from contact_facts"
        " where contact='+1sentinel@s.whatsapp.net' and key='test_key'"
    ).fetchone()
    assert row is not None, "Sentinel row in contact_facts was destroyed by upgrade"
    assert row["value"] == "test_value"

    # Step 4c: 6 builtin subagents seeded
    agent_count = conn.execute("select count(*) from subagents").fetchone()[0]
    assert agent_count == 6, f"Expected 6 builtin subagents, got {agent_count}"

    # Step 4d: native tools catalog populated
    tool_count = conn.execute("select count(*) from tools").fetchone()[0]
    assert tool_count >= 30, f"Expected >= 30 native tools, got {tool_count}"

    conn.close()


# ---------------------------------------------------------------------------
# SHOULD FIX 3: Unique index on (kind, source_ref) rejects duplicate inserts
# ---------------------------------------------------------------------------


def test_tools_unique_index_rejects_duplicate_kind_source_ref(tmp_path: Path) -> None:
    """The unique index on (kind, source_ref) must reject a plain duplicate INSERT."""
    conn = _make_conn(tmp_path / "tools_unique.db")
    init_schema(conn)

    conn.execute(
        "insert into tools (kind, source_ref, name, description, is_enabled)"
        " values ('native', 'tools.some_tool', 'some_tool', 'desc', 1)"
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "insert into tools (kind, source_ref, name, description, is_enabled)"
            " values ('native', 'tools.some_tool', 'some_tool', 'desc', 1)"
        )

    conn.close()
