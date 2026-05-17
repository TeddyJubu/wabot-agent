from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wabot_agent.agent import AgentRunResult
from wabot_agent.api import create_app
from wabot_agent.auto_reply import deliver_auto_reply
from wabot_agent.config import Settings
from wabot_agent.memory import InboundMessage
from wabot_agent.wabot import FakeWabotClient


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="allowlist",
        WABOT_AGENT_ALLOWED_RECIPIENTS="+15550001111",
        WABOT_AGENT_AUTO_REPLY=True,
        OPENROUTER_MODEL="openai/gpt-5.2",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )


@pytest.mark.asyncio
async def test_deliver_auto_reply_sends_final_output(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    wabot = FakeWabotClient()
    inbound = InboundMessage(
        id="m1",
        sender="+15550001111",
        text="hello",
        chat="+15550001111",
    )
    result = AgentRunResult(
        run_id="run-1",
        final_output="Thanks for your message!",
        session_id="+15550001111",
        live_model=False,
    )

    auto = await deliver_auto_reply(
        settings=settings, wabot=wabot, inbound=inbound, result=result
    )

    assert auto["sent"] is True
    assert len(wabot.sent) == 1
    assert wabot.sent[0]["to"] == "+15550001111"
    assert wabot.sent[0]["text"] == "Thanks for your message!"


@pytest.mark.asyncio
async def test_deliver_auto_reply_skips_when_agent_already_sent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    wabot = FakeWabotClient()
    inbound = InboundMessage(
        id="m2",
        sender="+15550001111",
        text="hello",
        chat="+15550001111",
    )
    result = AgentRunResult(
        run_id="run-2",
        final_output="duplicate",
        session_id="+15550001111",
        live_model=False,
        sent_destinations=frozenset({"+15550001111"}),
    )

    auto = await deliver_auto_reply(
        settings=settings, wabot=wabot, inbound=inbound, result=result
    )

    assert auto["sent"] is False
    assert auto["reason"] == "already_sent_by_agent"
    assert wabot.sent == []


def test_inbound_webhook_wires_auto_reply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_deliver(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"sent": True, "policy": "allowlist", "to": "+1***1111"}

    monkeypatch.setattr("wabot_agent.api.deliver_auto_reply", fake_deliver)

    settings = _settings(tmp_path)
    app = create_app(settings)
    headers = {"Authorization": "Bearer inbound-secret"}
    payload = {"id": "msg-auto-1", "from": "+15550001111", "text": "hi there"}

    resp = TestClient(app).post("/whatsapp/inbound", json=payload, headers=headers)

    assert resp.status_code == 200
    assert resp.json()["auto_reply"]["sent"] is True
    assert len(calls) == 1
    assert calls[0]["inbound"].sender == "+15550001111"  # type: ignore[index]
