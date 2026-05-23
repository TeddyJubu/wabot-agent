"""Unit tests for AppDeps wiring + register_health_routes seam.

Pins MASTER ME-1 Part 2: route registration must work via a typed
AppDeps argument, not by capturing create_app closure or mutating
app.state. Future route extractions follow the same pattern.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from wabot_agent.api.deps import AppDeps, PairingState, SchedulerState, SnapshotCache
from wabot_agent.api.routes.health import register_health_routes


def _fake_deps() -> AppDeps:
    """Build a minimal AppDeps suitable for unit-testing one route module.

    Uses MagicMock for the collaborators so we don't need real Settings,
    MemoryStore, etc. — that's exactly the property the seam is supposed
    to give us.
    """
    return AppDeps(
        settings=MagicMock(name="settings"),
        memory=MagicMock(name="memory"),
        wabot=MagicMock(name="wabot"),
        event_log=MagicMock(name="event_log"),
        hub=MagicMock(name="hub"),
        pairing_state=PairingState(),
        scheduler_state=SchedulerState(),
        snapshot_cache=SnapshotCache(),
    )


def test_register_health_routes_unit_testable_without_app_state() -> None:
    """The seam works: a route module accepts AppDeps and registers
    onto an APIRouter that can be mounted by any FastAPI app."""
    router = APIRouter()
    register_health_routes(router, _fake_deps())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    # the body shape may include keys like {"ok": True, ...} — assert
    # the SHAPE not the exact contents; this test pins the SEAM, not
    # the response body (which is asserted elsewhere in test_api.py).
    assert isinstance(resp.json(), dict)


def test_create_app_exposes_deps_on_app_state(tmp_path: Path) -> None:
    """create_app stashes AppDeps on app.state.deps so future routes
    can opt into either the typed dependency arg OR Request.app.state.deps."""
    from wabot_agent.api import create_app
    from wabot_agent.config import Settings

    settings = Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SKILLS_DIR=Path("skills"),
        WABOT_AGENT_SEND_POLICY="dry_run",
        OPENROUTER_MODEL="openai/gpt-5.2",
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )
    app = create_app(settings)
    deps = app.state.deps
    assert isinstance(deps, AppDeps)
    assert deps.pairing_state is not None  # the sub-dataclass instance
    assert deps.snapshot_cache is not None
