"""Phase 3a — Tools catalog API tests.

Covers all acceptance criteria from PLAN §5 (Phase 3a):
- GET /api/tools returns native tools in the 'native' group.
- GET /api/tools shows is_assigned_to as a slug list after a join insert.
- POST /tools/refresh returns counts; running again is idempotent.
- PATCH /tools/{id} toggles is_enabled.
- PATCH /tools/{id} with non-existent id → 404.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wabot_agent.api import create_app
from wabot_agent.config import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SKILLS_DIR=Path("skills"),
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="test-inbound",
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )


def auth_headers(settings: Settings) -> dict[str, str]:
    return {"X-Operator-Token": settings.operator_token or ""}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def client_and_settings(tmp_path: Path):
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    client = TestClient(create_app(settings), raise_server_exceptions=True)
    return client, settings


# ---------------------------------------------------------------------------
# Test: GET /api/tools returns native tools
# ---------------------------------------------------------------------------


def test_list_tools_returns_native_group(client_and_settings: tuple) -> None:
    client, settings = client_and_settings
    headers = auth_headers(settings)

    resp = client.get("/api/tools", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "native" in data
    assert "mcp" in data
    assert "composio" in data
    assert "skill_action" in data

    # Expect at least 30 native tools from the seed
    native = data["native"]
    assert len(native) >= 30, f"Expected >= 30 native tools, got {len(native)}"

    # Validate shape of first row
    t = native[0]
    assert "id" in t
    assert "kind" in t
    assert t["kind"] == "native"
    assert "name" in t
    assert "source_ref" in t
    assert "is_enabled" in t
    assert "is_assigned_to" in t
    assert isinstance(t["is_assigned_to"], list)


# ---------------------------------------------------------------------------
# Test: is_assigned_to reflects actual assignments
# ---------------------------------------------------------------------------


def test_list_tools_shows_is_assigned_to(client_and_settings: tuple) -> None:
    client, settings = client_and_settings
    headers = auth_headers(settings)

    # Create a custom agent
    client.post(
        "/api/agents",
        headers=headers,
        json={
            "slug": "tool_assign_test",
            "display_name": "Assign Test",
            "instructions": "Test.",
        },
    )

    # Get the first native tool
    tools_resp = client.get("/api/tools", headers=headers)
    native = tools_resp.json()["native"]
    tool_id = native[0]["id"]

    # Assign it
    assign_resp = client.put(
        "/api/agents/tool_assign_test/tools",
        headers=headers,
        json={"tool_ids": [tool_id]},
    )
    assert assign_resp.status_code == 200

    # Re-fetch the tools list; tool should show the agent slug in is_assigned_to
    tools_resp2 = client.get("/api/tools", headers=headers)
    native2 = tools_resp2.json()["native"]
    assigned_tool = next((t for t in native2 if t["id"] == tool_id), None)
    assert assigned_tool is not None
    assert "tool_assign_test" in assigned_tool["is_assigned_to"]


# ---------------------------------------------------------------------------
# Test: POST /tools/refresh returns counts; idempotent
# ---------------------------------------------------------------------------


def test_refresh_catalog_returns_counts_and_is_idempotent(
    client_and_settings: tuple,
) -> None:
    client, settings = client_and_settings
    headers = auth_headers(settings)

    # First refresh (tools already seeded on DB init, so native_added = 0)
    r1 = client.post("/api/tools/refresh", headers=headers)
    assert r1.status_code == 200
    d1 = r1.json()
    assert "native_added" in d1
    assert "composio_added" in d1
    assert "mcp_added" in d1
    assert isinstance(d1["native_added"], int)
    assert d1["mcp_added"] == 0  # always 0 in v1

    # Second refresh must be idempotent (no count changes)
    r2 = client.post("/api/tools/refresh", headers=headers)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["native_added"] == 0  # already seeded, nothing new


# ---------------------------------------------------------------------------
# Test: PATCH /tools/{id} toggles is_enabled
# ---------------------------------------------------------------------------


def test_toggle_tool_is_enabled(client_and_settings: tuple) -> None:
    client, settings = client_and_settings
    headers = auth_headers(settings)

    # Get a tool id
    tools_resp = client.get("/api/tools", headers=headers)
    tool = tools_resp.json()["native"][0]
    tool_id = tool["id"]
    # Seeded tools should be enabled by default; explicit assert so this
    # test fails loudly if that ever changes.
    assert tool["is_enabled"] is True

    # Toggle off
    patch_resp = client.patch(
        f"/api/tools/{tool_id}",
        headers=headers,
        json={"is_enabled": False},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_enabled"] is False

    # Toggle back on
    patch_resp2 = client.patch(
        f"/api/tools/{tool_id}",
        headers=headers,
        json={"is_enabled": True},
    )
    assert patch_resp2.status_code == 200
    assert patch_resp2.json()["is_enabled"] is True


# ---------------------------------------------------------------------------
# Test: PATCH /tools/{id} non-existent → 404
# ---------------------------------------------------------------------------


def test_toggle_nonexistent_tool_returns_404(client_and_settings: tuple) -> None:
    client, settings = client_and_settings
    headers = auth_headers(settings)

    resp = client.patch(
        "/api/tools/999999",
        headers=headers,
        json={"is_enabled": False},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test: GET /api/tools requires auth
# ---------------------------------------------------------------------------


def test_tools_require_auth(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    client = TestClient(create_app(settings))
    resp = client.get("/api/tools")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# SHOULD FIX 2 — Test: refresh returns delta, not total
# ---------------------------------------------------------------------------


def test_refresh_catalog_returns_delta_not_total(client_and_settings: tuple) -> None:
    client, settings = client_and_settings
    headers = auth_headers(settings)

    # First call — tools already seeded at DB init, so native_added should be 0
    r1 = client.post("/api/tools/refresh", headers=headers)
    assert r1.status_code == 200

    # Second call — absolutely nothing new, delta must be 0 for both native and composio
    r2 = client.post("/api/tools/refresh", headers=headers)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["native_added"] == 0
    assert d2["composio_added"] == 0


# ---------------------------------------------------------------------------
# SHOULD FIX 4 — Test: write endpoints require auth
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/api/tools/refresh", None),
        ("patch", "/api/tools/1", {"is_enabled": False}),
    ],
)
def test_write_endpoints_require_auth(
    tmp_path: Path, method: str, path: str, body: dict | None
) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    client = TestClient(create_app(settings))

    fn = getattr(client, method)
    if body is not None:
        resp = fn(path, json=body)
    else:
        resp = fn(path)

    assert resp.status_code in (401, 403)
