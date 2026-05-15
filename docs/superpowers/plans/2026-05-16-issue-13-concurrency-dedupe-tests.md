# Plan: Issue #13 — concurrency & retry-semantics tests for inbound dedupe

- **Issue**: [#13](https://github.com/TeddyJubu/wabot-agent/issues/13) — *Testing: add concurrency and retry semantics coverage for inbound dedupe*
- **Status**: planning (no implementation in this branch)
- **Scope**: tests only; surface bugs, do not fix them in this plan

## 1. API surface as it exists today

Authoritative file: [`src/wabot_agent/memory.py`](../../../src/wabot_agent/memory.py).

| Function | Signature | Behaviour |
|---|---|---|
| `MemoryStore.claim_message` | `(message_id: str, sender: str) -> bool` | Inserts a `processed_messages` row with `status='processing'` if no row exists. If a row exists with status `processing` or `done`, returns `False`. If status `failed`, UPDATEs back to `processing` and returns `True`. |
| `MemoryStore.complete_message` | `(message_id: str, run_id: str \| None) -> None` | UPDATE: sets `status='done'`, clears `error`, stamps `processed_at`, stores `run_id`. No-ops silently if the row is absent. |
| `MemoryStore.fail_message` | `(message_id: str, error: str) -> None` | UPDATE: sets `status='failed'`, stores redacted `error`, stamps `processed_at`. No-ops silently if absent. |
| `MemoryStore.is_processed` | `(message_id: str) -> bool` | True iff a row exists with status in `{'processing', 'done'}`. |
| `MemoryStore.mark_processed` | `(message_id, sender) -> None` | Convenience: `claim_message` then `complete_message(None)`. |

Connection model:

- `MemoryStore.__init__` creates an instance-level `threading.RLock`.
- `connect()` is a context manager that acquires the lock for the **entire** open-commit-close lifecycle, opens a fresh `sqlite3.Connection`, and sets per-connection pragmas (`synchronous=NORMAL`, `busy_timeout=5000`). `journal_mode=WAL` is set once and persists in the DB file.
- One connection per call. Each `claim_message`/`complete_message`/`fail_message` opens, executes, commits, closes.

The inbound webhook in [`src/wabot_agent/api.py`](../../../src/wabot_agent/api.py) lines 331-377 is:

```
claim_message → (if False) return duplicate
              → run_agent
                ├── raises  → fail_message → re-raise (500 to caller)
                └── returns → complete_message
```

## 2. Race conditions and gaps I found while reading the code

These are **findings only**. The acceptance criteria do not require fixing them; the new tests should expose them so they're visible.

### Finding A — multi-instance race window in `claim_message` (lines 128-155)

`claim_message` does a `SELECT status` and then either an `INSERT` or an `UPDATE` as a **second statement**, both inside the same Python-level connection context. The `threading.RLock` is per-`MemoryStore` instance and is held for the whole transaction, so **within one `MemoryStore` object** the operation is effectively atomic at the Python level. The race window is exposed when two `MemoryStore` instances point at the same DB file — i.e. two processes (gunicorn/uvicorn workers, the future scenario the issue gestures at) or two threads each holding their own store.

What goes wrong with two stores racing on a fresh `message_id`:

1. Both `SELECT`s return no row.
2. Both fall through to the `INSERT`. SQLite serialises writes via the database write lock, so one INSERT succeeds and the other raises `sqlite3.IntegrityError: UNIQUE constraint failed: processed_messages.message_id`.
3. The code does not catch `IntegrityError` — it propagates out of `claim_message`. The webhook handler turns this into a 500. The other writer gets `True`. We never return `False` to the loser; we return *an exception*. From the operator's perspective, exactly-one-claim still holds (only one path proceeds to `run_agent`), but the loser gets an HTTP error instead of `{"duplicate": true}`.

What goes wrong with two stores racing on a `failed` row (retry path):

1. Both `SELECT`s see `status='failed'`.
2. Both fall through to the `UPDATE` branch. UPDATE does **not** raise on conflict.
3. Both return `True`. **Two callers each believe they have an exclusive claim.** `run_agent` runs twice, the user receives a duplicate reply.

The retry-race is the more dangerous bug. The test will assert "exactly one True out of N" and is expected to **fail today** on the failed-retry contention test. We will mark it `xfail(strict=True)` with a reference to this finding so it lights up green the moment somebody atomicises the claim, and so green CI is honest in the meantime.

### Finding B — `complete_message` / `fail_message` are silent no-ops when row absent

If the row disappears (manual DB surgery, schema rebuild, very long retention sweep), `complete_message`/`fail_message` happily UPDATE zero rows and return. Callers cannot detect the missing row. Not in scope for issue #13, just noting.

### Finding C — `is_processed` does not distinguish `processing` from `done`

`is_processed` returns True for both `processing` and `done`. This is correct for "should we skip this inbound?" but means a crashed worker that left a row stuck in `processing` will look forever-deduped to `is_processed` even though no completion happened. There is no janitor or `processing` TTL. Out of scope; noting for the operator.

## 3. Test design

All tests go under `tests/` with the default `offline` marker (no marker needed; `offline` is the default and live tests are marked explicitly). New file: **`tests/test_inbound_concurrency.py`**.

Concurrency primitive: **`asyncio.to_thread` + `asyncio.gather` + `threading.Barrier`**. Rationale:

- pytest-asyncio is in `asyncio_mode = "auto"`, so async test functions are first-class.
- `asyncio.to_thread` puts each worker on a real OS thread; `threading.Barrier(N)` makes them all arrive at the contended call simultaneously without `time.sleep`.
- Using **multiple `MemoryStore` instances pointed at the same DB path** is the only way to bypass the per-instance `RLock` and exercise the SQL-level race. One store + threads would just serialise on the RLock and the test would pass for the wrong reason.

Determinism: barrier-synchronised, no sleeps. The threads release as one batch. We assert on returned values (booleans, row counts) — never on wall-clock timing.

Runtime budget: target **< 1.0 s for the whole file**. Concrete budgets per test below.

### 3.1 Helpers added to `tests/conftest.py`

```python
@pytest.fixture
def memory_path(tmp_path: Path) -> Path:
    """A DB path shared across fixtures, for multi-store concurrency tests."""
    return tmp_path / "agent.db"

@pytest.fixture
def memory_factory(memory_path: Path):
    """Yields fresh MemoryStore instances against the same path.
    Each instance has its own threading.RLock — required to exercise
    the SQL-level race in claim_message."""
    def _make() -> MemoryStore:
        return MemoryStore(memory_path)
    return _make
```

The existing `memory` fixture stays as-is. New tests that need a single store use it. Tests that need contention call `memory_factory()` N times.

A small helper inside the test file (not exported):

```python
async def _race(workers: list[Callable[[], Any]]) -> list[Any]:
    """Run callables concurrently in threads, all released simultaneously
    by a barrier. Returns results in submission order."""
    barrier = threading.Barrier(len(workers))
    def _wrap(fn):
        def _run():
            barrier.wait(timeout=2.0)
            return fn()
        return _run
    return await asyncio.gather(*(asyncio.to_thread(_wrap(w)) for w in workers))
```

### 3.2 Test inventory

| # | Test | Acceptance criterion | Expected today |
|---|---|---|---|
| T1 | `test_parallel_claim_yields_single_winner` | AC1, AC4 | **xfail(strict)** — exposes Finding A (IntegrityError on loser instead of `False`) |
| T2 | `test_duplicate_delivery_storm_processes_once` | AC2 | pass |
| T3 | `test_failed_message_can_be_retried_to_done` | AC3 | pass |
| T4 | `test_concurrent_retry_after_failure_yields_single_winner` | AC1, AC3, AC4 | **xfail(strict)** — exposes Finding A in the UPDATE branch (two `True`s) |
| T5 | `test_complete_after_claim_is_idempotent_to_is_processed` | AC2 | pass |
| T6 | `test_inbound_webhook_storm_returns_one_non_duplicate` | AC1, AC2 (integration) | pass |

#### T1 — parallel claims, fresh message_id

- Build 10 `MemoryStore` instances pointed at the same path via `memory_factory`.
- Each worker calls `store.claim_message("msg-race", "+15550000001")`.
- `_race` releases all 10 simultaneously.
- Assert exactly one `True` and nine `False`s. **Currently** we expect one `True` and up to nine `IntegrityError` exceptions plus possibly some `False`s, depending on timing. The test asserts the contract; it will `xfail(strict=True)` until the claim is atomicised. Mark with `pytest.mark.xfail(reason="Finding A: race window in claim_message; tracked in plan 2026-05-16-issue-13")`.
- Final assertion: only one row in `processed_messages`, status `processing`.
- Budget: ~150 ms.

#### T2 — duplicate delivery storm, single store

- Use the existing `memory` fixture (single store; this exercises the *common* deployment shape where one uvicorn process serves all inbound calls).
- 20 workers call `memory.claim_message("msg-storm", sender)` concurrently via `_race`.
- Assert exactly one `True`, nineteen `False`s. Should pass today (RLock serialises).
- Then call `complete_message` once and assert `is_processed("msg-storm") is True`.
- Budget: ~200 ms.

#### T3 — fail → retry → complete (sequential)

- `claim_message("msg-retry", s)` → True.
- `fail_message("msg-retry", "boom")` — assert row status is `failed`.
- `claim_message("msg-retry", s)` → True (the retry path).
- `complete_message("msg-retry", "run-123")` — assert status `done`, `run_id` stored, `error` cleared.
- `is_processed("msg-retry")` → True.
- Final `claim_message` → False (done is terminal).
- Budget: ~10 ms.

#### T4 — concurrent retry after failure

- Seed: with one store, `claim_message` then `fail_message` to land the row in `status='failed'`.
- Build 10 fresh stores via `memory_factory`; race them on `claim_message("msg-retry-race", s)`.
- Assert exactly one `True` and nine `False`s. **Expected to fail today**: the UPDATE branch returns `True` for every winner, so we expect to see multiple `True`s. Mark `xfail(strict=True, reason="Finding A: UPDATE branch in claim_message has no atomicity guard; multiple callers can both promote failed→processing")`.
- This is the most important test in the file — it makes the duplicate-reply hazard visible.
- Budget: ~150 ms.

#### T5 — completed state is sticky

- `mark_processed("msg-done", s)`.
- 10 racing `claim_message` calls (multi-store) — assert all `False`.
- Budget: ~150 ms.

#### T6 — webhook-level smoke

- Uses `TestClient(create_app(...))` like the existing `test_inbound_is_idempotent`.
- POST 10 copies of the same `{"id": "msg-webhook-storm", ...}` concurrently via a small `ThreadPoolExecutor` (FastAPI's `TestClient` is sync; threading is the natural fit, and here we *want* the single-store path because that's what production uses).
- Assert exactly one response with `duplicate: false` and nine with `duplicate: true`.
- Assert HTTP 200 on all of them. (If Finding A were exposed at the webhook layer some would 500; with a single store and asyncio they won't.)
- Budget: ~250 ms.

### 3.3 Acceptance-criterion mapping

| AC | Covered by |
|---|---|
| AC1: under concurrent claims, only one path wins initial processing | T1 (multi-store), T2 (single-store), T6 (webhook) |
| AC2: duplicate deliveries do not cause duplicate processing | T2, T5, T6 |
| AC3: failed messages can be retried and completed correctly | T3, T4 |
| AC4: exactly-one-claim semantics under concurrency | T1, T4 |

### 3.4 What we explicitly do *not* do

- No fixes to `memory.py`. Issue #13 is testing only.
- No `pytest-xdist` parallelism inside the tests. Determinism comes from the barrier; xdist would just run the suite in parallel processes, which we don't need.
- No `time.sleep` anywhere. Sleep-based determinism is a smell.
- No `live`-marked tests. All offline.
- No webhook test that asserts `duplicate: true` on every response after the first — that would mask Finding A if it ever bubbles up. We assert "exactly one `duplicate: false`" instead.

## 4. Total runtime budget

Sum of per-test budgets: ~910 ms. We aim for **< 1.0 s** end-to-end for `tests/test_inbound_concurrency.py`. If the file ever exceeds 2 s, treat that as a regression and find out why before merging.

## 5. Open questions for the operator

1. **xfail vs unmarked-failing for T1/T4.** I'm choosing `xfail(strict=True)` so CI stays green and the tests turn red the moment someone fixes the underlying race. Alternative: leave them unmarked failing so CI is red until the race is fixed (more pressure, more friction). Operator preference?
2. **Should T6 use multiple processes?** Real production is multi-worker (gunicorn). A `subprocess.Popen` x 2 uvicorn test would be closer to truth but ~2 s of overhead and flaky on CI. I'd defer that to a separate `live`-marked integration test in a future issue.
3. **Finding B & C** — out of scope for #13; want them filed as separate issues?
