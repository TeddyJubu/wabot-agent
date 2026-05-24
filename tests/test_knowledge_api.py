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
    # Phase 1: single consolidated instructions doc, no memory doc.
    assert len(index["docs"]) == 1
    assert index["docs"][0]["id"] == "instructions"
    assert index["budgets"]["instructions"] == 10000
    assert "memory" not in index["budgets"]

    put_ins = client.put(
        "/api/knowledge/instructions",
        headers=headers,
        json={"content": "## Rules\nBe polite."},
    )
    assert put_ins.status_code == 200
    assert put_ins.json()["ok"] is True

    get_ins = client.get("/api/knowledge/instructions", headers=headers).json()
    assert "Be polite" in get_ins["content"]

    # Legacy /api/knowledge/memory routes are gone — both verbs return 404.
    assert client.get("/api/knowledge/memory", headers=headers).status_code == 404
    assert (
        client.put(
            "/api/knowledge/memory", headers=headers, json={"content": "x"}
        ).status_code
        == 404
    )

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


def test_knowledge_instructions_put_enforces_budget(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={"operator_token": "secret", "knowledge_instructions_max_chars": 50}
    )
    client = TestClient(create_app(settings))
    headers = auth_headers(settings)

    resp = client.put(
        "/api/knowledge/instructions",
        headers=headers,
        json={"content": "x" * 100},
    )
    assert resp.status_code == 413
    body = resp.json()["detail"]
    assert body["budget"] == 50
    assert body["actual"] == 100

    # Boundary: exactly at budget is accepted.
    ok = client.put(
        "/api/knowledge/instructions",
        headers=headers,
        json={"content": "y" * 50},
    )
    assert ok.status_code == 200


def test_knowledge_instructions_put_budget_boundaries(tmp_path: Path) -> None:
    """Boundary matrix for the 413 budget guard.

    - budget chars         -> 200
    - budget+1 chars       -> 413 with {detail, budget, actual}
    - budget*10 chars      -> 413, actual reflects real length (not truncated
      before the check)
    """
    budget = 100
    settings = make_settings(tmp_path).model_copy(
        update={
            "operator_token": "secret",
            "knowledge_instructions_max_chars": budget,
        }
    )
    client = TestClient(create_app(settings))
    headers = auth_headers(settings)

    at_budget = client.put(
        "/api/knowledge/instructions",
        headers=headers,
        json={"content": "a" * budget},
    )
    assert at_budget.status_code == 200

    over = client.put(
        "/api/knowledge/instructions",
        headers=headers,
        json={"content": "b" * (budget + 1)},
    )
    assert over.status_code == 413
    detail = over.json()["detail"]
    assert set(detail.keys()) >= {"detail", "budget", "actual"}
    assert detail["detail"] == "Content exceeds budget"
    assert detail["budget"] == budget
    assert detail["actual"] == budget + 1

    huge = client.put(
        "/api/knowledge/instructions",
        headers=headers,
        json={"content": "c" * (budget * 10)},
    )
    assert huge.status_code == 413
    huge_detail = huge.json()["detail"]
    assert huge_detail["budget"] == budget
    # Real length must reach the response — proves the server did not silently
    # truncate the input before length-checking.
    assert huge_detail["actual"] == budget * 10
