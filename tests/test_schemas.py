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
        # Note: timestamp strings are chosen so they don't match the
        # phone-number regex in redact() — the existing wire path already
        # mangled date-shaped strings (a known pre-existing quirk), and we
        # preserve that behavior to avoid a wire-shape break in this issue.
        updated_at="iso-not-a-phone",
        expires_at="iso-not-a-phone-30s",
        detail="waiting for scan",
    )

    payload = PairingPayload.from_wabot(qr)

    assert payload.supported is True
    assert payload.reachable is True
    assert payload.logged_in is False
    assert payload.connected is False
    assert payload.qr_available is True
    assert payload.event == "qr"
    assert payload.updated_at == "iso-not-a-phone"
    assert payload.expires_at == "iso-not-a-phone-30s"
    assert payload.detail == "waiting for scan"
    # The raw QR string is intentionally NOT part of the public payload.
    assert "qr" not in payload.model_dump() or payload.model_dump().get("qr") is None


def test_pairing_payload_omits_raw_qr() -> None:
    """The raw QR payload is fetched separately via /api/whatsapp/pairing.svg.

    Putting it in the JSON payload would leak it into the SSE backlog (256-entry
    ring) and the events.jsonl audit log, which are intentionally a lower trust
    tier than the SVG endpoint.
    """
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
