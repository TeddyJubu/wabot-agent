from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from vignesh_agent.api import create_app
from vignesh_agent.config import Settings


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        VIGNESH_OFFLINE_MODE=True,
        VIGNESH_DATA_DIR=tmp_path,
        VIGNESH_DB_PATH=tmp_path / "agent.db",
        VIGNESH_LOG_PATH=tmp_path / "events.jsonl",
        VIGNESH_MCP_CONFIG=None,
        VIGNESH_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
    )


def test_health_and_ready(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))

    assert client.get("/health").json()["ok"] is True
    ready = client.get("/ready").json()
    assert ready["live_model"] is False
    assert ready["send_policy"] == "dry_run"


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

