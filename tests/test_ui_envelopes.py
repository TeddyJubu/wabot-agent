from __future__ import annotations

from wabot_agent.ui_envelopes import build_ui_envelope


def test_unknown_tool_returns_none() -> None:
    assert build_ui_envelope("not_a_tool", {"foo": 1}) is None


def test_non_dict_result_returns_none() -> None:
    assert build_ui_envelope("wabot_health", "ok") is None
    assert build_ui_envelope("wabot_health", None) is None


def test_wabot_health_ok() -> None:
    env = build_ui_envelope(
        "wabot_health",
        {"ok": True, "version": "0.4.2", "uptime_s": 8420, "last_seen_s": 3},
    )
    assert env == {
        "kind": "wabot_status",
        "data": {
            "status": "ok",
            "version": "0.4.2",
            "uptime_s": 8420,
            "last_seen_s": 3,
        },
        "actions": [
            {"id": "recheck", "label": "Recheck", "tool": "wabot_health", "args": {}}
        ],
    }


def test_wabot_health_degraded() -> None:
    env = build_ui_envelope("wabot_health", {"ok": False, "error": "connect refused"})
    assert env is not None
    assert env["kind"] == "wabot_status"
    assert env["data"]["status"] == "bad"
    assert env["data"]["error"] == "connect refused"


def test_send_text_dry_run_emits_send_confirm() -> None:
    env = build_ui_envelope(
        "send_whatsapp_text",
        {
            "policy": "dry_run",
            "to": "+15551234567",
            "body": "hello",
            "delivered": False,
        },
    )
    assert env is not None
    assert env["kind"] == "send_confirm"
    assert env["data"]["policy"] == "dry_run"
    assert env["data"]["recipient_masked"].endswith("4567")
    assert env["data"]["recipient_masked"].startswith("+1")
    assert "***" in env["data"]["recipient_masked"]
    assert env["data"]["body_preview"] == "hello"
    assert env["data"]["needs_approval"] is False
    assert env["actions"] == []


def test_send_text_allowlist_needs_approval() -> None:
    env = build_ui_envelope(
        "send_whatsapp_text",
        {"policy": "allowlist", "to": "+15551234567", "body": "x" * 200},
    )
    assert env is not None
    assert env["data"]["needs_approval"] is True
    assert len(env["data"]["body_preview"]) <= 141
    assert env["data"]["body_preview"].endswith("…")
    assert [a["id"] for a in env["actions"]] == ["approve", "cancel"]


def test_send_image_includes_image_metadata() -> None:
    env = build_ui_envelope(
        "send_whatsapp_image",
        {
            "policy": "allowlist",
            "to": "+15551234567",
            "path": "/media/hello.png",
            "caption": "look",
        },
    )
    assert env is not None
    assert env["data"]["image_path"] == "/media/hello.png"
    assert env["data"]["caption_preview"] == "look"


def test_recall_contact_memory_emits_memory_card() -> None:
    env = build_ui_envelope(
        "recall_contact_memory",
        {
            "contact": "+15551234567",
            "facts": [
                {"id": "f1", "text": "prefers async"},
                {"id": "f2", "text": "PT timezone"},
            ],
        },
    )
    assert env is not None
    assert env["kind"] == "memory"
    assert env["data"]["contact_masked"].endswith("4567")
    assert len(env["data"]["facts"]) == 2
    assert env["data"]["facts"][0]["text"] == "prefers async"


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


def test_mask_recipient_handles_short_input() -> None:
    env = build_ui_envelope(
        "send_whatsapp_text",
        {"policy": "dry_run", "to": "123", "body": "x"},
    )
    assert env is not None
    assert env["data"]["recipient_masked"] == "***"


def test_builder_swallows_exceptions() -> None:
    env = build_ui_envelope("recall_contact_memory", {"contact": None, "facts": "not-a-list"})
    assert env is not None
    assert env["data"]["contact_masked"] == "***"
    assert env["data"]["facts"] == []
