"""Phase 4 — MCP admin API tests.

Covers:
- Auth required on all endpoints.
- List on fresh DB (no seed when mcp_config=None).
- CRUD happy paths (create, patch, delete).
- 404 on missing server id.
- POST /servers/{id}/check — success (3 tools) and error path (monkeypatched).
- GET /registry/search — curated + composio sources (monkeypatched).
- POST /registry/install — installs by id.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
        WABOT_AGENT_SKILLS_DIR=tmp_path / "skills",
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="test-inbound",
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


def _stdio_payload(name: str = "my-server") -> dict:
    return {
        "name": name,
        "transport": "stdio",
        "config_json": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        },
    }


def _http_payload(name: str = "my-http-server") -> dict:
    return {
        "name": name,
        "transport": "http",
        "config_json": {"url": "http://localhost:9000/mcp"},
    }


# ---------------------------------------------------------------------------
# Auth: all endpoints require token
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("get", "/api/mcp/servers", {}),
        ("post", "/api/mcp/servers", {"json": _stdio_payload()}),
        ("patch", "/api/mcp/servers/1", {"json": {}}),
        ("delete", "/api/mcp/servers/1", {}),
        ("post", "/api/mcp/servers/1/check", {}),
        ("get", "/api/mcp/registry/search", {}),
        ("post", "/api/mcp/registry/install", {"json": {"registry_id": "mcp_filesystem"}}),
    ],
)
def test_mcp_auth_required(ctx, method, path, kwargs):
    client, _ = ctx
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# List on fresh DB
# ---------------------------------------------------------------------------


def test_list_servers_empty(ctx):
    client, settings = ctx
    resp = client.get("/api/mcp/servers", headers=auth_headers(settings))
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_server_stdio(ctx):
    client, settings = ctx
    resp = client.post(
        "/api/mcp/servers",
        headers=auth_headers(settings),
        json=_stdio_payload("fs-server"),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "fs-server"
    assert data["transport"] == "stdio"
    assert data["health_status"] == "unknown"


def test_create_server_http(ctx):
    client, settings = ctx
    resp = client.post(
        "/api/mcp/servers",
        headers=auth_headers(settings),
        json=_http_payload("http-server"),
    )
    assert resp.status_code == 201
    assert resp.json()["transport"] == "http"


def test_create_server_invalid_name(ctx):
    client, settings = ctx
    payload = {"name": "Invalid-Name!", "transport": "stdio", "config_json": {"command": "x"}}
    resp = client.post("/api/mcp/servers", headers=auth_headers(settings), json=payload)
    assert resp.status_code == 400


def test_create_server_missing_command(ctx):
    client, settings = ctx
    payload = {"name": "bad-server", "transport": "stdio", "config_json": {"args": []}}
    resp = client.post("/api/mcp/servers", headers=auth_headers(settings), json=payload)
    assert resp.status_code == 400
    assert "command" in resp.json()["detail"]


def test_create_server_missing_url(ctx):
    client, settings = ctx
    payload = {"name": "bad-http", "transport": "http", "config_json": {"headers": {}}}
    resp = client.post("/api/mcp/servers", headers=auth_headers(settings), json=payload)
    assert resp.status_code == 400
    assert "url" in resp.json()["detail"]


def test_create_server_duplicate_name(ctx):
    client, settings = ctx
    headers = auth_headers(settings)
    r1 = client.post("/api/mcp/servers", headers=headers, json=_stdio_payload("dup-server"))
    assert r1.status_code == 201
    r2 = client.post("/api/mcp/servers", headers=headers, json=_stdio_payload("dup-server"))
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------


def test_patch_server(ctx):
    client, settings = ctx
    headers = auth_headers(settings)
    create_resp = client.post(
        "/api/mcp/servers", headers=headers, json=_stdio_payload("patch-server")
    )
    server_id = create_resp.json()["id"]

    patch_resp = client.patch(
        f"/api/mcp/servers/{server_id}",
        headers=headers,
        json={"is_enabled": False},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_enabled"] in (False, 0)


def test_patch_server_not_found(ctx):
    client, settings = ctx
    resp = client.patch(
        "/api/mcp/servers/99999",
        headers=auth_headers(settings),
        json={"is_enabled": False},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_server(ctx):
    client, settings = ctx
    headers = auth_headers(settings)
    create_resp = client.post(
        "/api/mcp/servers", headers=headers, json=_stdio_payload("del-server")
    )
    server_id = create_resp.json()["id"]

    del_resp = client.delete(f"/api/mcp/servers/{server_id}", headers=headers)
    assert del_resp.status_code == 204

    list_resp = client.get("/api/mcp/servers", headers=headers)
    ids = [s["id"] for s in list_resp.json()]
    assert server_id not in ids


def test_delete_server_not_found(ctx):
    client, settings = ctx
    resp = client.delete("/api/mcp/servers/99999", headers=auth_headers(settings))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Check — success (monkeypatched: 3 tools)
# ---------------------------------------------------------------------------


def test_check_server_success(ctx):
    client, settings = ctx
    headers = auth_headers(settings)
    create_resp = client.post("/api/mcp/servers", headers=headers, json=_stdio_payload("check-ok"))
    server_id = create_resp.json()["id"]

    # Build fake tool objects.
    fake_tools = [MagicMock(name=f"tool_{i}") for i in range(3)]
    for t in fake_tools:
        t.name = f"tool_{t.name.call_args}"  # give each a unique .name attr

    class _FakeTool:
        def __init__(self, n):
            self.name = n

    fake_tools = [_FakeTool(f"tool_{i}") for i in range(3)]

    async def _fake_check(store, settings_, server_id_):
        return {
            "health_status": "ok",
            "health_message": "3 tools",
            "last_checked_at": "2026-05-24T00:00:00+00:00",
            "tool_count": 3,
            "id": server_id_,
        }

    with patch("wabot_agent.api.routes.mcp_admin.check_server", side_effect=_fake_check):
        resp = client.post(f"/api/mcp/servers/{server_id}/check", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["health_status"] == "ok"
    assert data["tool_count"] == 3


# ---------------------------------------------------------------------------
# Check — error path (monkeypatched: raises)
# ---------------------------------------------------------------------------


def test_check_server_error_path(ctx):
    client, settings = ctx
    headers = auth_headers(settings)
    create_resp = client.post("/api/mcp/servers", headers=headers, json=_stdio_payload("check-err"))
    server_id = create_resp.json()["id"]

    async def _fake_check_error(store, settings_, server_id_):
        return {
            "health_status": "error",
            "health_message": "connection refused",
            "last_checked_at": "2026-05-24T00:00:00+00:00",
            "tool_count": 0,
            "id": server_id_,
        }

    with patch("wabot_agent.api.routes.mcp_admin.check_server", side_effect=_fake_check_error):
        resp = client.post(f"/api/mcp/servers/{server_id}/check", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["health_status"] == "error"
    assert data["tool_count"] == 0


def test_check_server_not_found(ctx):
    client, settings = ctx

    async def _fake_check_none(store, settings_, server_id_):
        return {}

    with patch("wabot_agent.api.routes.mcp_admin.check_server", side_effect=_fake_check_none):
        resp = client.post("/api/mcp/servers/99999/check", headers=auth_headers(settings))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Registry search — curated + composio (monkeypatched)
# ---------------------------------------------------------------------------


def test_registry_search_curated_only(ctx):
    client, settings = ctx
    resp = client.get("/api/mcp/registry/search", headers=auth_headers(settings))
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) >= 4  # seeded curated entries
    sources = {e["source"] for e in entries}
    assert "curated" in sources


def test_registry_search_includes_composio(ctx, monkeypatch):
    client, settings = ctx

    fake_composio = [
        {
            "id": "composio_gmail",
            "slug": "gmail",
            "name": "Gmail",
            "description": "Send and read Gmail messages.",
            "transport_hint": "http",
            "tags": ["email", "google"],
            "source": "composio",
        }
    ]

    import wabot_agent.composio_mcp_registry as adapter
    monkeypatch.setattr(adapter, "fetch_composio_mcp_index", lambda api_key, **kw: fake_composio)

    # Also clear the cache so the monkeypatched function is called.
    import wabot_agent.mcp_service as svc
    svc._composio_cache = None

    monkeypatch.setenv("COMPOSIO_API_KEY", "fake-key")

    resp = client.get(
        "/api/mcp/registry/search",
        headers=auth_headers(settings),
        params={"q": ""},
    )
    assert resp.status_code == 200
    entries = resp.json()
    sources = {e["source"] for e in entries}
    assert "curated" in sources
    assert "composio" in sources
    composio_entries = [e for e in entries if e["source"] == "composio"]
    assert any(e["slug"] == "gmail" for e in composio_entries)

    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    svc._composio_cache = None


def test_registry_search_filter(ctx):
    client, settings = ctx
    resp = client.get(
        "/api/mcp/registry/search",
        headers=auth_headers(settings),
        params={"q": "github"},
    )
    assert resp.status_code == 200
    entries = resp.json()
    assert all(
        "github" in (e["name"] + e["description"] + " ".join(e["tags"])).lower()
        for e in entries
    )


# ---------------------------------------------------------------------------
# Registry install
# ---------------------------------------------------------------------------


def test_registry_install(ctx):
    client, settings = ctx
    headers = auth_headers(settings)
    resp = client.post(
        "/api/mcp/registry/install",
        headers=headers,
        json={"registry_id": "mcp_filesystem"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "filesystem"

    # Confirm it appears in the list.
    list_resp = client.get("/api/mcp/servers", headers=headers)
    names = [s["name"] for s in list_resp.json()]
    assert "filesystem" in names


def test_registry_install_unknown_id(ctx):
    client, settings = ctx
    resp = client.post(
        "/api/mcp/registry/install",
        headers=auth_headers(settings),
        json={"registry_id": "mcp_does_not_exist_99999"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# SHOULD FIX — secret masking in GET responses
# ---------------------------------------------------------------------------


def test_get_servers_masks_secret_values(ctx):
    """Keys matching secret patterns (API_KEY, token, etc.) must be masked
    in the config_json returned from GET /api/mcp/servers."""
    client, settings = ctx
    headers = auth_headers(settings)

    payload = {
        "name": "mask-test",
        "transport": "stdio",
        "config_json": {
            "command": "/bin/x",
            "env": {
                "API_KEY": "sk-abc123",
                "PLAIN_VAR": "public",
            },
        },
    }
    create_resp = client.post("/api/mcp/servers", headers=headers, json=payload)
    assert create_resp.status_code == 201

    list_resp = client.get("/api/mcp/servers", headers=headers)
    assert list_resp.status_code == 200
    servers = list_resp.json()
    server = next(s for s in servers if s["name"] == "mask-test")

    import json as _json
    config = _json.loads(server["config_json"])
    assert "(masked)" in config["env"]["API_KEY"]
    assert config["env"]["PLAIN_VAR"] == "public"


def test_get_servers_masks_authorization_header(ctx):
    """Authorization header values (which contain 'auth') must be masked."""
    client, settings = ctx
    headers = auth_headers(settings)

    payload = {
        "name": "auth-header-test",
        "transport": "http",
        "config_json": {
            "url": "http://example.com/mcp",
            "headers": {
                "Authorization": "Bearer abc",
                "Content-Type": "application/json",
            },
        },
    }
    create_resp = client.post("/api/mcp/servers", headers=headers, json=payload)
    assert create_resp.status_code == 201

    list_resp = client.get("/api/mcp/servers", headers=headers)
    assert list_resp.status_code == 200
    servers = list_resp.json()
    server = next(s for s in servers if s["name"] == "auth-header-test")

    import json as _json
    config = _json.loads(server["config_json"])
    assert "(masked)" in config["headers"]["Authorization"]
    # Non-secret header should be untouched.
    assert config["headers"]["Content-Type"] == "application/json"
