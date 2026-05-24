"""End-to-end integration tests: knowledge content actually reaches the prompt.

This is the test the Phase 1 audit flagged as missing — PUT instructions via
the API, then assert the same content lands in ``build_agent_instructions``'s
output. Also exercises cache invalidation by writing a second sentinel and
asserting the old one is gone.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wabot_agent.agent import build_agent_instructions
from wabot_agent.api import create_app
from wabot_agent.config import Settings
from wabot_agent.instructions_cache import invalidate_instructions_cache


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


def test_put_instructions_reaches_build_agent_instructions(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    client = TestClient(create_app(settings))
    headers = auth_headers(settings)
    # Clear any cached prompt residue from earlier tests in the same process.
    invalidate_instructions_cache()

    sentinel = "SENTINEL_INSTRUCTIONS_XYZ123"
    resp = client.put(
        "/api/knowledge/instructions",
        headers=headers,
        json={"content": sentinel},
    )
    assert resp.status_code == 200

    prompt = build_agent_instructions(settings, "")
    assert sentinel in prompt
    # The block is injected under the Client instructions heading once.
    assert "## Client instructions" in prompt
    assert prompt.count("## Client instructions") == 1


def test_cache_invalidation_after_second_put(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    client = TestClient(create_app(settings))
    headers = auth_headers(settings)
    invalidate_instructions_cache()

    sentinel_old = "SENTINEL_OLD_AAA111"
    sentinel_new = "SENTINEL_NEW_BBB222"

    assert (
        client.put(
            "/api/knowledge/instructions",
            headers=headers,
            json={"content": sentinel_old},
        ).status_code
        == 200
    )
    first = build_agent_instructions(settings, "")
    assert sentinel_old in first
    assert sentinel_new not in first

    assert (
        client.put(
            "/api/knowledge/instructions",
            headers=headers,
            json={"content": sentinel_new},
        ).status_code
        == 200
    )
    second = build_agent_instructions(settings, "")
    assert sentinel_new in second
    # Cache invalidation must drop the stale sentinel.
    assert sentinel_old not in second
