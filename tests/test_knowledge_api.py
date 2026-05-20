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
        WABOT_AGENT_KNOWLEDGE_DIR=tmp_path / "knowledge",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )


def auth_headers(settings: Settings) -> dict[str, str]:
    return {"X-Operator-Token": settings.operator_token or ""}


def test_knowledge_routes_require_auth(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    client = TestClient(create_app(settings))

    assert client.get("/api/knowledge").status_code == 401
    assert client.get("/knowledge", follow_redirects=False).status_code == 302


def test_knowledge_crud_and_memory_extensions(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    client = TestClient(create_app(settings))
    headers = auth_headers(settings)

    index = client.get("/api/knowledge", headers=headers).json()
    assert len(index["docs"]) == 2
    assert index["budgets"]["instructions"] == 6000

    put_ins = client.put(
        "/api/knowledge/instructions",
        headers=headers,
        json={"content": "## Rules\nBe polite."},
    )
    assert put_ins.status_code == 200
    assert put_ins.json()["ok"] is True

    get_ins = client.get("/api/knowledge/instructions", headers=headers).json()
    assert "Be polite" in get_ins["content"]

    client.put(
        "/api/knowledge/memory",
        headers=headers,
        json={"content": "Operator prefers bullet replies."},
    )
    mem = client.get("/api/knowledge/memory", headers=headers).json()
    assert "bullet replies" in mem["content"]

    contact = "15550001111@s.whatsapp.net"
    upsert = client.put(
        f"/api/memory/{contact}/facts",
        headers=headers,
        json={"key": "timezone", "value": "US/Pacific"},
    )
    assert upsert.status_code == 200
    assert upsert.json()["stored"] is True

    recalled = client.get(f"/api/memory/{contact}", headers=headers).json()
    assert len(recalled["facts"]) == 1
    assert recalled["facts"][0]["value"] == "US/Pacific"

    contacts = client.get("/api/knowledge/contacts", headers=headers).json()
    assert contacts["contacts"][0]["contact"] == contact

    deleted = client.delete(
        f"/api/memory/{contact}/facts/timezone",
        headers=headers,
    )
    assert deleted.json()["deleted"] is True

    note = client.put(
        "/api/memory/agent-notes",
        headers=headers,
        json={"key": "send_policy_hint", "value": "dry_run only"},
    )
    assert note.json()["stored"] is True

    notes = client.get("/api/memory/agent-notes", headers=headers).json()
    assert len(notes["items"]) >= 1
    assert notes["items"][0]["value"] == "dry_run only"

    removed = client.delete("/api/memory/agent-notes/send_policy_hint", headers=headers)
    assert removed.json()["deleted"] is True
