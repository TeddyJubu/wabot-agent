from __future__ import annotations

from vignesh_agent.memory import MemoryStore


def test_contact_memory_rejects_sensitive_values(memory: MemoryStore) -> None:
    result = memory.remember_contact_fact("+15550001111", "api_key", "sk-or-secret", "test")

    assert result["stored"] is False
    assert memory.recall_contact("+15550001111")["facts"] == []


def test_contact_memory_stores_safe_fact(memory: MemoryStore) -> None:
    result = memory.remember_contact_fact("+15550001111", "preferred_reply_style", "short", "test")

    assert result["stored"] is True
    recalled = memory.recall_contact("+15550001111")
    assert recalled["facts"][0]["key"] == "preferred_reply_style"
    assert recalled["facts"][0]["value"] == "short"


def test_processed_messages_are_idempotent(memory: MemoryStore) -> None:
    assert memory.is_processed("msg-1") is False
    memory.mark_processed("msg-1", "+15550001111")
    memory.mark_processed("msg-1", "+15550001111")

    assert memory.is_processed("msg-1") is True
    assert memory.stats()["processed_messages"] == 1


def test_failed_inbound_claim_can_be_retried(memory: MemoryStore) -> None:
    assert memory.claim_message("msg-2", "+15550001111") is True
    assert memory.claim_message("msg-2", "+15550001111") is False

    memory.fail_message("msg-2", "temporary provider error")

    assert memory.claim_message("msg-2", "+15550001111") is True
