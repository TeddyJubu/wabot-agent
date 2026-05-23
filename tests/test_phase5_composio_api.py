"""Phase 5 — Composio API tests.

100% offline. All Composio SDK calls are monkeypatched.
"""
from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from wabot_agent.api import create_app
from wabot_agent.config import Settings

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

FIXTURE_APPS = [
    {
        "slug": "gmail",
        "name": "Gmail",
        "description": "Google mail",
        "logo_url": "https://example.com/gmail.png",
        "categories": ["email"],
        "auth_schemes": ["OAUTH2"],
    },
    {
        "slug": "github",
        "name": "GitHub",
        "description": "GitHub",
        "logo_url": None,
        "categories": ["developer"],
        "auth_schemes": ["OAUTH2", "API_KEY"],
    },
    {
        "slug": "slack",
        "name": "Slack",
        "description": "Slack messaging",
        "logo_url": None,
        "categories": ["communication"],
        "auth_schemes": ["OAUTH2"],
    },
]


def make_settings(tmp_path: Path, *, with_key: bool = False) -> Settings:
    s = Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path / "data",
        WABOT_AGENT_DB_PATH=tmp_path / "data" / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "data" / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "data" / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SKILLS_DIR=tmp_path / "skills",
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="test-inbound",
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )
    if with_key:
        s = s.model_copy(update={"composio_api_key": "testkey123456", "composio_enabled": True})
    return s


def auth_headers(settings: Settings) -> dict[str, str]:
    return {"X-Operator-Token": settings.operator_token or ""}


@pytest.fixture(autouse=True)
def _clean_composio_env(monkeypatch):
    """Ensure COMPOSIO_API_KEY env doesn't leak between tests."""
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)


@pytest.fixture
def ctx(tmp_path: Path):
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    client = TestClient(create_app(settings), raise_server_exceptions=True)
    return client, settings


@pytest.fixture
def ctx_with_key(tmp_path: Path):
    settings = make_settings(tmp_path, with_key=True).model_copy(
        update={"operator_token": "secret"}
    )
    client = TestClient(create_app(settings), raise_server_exceptions=True)
    return client, settings


# ---------------------------------------------------------------------------
# Auth required on all endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("get", "/api/composio/status", {}),
        ("post", "/api/composio/api-key", {"json": {"api_key": "mykey12345"}}),
        ("get", "/api/composio/apps", {}),
        ("get", "/api/composio/connections", {}),
        ("post", "/api/composio/connections", {"json": {"app_slug": "gmail"}}),
        ("post", "/api/composio/connections/1/refresh", {}),
        ("delete", "/api/composio/connections/1", {}),
    ],
)
def test_auth_required(ctx, method, path, kwargs):
    client, _ = ctx
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/composio/status — no key
# ---------------------------------------------------------------------------


def test_status_no_key(ctx):
    client, settings = ctx
    resp = client.get("/api/composio/status", headers=auth_headers(settings))
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["api_key_present"] is False
    assert data["last_error"] is None


# ---------------------------------------------------------------------------
# GET /api/composio/status — key present (mock composio client init)
# ---------------------------------------------------------------------------


def test_status_with_key(ctx_with_key):
    client, settings = ctx_with_key
    with patch("wabot_agent.composio_tools._get_composio_client") as mock_client:
        mock_client.return_value = MagicMock()
        with patch("wabot_agent.composio_tools._ensure_composio_api_key"):
            resp = client.get("/api/composio/status", headers=auth_headers(settings))
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["api_key_present"] is True


# ---------------------------------------------------------------------------
# POST /api/composio/api-key — writes runtime_secrets.json with 0o600
# ---------------------------------------------------------------------------


def test_post_api_key_writes_runtime_secrets(tmp_path):
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    with patch("wabot_agent.composio_tools._get_composio_client") as mock_client, \
         patch("wabot_agent.composio_tools._ensure_composio_api_key"), \
         patch("wabot_agent.composio_tools.reset_composio_client_for_tests"):
        mock_client.return_value = MagicMock()
        client = TestClient(create_app(settings), raise_server_exceptions=True)
        resp = client.post(
            "/api/composio/api-key",
            headers=auth_headers(settings),
            json={"api_key": "mynewkey12345"},
        )
    assert resp.status_code == 200
    secrets_path = tmp_path / "data" / "runtime_secrets.json"
    assert secrets_path.exists()
    mode = stat.S_IMODE(secrets_path.stat().st_mode)
    assert mode == 0o600
    data = json.loads(secrets_path.read_text())
    assert data["COMPOSIO_API_KEY"] == "mynewkey12345"


def test_post_api_key_does_not_log_value(tmp_path, caplog):
    import logging

    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    secret_value = "supersecretapikeyXYZ"
    with patch("wabot_agent.composio_tools._get_composio_client") as mock_client, \
         patch("wabot_agent.composio_tools._ensure_composio_api_key"), \
         patch("wabot_agent.composio_tools.reset_composio_client_for_tests"):
        mock_client.return_value = MagicMock()
        with caplog.at_level(logging.DEBUG):
            client = TestClient(create_app(settings), raise_server_exceptions=True)
            client.post(
                "/api/composio/api-key",
                headers=auth_headers(settings),
                json={"api_key": secret_value},
            )
    for record in caplog.records:
        assert secret_value not in record.getMessage(), (
            f"Secret value found in log: {record.getMessage()}"
        )


def test_post_api_key_with_allow_env_write(tmp_path, monkeypatch):
    monkeypatch.setenv("WABOT_AGENT_ALLOW_ENV_WRITE", "true")
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    with patch("wabot_agent.composio_tools._get_composio_client") as mock_client, \
         patch("wabot_agent.composio_tools._ensure_composio_api_key"), \
         patch("wabot_agent.composio_tools.reset_composio_client_for_tests"):
        mock_client.return_value = MagicMock()
        client = TestClient(create_app(settings), raise_server_exceptions=True)
        resp = client.post(
            "/api/composio/api-key",
            headers=auth_headers(settings),
            json={"api_key": "envwritekey123"},
        )
    assert resp.status_code == 200
    # .env should have been written somewhere under tmp_path
    env_written = False
    for candidate in [tmp_path / ".env", tmp_path / "data" / ".env"]:
        if candidate.exists() and "COMPOSIO_API_KEY=envwritekey123" in candidate.read_text():
            env_written = True
    assert env_written


# ---------------------------------------------------------------------------
# POST /api/composio/api-key — too short → 422
# ---------------------------------------------------------------------------


def test_post_api_key_too_short(ctx):
    client, settings = ctx
    resp = client.post(
        "/api/composio/api-key",
        headers=auth_headers(settings),
        json={"api_key": "short"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/composio/apps — returns list (mocked), cached on second call
# ---------------------------------------------------------------------------


def test_get_apps_returns_list(ctx_with_key):
    client, settings = ctx_with_key
    with patch("wabot_agent.composio_service._list_apps_upstream", return_value=FIXTURE_APPS):
        resp = client.get("/api/composio/apps", headers=auth_headers(settings))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    slugs = {a["slug"] for a in data}
    assert "gmail" in slugs


def test_get_apps_caches_second_call(ctx_with_key):
    client, settings = ctx_with_key
    import wabot_agent.composio_service as svc

    # Clear cache
    svc._invalidate_apps_cache()

    call_count = {"n": 0}

    def fake_upstream(s):
        call_count["n"] += 1
        return FIXTURE_APPS

    with patch("wabot_agent.composio_service._list_apps_upstream", side_effect=fake_upstream):
        client.get("/api/composio/apps", headers=auth_headers(settings))
        client.get("/api/composio/apps", headers=auth_headers(settings))

    assert call_count["n"] == 1, "Second call should have hit cache"


def test_get_apps_503_when_no_key(ctx):
    import wabot_agent.composio_service as svc

    svc._invalidate_apps_cache()
    client, settings = ctx
    resp = client.get("/api/composio/apps", headers=auth_headers(settings))
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/composio/connections — empty
# ---------------------------------------------------------------------------


def test_list_connections_empty(ctx):
    client, settings = ctx
    resp = client.get("/api/composio/connections", headers=auth_headers(settings))
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /api/composio/connections — creates row with status=pending
# ---------------------------------------------------------------------------


def _fake_initiate(settings, app_slug, user_id):
    return {
        "redirect_url": f"https://composio.dev/auth/{app_slug}?token=abc",
        "connection_id": "upstream-conn-id-123",
    }


def test_create_connection_pending(ctx_with_key):
    client, settings = ctx_with_key
    with patch(
        "wabot_agent.composio_service._initiate_connection_upstream",
        side_effect=_fake_initiate,
    ):
        resp = client.post(
            "/api/composio/connections",
            headers=auth_headers(settings),
            json={"app_slug": "gmail", "user_id": None},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["app_slug"] == "gmail"
    assert "redirect_url" in data
    assert "composio.dev" in data["redirect_url"]
    assert data["id"] is not None


def test_create_connection_appears_in_list(ctx_with_key):
    client, settings = ctx_with_key
    with patch(
        "wabot_agent.composio_service._initiate_connection_upstream",
        side_effect=_fake_initiate,
    ):
        client.post(
            "/api/composio/connections",
            headers=auth_headers(settings),
            json={"app_slug": "slack", "user_id": None},
        )
    resp = client.get("/api/composio/connections", headers=auth_headers(settings))
    assert resp.status_code == 200
    slugs = [c["app_slug"] for c in resp.json()]
    assert "slack" in slugs


# ---------------------------------------------------------------------------
# POST /api/composio/connections — duplicate → 409
# ---------------------------------------------------------------------------


def test_create_connection_duplicate_409(ctx_with_key):
    client, settings = ctx_with_key
    # First: create as connected by inserting directly via service
    from wabot_agent.memory import MemoryStore

    store = MemoryStore(settings.db_path, settings)
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO composio_connections (app_slug, display_name, status, user_id) "
            "VALUES ('gmail', 'Gmail', 'connected', NULL)"
        )

    with patch(
        "wabot_agent.composio_service._initiate_connection_upstream",
        side_effect=_fake_initiate,
    ):
        resp = client.post(
            "/api/composio/connections",
            headers=auth_headers(settings),
            json={"app_slug": "gmail", "user_id": None},
        )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /connections/{id}/refresh — updates status
# ---------------------------------------------------------------------------


def test_refresh_connection_updates_status(ctx_with_key):
    client, settings = ctx_with_key

    # Create a pending connection
    with patch(
        "wabot_agent.composio_service._initiate_connection_upstream",
        side_effect=_fake_initiate,
    ):
        create_resp = client.post(
            "/api/composio/connections",
            headers=auth_headers(settings),
            json={"app_slug": "gmail", "user_id": None},
        )
    conn_id = create_resp.json()["id"]

    def fake_status(settings, app_slug, user_id):
        return {"status": "connected", "metadata": {"account": "test@example.com"}}

    with patch(
        "wabot_agent.composio_service._get_connection_status_upstream",
        side_effect=fake_status,
    ):
        resp = client.post(
            f"/api/composio/connections/{conn_id}/refresh",
            headers=auth_headers(settings),
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "connected"
    assert data["id"] == conn_id


def test_refresh_connection_404(ctx_with_key):
    client, settings = ctx_with_key
    with patch("wabot_agent.composio_service._get_connection_status_upstream", return_value=None):
        resp = client.post(
            "/api/composio/connections/9999/refresh",
            headers=auth_headers(settings),
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /connections/{id}
# ---------------------------------------------------------------------------


def test_delete_connection(ctx_with_key):
    client, settings = ctx_with_key

    with patch(
        "wabot_agent.composio_service._initiate_connection_upstream",
        side_effect=_fake_initiate,
    ):
        create_resp = client.post(
            "/api/composio/connections",
            headers=auth_headers(settings),
            json={"app_slug": "github", "user_id": None},
        )
    conn_id = create_resp.json()["id"]

    with patch("wabot_agent.composio_service._disconnect_upstream"):
        resp = client.delete(
            f"/api/composio/connections/{conn_id}",
            headers=auth_headers(settings),
        )
    assert resp.status_code == 204

    # Should be gone
    list_resp = client.get("/api/composio/connections", headers=auth_headers(settings))
    ids = [c["id"] for c in list_resp.json()]
    assert conn_id not in ids


def test_delete_connection_404(ctx_with_key):
    client, settings = ctx_with_key
    with patch("wabot_agent.composio_service._disconnect_upstream"):
        resp = client.delete(
            "/api/composio/connections/9999",
            headers=auth_headers(settings),
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /apps — 502 on upstream error
# ---------------------------------------------------------------------------


def test_get_apps_502_on_upstream_error(ctx_with_key):
    client, settings = ctx_with_key
    import wabot_agent.composio_service as svc

    svc._invalidate_apps_cache()

    with patch(
        "wabot_agent.composio_service._list_apps_upstream",
        side_effect=RuntimeError("upstream down"),
    ):
        resp = client.get("/api/composio/apps", headers=auth_headers(settings))
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# SHOULD FIX 1 — API key change invalidates apps cache
# ---------------------------------------------------------------------------


def test_api_key_change_invalidates_apps_cache(tmp_path):
    """Changing the API key must clear the apps cache so new account's apps appear."""
    import wabot_agent.composio_service as svc

    settings = make_settings(tmp_path, with_key=True).model_copy(
        update={"operator_token": "secret"}
    )

    _app_a: dict = {
        "slug": "a", "name": "A", "description": None,
        "logo_url": None, "categories": [], "auth_schemes": [],
    }
    _app_b: dict = {
        "slug": "b", "name": "B", "description": None,
        "logo_url": None, "categories": [], "auth_schemes": [],
    }
    call_sequence: list[list[dict]] = [[_app_a], [_app_b]]
    call_iter = iter(call_sequence)

    def fake_upstream(_settings):
        return next(call_iter)

    with patch("wabot_agent.composio_tools._get_composio_client") as mock_client, \
         patch("wabot_agent.composio_tools._ensure_composio_api_key"), \
         patch("wabot_agent.composio_tools.reset_composio_client_for_tests"), \
         patch("wabot_agent.composio_service._list_apps_upstream", side_effect=fake_upstream):
        mock_client.return_value = MagicMock()
        svc._invalidate_apps_cache()
        client = TestClient(create_app(settings), raise_server_exceptions=True)
        headers = auth_headers(settings)

        # First GET /apps — should return ['a']
        resp1 = client.get("/api/composio/apps", headers=headers)
        assert resp1.status_code == 200
        assert [a["slug"] for a in resp1.json()] == ["a"]

        # POST /api-key with a new key — must invalidate cache
        resp_key = client.post(
            "/api/composio/api-key",
            headers=headers,
            json={"api_key": "newkey_abcdefgh"},
        )
        assert resp_key.status_code == 200

        # GET /apps again — cache must have been cleared, should return ['b']
        resp2 = client.get("/api/composio/apps", headers=headers)
        assert resp2.status_code == 200
        assert [a["slug"] for a in resp2.json()] == ["b"], (
            "Apps cache was not invalidated after API key change"
        )


# ---------------------------------------------------------------------------
# NIT 2 — API key regex: invalid chars → 422
# ---------------------------------------------------------------------------


def test_api_key_with_invalid_chars_returns_422(ctx):
    client, settings = ctx
    headers = auth_headers(settings)

    # Space in key
    resp = client.post("/api/composio/api-key", headers=headers, json={"api_key": "has spaces1"})
    assert resp.status_code == 422

    # HTML tag in key
    resp = client.post("/api/composio/api-key", headers=headers, json={"api_key": "has<tag>xyz"})
    assert resp.status_code == 422


def test_api_key_valid_format_accepted(tmp_path):
    """A properly-formed key must not be rejected by schema validation."""
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    with patch("wabot_agent.composio_tools._get_composio_client") as mock_client, \
         patch("wabot_agent.composio_tools._ensure_composio_api_key"), \
         patch("wabot_agent.composio_tools.reset_composio_client_for_tests"):
        mock_client.return_value = MagicMock()
        client = TestClient(create_app(settings), raise_server_exceptions=True)
        resp = client.post(
            "/api/composio/api-key",
            headers=auth_headers(settings),
            json={"api_key": "ak_validkey_1234"},
        )
    # Must not be a 422 (validation error) — 200/503/502 all acceptable
    assert resp.status_code != 422
