from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wabot_agent.config import Settings
from wabot_agent.memory import MemoryStore, now_iso
from wabot_agent.tools import _parse_due_at_iso


@pytest.fixture
def memory(tmp_path) -> MemoryStore:
    return MemoryStore(tmp_path / "reminders.db")


def test_parse_due_at_iso_accepts_z_suffix() -> None:
    parsed = _parse_due_at_iso("2026-05-19T12:00:00Z")
    assert parsed is not None
    assert parsed.endswith("+00:00") or "+00:00" in parsed


def test_create_and_list_reminders(memory: MemoryStore) -> None:
    due = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    created = memory.create_reminder(
        requester_jid="owner@s.whatsapp.net",
        message="Take a break",
        due_at=due,
    )
    assert created["created"] is True

    rows = memory.list_reminders(requester_jid="owner@s.whatsapp.net", status="pending")
    assert len(rows) == 1
    assert rows[0]["message"] == "Take a break"


def test_cancel_reminder(memory: MemoryStore) -> None:
    due = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    created = memory.create_reminder(
        requester_jid="owner@s.whatsapp.net",
        message="cancel me",
        due_at=due,
    )
    result = memory.cancel_reminder(str(created["id"]), requester_jid="owner@s.whatsapp.net")
    assert result["cancelled"] is True
    rows = memory.list_reminders(requester_jid="owner@s.whatsapp.net", status="pending")
    assert rows == []


def test_release_reminder_claim(memory: MemoryStore) -> None:
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    memory.create_reminder(
        requester_jid="owner@s.whatsapp.net",
        message="retry me",
        due_at=past,
    )
    claimed = memory.claim_due_reminders(now=now_iso(), limit=5)
    reminder_id = str(claimed[0]["id"])
    assert memory.release_reminder_claim(reminder_id) is True
    rows = memory.list_reminders(requester_jid="owner@s.whatsapp.net", status="pending")
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"


def test_claim_due_reminders_atomic(memory: MemoryStore) -> None:
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    memory.create_reminder(
        requester_jid="owner@s.whatsapp.net",
        message="due now",
        due_at=past,
    )
    claimed = memory.claim_due_reminders(now=now_iso(), limit=5)
    assert len(claimed) == 1
    assert claimed[0]["status"] == "processing"

    again = memory.claim_due_reminders(now=now_iso(), limit=5)
    assert again == []


def test_reminder_idempotency(memory: MemoryStore) -> None:
    due = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    first = memory.create_reminder(
        requester_jid="owner@s.whatsapp.net",
        message="once",
        due_at=due,
        idempotency_key="key-1",
    )
    second = memory.create_reminder(
        requester_jid="owner@s.whatsapp.net",
        message="once",
        due_at=due,
        idempotency_key="key-1",
    )
    assert first["created"] is True
    assert second["created"] is False
    assert second["id"] == first["id"]


def test_count_pending_reminders(memory: MemoryStore) -> None:
    due = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    memory.create_reminder(
        requester_jid="owner@s.whatsapp.net",
        message="a",
        due_at=due,
    )
    memory.create_reminder(
        requester_jid="owner@s.whatsapp.net",
        message="b",
        due_at=due,
    )
    assert memory.count_pending_reminders("owner@s.whatsapp.net") == 2


def test_reminders_enabled_setting() -> None:
    settings = Settings(reminders_enabled=False, _env_file=None)
    assert settings.reminders_enabled is False
