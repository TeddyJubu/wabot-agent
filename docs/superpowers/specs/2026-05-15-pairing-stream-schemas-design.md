# Pairing + Stream Event Schemas — Design

- **Date:** 2026-05-15
- **Issue:** [#9 — API: formalize pairing + stream event schemas with Pydantic models](https://github.com/TeddyJubu/vignesh/issues/9)
- **Status:** Approved (brainstorm) — pending plan
- **Scope:** Narrow — pairing payload + SSE envelope only. Per-event payload typing is deliberately out of scope for this change.

## Problem

The pairing payload and SSE event framing are maintained by convention, not by typed contract.

1. The canonical pairing JSON shape is a closure (`_pairing_payload` in [src/wabot_agent/api.py:105](../../../src/wabot_agent/api.py)) called by both `GET /api/whatsapp/pairing` and the SSE `pairing_changed` poller. The shape stays aligned only because both call sites happen to call the same helper.
2. The TypeScript `PairingState` interface in [web/src/api/pairing.ts:1](../../../web/src/api/pairing.ts) declares 7 fields; the Python helper emits 9. Drift already exists (`event`, `expires_at` are untyped on the consumer side).
3. The REST handler calls `redact()` on the pairing payload before returning. The SSE poller publishes the raw payload to the hub **without** redaction (api.py:135 vs api.py:240). If wabot returns a `detail` containing a phone number, REST scrubs it and SSE leaks it.
4. SSE frames are built by `_sse_frame(event_id, name, data)` with no validation. A publisher passing an empty name or a non-dict payload would produce a malformed frame that the browser silently discards.

These are the kinds of bugs that get harder to find as more consumers grow on top of the new public surface. Issue #9 was filed alongside PR #7 specifically to lock the contract before that happens.

## Goals

- Pairing payload is one Pydantic model used by REST and SSE.
- Redaction is part of constructing that model — there is no way to build a public payload that hasn't been redacted.
- Every event over `/api/stream` is wrapped in a typed envelope; framing errors fail fast at the publisher, not silently on the wire.
- TS authors find out about Python-side drift in code review, by way of a diff to a checked-in JSON Schema snapshot.

## Non-goals

- Typing per-event `data` payloads (e.g., `AgentRunComplete`, `InboundMessage`). Each event keeps `data: dict[str, Any]` at this stage. A follow-up issue can convert specific events as the need arises.
- Changing event names, removing fields, or any other wire-format break. Acceptance criterion: "no unintended client-facing breaking changes."
- Auto-generating TS types from Pydantic. Hand-written TS + drift-by-review is sufficient at this scope.
- Touching the chat NDJSON stream (`/api/chat/stream`). That's a different transport; out of scope.

## Approach

**One new module, two new models, three call sites converted to use them, one snapshot file, one Vitest case.**

The three call sites that produce pairing data on the wire — `GET /api/whatsapp/pairing`, the `pairing_changed` SSE poller, and the `pairing` sub-field of `ready_snapshot` — all construct `PairingPayload.from_wabot()`. The `_sse_frame()` serializer accepts a `StreamEventEnvelope` argument so all event names + payloads flow through one typed chokepoint.

### `src/wabot_agent/schemas.py` (new)

```python
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from .redaction import redact
from .wabot import WabotPairingQR


class PairingPayload(BaseModel):
    """Public, redacted projection of WabotPairingQR.

    Single source of truth for the JSON shape emitted by both
    GET /api/whatsapp/pairing and the SSE `pairing_changed` event.
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
    def from_wabot(cls, p: WabotPairingQR) -> "PairingPayload":
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
    """Wire format for every event over /api/stream."""
    id: int | None = None
    name: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
```

### `src/wabot_agent/api.py` (changed)

- Remove the `_pairing_payload` closure.
- `GET /api/whatsapp/pairing` declares `response_model=PairingPayload` and returns `PairingPayload.from_wabot(await wabot.pairing_qr())`. FastAPI's auto-OpenAPI now includes the schema for free.
- `_pairing_poll_loop` constructs `PairingPayload.from_wabot(...).model_dump()` and publishes that dict to the hub. Identical shape to REST.
- `_build_initial_snapshot()`'s embedded `pairing` field is also built via `PairingPayload.from_wabot(...).model_dump()` — keeps the cold-start path aligned with the live-event path.
- `_sse_frame(event_id, name, data)` becomes `_sse_frame(envelope: StreamEventEnvelope) -> str`. Call sites in `event_stream()` construct `StreamEventEnvelope(...)` once per frame; the framing logic itself is unchanged.

### `src/wabot_agent/events.py` (changed)

- `EventHub.publish(name, payload)` validates by constructing `StreamEventEnvelope(name=name, data=payload)` at the call site, then continues with the existing storage/queue logic. Bad name (empty string) or bad payload type (not a dict) raises immediately at the publisher.
- `EventLog.write(name, payload)` uses the same construction so JSONL writes and hub publishes share the validation path.

### `web/src/api/pairing.ts` (changed)

The `PairingState` interface gains the two fields that were already on the wire:

```ts
export interface PairingState {
  qr_available: boolean;
  logged_in: boolean | null;
  connected: boolean | null;
  reachable: boolean;
  supported: boolean;
  event?: string | null;
  updated_at?: string | null;
  expires_at?: string | null;
  detail?: string | null;
}
```

`subscribePairing` keeps the same event-name listeners and the same JSON.parse behavior. No runtime change.

### `tests/snapshots/pairing_payload.schema.json` (new)

Output of `PairingPayload.model_json_schema()`, checked in. Diffs are reviewable line items in PRs.

## Data flow

### REST — `GET /api/whatsapp/pairing`

```
wabot daemon → WabotPairingQR → PairingPayload.from_wabot() → FastAPI serializes (Pydantic → JSON)
   (HTTP)       (dataclass)       (redact applied here)
```

### SSE — `pairing_changed`

```
poll loop → WabotPairingQR → PairingPayload.from_wabot() → model_dump() → hub.publish("pairing_changed", dict)
              (dataclass)      (redact applied here)         (dict for      → SSE subscriber gets envelope
                                                              hub storage)    → _sse_frame(envelope) → wire
```

### Envelope discipline

Every frame yielded by the `/api/stream` generator goes through one call:

```python
yield _sse_frame(StreamEventEnvelope(id=event.id, name=event.name, data=event.payload))
yield _sse_frame(StreamEventEnvelope(name="ready_snapshot", data=snapshot))
yield _sse_frame(StreamEventEnvelope(name="heartbeat", data={}))
```

The envelope is the only path data can take to the wire. Bad framing fails at construction, not on the consumer.

## Redaction invariant

`PairingPayload` is the only object that crosses the trust boundary out of the wabot layer. Construction is centralized in `from_wabot()`. The three call sites — `GET /api/whatsapp/pairing` (REST), the `_pairing_poll_loop` (live SSE event), and `_build_initial_snapshot` (cold-start SSE bundle) — all consume the same classmethod. There is no documented or undocumented way to get an unredacted public payload onto the wire without bypassing the class — and `_sse_frame`'s type signature plus `response_model=` prevent that for SSE and REST respectively.

## Error handling

| Failure | REST behavior | SSE behavior |
|---|---|---|
| `WabotPairingQR` has an unexpected value | Pydantic `ValidationError` → FastAPI 500 | Existing `except Exception: payload = None` swallows; pairing card stays on last-known-good; next tick retries |
| Publisher passes `name=""` or `data="not a dict"` | n/a — REST doesn't publish | `StreamEventEnvelope(...)` raises at the publisher's call site; bug surfaces at the publish point, not on the wire |
| Envelope construction raises inside `_sse_frame` | n/a | Generator's `try/finally` cleans up the subscription; `EventSource` auto-reconnects |

## Testing strategy

### Python (`tests/`)

```
tests/
├── test_schemas.py                  # NEW — unit tests for the models themselves
├── test_pairing_contract.py         # NEW — REST ≡ SSE shape parity
├── test_stream_envelope_contract.py # NEW — every published event is a valid envelope
└── snapshots/
    └── pairing_payload.schema.json  # NEW — JSON Schema snapshot
```

| Test | Asserts |
|---|---|
| `test_pairing_payload_from_wabot_roundtrip` | `PairingPayload.from_wabot(WabotPairingQR(...))` has the expected field values. |
| `test_pairing_payload_redacts_detail` | `WabotPairingQR(detail="+1234567890 unauthorized")` → `payload.detail` has the number masked. **Contract test for the SSE-leak bug.** |
| `test_stream_envelope_rejects_empty_name` | `StreamEventEnvelope(name="", data={})` raises `ValidationError`. |
| `test_stream_envelope_rejects_non_dict_data` | `StreamEventEnvelope(name="x", data="oops")` raises `ValidationError`. |
| `test_rest_and_sse_emit_identical_pairing_shape` | With `FakeWabotClient` returning a known `WabotPairingQR`, the JSON body from `GET /api/whatsapp/pairing` equals the parsed `pairing_changed.data` read from `/api/stream`. **Headline acceptance test for #9.** |
| `test_every_published_event_is_valid_envelope` | Publish events with various names/payloads via the hub, read SSE frames, parse each — all parse as `StreamEventEnvelope`. |
| `test_pairing_payload_schema_matches_snapshot` | `PairingPayload.model_json_schema()` equals the checked-in `tests/snapshots/pairing_payload.schema.json`. On a legitimate change, regenerate with the helper documented below. |

**Snapshot refresh.** Add a one-line script in `scripts/dump-schemas.py`:

```python
# scripts/dump-schemas.py
import json
from wabot_agent.schemas import PairingPayload

print(json.dumps(PairingPayload.model_json_schema(), indent=2, sort_keys=True))
```

Refresh with `uv run python scripts/dump-schemas.py > tests/snapshots/pairing_payload.schema.json`. The diff is the reviewable artifact.

All tests run under the existing `offline` marker — no network, no creds.

### Frontend (`web/src/__tests__/`)

```ts
// pairing-schema.test.ts (NEW)
import schema from '../../../tests/snapshots/pairing_payload.schema.json';

const EXPECTED_KEYS = [
  'connected', 'detail', 'event', 'expires_at', 'logged_in',
  'qr_available', 'reachable', 'supported', 'updated_at',
].sort();

it('PairingState matches the Python schema snapshot', () => {
  expect(Object.keys(schema.properties).sort()).toEqual(EXPECTED_KEYS);
});
```

If a backend dev adds or removes a field:
1. `test_pairing_payload_schema_matches_snapshot` fails → they refresh the snapshot.
2. `pairing-schema.test.ts` fails → they update `EXPECTED_KEYS`.
3. The TS `PairingState` interface still won't match the data the runtime sees → they update it too.

Drift is structurally unmergeable without touching all three files in one PR.

## Migration / rollout

- No env vars added.
- No database migration.
- No public field deletions, no event-name changes — `gh issue view 9` acceptance: "no unintended client-facing breaking changes."
- Backward-compatible for any external script that hits `GET /api/whatsapp/pairing` (same JSON keys, same values).
- One-shot deploy: merge the PR, restart the service.

## Risks

| Risk | Mitigation |
|---|---|
| A current `hub.publish` site happens to pass a non-dict payload and the stricter validation breaks it. | Run the full pytest suite before merging; all current publish sites pass dicts. The fail-fast behavior is itself the point — if there's an existing bug, surface it now. |
| `redact()` reshapes a value in a way that breaks Pydantic validation (e.g., turns `None` into a non-string for `detail`). | Add `test_pairing_payload_redacts_detail` and similar; `redact()` is well-tested and only replaces matching string patterns. |
| Snapshot tests become noisy if `model_json_schema()` output is non-deterministic across Pydantic versions. | Pin the Pydantic minor version in `pyproject.toml` (already pinned via `uv.lock`); JSON Schema output is stable within a minor. |
| TS authors update the snapshot but forget the `PairingState` interface. | `pairing-schema.test.ts` checks key parity; runtime type mismatches surface in browser console because the TS interface only differs from the wire by *missing* fields, which is the safe direction (no crashes). |

## Out of scope (follow-ups)

- Typing per-event payloads (`AgentRunComplete`, `InboundMessage`, `SendBlocked`, ...) — each is its own small follow-up.
- Auto-generating TS types from Pydantic (`pydantic-to-typescript` / `json-schema-to-typescript`) — revisit if the hand-edit cadence becomes painful.
- Surfacing the JSON Schema at a public endpoint (`GET /api/schemas/pairing`) for third-party tooling — no current consumer.
