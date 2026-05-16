"""Tests for the UI envelope builders.

These tests deliberately feed *real* tool result payload shapes — the
shapes that `tools.py` and `memory.py` actually emit — so the envelope
builders stay locked to the tool contract. Earlier versions of these
tests used envelope-shaped fake payloads, which let the schemas drift
apart silently.
"""
from __future__ import annotations

from wabot_agent.ui_envelopes import build_ui_envelope


def test_get_last_inbound_builds_inbox_card() -> None:
    env = build_ui_envelope(
        "get_last_whatsapp_inbound_message",
        {
            "found": True,
            "message": {
                "from": "+15550001111",
                "text": "hello there",
                "push_name": "Teddy",
            },
            "source": "wabot_daemon",
        },
    )
    assert env is not None
    assert env["kind"] == "inbox_message"
    assert env["data"]["messages"][0]["sender"] == "Teddy"
    assert env["data"]["messages"][0]["text"] == "hello there"


def test_unknown_tool_returns_none() -> None:
    assert build_ui_envelope("not_a_tool", {"foo": 1}) is None


def test_non_dict_result_returns_none() -> None:
    assert build_ui_envelope("wabot_health", "ok") is None
    assert build_ui_envelope("wabot_health", None) is None


# wabot_health → wabot_status -------------------------------------------------


def test_wabot_health_ready_is_ok() -> None:
    env = build_ui_envelope(
        "wabot_health",
        {
            "reachable": True,
            "logged_in": True,
            "connected": True,
            "ready": True,
            "detail": None,
        },
    )
    assert env is not None
    assert env["kind"] == "wabot_status"
    assert env["data"]["status"] == "ok"
    assert "error" not in env["data"]
    assert env["actions"][0]["id"] == "recheck"


def test_wabot_health_reachable_but_not_ready_is_warn() -> None:
    env = build_ui_envelope(
        "wabot_health",
        {
            "reachable": True,
            "logged_in": False,
            "connected": False,
            "ready": False,
            "detail": "logged out / session invalidated",
        },
    )
    assert env is not None
    assert env["data"]["status"] == "warn"
    assert env["data"]["error"] == "logged out / session invalidated"


def test_wabot_health_unreachable_is_bad() -> None:
    env = build_ui_envelope(
        "wabot_health",
        {
            "reachable": False,
            "logged_in": None,
            "connected": None,
            "ready": False,
            "detail": "All connection attempts failed",
        },
    )
    assert env is not None
    assert env["data"]["status"] == "bad"
    assert env["data"]["error"] == "All connection attempts failed"


# send_whatsapp_* → send_confirm ---------------------------------------------


def test_send_text_success_shows_delivered() -> None:
    # Mirrors the `sent=True` branch in tools.send_whatsapp_text.
    env = build_ui_envelope(
        "send_whatsapp_text",
        {
            "sent": True,
            "policy": "allowlist",
            "to": "+15***4567",
            "result": {"id": "wamid.1"},
        },
    )
    assert env is not None
    assert env["kind"] == "send_confirm"
    assert env["data"]["policy"] == "allowlist"
    assert env["data"]["delivered"] is True
    assert env["data"]["needs_approval"] is False
    # `to` is already masked by the tool; the envelope re-masks defensively.
    assert "***" in env["data"]["recipient_masked"]
    assert env["data"]["recipient_masked"].endswith("4567")
    # Tools don't echo the message body, so the preview stays empty.
    assert env["data"]["body_preview"] == ""
    # Nothing to approve on a finished send.
    assert env["actions"] == []


def test_send_text_blocked_by_dry_run_reads_reason_as_policy() -> None:
    # Mirrors the `_is_send_allowed → dry_run` blocked branch.
    env = build_ui_envelope(
        "send_whatsapp_text",
        {
            "sent": False,
            "reason": "dry_run",
            "to": "+15***4567",
            "operator_action": "Set WABOT_AGENT_SEND_POLICY=allowlist …",
        },
    )
    assert env is not None
    assert env["data"]["policy"] == "dry_run"
    assert env["data"]["delivered"] is False
    assert env["data"]["needs_approval"] is False
    assert env["actions"] == []


def test_send_text_blocked_by_recipient_falls_back_to_dry_run_policy() -> None:
    # `recipient_not_allowlisted` is not a policy name → conservative fallback.
    env = build_ui_envelope(
        "send_whatsapp_text",
        {
            "sent": False,
            "reason": "recipient_not_allowlisted",
            "to": "+15***4567",
        },
    )
    assert env is not None
    assert env["data"]["policy"] == "dry_run"
    assert env["data"]["delivered"] is False


def test_send_image_blocked_payload_does_not_crash_without_path() -> None:
    # tools.send_whatsapp_image's `image_path_not_allowed` branch returns
    # {sent, reason, detail} with no `path` key — make sure the builder
    # tolerates it (image_path becomes None, not a KeyError).
    env = build_ui_envelope(
        "send_whatsapp_image",
        {
            "sent": False,
            "reason": "image_path_not_allowed",
            "detail": "Images must live under /opt/wabot-agent/data/media.",
        },
    )
    assert env is not None
    assert env["data"]["image_path"] is None
    assert env["data"]["caption_preview"] == ""


def test_send_image_includes_image_metadata_when_present() -> None:
    # Mirrors the blocked-by-policy branch where `path` IS included.
    env = build_ui_envelope(
        "send_whatsapp_image",
        {
            "sent": False,
            "reason": "recipient_not_allowlisted",
            "to": "+15***4567",
            "path": "hello.png",
        },
    )
    assert env is not None
    assert env["data"]["image_path"] == "hello.png"


# recall_contact_memory → memory ---------------------------------------------


def test_recall_contact_memory_maps_key_value_facts() -> None:
    # Mirrors MemoryStore.recall_contact: each fact has {key,value,source,updated_at}.
    env = build_ui_envelope(
        "recall_contact_memory",
        {
            "contact": "+15551234567",
            "facts": [
                {
                    "key": "timezone",
                    "value": "PT",
                    "source": "run-1",
                    "updated_at": "2026-01-01",
                },
                {
                    "key": "tone",
                    "value": "prefers async",
                    "source": "run-2",
                    "updated_at": "2026-01-02",
                },
            ],
        },
    )
    assert env is not None
    assert env["kind"] == "memory"
    assert env["data"]["contact_masked"].endswith("4567")
    assert env["data"]["facts"] == [
        {"id": "timezone", "text": "timezone: PT"},
        {"id": "tone", "text": "tone: prefers async"},
    ]


def test_remember_contact_fact_payload_has_no_facts_list() -> None:
    # `remember_contact_fact` returns {stored, contact, key} — no facts list.
    # Card renders an empty card (no crash).
    env = build_ui_envelope(
        "remember_contact_fact",
        {"stored": True, "contact": "+15551234567", "key": "timezone"},
    )
    assert env is not None
    assert env["data"]["facts"] == []


# __pairing_qr ----------------------------------------------------------------


def test_pairing_emits_qr_card() -> None:
    env = build_ui_envelope(
        "__pairing_qr", {"available": True, "linked_device": "iPhone"}
    )
    assert env == {
        "kind": "pairing_qr",
        "data": {"available": True, "linked_device": "iPhone"},
        "actions": [
            {"id": "refresh", "label": "Refresh", "tool": "__pairing_qr", "args": {}}
        ],
    }


# Robustness ------------------------------------------------------------------


def test_mask_recipient_handles_short_input() -> None:
    env = build_ui_envelope(
        "send_whatsapp_text",
        {"sent": False, "reason": "dry_run", "to": "123"},
    )
    assert env is not None
    assert env["data"]["recipient_masked"] == "***"


def test_builder_swallows_exceptions() -> None:
    env = build_ui_envelope(
        "recall_contact_memory", {"contact": None, "facts": "not-a-list"}
    )
    assert env is not None
    assert env["data"]["contact_masked"] == "***"
    assert env["data"]["facts"] == []
