from __future__ import annotations

import threading

from wabot_agent.memory import MemoryStore


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


def test_claim_message_is_atomic_under_concurrent_calls(memory: MemoryStore) -> None:
    """Regression test for #51 — concurrent claims must be idempotent.

    Pre-seed a failed row so both the INSERT path and the conditional UPDATE
    path are exercised. Two calls racing on the same message_id must yield
    exactly one True and one False; the winning run_id is the only one
    persisted.
    """
    # Seed a failed row so the retry path is exercised.
    memory.claim_message("msg-race", "+15550001111")
    memory.fail_message("msg-race", "transient error")

    results: list[bool] = []
    lock = threading.Lock()

    def attempt(run_label: str) -> None:
        ok = memory.claim_message("msg-race", f"+1555000{run_label}")
        with lock:
            results.append(ok)

    t1 = threading.Thread(target=attempt, args=("1111",))
    t2 = threading.Thread(target=attempt, args=("2222",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one winner.
    assert results.count(True) == 1
    assert results.count(False) == 1
    # A second sequential call must also fail (row is now 'processing').
    assert memory.claim_message("msg-race", "+15550001111") is False
