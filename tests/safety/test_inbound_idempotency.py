"""Regression suite for the inbound dedup safety invariant.

CLAUDE.md: "Inbound webhooks are deduped by `message_id` via a state machine
(processing|done|failed). The stored message body must not be overwritten by a
replayed webhook that reuses an existing `message_id`."

The bug fixed in `fix/inbound-record-after-claim` (api.py: `_process_whatsapp_inbound`)
was that `memory.record_inbound(inbound)` ran BEFORE `memory.claim_message(...)`.
Because `record_inbound` uses `INSERT ... ON CONFLICT DO UPDATE` on `message_id`,
an attacker who controlled `message_id` and replayed a webhook with mutated `text`
silently rewrote the persisted body even though `claim_message` correctly returned
`duplicate=True` on the second request.

These tests pin the invariant: a duplicate POST to /whatsapp/inbound must NOT
overwrite the original body in `inbound_messages`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wabot_agent.api import create_app
from wabot_agent.config import Settings
from wabot_agent.memory import MemoryStore


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="dry_run",
        OPENROUTER_MODEL="openai/gpt-5.2",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )


_AUTH = {"Authorization": "Bearer inbound-secret"}


def test_replay_with_mutated_text_does_not_overwrite_stored_body(
    tmp_path: Path,
) -> None:
    """The body persisted on the FIRST accepted webhook must survive a replay
    that reuses the same message_id with a mutated text payload."""
    settings = _make_settings(tmp_path)
    client = TestClient(create_app(settings))

    original = {
        "id": "msg-replay-1",
        "from": "+15550001111",
        "text": "original benign text",
    }
    mutated = {**original, "text": "ATTACKER MUTATED PAYLOAD"}

    first = client.post("/whatsapp/inbound", json=original, headers=_AUTH)
    second = client.post("/whatsapp/inbound", json=mutated, headers=_AUTH)

    assert first.status_code == 200
    assert first.json()["duplicate"] is False

    assert second.status_code == 200
    assert second.json()["duplicate"] is True, (
        "second webhook with same message_id must be rejected as a duplicate"
    )

    # The stored body must still match the FIRST payload, not the mutated one.
    memory = MemoryStore(settings.db_path)
    stored = memory.last_inbound()
    assert stored is not None
    assert stored["id"] == "msg-replay-1"
    assert stored["text"] == "original benign text", (
        "record_inbound must run AFTER claim_message succeeds; a duplicate "
        "webhook must not overwrite the persisted message body"
    )


def test_replay_on_empty_text_branch_does_not_overwrite_stored_body(
    tmp_path: Path,
) -> None:
    """The empty-text-no-media branch has its own claim/record/complete sequence.
    A replay that adds text after an empty-payload first send must not overwrite
    the empty body (and must still be rejected as a duplicate)."""
    settings = _make_settings(tmp_path)
    client = TestClient(create_app(settings))

    original = {"id": "msg-replay-empty", "from": "+15550001111", "text": ""}
    mutated = {**original, "text": "ATTACKER ADDED TEXT"}

    first = client.post("/whatsapp/inbound", json=original, headers=_AUTH)
    second = client.post("/whatsapp/inbound", json=mutated, headers=_AUTH)

    assert first.status_code == 200
    assert first.json().get("skipped") is True
    assert first.json().get("reason") == "empty_text_no_media"

    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    memory = MemoryStore(settings.db_path)
    stored = memory.last_inbound()
    assert stored is not None
    assert stored["id"] == "msg-replay-empty"
    assert stored["text"] == "", (
        "empty-text branch must also reject the replayed mutation"
    )


@pytest.mark.parametrize("attempts", [3, 5])
def test_repeated_replay_storm_never_overwrites_body(
    tmp_path: Path, attempts: int
) -> None:
    """Sanity: hammering the endpoint N times with mutated text must still leave
    the original body in place (catches accidental retry-only fixes that drop
    the first dedup gate)."""
    settings = _make_settings(tmp_path)
    client = TestClient(create_app(settings))

    first_payload = {
        "id": "msg-storm-1",
        "from": "+15550001111",
        "text": "first arrival",
    }
    first = client.post("/whatsapp/inbound", json=first_payload, headers=_AUTH)
    assert first.status_code == 200
    assert first.json()["duplicate"] is False

    for i in range(attempts):
        replay = {**first_payload, "text": f"mutation {i}"}
        resp = client.post("/whatsapp/inbound", json=replay, headers=_AUTH)
        assert resp.status_code == 200
        assert resp.json()["duplicate"] is True

    memory = MemoryStore(settings.db_path)
    stored = memory.last_inbound()
    assert stored is not None
    assert stored["text"] == "first arrival"
