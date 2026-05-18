from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wabot_agent.memory import MemoryStore, now_iso


@pytest.fixture
def memory(tmp_path) -> MemoryStore:
    return MemoryStore(tmp_path / "outbound.db")


def test_create_and_complete_outbound_task(memory: MemoryStore) -> None:
    expires = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    created = memory.create_outbound_task(
        owner_jid="owner@s.whatsapp.net",
        target_jid="+15550002222",
        chat_jid="+15550002222",
        prompt_summary="Ask about meeting",
        expires_at=expires,
    )
    task_id = str(created["id"])

    match = memory.find_pending_outbound_task(
        sender="+15550002222",
        chat="+15550002222",
        is_group=False,
    )
    assert match is not None

    done = memory.complete_outbound_task(
        task_id,
        reply_text="Yes, Friday works",
        reply_message_id="reply-1",
    )
    assert done["completed"] is True

    assert (
        memory.find_pending_outbound_task(
            sender="+15550002222",
            chat="+15550002222",
            is_group=False,
        )
        is None
    )


def test_group_outbound_task_matches_chat(memory: MemoryStore) -> None:
    expires = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    memory.create_outbound_task(
        owner_jid="owner@s.whatsapp.net",
        target_jid="111@s.whatsapp.net",
        chat_jid="120363@g.us",
        expires_at=expires,
    )
    match = memory.find_pending_outbound_task(
        sender="111@s.whatsapp.net",
        chat="120363@g.us",
        is_group=True,
    )
    assert match is not None


def test_group_broadcast_task_matches_any_sender_in_chat(memory: MemoryStore) -> None:
    expires = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    memory.create_outbound_task(
        owner_jid="owner@s.whatsapp.net",
        target_jid="120363@g.us",
        chat_jid="120363@g.us",
        expires_at=expires,
    )
    match = memory.find_pending_outbound_task(
        sender="222@s.whatsapp.net",
        chat="120363@g.us",
        is_group=True,
    )
    assert match is not None


def test_expire_outbound_tasks(memory: MemoryStore) -> None:
    expires = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    created = memory.create_outbound_task(
        owner_jid="owner@s.whatsapp.net",
        target_jid="+15550003333",
        chat_jid="+15550003333",
        expires_at=expires,
    )
    expired = memory.expire_outbound_tasks(now=now_iso())
    assert len(expired) == 1
    assert expired[0]["id"] == created["id"]

    task = memory.get_outbound_task(str(created["id"]))
    assert task is not None
    assert task["status"] == "expired"


def test_list_outbound_tasks_for_owner(memory: MemoryStore) -> None:
    expires = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    memory.create_outbound_task(
        owner_jid="owner@s.whatsapp.net",
        target_jid="+15550004444",
        chat_jid="+15550004444",
        expires_at=expires,
    )
    rows = memory.list_outbound_tasks(owner_jid="owner@s.whatsapp.net")
    assert len(rows) == 1


def test_owner_inbound_does_not_match_own_task(memory: MemoryStore) -> None:
    expires = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    memory.create_outbound_task(
        owner_jid="owner@s.whatsapp.net",
        target_jid="+15550005555",
        chat_jid="+15550005555",
        expires_at=expires,
    )
    # Owner messaging themselves should not complete the task via find (API skips owner)
    match = memory.find_pending_outbound_task(
        sender="owner@s.whatsapp.net",
        chat="owner@s.whatsapp.net",
        is_group=False,
    )
    # find still returns if sender equals target incorrectly — target is +1555 not owner
    assert match is None
