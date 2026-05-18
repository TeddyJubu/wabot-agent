from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from wabot_agent.config import Settings
from wabot_agent.memory import MemoryStore
from wabot_agent.web_agent import web_agent_health
from wabot_agent.web_research import _extract_result_text, _pick_extension, execute_web_research_job


@pytest.fixture
def memory(tmp_path) -> MemoryStore:
    return MemoryStore(tmp_path / "web.db")


def test_extract_result_text_prefers_data_string() -> None:
    assert _extract_result_text({"data": "a,b\n1,2"}) == "a,b\n1,2"


def test_pick_extension_csv() -> None:
    assert _pick_extension("csv", "businessName,phone\nAcme,123") == ".csv"


@pytest.mark.asyncio
async def test_web_agent_health_disabled() -> None:
    settings = Settings(web_agent_enabled=False)
    result = await web_agent_health(settings)
    assert result["ok"] is False
    assert result["reason"] == "disabled"


def test_create_and_claim_web_research_job(memory: MemoryStore) -> None:
    created = memory.create_web_research_job(
        requester_jid="owner@s.whatsapp.net",
        prompt="Find dental clinics in Singapore",
        title="sg-dental",
        output_format="csv",
    )
    assert created["created"] is True
    assert memory.count_web_research_jobs(status="pending") == 1
    job = memory.claim_pending_web_research_job()
    assert job is not None
    assert job["status"] == "running"
    memory.complete_web_research_job(
        str(job["id"]),
        error=None,
        result_path="research/out.csv",
        preview="preview",
        duration_ms=1000,
        steps=5,
    )
    row = memory.get_web_research_job(str(job["id"]))
    assert row is not None
    assert row["status"] == "completed"


@pytest.mark.asyncio
async def test_execute_web_research_job_saves_and_completes(tmp_path) -> None:
    settings = Settings(
        web_agent_enabled=True,
        web_agent_notify_on_complete=True,
        send_policy="allow_all",
        data_dir=tmp_path / "data",
        media_dir=tmp_path / "data" / "media",
        db_path=tmp_path / "data" / "db.sqlite",
        log_path=tmp_path / "data" / "events.jsonl",
    )
    settings.ensure_dirs()
    memory = MemoryStore(settings.db_path)
    memory.create_web_research_job(
        requester_jid="owner@s.whatsapp.net",
        prompt="test",
        output_format="csv",
    )
    claimed = memory.claim_pending_web_research_job()
    assert claimed is not None

    wabot = AsyncMock()
    wabot.health.return_value = type("H", (), {"ready": True})()
    wabot.send_text = AsyncMock(return_value={"ok": True})
    wabot.send_media = AsyncMock(return_value={"ok": True})

    mock_payload = {
        "text": "businessName,phone\nClinic A,123",
        "durationMs": 500,
        "steps": 3,
    }

    with patch(
        "wabot_agent.web_research.run_web_agent",
        new_callable=AsyncMock,
        return_value=mock_payload,
    ):
        from wabot_agent.events import EventHub, EventLog

        hub = EventHub()
        event_log = EventLog(settings.log_path, hub=hub)
        await execute_web_research_job(
            claimed,
            settings=settings,
            memory=memory,
            wabot=wabot,
            event_log=event_log,
            hub=hub,
        )

    row = memory.get_web_research_job(str(claimed["id"]))
    assert row is not None
    assert row["status"] == "completed"
    assert row["result_path"]
    wabot.send_text.assert_called_once()
    wabot.send_media.assert_called_once()
