"""Phase 6 — Metrics API tests + migration tests.

100% offline: no LLM or network calls.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wabot_agent.api import create_app
from wabot_agent.config import Settings
from wabot_agent.memory import MemoryStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_settings(tmp_path: Path) -> Settings:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path / "data",
        WABOT_AGENT_DB_PATH=tmp_path / "data" / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "data" / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "data" / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SKILLS_DIR=tmp_path / "skills",
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="test-inbound",
        WABOT_AGENT_BACKGROUND_HEALTH_CHECKS_ENABLED=False,
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )


def auth_headers(settings: Settings) -> dict[str, str]:
    return {"X-Operator-Token": settings.operator_token or ""}


@pytest.fixture
def ctx(tmp_path: Path):
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    client = TestClient(create_app(settings), raise_server_exceptions=True)
    return client, settings


# ---------------------------------------------------------------------------
# Task 6.1 — Migration tests
# ---------------------------------------------------------------------------


class TestPhase6Migrations:
    def test_new_db_has_all_columns(self, tmp_path: Path):
        """A fresh DB must have all 7 new columns on the runs table."""
        db = tmp_path / "fresh.db"
        store = MemoryStore(db)
        with store.connect() as conn:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        expected = {
            "subagent_slug", "model", "provider",
            "prompt_tokens", "completion_tokens", "cost_usd", "latency_ms",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_pre_phase6_db_migrates_cleanly(self, tmp_path: Path):
        """A DB with only original runs columns must have new columns added."""
        db = tmp_path / "legacy.db"
        # Create the table WITHOUT the new columns (simulates pre-Phase-6 DB)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                sender TEXT,
                user_input TEXT,
                final_output TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        # Insert a row to ensure data is preserved
        conn.execute(
            "INSERT INTO runs (run_id, sender, user_input, final_output, created_at) "
            "VALUES ('legacy-1', '123', 'hello', 'world', datetime('now'))"
        )
        conn.commit()
        conn.close()

        # Now open via MemoryStore which runs init_schema / migrations
        store = MemoryStore(db)
        with store.connect() as conn:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
            # Data must be preserved
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = 'legacy-1'"
            ).fetchone()

        expected_new = {
            "subagent_slug", "model", "provider",
            "prompt_tokens", "completion_tokens", "cost_usd", "latency_ms",
        }
        assert expected_new.issubset(cols), f"Missing after migration: {expected_new - cols}"
        assert row is not None, "Existing data row was lost during migration"
        assert row["final_output"] == "world"


# ---------------------------------------------------------------------------
# Task 6.5 — Auth required on all endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/metrics/overview",
        "/api/metrics/runs",
        "/api/metrics/tools",
        "/api/metrics/costs",
        "/api/metrics/health",
    ],
)
def test_auth_required(ctx, path):
    client, _ = ctx
    resp = client.get(path)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Task 6.4 — get_overview
# ---------------------------------------------------------------------------


class TestGetOverview:
    def test_empty_db_returns_zeros(self, ctx):
        client, settings = ctx
        resp = client.get("/api/metrics/overview", headers=auth_headers(settings))
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages_today"] == 0
        assert data["runs_today"] == 0
        assert data["cost_usd_24h"] == 0.0
        assert data["avg_latency_ms_24h"] is None
        assert data["queue_depth"] == 0
        assert data["integrations_health"]["ok"] == 0
        assert data["integrations_health"]["error"] == 0

    def test_no_division_by_zero_on_delta(self, ctx):
        """When yesterday = 0, delta_pct should be null not an error."""
        client, settings = ctx
        resp = client.get("/api/metrics/overview", headers=auth_headers(settings))
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages_today_delta_pct"] is None
        assert data["runs_today_delta_pct"] is None

    def test_with_data(self, tmp_path: Path):
        settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
        store = MemoryStore(settings.db_path, settings)

        now = datetime.now(UTC)
        yesterday = now - timedelta(days=1)

        with store.connect() as conn:
            # 3 messages today
            for i in range(3):
                conn.execute(
                    "INSERT INTO inbound_messages (message_id, sender, text, received_at) "
                    "VALUES (?, 'sender', 'hi', ?)",
                    (f"msg-{i}", now.isoformat()),
                )
            # 1 message yesterday
            conn.execute(
                "INSERT INTO inbound_messages (message_id, sender, text, received_at) "
                "VALUES ('msg-y1', 'sender', 'hi', ?)",
                (yesterday.isoformat(),),
            )
            # 2 runs today with cost
            for i in range(2):
                conn.execute(
                    "INSERT INTO runs (run_id, created_at, cost_usd, latency_ms) "
                    "VALUES (?, ?, 0.01, 500)",
                    (f"run-{i}", now.isoformat()),
                )
            # 1 pending outbound task
            import uuid
            tid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO outbound_tasks "
                "(id, owner_jid, target_jid, chat_jid, status, sent_at, expires_at) "
                "VALUES (?, 'owner', 'target', 'chat', 'pending', ?, datetime('now','+7 days'))",
                (tid, now.isoformat()),
            )
            conn.commit()

        client = TestClient(create_app(settings), raise_server_exceptions=True)
        resp = client.get("/api/metrics/overview", headers=auth_headers(settings))
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages_today"] == 3
        assert data["runs_today"] == 2
        assert data["cost_usd_24h"] > 0
        assert data["queue_depth"] == 1
        # delta_pct: 3 today vs 1 yesterday = 200%
        assert data["messages_today_delta_pct"] == pytest.approx(200.0, rel=0.01)


# ---------------------------------------------------------------------------
# Task 6.4 — get_runs_series
# ---------------------------------------------------------------------------


class TestGetRunsSeries:
    def test_empty_returns_empty_series(self, ctx):
        client, settings = ctx
        resp = client.get(
            "/api/metrics/runs?window=24h&bucket=hour",
            headers=auth_headers(settings),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["window"] == "24h"
        assert data["bucket"] == "hour"
        assert data["series"] == []

    def test_runs_bucketed_by_hour(self, tmp_path: Path):
        settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
        store = MemoryStore(settings.db_path, settings)

        now = datetime.now(UTC)
        two_hours_ago = now - timedelta(hours=2)
        # 3 runs in current hour, 2 runs 2 hours ago
        with store.connect() as conn:
            for i in range(3):
                conn.execute(
                    "INSERT INTO runs (run_id, created_at, subagent_slug) "
                    "VALUES (?, ?, 'orchestrator')",
                    (f"r-now-{i}", now.isoformat()),
                )
            for i in range(2):
                conn.execute(
                    "INSERT INTO runs (run_id, created_at, subagent_slug) "
                    "VALUES (?, ?, 'scraper')",
                    (f"r-old-{i}", two_hours_ago.isoformat()),
                )
            conn.commit()

        client = TestClient(create_app(settings), raise_server_exceptions=True)
        resp = client.get(
            "/api/metrics/runs?window=24h&bucket=hour",
            headers=auth_headers(settings),
        )
        assert resp.status_code == 200
        data = resp.json()
        total = sum(b["count"] for b in data["series"])
        assert total == 5

    def test_outside_window_excluded(self, tmp_path: Path):
        """Run from 25 hours ago must not appear in window=24h."""
        settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
        store = MemoryStore(settings.db_path, settings)

        # Use a timestamp 30 hours ago formatted as naive UTC string
        # (matching what SQLite datetime('now') returns) to avoid boundary issues
        now = datetime.now(UTC)
        old = now - timedelta(hours=30)
        old_str = old.strftime("%Y-%m-%d %H:%M:%S")
        with store.connect() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, created_at) VALUES ('old-run', ?)",
                (old_str,),
            )
            conn.commit()

        client = TestClient(create_app(settings), raise_server_exceptions=True)
        resp = client.get(
            "/api/metrics/runs?window=24h&bucket=hour",
            headers=auth_headers(settings),
        )
        data = resp.json()
        total = sum(b["count"] for b in data["series"])
        assert total == 0

    def test_different_windows(self, ctx):
        client, settings = ctx
        for window in ("1h", "24h", "7d", "30d"):
            resp = client.get(
                f"/api/metrics/runs?window={window}",
                headers=auth_headers(settings),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["window"] == window


# ---------------------------------------------------------------------------
# Task 6.4 — get_top_tools
# ---------------------------------------------------------------------------


class TestGetTopTools:
    def test_empty_returns_empty(self, ctx):
        client, settings = ctx
        resp = client.get("/api/metrics/tools?window=24h&limit=10", headers=auth_headers(settings))
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []

    def test_sorted_by_invocations(self, tmp_path: Path):
        settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
        store = MemoryStore(settings.db_path, settings)

        now = datetime.now(UTC)
        with store.connect() as conn:
            # 5 search_web events, 2 wabot_health events
            for _i in range(5):
                conn.execute(
                    "INSERT INTO tool_events (run_id, name, payload, created_at) "
                    "VALUES ('r1', 'search_web', '{}', ?)",
                    (now.isoformat(),),
                )
            for _i in range(2):
                conn.execute(
                    "INSERT INTO tool_events (run_id, name, payload, created_at) "
                    "VALUES ('r1', 'wabot_health', '{}', ?)",
                    (now.isoformat(),),
                )
            conn.commit()

        client = TestClient(create_app(settings), raise_server_exceptions=True)
        resp = client.get("/api/metrics/tools?window=24h&limit=10", headers=auth_headers(settings))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        assert items[0]["tool_name"] == "search_web"
        assert items[0]["invocations"] == 5
        assert items[1]["tool_name"] == "wabot_health"
        assert items[1]["invocations"] == 2

    def test_limit_respected(self, tmp_path: Path):
        settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
        store = MemoryStore(settings.db_path, settings)

        now = datetime.now(UTC)
        with store.connect() as conn:
            for tool in ["tool_a", "tool_b", "tool_c"]:
                conn.execute(
                    "INSERT INTO tool_events (run_id, name, payload, created_at) "
                    "VALUES ('r1', ?, '{}', ?)",
                    (tool, now.isoformat()),
                )
            conn.commit()

        client = TestClient(create_app(settings), raise_server_exceptions=True)
        resp = client.get("/api/metrics/tools?window=24h&limit=2", headers=auth_headers(settings))
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2


# ---------------------------------------------------------------------------
# Task 6.4 — get_costs
# ---------------------------------------------------------------------------


class TestGetCosts:
    def test_empty_db_returns_zero(self, ctx):
        client, settings = ctx
        resp = client.get("/api/metrics/costs?window=24h", headers=auth_headers(settings))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_usd"] == 0.0
        assert data["by_day"] == []
        assert data["by_provider"] == []

    def test_sums_correctly(self, tmp_path: Path):
        settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
        store = MemoryStore(settings.db_path, settings)

        now = datetime.now(UTC)
        with store.connect() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, created_at, cost_usd, provider, model) "
                "VALUES ('r1', ?, 0.05, 'openai', 'gpt-4o')",
                (now.isoformat(),),
            )
            conn.execute(
                "INSERT INTO runs (run_id, created_at, cost_usd, provider, model) "
                "VALUES ('r2', ?, 0.03, 'openai', 'gpt-4o-mini')",
                (now.isoformat(),),
            )
            conn.execute(
                "INSERT INTO runs (run_id, created_at, cost_usd, provider, model) "
                "VALUES ('r3', ?, 0.02, 'anthropic', 'claude-sonnet-4-6')",
                (now.isoformat(),),
            )
            conn.commit()

        client = TestClient(create_app(settings), raise_server_exceptions=True)
        resp = client.get("/api/metrics/costs?window=24h", headers=auth_headers(settings))
        assert resp.status_code == 200
        data = resp.json()
        assert abs(data["total_usd"] - 0.10) < 0.001
        providers = {p["provider"] for p in data["by_provider"]}
        assert "openai" in providers
        assert "anthropic" in providers
        openai_entry = next(p for p in data["by_provider"] if p["provider"] == "openai")
        assert abs(openai_entry["usd"] - 0.08) < 0.001
        assert "gpt-4o" in openai_entry["model_breakdown"]


# ---------------------------------------------------------------------------
# Task 6.4 — get_health
# ---------------------------------------------------------------------------


class TestGetHealth:
    def test_empty_db(self, ctx):
        client, settings = ctx
        resp = client.get("/api/metrics/health", headers=auth_headers(settings))
        assert resp.status_code == 200
        data = resp.json()
        assert "wabot_daemon" in data
        assert "mcp_servers" in data
        assert "composio" in data
        assert data["mcp_servers"] == []
        assert data["composio"]["connections_count"] == 0

    def test_mcp_servers_grouped(self, tmp_path: Path):
        settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
        store = MemoryStore(settings.db_path, settings)

        with store.connect() as conn:
            conn.execute(
                "INSERT INTO mcp_servers (name, transport, config_json, health_status) "
                "VALUES ('server-ok', 'http', '{\"url\":\"http://x\"}', 'ok')"
            )
            conn.execute(
                "INSERT INTO mcp_servers (name, transport, config_json, health_status) "
                "VALUES ('server-err', 'http', '{\"url\":\"http://y\"}', 'error')"
            )
            conn.execute(
                "INSERT INTO composio_connections "
                "(app_slug, display_name, status, user_id) "
                "VALUES ('gmail', 'Gmail', 'connected', NULL)"
            )
            conn.commit()

        client = TestClient(create_app(settings), raise_server_exceptions=True)
        resp = client.get("/api/metrics/health", headers=auth_headers(settings))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["mcp_servers"]) == 2
        statuses = {s["status"] for s in data["mcp_servers"]}
        assert "ok" in statuses
        assert "error" in statuses
        assert data["composio"]["connections_count"] == 1
        assert data["composio"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Phase 6 review BLOCKER 2: SQL-injection defence in get_runs_series
# ---------------------------------------------------------------------------


def test_get_runs_series_rejects_unsafe_bucket_format(tmp_path):
    """Calling get_runs_series directly (bypassing the route whitelist)
    with a forged strftime format must raise ValueError, not execute SQL.

    Guards against accidental regression if anyone modifies _bucket_fmt
    to return user-controlled values without re-checking them at the
    SQL-construction site.
    """
    from unittest.mock import patch

    from wabot_agent.metrics_service import get_runs_series

    store = MemoryStore(tmp_path / "agent.db")

    with patch(
        "wabot_agent.metrics_service._bucket_fmt",
        return_value="')||sqlite_version()--",
    ):
        with pytest.raises(ValueError, match="unsafe bucket format"):
            get_runs_series(store, window="24h", bucket="hour")


def test_get_runs_series_accepts_all_legitimate_bucket_values(tmp_path):
    """All values in the _BUCKET_STRFTIME dict must pass the
    defence-in-depth guard so no real bucket gets rejected."""
    from wabot_agent.metrics_service import _BUCKET_STRFTIME, get_runs_series

    store = MemoryStore(tmp_path / "agent.db")
    for bucket in _BUCKET_STRFTIME:
        result = get_runs_series(store, window="24h", bucket=bucket)
        assert "series" in result
