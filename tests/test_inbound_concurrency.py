"""Concurrency and retry-semantics coverage for inbound deduplication.

See `docs/superpowers/plans/2026-05-16-issue-13-concurrency-dedupe-tests.md`
for the design rationale and the race-window findings these tests expose.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from wabot_agent.api import create_app
from wabot_agent.config import Settings
from wabot_agent.memory import MemoryStore

# Each call into the race helper is a thunk that returns either the boolean
# result of claim_message or, in the racy path, an Exception instance that the
# helper swallowed so the gather did not abort the other workers.
_Worker = Callable[[], Any]


async def _race(workers: list[_Worker]) -> list[Any]:
    """Run callables concurrently in OS threads, all released simultaneously.

    Uses a `threading.Barrier` so every worker hits the contended call at the
    same instant — no `time.sleep`, no wall-clock dependence. Exceptions are
    captured rather than re-raised so a single losing worker does not abort
    `asyncio.gather` for the others; assertions about the racing contract are
    made on the returned list.

    A dedicated `ThreadPoolExecutor` sized to `len(workers)` is required: the
    loop's default executor caps at `min(32, cpu_count + 4)`, which on small
    CI runners can be smaller than the worker count and would leave some
    threads queued, breaking the barrier with `BrokenBarrierError`.
    """
    barrier = threading.Barrier(len(workers))

    def _wrap(fn: _Worker) -> Callable[[], Any]:
        def _run() -> Any:
            barrier.wait(timeout=2.0)
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 — we want to surface the type
                return exc

        return _run

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        return await asyncio.gather(
            *(loop.run_in_executor(pool, _wrap(w)) for w in workers)
        )


# ---------------------------------------------------------------------------
# T1 — parallel claims on a fresh message_id (multi-store)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Finding A in plan 2026-05-16-issue-13: claim_message does SELECT-then-INSERT "
        "in two statements. Two MemoryStore instances racing on a fresh message_id "
        "both fall through to INSERT; one succeeds and the other raises "
        "sqlite3.IntegrityError instead of returning False. SQLite's writer "
        "serialisation makes any single race attempt only mostly-reliably observable, "
        "so we run several independent races and the contract is asserted on every "
        "attempt — any violation fails the test. Strict-xfail so XPASS flags the "
        "moment the claim is atomicised."
    ),
)
async def test_parallel_claim_yields_single_winner(tmp_path: Path) -> None:
    sender = "+15550000001"

    # SQLite serialises writers, so a single race attempt only ~90% reliably
    # exposes the IntegrityError leak. 8 independent attempts make a clean run
    # essentially impossible with the bug present (empirically 0/100 false
    # negatives in stress runs).
    for attempt in range(8):
        db_path = tmp_path / f"race-{attempt}.db"
        stores = [MemoryStore(db_path) for _ in range(10)]
        msg_id = f"msg-race-{attempt}"

        workers: list[_Worker] = [
            (lambda s=store, m=msg_id: s.claim_message(m, sender)) for store in stores
        ]
        results = await _race(workers)

        booleans = [r for r in results if isinstance(r, bool)]
        integrity_errors = [
            r for r in results if isinstance(r, sqlite3.IntegrityError)
        ]

        # Contract assertions — what should hold once the race is fixed.
        assert integrity_errors == [], (
            f"attempt {attempt}: claim_message leaked IntegrityError to "
            f"{len(integrity_errors)} caller(s); see Finding A in the plan"
        )
        assert booleans.count(True) == 1, (
            f"attempt {attempt}: expected 1 winner, saw {booleans.count(True)}"
        )
        assert booleans.count(False) == 9

        # Exactly one row in `processed_messages` regardless.
        with stores[0].connect() as conn:
            rows = conn.execute(
                "select message_id, status from processed_messages"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "processing"


# ---------------------------------------------------------------------------
# T2 — duplicate-delivery storm on a single store (production shape)
# ---------------------------------------------------------------------------


async def test_duplicate_delivery_storm_processes_once(memory: MemoryStore) -> None:
    sender = "+15550000002"
    workers: list[_Worker] = [
        lambda: memory.claim_message("msg-storm", sender) for _ in range(20)
    ]

    results = await _race(workers)

    assert all(isinstance(r, bool) for r in results)
    assert results.count(True) == 1
    assert results.count(False) == 19

    # Completing once should make is_processed sticky.
    memory.complete_message("msg-storm", run_id="run-storm")
    assert memory.is_processed("msg-storm") is True


# ---------------------------------------------------------------------------
# T3 — fail → retry → complete (sequential)
# ---------------------------------------------------------------------------


def test_failed_message_can_be_retried_to_done(memory: MemoryStore) -> None:
    sender = "+15550000003"

    assert memory.claim_message("msg-retry", sender) is True
    memory.fail_message("msg-retry", "boom")

    with memory.connect() as conn:
        row = conn.execute(
            "select status, error from processed_messages where message_id = ?",
            ("msg-retry",),
        ).fetchone()
    assert row["status"] == "failed"
    assert row["error"] == "boom"

    # Retry path: failed → processing → done.
    assert memory.claim_message("msg-retry", sender) is True
    memory.complete_message("msg-retry", run_id="run-retry")

    with memory.connect() as conn:
        row = conn.execute(
            "select status, run_id, error from processed_messages where message_id = ?",
            ("msg-retry",),
        ).fetchone()
    assert row["status"] == "done"
    assert row["run_id"] == "run-retry"
    assert row["error"] is None

    assert memory.is_processed("msg-retry") is True
    # Done is terminal — further claims are rejected.
    assert memory.claim_message("msg-retry", sender) is False


# ---------------------------------------------------------------------------
# T4 — concurrent retry after failure (multi-store)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Finding A in plan 2026-05-16-issue-13: claim_message's failed→processing "
        "transition is a SELECT followed by an unguarded UPDATE. With two MemoryStore "
        "instances on the same DB, both SELECTs can see status='failed' and both "
        "UPDATEs succeed, so multiple callers receive True for the same message — "
        "the duplicate-reply hazard. SQLite's writer serialisation makes any single "
        "race attempt only ~50% likely to observe multi-True, so we run several "
        "independent races per test invocation; the contract is asserted on every "
        "attempt and ANY violation fails the test. Strict-xfail so the test XPASSes "
        "(and CI goes red) the moment the claim is atomicised across all attempts."
    ),
)
async def test_concurrent_retry_after_failure_yields_single_winner(
    tmp_path: Path,
) -> None:
    sender = "+15550000004"
    # SQLite serialises writers, so the SELECT→UPDATE window of any single
    # `claim_message` race is intermittently observable (~50% per attempt).
    # We run 12 independent fresh-DB attempts; with the bug present,
    # p(no race observed across 12 attempts) is ~0.02% (empirically: 0/50
    # false-negatives in stress runs). With the bug fixed every attempt
    # returns exactly one True and the strict-xfail flips to XPASS — the
    # signal that this test should be deleted.
    for attempt in range(12):
        db_path = tmp_path / f"race-{attempt}.db"
        seed = MemoryStore(db_path)
        msg_id = f"msg-retry-race-{attempt}"
        assert seed.claim_message(msg_id, sender) is True
        seed.fail_message(msg_id, "first attempt failed")

        stores = [MemoryStore(db_path) for _ in range(20)]
        workers: list[_Worker] = [
            (lambda s=store, m=msg_id: s.claim_message(m, sender)) for store in stores
        ]
        results = await _race(workers)

        booleans = [r for r in results if isinstance(r, bool)]
        assert len(booleans) == 20, f"attempt {attempt}: non-bool results {results!r}"
        winners = booleans.count(True)
        assert winners == 1, (
            f"attempt {attempt}: expected exactly one winner on failed→processing, "
            f"saw {winners}; see Finding A in the plan — this is the duplicate-reply "
            "hazard"
        )
        assert booleans.count(False) == 19


# ---------------------------------------------------------------------------
# T5 — done is sticky under racing claims
# ---------------------------------------------------------------------------


async def test_complete_after_claim_is_idempotent_to_is_processed(
    memory_factory: Callable[[], MemoryStore],
) -> None:
    sender = "+15550000005"
    seed = memory_factory()
    seed.mark_processed("msg-done", sender)
    assert seed.is_processed("msg-done") is True

    stores = [memory_factory() for _ in range(10)]
    workers: list[_Worker] = [
        (lambda s=store: s.claim_message("msg-done", sender)) for store in stores
    ]
    results = await _race(workers)

    assert all(r is False for r in results), (
        f"completed messages must reject all retries, got {results!r}"
    )


# ---------------------------------------------------------------------------
# T6 — webhook-level smoke: duplicate storm hits the FastAPI handler
# ---------------------------------------------------------------------------
#
# TODO(follow-up issue): A `live`-gated, multi-process variant of this test
# (e.g. two uvicorn workers fronted by gunicorn) would exercise the same
# race window as T1/T4 at the HTTP boundary. Deferred so this PR stays
# tests-only and the suite stays sub-2s on CI. See plan §6.


def test_inbound_webhook_storm_returns_one_non_duplicate(tmp_path: Path) -> None:
    settings = Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
    )
    client = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer inbound-secret"}
    payload = {"id": "msg-webhook-storm", "from": "+15550000006", "text": "hi"}

    def _post() -> Any:
        return client.post("/whatsapp/inbound", json=payload, headers=headers)

    # FastAPI's TestClient is sync, so a ThreadPoolExecutor with a barrier
    # is the natural primitive here. Single-store path (one app instance) —
    # the RLock serialises and the race window does not appear, which is
    # the production deployment shape we care about for this smoke test.
    barrier = threading.Barrier(10)

    def _post_synced() -> Any:
        barrier.wait(timeout=2.0)
        return _post()

    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(lambda _: _post_synced(), range(10)))

    assert all(r.status_code == 200 for r in responses), [
        (r.status_code, r.text) for r in responses
    ]
    bodies = [r.json() for r in responses]
    non_duplicates = [b for b in bodies if b["duplicate"] is False]
    duplicates = [b for b in bodies if b["duplicate"] is True]
    assert len(non_duplicates) == 1, bodies
    assert len(duplicates) == 9, bodies
