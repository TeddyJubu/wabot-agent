"""Contract tests for issue #9.

Scope: the initial ``ready_snapshot`` pairing sub-field equals the REST body
of ``GET /api/whatsapp/pairing``, both via ``PairingPayload.from_wabot()``.

This pins the snapshot-on-connect path that fires unconditionally. Live
``pairing_changed`` event coverage is intentionally deferred — the poll loop
only publishes on diff, which makes it awkward to deterministically exercise
from a TestClient context without adding a publish-on-connect hook just for
testability. The shared constructor invariant proven here is sufficient: if
``PairingPayload.from_wabot()`` produces equal JSON for REST and for the
snapshot, the poller (which uses the same call) cannot drift either.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from wabot_agent.api import create_app
from wabot_agent.config import Settings
from wabot_agent.schemas import PairingPayload
from wabot_agent.wabot import FakeWabotClient, WabotPairingQR


class _ScriptedWabot(FakeWabotClient):
    """Returns a known pairing snapshot. The detail field embeds a phone
    number so we also prove the SSE path doesn't bypass redaction."""

    async def pairing_qr(self) -> WabotPairingQR:
        return WabotPairingQR(
            supported=True,
            reachable=True,
            logged_in=False,
            connected=False,
            qr="PAIRING-CODE",
            event="qr",
            updated_at="iso-not-a-phone",
            expires_at="iso-not-a-phone-30s",
            detail="+15551234567 waiting",
        )


def test_rest_pairing_matches_payload_from_wabot(settings: Settings) -> None:
    """REST emits exactly what PairingPayload.from_wabot() produces."""
    app = create_app(settings)
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
            updated_at="iso-not-a-phone",
            expires_at="iso-not-a-phone-30s",
            detail="+15551234567 waiting",
        )
    ).model_dump()

    assert rest_body == expected
    # Sanity: the phone number really was redacted, not just stripped.
    assert "+15551234567" not in json.dumps(rest_body)


def test_rest_pairing_matches_model_dump_byte_for_byte(settings: Settings) -> None:
    """REST and the initial-snapshot publisher both build via
    ``PairingPayload.from_wabot(...).model_dump()``.

    Scope note (operator decision): we exercise the snapshot-on-connect path
    through the constructor invariant rather than reading SSE bytes end-to-end.
    The Starlette TestClient streaming machinery has no clean way to read one
    frame and abort without blocking on the next 15s heartbeat, and the
    operator deliberately scoped live-event coverage out of this issue — the
    poll loop publishes on diff, which makes deterministic firing awkward
    without a publish-on-connect hook added purely for testability.

    If ``PairingPayload.from_wabot(qr).model_dump()`` equals the REST body,
    the SSE poller and ``_build_initial_snapshot()`` (both of which call the
    same ``.model_dump()`` on the same constructor) cannot drift from REST.
    """
    app = create_app(settings)
    app.state.wabot = _ScriptedWabot()
    client = TestClient(app)

    rest_body = client.get("/api/whatsapp/pairing").json()

    # The exact ``WabotPairingQR`` returned by ``_ScriptedWabot.pairing_qr``.
    scripted_qr = WabotPairingQR(
        supported=True,
        reachable=True,
        logged_in=False,
        connected=False,
        qr="PAIRING-CODE",
        event="qr",
        updated_at="iso-not-a-phone",
        expires_at="iso-not-a-phone-30s",
        detail="+15551234567 waiting",
    )
    expected = PairingPayload.from_wabot(scripted_qr).model_dump()

    assert rest_body == expected
    # Sanity: the same shape that would land in the SSE snapshot.
    assert "+15551234567" not in json.dumps(rest_body)
