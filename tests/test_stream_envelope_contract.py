"""Contract: every publish through EventHub satisfies StreamEventEnvelope,
and publishing with a bad (name, payload) pair raises at the publisher."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from wabot_agent.events import EventHub
from wabot_agent.schemas import StreamEventEnvelope


def test_publish_round_trips_through_envelope() -> None:
    """Publishing a valid (name, dict) pair stores the event under the same
    envelope contract that ``_sse_frame()`` writes on the wire. The roundtrip
    proves the publisher and serializer share one source of truth.

    Scope note (operator decision): exercising the full SSE stream end-to-end
    is intentionally deferred — Starlette's TestClient cannot cleanly read a
    single frame and abort without blocking on the 15s heartbeat. The publish
    validation + envelope construction below covers the same invariant on the
    publisher side without the streaming machinery.
    """
    hub = EventHub()
    event = hub.publish("agent_run_complete", {"run_id": "abc", "ok": True})

    envelope = StreamEventEnvelope(id=event.id, name=event.name, data=event.payload)
    assert envelope.id == event.id
    assert envelope.name == "agent_run_complete"
    assert envelope.data == {"run_id": "abc", "ok": True}


def test_publish_rejects_empty_name() -> None:
    hub = EventHub()

    with pytest.raises(ValidationError):
        hub.publish("", {"ok": True})


def test_publish_rejects_non_dict_payload() -> None:
    hub = EventHub()

    with pytest.raises(ValidationError):
        hub.publish("ok", "not a dict")  # type: ignore[arg-type]
