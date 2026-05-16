"""Typed wire contracts for the pairing payload and SSE event envelope.

Issue #9 — see docs/superpowers/specs/2026-05-15-pairing-stream-schemas-design.md.

`PairingPayload` is the single source of truth for the JSON shape returned by
both `GET /api/whatsapp/pairing` (REST) and the SSE `pairing_changed` event.
Construction via `from_wabot()` applies `redact()` so every public payload is
redacted at the producer; `EventHub.publish()` keeps its own `redact()` as
defense in depth.

`StreamEventEnvelope` is the wire format for every frame written to
`/api/stream`. Building one at the publish call site (in `EventHub.publish`)
makes name typos and wrong-shape payloads raise a `ValidationError` at the
publisher instead of producing a syntactically valid but semantically broken
frame on the wire. `EventLog.write` persists frames to disk without envelope
validation — the validation guarantee applies only to the SSE path.

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
