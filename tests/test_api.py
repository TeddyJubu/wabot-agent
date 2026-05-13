from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wabot_agent.api import create_app
from wabot_agent.config import Settings


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
    )


def test_settings_accepts_legacy_vignesh_aliases(tmp_path: Path) -> None:
    settings = Settings(
        VIGNESH_OFFLINE_MODE=True,
        VIGNESH_DB_PATH=tmp_path / "legacy.db",
        VIGNESH_SEND_POLICY="dry_run",
        OPENROUTER_API_KEY=None,
    )

    assert settings.offline_mode is True
    assert settings.db_path == tmp_path / "legacy.db"
    assert settings.send_policy == "dry_run"


def test_health_and_ready(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))

    assert client.get("/health").json()["ok"] is True
    ready = client.get("/ready").json()
    assert ready["live_model"] is False
    assert ready["send_policy"] == "dry_run"


def test_operator_endpoints_require_token_when_configured(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "operator-secret"})
    client = TestClient(create_app(settings))

    assert client.get("/ready").status_code == 401
    ok = client.get("/ready", headers={"X-Operator-Token": "operator-secret"})
    assert ok.status_code == 200


def test_dashboard_token_sets_operator_cookie(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "operator-secret"})
    client = TestClient(create_app(settings))

    denied = client.get("/")
    allowed = client.get("/?token=operator-secret")
    ready = client.get("/ready")

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert ready.status_code == 200


def test_runs_limit_rejects_negative_values(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))

    assert client.get("/api/runs?limit=-1").status_code == 422


def test_inbound_requires_token(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))
    payload = {"id": "msg-1", "from": "+15550001111", "text": "hello"}

    assert client.post("/whatsapp/inbound", json=payload).status_code == 401


def test_inbound_is_idempotent(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))
    payload = {"id": "msg-1", "from": "+15550001111", "text": "hello"}
    headers = {"Authorization": "Bearer inbound-secret"}

    first = client.post("/whatsapp/inbound", json=payload, headers=headers)
    second = client.post("/whatsapp/inbound", json=payload, headers=headers)

    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
