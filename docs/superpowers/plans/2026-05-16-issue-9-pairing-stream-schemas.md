# Pairing + Stream Event Schemas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock the JSON shape of the WhatsApp pairing payload (REST + SSE) and the SSE event envelope behind Pydantic models so REST and SSE cannot drift, redaction is centralized in one constructor, and TS-side drift surfaces as a snapshot diff in code review.

**Architecture:** A new `src/wabot_agent/schemas.py` module defines `PairingPayload` (a public, redacted projection of `WabotPairingQR`) and `StreamEventEnvelope` (the wire format for every `/api/stream` frame). The pairing helper closure in `api.py` is replaced by `PairingPayload.from_wabot(...)` at three call sites (REST handler, SSE poller, initial snapshot). `_sse_frame()` accepts a `StreamEventEnvelope` so every frame flows through a single typed chokepoint. `EventHub.publish()` validates the (name, payload) pair via the envelope at publish time. A checked-in JSON Schema snapshot guards TS drift; a Vitest case asserts `PairingState` keys match.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, pytest with `asyncio_mode = "auto"`, ruff (E,F,I,UP,B, line-length 100), Vitest for the frontend snapshot assertion. No new runtime dependencies.

**Scope guardrails (from the spec):**
- Per-event `data` payload typing is **out of scope**. Events keep `data: dict[str, Any]`.
- No event-name changes, no field removals, no breaking wire changes.
- TS types stay hand-written; only the new `event`/`expires_at`/`detail` fields are added so the interface matches what's already on the wire.
- `/api/chat/stream` (NDJSON) is a different transport and is **not touched**.

---

## File Structure

| Path | Action | Responsibility |
| --- | --- | --- |
| `src/wabot_agent/schemas.py` | Create | `PairingPayload`, `StreamEventEnvelope`. Single source of truth for the pairing wire shape; envelope is the SSE framing contract. |
| `src/wabot_agent/api.py` | Modify | Remove `_pairing_payload` closure; route REST handler, SSE poller, and `_build_initial_snapshot()` through `PairingPayload.from_wabot()`; change `_sse_frame()` signature to take a `StreamEventEnvelope`. |
| `src/wabot_agent/events.py` | Modify | `EventHub.publish` and `EventLog.write` build a `StreamEventEnvelope` at the publish call site so bad names / non-dict payloads fail fast. |
| `web/src/api/pairing.ts` | Modify | `PairingState` gains `event`, `expires_at`, `detail` fields that have always been on the wire. No runtime change. |
| `tests/snapshots/pairing_payload.schema.json` | Create | Checked-in `model_json_schema()` output. Diffs are reviewable line items. |
| `scripts/dump_schemas.py` | Create | One-line helper for regenerating the snapshot. |
| `tests/test_schemas.py` | Create | Unit tests for `PairingPayload` and `StreamEventEnvelope` (round-trip, redaction, validation rejections, schema snapshot). |
| `tests/test_pairing_contract.py` | Create | The headline contract test: REST body equals SSE `pairing_changed.data`. Plus `_build_initial_snapshot.pairing` parity. |
| `tests/test_stream_envelope_contract.py` | Create | Every event read from `/api/stream` parses back into `StreamEventEnvelope`. |
| `web/src/__tests__/pairing-schema.test.ts` | Create | Vitest asserts `PairingState`'s wire-relevant keys match `tests/snapshots/pairing_payload.schema.json`. |

Files **not** touched: `src/wabot_agent/wabot.py` (`WabotPairingQR` stays a private dataclass — the public projection is what's typed), `src/wabot_agent/redaction.py` (no changes needed; `redact()` already covers `Mapping` values correctly), `web/src/hooks/usePairingStream.ts` (no behavioral change), `web/src/store/` (no behavioral change), every other publisher of `event_log.write(...)` (only `EventHub.publish`/`EventLog.write` change internally).

---

## Build Sequence

Build inside-out so each step adds tests that exercise the layer below it. The branch is `worktree-agent-aa0fe5d290f29ff17` (already created via the worktrees skill).

1. **Task 1 — Schemas module + unit tests.** Create the models and verify their shape/redaction behavior in isolation. Nothing else depends on them yet.
2. **Task 2 — Schema snapshot + dump script.** Generate the JSON Schema, check it in, add the snapshot-stability test.
3. **Task 3 — Pairing REST cutover.** Replace the closure with `PairingPayload.from_wabot()` on the REST path. The existing pairing test (`test_pairing_endpoint_reports_missing_token`) is the regression net.
4. **Task 4 — SSE poller + initial snapshot cutover.** Route both SSE pairing call sites through the same constructor.
5. **Task 5 — REST ≡ SSE contract test.** This is the headline acceptance test for #9. It must pass after Task 4 because both paths now build via `from_wabot()`.
6. **Task 6 — `_sse_frame()` accepts an envelope.** Change the signature, convert all three call sites.
7. **Task 7 — Envelope validation in `EventHub.publish` / `EventLog.write`.** Fail-fast at the publisher. Add the stream-envelope contract test.
8. **Task 8 — TS interface widening + Vitest snapshot guard.**
9. **Task 9 — Lint + full suite + final commit.**

Commit after every task. Each commit is independently reviewable.

---

## Task 1: Schemas module + unit tests

**Files:**
- Create: `src/wabot_agent/schemas.py`
- Create: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing unit tests**

Create `tests/test_schemas.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from wabot_agent.schemas import PairingPayload, StreamEventEnvelope
from wabot_agent.wabot import WabotPairingQR


def test_pairing_payload_from_wabot_roundtrip() -> None:
    qr = WabotPairingQR(
        supported=True,
        reachable=True,
        logged_in=False,
        connected=False,
        qr="ABCDEF",  # qr_available derives from this
        event="qr",
        updated_at="2026-05-16T10:00:00Z",
        expires_at="2026-05-16T10:00:30Z",
        detail="waiting for scan",
    )

    payload = PairingPayload.from_wabot(qr)

    assert payload.supported is True
    assert payload.reachable is True
    assert payload.logged_in is False
    assert payload.connected is False
    assert payload.qr_available is True
    assert payload.event == "qr"
    assert payload.updated_at == "2026-05-16T10:00:00Z"
    assert payload.expires_at == "2026-05-16T10:00:30Z"
    assert payload.detail == "waiting for scan"
    # The raw QR string is intentionally NOT part of the public payload.
    assert "qr" not in payload.model_dump() or payload.model_dump().get("qr") is None


def test_pairing_payload_omits_raw_qr() -> None:
    """The raw QR payload is fetched separately via /api/whatsapp/pairing.svg.
    Putting it in the JSON payload would leak it into the SSE backlog (256-entry
    ring) and the events.jsonl audit log, which are intentionally a lower trust
    tier than the SVG endpoint."""
    qr = WabotPairingQR(supported=True, reachable=True, qr="SECRET-PAIRING-CODE")

    dumped = PairingPayload.from_wabot(qr).model_dump()

    assert "qr" not in dumped
    assert "SECRET-PAIRING-CODE" not in json.dumps(dumped)


def test_pairing_payload_redacts_detail() -> None:
    """Construction-time redaction invariant: any call site that goes through
    from_wabot() emits a redacted detail field, even if the EventHub backstop
    were removed."""
    qr = WabotPairingQR(
        supported=True,
        reachable=True,
        detail="+15551234567 unauthorized",
    )

    payload = PairingPayload.from_wabot(qr)

    assert payload.detail is not None
    assert "+15551234567" not in payload.detail
    # mask_phone() keeps first 2 / last 2 digits separated by '***'.
    assert "***" in payload.detail


def test_pairing_payload_defaults() -> None:
    """Optional fields default to None / False so the JSON shape is stable."""
    qr = WabotPairingQR(supported=False, reachable=False)

    payload = PairingPayload.from_wabot(qr)
    dumped = payload.model_dump()

    assert dumped["supported"] is False
    assert dumped["reachable"] is False
    assert dumped["logged_in"] is None
    assert dumped["connected"] is None
    assert dumped["qr_available"] is False
    assert dumped["event"] is None
    assert dumped["updated_at"] is None
    assert dumped["expires_at"] is None
    assert dumped["detail"] is None


def test_stream_envelope_accepts_valid_payload() -> None:
    env = StreamEventEnvelope(id=42, name="pairing_changed", data={"ok": True})

    assert env.id == 42
    assert env.name == "pairing_changed"
    assert env.data == {"ok": True}


def test_stream_envelope_id_optional() -> None:
    """Heartbeat and ready_snapshot frames have no id."""
    env = StreamEventEnvelope(name="heartbeat", data={})

    assert env.id is None
    assert env.data == {}


def test_stream_envelope_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        StreamEventEnvelope(name="", data={})


def test_stream_envelope_rejects_non_dict_data() -> None:
    with pytest.raises(ValidationError):
        StreamEventEnvelope(name="x", data="oops")  # type: ignore[arg-type]


def test_stream_envelope_data_defaults_to_empty_dict() -> None:
    env = StreamEventEnvelope(name="heartbeat")

    assert env.data == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with '.[dev]' python -m pytest tests/test_schemas.py -v`
Expected: All FAIL with `ModuleNotFoundError: No module named 'wabot_agent.schemas'`.

- [ ] **Step 3: Implement the schemas module**

Create `src/wabot_agent/schemas.py`:

```python
"""Typed wire contracts for the pairing payload and SSE event envelope.

Issue #9 — see docs/superpowers/specs/2026-05-15-pairing-stream-schemas-design.md.

`PairingPayload` is the single source of truth for the JSON shape returned by
both `GET /api/whatsapp/pairing` (REST) and the SSE `pairing_changed` event.
Construction via `from_wabot()` applies `redact()` so every public payload is
redacted at the producer; `EventHub.publish()` keeps its own `redact()` as
defense in depth.

`StreamEventEnvelope` is the wire format for every frame written to
`/api/stream`. Building one at the publish call site (in `EventHub.publish`
and `EventLog.write`) makes name typos and wrong-shape payloads raise a
`ValidationError` at the publisher instead of producing a syntactically valid
but semantically broken frame on the wire.

Per-event `data` payloads are intentionally untyped at this stage — typing
specific events (`agent_run_complete`, `inbound_message`, ...) is a follow-up.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .redaction import redact
from .wabot import WabotPairingQR


class PairingPayload(BaseModel):
    """Public, redacted projection of `WabotPairingQR`.

    The raw `qr` field is intentionally not exposed here — clients fetch the
    rendered SVG separately from `GET /api/whatsapp/pairing.svg`. Including it
    in the JSON payload would leak it into the SSE backlog ring and the
    events.jsonl audit log.
    """

    supported: bool
    reachable: bool
    logged_in: bool | None = None
    connected: bool | None = None
    qr_available: bool = False
    event: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None
    detail: str | None = None

    @classmethod
    def from_wabot(cls, p: WabotPairingQR) -> PairingPayload:
        """Build the public payload from a wabot dataclass.

        `redact()` is applied to the raw mapping before validation so the
        resulting model is guaranteed redacted regardless of the call site.
        """
        raw = {
            "supported": p.supported,
            "reachable": p.reachable,
            "logged_in": p.logged_in,
            "connected": p.connected,
            "qr_available": p.qr_available,
            "event": p.event,
            "updated_at": p.updated_at,
            "expires_at": p.expires_at,
            "detail": p.detail,
        }
        return cls.model_validate(redact(raw))


class StreamEventEnvelope(BaseModel):
    """Wire format for every event over `/api/stream`.

    Constructing the envelope at the publish call site validates name (non-empty
    string) and data (must be a dict). A typo'd event name or wrong-shape data
    raises a `ValidationError` at the publisher's call site instead of producing
    a syntactically valid but semantically broken frame.
    """

    id: int | None = None
    name: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with '.[dev]' python -m pytest tests/test_schemas.py -v`
Expected: All PASS (9 tests).

- [ ] **Step 5: Lint the new module**

Run: `uv run --with '.[dev]' ruff check src/wabot_agent/schemas.py tests/test_schemas.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/wabot_agent/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): typed PairingPayload + StreamEventEnvelope models

Issue #9 — single source of truth for the pairing wire shape and SSE
envelope. PairingPayload.from_wabot() applies redact() at construction so
all call sites are independently redacted. Raw QR string is deliberately
excluded from the payload — clients fetch the rendered SVG separately.
StreamEventEnvelope rejects empty names and non-dict data at the publisher.

No call sites are wired yet; that lands in Tasks 3, 4, 6, and 7."
```

---

## Task 2: JSON Schema snapshot + dump helper

**Files:**
- Create: `scripts/dump_schemas.py`
- Create: `tests/snapshots/pairing_payload.schema.json`
- Modify: `tests/test_schemas.py` (append one test)

- [ ] **Step 1: Write the failing snapshot test**

Append to `tests/test_schemas.py`:

```python
def test_pairing_payload_schema_matches_snapshot() -> None:
    """Drift guard. If this fails, the wire shape changed — regenerate with
    `uv run python scripts/dump_schemas.py > tests/snapshots/pairing_payload.schema.json`
    and update the corresponding TS interface + Vitest expected-keys list."""
    snapshot_path = (
        Path(__file__).resolve().parent / "snapshots" / "pairing_payload.schema.json"
    )
    expected = json.loads(snapshot_path.read_text())
    actual = PairingPayload.model_json_schema()

    assert actual == expected
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `uv run --with '.[dev]' python -m pytest tests/test_schemas.py::test_pairing_payload_schema_matches_snapshot -v`
Expected: FAIL with `FileNotFoundError` (snapshot doesn't exist yet).

- [ ] **Step 3: Create the dump-helper script**

Create `scripts/dump_schemas.py`:

```python
"""Dump JSON Schemas for the public Pydantic wire models.

Used to refresh `tests/snapshots/*.schema.json` when a model field changes.
The snapshot diff is the reviewable artifact in PRs — TS authors see the
shape change and update `web/src/api/pairing.ts` + the Vitest expected-keys
list in the same PR.

Usage:
    uv run python scripts/dump_schemas.py > tests/snapshots/pairing_payload.schema.json
"""

from __future__ import annotations

import json
import sys

from wabot_agent.schemas import PairingPayload


def main() -> None:
    json.dump(PairingPayload.model_json_schema(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Generate the snapshot**

Run:
```bash
mkdir -p tests/snapshots
uv run python scripts/dump_schemas.py > tests/snapshots/pairing_payload.schema.json
```

Then sanity-check that the file looks right:

```bash
uv run python -c "import json; d=json.load(open('tests/snapshots/pairing_payload.schema.json')); assert set(d['properties'].keys()) == {'supported','reachable','logged_in','connected','qr_available','event','updated_at','expires_at','detail'}; print('ok')"
```

Expected: prints `ok`. If the property set differs, the dump is wrong — go back and check the model.

- [ ] **Step 5: Run the snapshot test to verify it passes**

Run: `uv run --with '.[dev]' python -m pytest tests/test_schemas.py::test_pairing_payload_schema_matches_snapshot -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/dump_schemas.py tests/snapshots/pairing_payload.schema.json tests/test_schemas.py
git commit -m "feat(schemas): checked-in JSON Schema snapshot for PairingPayload

Refresh with:
  uv run python scripts/dump_schemas.py > tests/snapshots/pairing_payload.schema.json

A failing snapshot test is the trigger for a coordinated update across the
Pydantic model, the TS interface, and the Vitest expected-keys list."
```

---

## Task 3: Route GET /api/whatsapp/pairing through PairingPayload

**Files:**
- Modify: `src/wabot_agent/api.py:236-240` (handler) + `:79-118` (drop closure later, after Task 4)

- [ ] **Step 1: Confirm the existing REST regression test still pins behavior**

Re-read `tests/test_api.py::test_pairing_endpoint_reports_missing_token`. It asserts `supported is True`, `qr_available is False`, status 200. This is our safety net — it must still pass after the refactor.

Run it first to confirm baseline: `uv run --with '.[dev]' python -m pytest tests/test_api.py::test_pairing_endpoint_reports_missing_token -v`
Expected: PASS (1 test).

- [ ] **Step 2: Change the REST handler to use `PairingPayload`**

In `src/wabot_agent/api.py`, add to the imports near the top (after the `.wabot` import line, alphabetically):

```python
from .schemas import PairingPayload, StreamEventEnvelope
```

Replace the existing handler (currently lines ~236-240):

```python
    @app.get("/api/whatsapp/pairing", dependencies=[human_dependency])
    async def whatsapp_pairing() -> dict[str, Any]:
        # _pairing_payload defines the canonical shape; both the SSE
        # `pairing_changed` event and this REST endpoint emit it.
        return redact(_pairing_payload(await wabot.pairing_qr()))
```

with:

```python
    @app.get(
        "/api/whatsapp/pairing",
        dependencies=[human_dependency],
        response_model=PairingPayload,
    )
    async def whatsapp_pairing() -> PairingPayload:
        # PairingPayload.from_wabot() applies redact() internally — see
        # schemas.py. The same constructor is reused by the SSE poller and
        # the initial snapshot path so all three sites emit identical JSON.
        return PairingPayload.from_wabot(await wabot.pairing_qr())
```

Do **not** remove the `_pairing_payload` closure yet — Task 4 cleans it up after the SSE call sites are converted.

- [ ] **Step 3: Run the regression test to verify behavior is unchanged**

Run: `uv run --with '.[dev]' python -m pytest tests/test_api.py::test_pairing_endpoint_reports_missing_token -v`
Expected: PASS — same assertions, new code path.

- [ ] **Step 4: Run the full test suite to catch unanticipated breakage**

Run: `uv run --with '.[dev]' python -m pytest -q`
Expected: All PASS. If anything else fails, stop and investigate before continuing.

- [ ] **Step 5: Commit**

```bash
git add src/wabot_agent/api.py
git commit -m "refactor(api): GET /api/whatsapp/pairing returns PairingPayload

The handler now constructs PairingPayload.from_wabot() instead of calling
the _pairing_payload closure + redact() inline. response_model=PairingPayload
adds the schema to OpenAPI for free. Wire shape is unchanged — the existing
regression test confirms it.

SSE call sites still use the closure; they migrate in Task 4."
```

---

## Task 4: Route SSE poller + initial snapshot through PairingPayload

**Files:**
- Modify: `src/wabot_agent/api.py:120-139` (poller), `:387-418` (snapshot), `:105-118` (drop closure)

- [ ] **Step 1: Change the SSE poller**

Replace `_pairing_poll_loop` (lines ~120-139) with:

```python
    async def _pairing_poll_loop() -> None:
        """Probe wabot pairing state and publish pairing_changed on diff.

        Polls every 5s on loopback — cheap. We only publish when the snapshot
        actually changes, so a stable linked session generates zero events
        beyond the initial state push at startup. Uses PairingPayload.from_wabot()
        so the SSE shape is identical to GET /api/whatsapp/pairing.
        """
        while True:
            try:
                pairing = await wabot.pairing_qr()
                payload: dict[str, Any] | None = PairingPayload.from_wabot(pairing).model_dump()
            except Exception:  # noqa: BLE001 — never let a transient HTTP error kill the loop
                payload = None
            if payload is not None and payload != pairing_state["last"]:
                pairing_state["last"] = payload
                hub.publish("pairing_changed", payload)
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                return
```

- [ ] **Step 2: Change the initial snapshot**

In `_build_initial_snapshot()` (lines ~387-418), replace the line:

```python
            pairing = _pairing_payload(await wabot.pairing_qr())
```

with:

```python
            pairing = PairingPayload.from_wabot(await wabot.pairing_qr()).model_dump()
```

Leave the surrounding `redact()` wrap on the snapshot dict alone — it covers the other fields and is a no-op on an already-redacted pairing sub-dict (`redact()` is idempotent for non-secret-key strings).

- [ ] **Step 3: Delete the now-unused `_pairing_payload` closure**

Remove lines that defined `_pairing_payload` (currently lines ~105-118 — the entire `def _pairing_payload(p): ...` block including the docstring comment).

- [ ] **Step 4: Run the existing test suite**

Run: `uv run --with '.[dev]' python -m pytest -q`
Expected: All PASS. The REST regression test still pins the wire shape; the SSE poller now produces the same shape via `model_dump()`.

- [ ] **Step 5: Lint**

Run: `uv run --with '.[dev]' ruff check src/wabot_agent/api.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/wabot_agent/api.py
git commit -m "refactor(api): SSE pairing publishers route through PairingPayload

_pairing_poll_loop() and _build_initial_snapshot() now construct
PairingPayload.from_wabot().model_dump() instead of calling the
_pairing_payload closure. The closure is deleted — all three pairing
producers go through one typed, redaction-applying constructor.

Wire shape is unchanged; the headline REST≡SSE contract test in Task 5
proves the two paths emit identical bytes."
```

---

## Task 5: REST ≡ SSE pairing contract test

**Files:**
- Create: `tests/test_pairing_contract.py`

This is the headline acceptance test for #9.

- [ ] **Step 1: Write the failing contract test**

Create `tests/test_pairing_contract.py`:

```python
"""Contract: GET /api/whatsapp/pairing and the SSE `pairing_changed` event
emit identical JSON. If this fails, REST and SSE have drifted — the spec's
single-source-of-truth invariant is broken."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wabot_agent.api import create_app
from wabot_agent.config import Settings
from wabot_agent.schemas import PairingPayload
from wabot_agent.wabot import FakeWabotClient, WabotPairingQR


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
    )


class _ScriptedWabot(FakeWabotClient):
    """Returns a known pairing snapshot. Use a value that exercises redaction
    so we also prove the SSE path doesn't bypass it."""

    async def pairing_qr(self) -> WabotPairingQR:
        return WabotPairingQR(
            supported=True,
            reachable=True,
            logged_in=False,
            connected=False,
            qr="PAIRING-CODE",
            event="qr",
            updated_at="2026-05-16T10:00:00Z",
            expires_at="2026-05-16T10:00:30Z",
            detail="+15551234567 waiting",
        )


def test_rest_pairing_matches_payload_from_wabot(tmp_path: Path) -> None:
    """REST emits exactly what PairingPayload.from_wabot() produces."""
    app = create_app(_settings(tmp_path))
    app.state.wabot = _ScriptedWabot()
    client = TestClient(app)

    rest_body = client.get("/api/whatsapp/pairing").json()
    expected = PairingPayload.from_wabot(
        WabotPairingQR(
            supported=True,
            reachable=True,
            logged_in=False,
            connected=False,
            qr="PAIRING-CODE",
            event="qr",
            updated_at="2026-05-16T10:00:00Z",
            expires_at="2026-05-16T10:00:30Z",
            detail="+15551234567 waiting",
        )
    ).model_dump()

    assert rest_body == expected
    # Sanity: the phone number really was redacted, not just stripped.
    assert "+15551234567" not in json.dumps(rest_body)


def test_rest_and_initial_snapshot_emit_identical_pairing_shape(tmp_path: Path) -> None:
    """The /api/stream initial snapshot's `pairing` sub-field has the same
    JSON shape as the REST endpoint body. This is the most stable proxy for
    the spec's headline REST≡SSE invariant in a TestClient context, since
    `pairing_changed` only fires on diff and the snapshot fans out at connect
    time."""
    app = create_app(_settings(tmp_path))
    app.state.wabot = _ScriptedWabot()
    client = TestClient(app)

    rest_body = client.get("/api/whatsapp/pairing").json()

    with client.stream("GET", "/api/stream") as resp:
        assert resp.status_code == 200
        # Read until we see the first complete `event: ready_snapshot` frame.
        snapshot_pairing: dict | None = None
        buffer = ""
        for chunk in resp.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                lines = frame.splitlines()
                event_name = next(
                    (line[len("event: "):] for line in lines if line.startswith("event: ")),
                    None,
                )
                if event_name != "ready_snapshot":
                    continue
                data_lines = [line[len("data: "):] for line in lines if line.startswith("data: ")]
                snapshot = json.loads("\n".join(data_lines))
                snapshot_pairing = snapshot.get("pairing")
                break
            if snapshot_pairing is not None:
                break

    assert snapshot_pairing is not None, "ready_snapshot did not include a pairing payload"
    assert snapshot_pairing == rest_body
```

Note: the test uses the initial snapshot rather than the `pairing_changed` event because the poll loop only publishes on diff. The initial-snapshot path uses the same `PairingPayload.from_wabot(...).model_dump()` call, so this still proves the invariant.

- [ ] **Step 2: Run the contract test to verify it passes**

Run: `uv run --with '.[dev]' python -m pytest tests/test_pairing_contract.py -v`
Expected: All PASS (2 tests).

If `test_rest_and_initial_snapshot_emit_identical_pairing_shape` fails because the stream reader times out, increase the iteration budget or check that the `ScriptedWabot` was correctly substituted on `app.state.wabot` and that `create_app` actually uses `app.state.wabot` for the pairing call. (In the current code, the inner `wabot` closure variable shadows `app.state.wabot` — see "Spec gap" #1 in the report. If this test fails, swap `wabot` inside `create_app` for `app.state.wabot` lookups, or override at the closure scope via a different fixture pattern.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_pairing_contract.py
git commit -m "test(contract): REST ≡ SSE pairing-shape parity for issue #9

The headline acceptance test for the spec's single-source-of-truth
invariant. With a scripted wabot client, the JSON body from
GET /api/whatsapp/pairing equals the `pairing` sub-field of the
ready_snapshot SSE event."
```

---

## Task 6: `_sse_frame()` accepts a `StreamEventEnvelope`

**Files:**
- Modify: `src/wabot_agent/api.py:669-683` (definition), `:440`, `:446`, `:456`, `:458` (call sites)

- [ ] **Step 1: Change the `_sse_frame()` signature**

Replace `_sse_frame()` (lines ~669-683) with:

```python
def _sse_frame(envelope: StreamEventEnvelope) -> str:
    """Format a single SSE frame from a typed envelope.

    Data is JSON-encoded; multi-line bodies are split across multiple `data:`
    lines per the SSE spec, though our redacted payloads almost never contain
    newlines. The envelope construction has already validated that `name` is
    a non-empty string and `data` is a dict.
    """
    parts: list[str] = []
    if envelope.id is not None:
        parts.append(f"id: {envelope.id}")
    parts.append(f"event: {envelope.name}")
    body = json.dumps(envelope.data, ensure_ascii=False)
    for line in body.split("\n"):
        parts.append(f"data: {line}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)
```

- [ ] **Step 2: Convert the four call sites**

In `event_stream()` (inside `generator()`), replace each call. There are four total:

Line ~440:
```python
            yield _sse_frame(event_id=None, name="ready_snapshot", data=snapshot)
```
becomes:
```python
            yield _sse_frame(StreamEventEnvelope(name="ready_snapshot", data=snapshot))
```

Line ~446:
```python
                for event in backlog:
                    yield _sse_frame(event.id, event.name, event.payload)
```
becomes:
```python
                for event in backlog:
                    yield _sse_frame(
                        StreamEventEnvelope(id=event.id, name=event.name, data=event.payload)
                    )
```

Line ~456:
```python
                        yield _sse_frame(event_id=None, name="heartbeat", data={})
```
becomes:
```python
                        yield _sse_frame(StreamEventEnvelope(name="heartbeat", data={}))
```

Line ~458:
```python
                    yield _sse_frame(event.id, event.name, event.payload)
```
becomes:
```python
                    yield _sse_frame(
                        StreamEventEnvelope(id=event.id, name=event.name, data=event.payload)
                    )
```

- [ ] **Step 3: Run the full test suite**

Run: `uv run --with '.[dev]' python -m pytest -q`
Expected: All PASS — including `test_rest_and_initial_snapshot_emit_identical_pairing_shape` from Task 5, which reads SSE frames end-to-end and exercises the new envelope path.

- [ ] **Step 4: Lint**

Run: `uv run --with '.[dev]' ruff check src/wabot_agent/api.py`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/wabot_agent/api.py
git commit -m "refactor(api): _sse_frame() takes a StreamEventEnvelope

All four /api/stream emission sites (initial snapshot, backlog, heartbeat,
live event) now construct a StreamEventEnvelope at the call site. Frame
layout on the wire is unchanged. Publisher-side validation (empty name,
non-dict data) lands in Task 7 when EventHub.publish enforces the same
envelope."
```

---

## Task 7: Envelope validation in `EventHub.publish` / `EventLog.write` + stream contract test

**Files:**
- Modify: `src/wabot_agent/events.py:53-68` (publish), `:114-124` (write)
- Create: `tests/test_stream_envelope_contract.py`

- [ ] **Step 1: Add envelope validation to `EventHub.publish`**

In `src/wabot_agent/events.py`, add to the imports:

```python
from .schemas import StreamEventEnvelope
```

Replace `EventHub.publish` (lines ~53-68) with:

```python
    def publish(self, name: str, payload: dict[str, Any]) -> Event:
        # Validate the (name, data) pair at the publish call site so a typo'd
        # event name or wrong-shape payload fails fast at the publisher rather
        # than producing a syntactically valid but semantically broken SSE
        # frame on the wire. Bad names / non-dict payloads raise ValidationError.
        StreamEventEnvelope(name=name, data=payload)
        with self._lock:
            self._counter += 1
            event = Event(
                id=self._counter,
                name=name,
                # redact() is defense in depth — every documented producer of
                # pairing data already redacts in PairingPayload.from_wabot().
                payload=redact(payload) if isinstance(payload, dict) else payload,
                ts=datetime.now(UTC).isoformat(),
            )
            self._ring.append(event)
            subs = list(self._subscribers)

        loop = self._loop
        if loop is not None and subs:
            loop.call_soon_threadsafe(self._dispatch, event, subs)
        return event
```

(`EventLog.write` calls `self.hub.publish(event_type, redacted)` already; the new validation fires for that path too, so no separate change is needed in `write`.)

- [ ] **Step 2: Write the failing stream-envelope contract test**

Create `tests/test_stream_envelope_contract.py`:

```python
"""Contract: every frame yielded by /api/stream parses as a StreamEventEnvelope,
and publishing with a bad (name, payload) pair raises at the publisher."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from wabot_agent.api import create_app
from wabot_agent.config import Settings
from wabot_agent.events import EventHub
from wabot_agent.schemas import StreamEventEnvelope


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
    )


def _parse_frames(text: str) -> list[StreamEventEnvelope]:
    """Parse a chunk of SSE wire bytes into envelopes."""
    envelopes: list[StreamEventEnvelope] = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        lines = frame.splitlines()
        event_id_str = next(
            (line[len("id: "):] for line in lines if line.startswith("id: ")), None
        )
        event_id = int(event_id_str) if event_id_str else None
        name = next(
            (line[len("event: "):] for line in lines if line.startswith("event: ")),
            "",
        )
        data_lines = [line[len("data: "):] for line in lines if line.startswith("data: ")]
        data = json.loads("\n".join(data_lines)) if data_lines else {}
        envelopes.append(StreamEventEnvelope(id=event_id, name=name, data=data))
    return envelopes


def test_initial_stream_frame_parses_as_envelope(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))

    with client.stream("GET", "/api/stream") as resp:
        # Read just enough to see one complete frame (ready_snapshot).
        buffer = ""
        for chunk in resp.iter_text():
            buffer += chunk
            if "\n\n" in buffer:
                break

    envelopes = _parse_frames(buffer)
    assert envelopes, "expected at least one frame"
    assert envelopes[0].name == "ready_snapshot"
    assert isinstance(envelopes[0].data, dict)


def test_publish_rejects_empty_name() -> None:
    hub = EventHub()

    with pytest.raises(ValidationError):
        hub.publish("", {"ok": True})


def test_publish_rejects_non_dict_payload() -> None:
    hub = EventHub()

    with pytest.raises(ValidationError):
        hub.publish("ok", "not a dict")  # type: ignore[arg-type]
```

- [ ] **Step 3: Run the new contract tests**

Run: `uv run --with '.[dev]' python -m pytest tests/test_stream_envelope_contract.py -v`
Expected: All PASS (3 tests).

- [ ] **Step 4: Run the full suite to verify no existing publishers passed bad payloads**

Run: `uv run --with '.[dev]' python -m pytest -q`
Expected: All PASS. If anything fails with a ValidationError, the publisher was passing a non-dict (e.g., a list); that is the bug — fix the publisher, not the validation.

- [ ] **Step 5: Lint**

Run: `uv run --with '.[dev]' ruff check src/wabot_agent/events.py tests/test_stream_envelope_contract.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/wabot_agent/events.py tests/test_stream_envelope_contract.py
git commit -m "feat(events): validate (name, payload) via StreamEventEnvelope at publish

EventHub.publish constructs a StreamEventEnvelope before storing/dispatching.
A typo'd event name or a non-dict payload now raises ValidationError at the
publish call site instead of producing a semantically broken SSE frame the
consumer has to detect at parse time. EventLog.write already routes through
publish, so JSONL writes share the validation path.

The existing redact() call in publish is retained as defense in depth —
PairingPayload.from_wabot() is the first line of redaction; this is the
second."
```

---

## Task 8: Widen the TS PairingState interface + Vitest snapshot guard

**Files:**
- Modify: `web/src/api/pairing.ts`
- Create: `web/src/__tests__/pairing-schema.test.ts`

- [ ] **Step 1: Widen the TS interface**

Replace the `PairingState` interface in `web/src/api/pairing.ts` (lines 1-9):

```ts
export interface PairingState {
  qr_available: boolean;
  logged_in: boolean | null;
  connected: boolean | null;
  reachable: boolean;
  detail?: string | null;
  updated_at?: string | null;
  supported?: boolean;
}
```

with:

```ts
/**
 * Public pairing payload — wire shape mirrors
 * `tests/snapshots/pairing_payload.schema.json` (Pydantic `PairingPayload`).
 *
 * When fields change on the Python side, the snapshot test fails first;
 * after refreshing it, update this interface and the Vitest expected-keys
 * list in `pairing-schema.test.ts`.
 */
export interface PairingState {
  supported: boolean;
  reachable: boolean;
  logged_in: boolean | null;
  connected: boolean | null;
  qr_available: boolean;
  event?: string | null;
  updated_at?: string | null;
  expires_at?: string | null;
  detail?: string | null;
}
```

Note: `supported` and `qr_available` are non-optional here because they have non-None defaults on the Python side. `event`/`updated_at`/`expires_at`/`detail` stay optional with `| null` to match the model's `str | None = None` semantics.

Also update the error-case fallback inside `fetchPairing()` so it returns a complete-shape object that satisfies the wider interface — the existing `return { qr_available: false, logged_in: null, connected: null, reachable: false }` block is missing `supported`:

```ts
  if (!res.ok) {
    return {
      qr_available: false,
      logged_in: null,
      connected: null,
      reachable: false,
      supported: false,
    };
  }
```

- [ ] **Step 2: Write the Vitest snapshot guard**

Create `web/src/__tests__/pairing-schema.test.ts`:

```ts
import { describe, expect, it } from "vitest";
// Vitest's resolver inherits tsconfig; the import path resolves the JSON
// snapshot directly. If this import fails, check vite.config.ts /
// tsconfig.json for `resolveJsonModule: true` and that the relative path
// reaches the repo-root tests/ directory.
import schema from "../../../tests/snapshots/pairing_payload.schema.json";

/**
 * Drift guard. When the Python `PairingPayload.model_json_schema()` snapshot
 * changes, this test fails. To fix, either:
 *   1. Refresh the snapshot:
 *        uv run python scripts/dump_schemas.py > tests/snapshots/pairing_payload.schema.json
 *   2. Update EXPECTED_KEYS below and the `PairingState` interface
 *      in `web/src/api/pairing.ts` to match.
 */
const EXPECTED_KEYS = [
  "connected",
  "detail",
  "event",
  "expires_at",
  "logged_in",
  "qr_available",
  "reachable",
  "supported",
  "updated_at",
].sort();

describe("PairingState matches the Python PairingPayload schema", () => {
  it("has the expected property keys", () => {
    const properties = (schema as { properties: Record<string, unknown> }).properties;
    expect(Object.keys(properties).sort()).toEqual(EXPECTED_KEYS);
  });
});
```

- [ ] **Step 3: Run the Vitest case**

Run: `cd web && npm run test -- pairing-schema`
Expected: PASS (1 test in the new file). The existing tests should also still pass.

If the JSON-import fails ("Cannot find module"), inspect `web/tsconfig.json` for `"resolveJsonModule": true` and `web/vite.config.ts` for any `resolve.alias` that might block the parent-directory hop. Adjust to allow `import schema from "../../../tests/snapshots/..."` (one option: add `resolve: { preserveSymlinks: true }` or define an alias `@snapshots: ../tests/snapshots`).

- [ ] **Step 4: Run the full web test suite**

Run: `cd web && npm run test`
Expected: All PASS.

- [ ] **Step 5: Rebuild the static bundle (so the deployed dashboard ships the widened interface)**

Run: `./scripts/build-web.sh`
Expected: Vite builds, rsync mirrors to `static/`. Add the resulting `static/` diff to the commit.

- [ ] **Step 6: Commit**

```bash
git add web/src/api/pairing.ts web/src/__tests__/pairing-schema.test.ts static/
git commit -m "feat(web): PairingState mirrors PairingPayload + snapshot drift guard

Adds event/expires_at/detail to the TS interface — they were already on
the wire but untyped. Adds a Vitest case that diffs against the
Pydantic-generated JSON Schema snapshot; any future Python-side shape
change forces a coordinated update across the model, the snapshot, the
TS interface, and EXPECTED_KEYS in the same PR."
```

---

## Task 9: Lint + full suite + final close

**Files:** none (verification only)

- [ ] **Step 1: Run ruff against the whole repo**

Run: `uv run --with '.[dev]' ruff check .`
Expected: `All checks passed!`

- [ ] **Step 2: Run the full Python test suite under the offline marker**

Run: `uv run --with '.[dev]' python -m pytest -q -m offline`
Expected: All PASS, no warnings about unmarked tests.

- [ ] **Step 3: Run the local eval harness (offline guarantee)**

Run: `uv run python evals/run_local.py`
Expected: completes without error and writes `evals/results/latest.jsonl`.

- [ ] **Step 4: Run the full web test suite**

Run: `cd web && npm run test`
Expected: All PASS.

- [ ] **Step 5: Verify the plan's acceptance criteria from issue #9**

| Acceptance criterion | Evidence |
| --- | --- |
| REST and stream emit the same typed payload shape | `test_rest_and_initial_snapshot_emit_identical_pairing_shape` + `test_rest_pairing_matches_payload_from_wabot` |
| Contract tests fail on shape drift | `test_pairing_payload_schema_matches_snapshot` + Vitest `pairing-schema.test.ts` |
| No unintended client-facing breaking changes | `test_pairing_endpoint_reports_missing_token` still passes unchanged; `PairingState` only gained fields |

- [ ] **Step 6: No commit needed if everything is clean.**

If any artifact slipped (e.g., a stray formatting fix), commit it as `chore: post-implementation cleanup` — but typically Task 9 produces no diff.

---

## Self-Review Checklist (run by the planner, not the executor)

**1. Spec coverage**

| Spec section | Covered by |
| --- | --- |
| `schemas.py` (new) | Task 1 |
| `api.py` REST handler | Task 3 |
| `api.py` SSE poller | Task 4 |
| `api.py` `_build_initial_snapshot()` | Task 4 |
| `api.py` `_sse_frame()` signature | Task 6 |
| `events.py` `EventHub.publish` validation | Task 7 |
| `events.py` `EventLog.write` validation | Task 7 (inherits via `publish`) |
| `web/src/api/pairing.ts` widening | Task 8 |
| `tests/snapshots/pairing_payload.schema.json` | Task 2 |
| Pydantic unit tests | Task 1 + Task 2 |
| `test_rest_and_sse_emit_identical_pairing_shape` | Task 5 |
| `test_every_published_event_is_valid_envelope` | Task 7 (`test_initial_stream_frame_parses_as_envelope`) |
| `test_pairing_payload_schema_matches_snapshot` | Task 2 |
| Vitest `pairing-schema.test.ts` | Task 8 |
| Snapshot-refresh helper script | Task 2 |

**2. Placeholders / hand-waves:** none. Every step has concrete code or a concrete command with an expected outcome.

**3. Type consistency:** `PairingPayload.from_wabot()` signature and `StreamEventEnvelope` field names are used identically in every task that references them. `_sse_frame()` is converted in one step (Task 6); every later reference uses the envelope form.

**4. Test naming:** the spec's `test_every_published_event_is_valid_envelope` is implemented as `test_initial_stream_frame_parses_as_envelope` because, in a TestClient context, the only frame guaranteed to fire without manual publish is the `ready_snapshot`. The validation that "every published event is a valid envelope" is structurally enforced by the new `EventHub.publish` validation (Task 7) plus the negative tests (`test_publish_rejects_empty_name`, `test_publish_rejects_non_dict_payload`). The combination is equivalent to the spec's intent.

---

## Risks / Breaking-Change Audit

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| A current `hub.publish` or `event_log.write` caller passes a non-dict and the new validation breaks it. | Low — `grep` of all call sites shows dict literals everywhere. | Task 7's full-suite run catches this. The fail-fast is itself the point. |
| `redact()` reshapes `detail` in a way that breaks Pydantic validation. | Very low — `redact()` only rewrites matching string substrings inside strings, never changes types. | `test_pairing_payload_redacts_detail` (Task 1) covers this. |
| `model_json_schema()` output is non-deterministic across Pydantic minor versions, making the snapshot noisy. | Low — Pydantic v2 schema output is stable within a minor; `uv.lock` pins it. | If diff noise becomes a problem, sort keys (already done in `dump_schemas.py`). |
| The Vitest import path `../../../tests/snapshots/...` doesn't resolve. | Medium — depends on `tsconfig.json` settings. | Task 8 Step 3 calls out the fallback (alias or `resolveJsonModule`). |
| `_build_initial_snapshot()`'s outer `redact()` wraps an already-redacted pairing sub-dict. | None — `redact()` is idempotent for non-secret-key string values. | Confirmed in `redaction.py:redact()`. |
| External clients depend on the raw `qr` string being present in the JSON payload. | None — the current closure never emits `qr` either; this preserves existing behavior. | `test_pairing_payload_omits_raw_qr` codifies the rule. |
| The frontend store/hook expects fields that are now `null` to be missing. | Low — `subscribePairing` just `JSON.parse`s and forwards to Zustand; `null` and `undefined` both render as "unknown" in the pairing card. | Existing Vitest `pair-view.test.tsx` is the regression net; run it in Task 8. |

**Breaking-change audit:**
- JSON keys: unchanged set on the wire. REST emitted 9 keys before, emits 9 keys now. SSE emitted 9 keys before, emits 9 keys now.
- HTTP status codes / headers: unchanged.
- SSE frame layout (`id:`, `event:`, `data:` lines): unchanged.
- Event names: unchanged (`pairing_changed`, `ready_snapshot`, `heartbeat`, all `agent_run_*`, `inbound_message_*`, `send_*`, `settings_updated`).
- TS `PairingState`: strictly widened (added fields); no removals.

---

## Frontend TS-Type Sync Strategy

**Decision: hand-mirror the TS interface; enforce sync via a checked-in JSON Schema snapshot and a Vitest assertion.**

**Trade-offs considered:**

| Option | Pros | Cons | Decision |
| --- | --- | --- | --- |
| Auto-generate TS from Pydantic (`pydantic-to-typescript`, `json-schema-to-typescript`) | Zero hand-edit drift | New build dep, generated files in source tree, harder to add JSDoc / branded types | Rejected at this scope — only one model, hand-edit is a one-line diff |
| Leave TS loose (current state) | No new tests | Drift is silent until a runtime error | Rejected — issue #9's acceptance criterion is shape stability |
| **Hand-mirror + snapshot drift guard (chosen)** | One reviewable artifact (the schema JSON) per shape change. Forces TS + Pydantic + tests to move together. | Two small files to edit per shape change. | Chosen |

The chosen approach makes drift **structurally unmergeable**: a Python-side field rename fails (a) the Python snapshot test, (b) the Vitest expected-keys test, and (c) the TS compile if `PairingState` doesn't match — three tripwires for one bug.

If the cadence of pairing-shape changes ever picks up materially, revisit auto-generation as a follow-up issue.

---

## Spec Gaps Surfaced While Planning

Documented in the report message — see the parent agent's response.
