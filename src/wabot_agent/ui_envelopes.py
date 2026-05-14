"""Build polished UI envelopes for tool results.

The agent's tool_output stream events carry an optional `ui` field. The
frontend reads that field and renders the matching ToolCard variant. This
module owns the mapping from (tool_name, raw_result) to the envelope shape.

Server-side construction (rather than letting the model emit UI specs) keeps
the surface area small and predictable: the model picks tools, the harness
picks the card.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

_BODY_PREVIEW_MAX = 140


def _mask_recipient(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "***"
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return "***"
    tail = digits[-4:]
    prefix = "+" + digits[0] if value.startswith("+") else ""
    return f"{prefix}***{tail}"


def _truncate(body: Any, limit: int = _BODY_PREVIEW_MAX) -> str:
    if not isinstance(body, str) or not body:
        return ""
    return body if len(body) <= limit else body[:limit] + "…"


def _wabot_status(result: dict[str, Any]) -> dict[str, Any]:
    ok = bool(result.get("ok"))
    data: dict[str, Any] = {"status": "ok" if ok else "bad"}
    for key in ("version", "uptime_s", "last_seen_s", "error"):
        if key in result:
            data[key] = result[key]
    return {
        "kind": "wabot_status",
        "data": data,
        "actions": [
            {"id": "recheck", "label": "Recheck", "tool": "wabot_health", "args": {}}
        ],
    }


def _send_confirm(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    policy = result.get("policy", "dry_run")
    delivered = bool(result.get("delivered", False))
    needs_approval = policy != "dry_run" and not delivered
    data: dict[str, Any] = {
        "policy": policy,
        "recipient_masked": _mask_recipient(result.get("to")),
        "body_preview": _truncate(result.get("body")),
        "needs_approval": needs_approval,
        "delivered": delivered,
    }
    if tool_name == "send_whatsapp_image":
        data["image_path"] = result.get("path")
        data["caption_preview"] = _truncate(result.get("caption"))
    if needs_approval:
        actions = [
            {"id": "approve", "label": "Approve", "tool": tool_name, "args": {}},
            {"id": "cancel", "label": "Cancel", "tool": None, "args": {}},
        ]
    else:
        actions = []
    return {"kind": "send_confirm", "data": data, "actions": actions}


def _memory(result: dict[str, Any]) -> dict[str, Any]:
    raw_facts = result.get("facts")
    facts_iter: list[Any] = raw_facts if isinstance(raw_facts, list) else []
    safe_facts = [
        {"id": str(f.get("id", "")), "text": str(f.get("text", ""))}
        for f in facts_iter
        if isinstance(f, dict)
    ]
    return {
        "kind": "memory",
        "data": {
            "contact_masked": _mask_recipient(result.get("contact")),
            "facts": safe_facts,
        },
        "actions": [],
    }


def _pairing_qr(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "pairing_qr",
        "data": {
            "available": bool(result.get("available", True)),
            "linked_device": result.get("linked_device"),
        },
        "actions": [
            {"id": "refresh", "label": "Refresh", "tool": "__pairing_qr", "args": {}}
        ],
    }


_Builder = Callable[[dict[str, Any]], dict[str, Any]]
_BUILDERS: dict[str, _Builder] = {
    "wabot_health": _wabot_status,
    "send_whatsapp_text": lambda r: _send_confirm("send_whatsapp_text", r),
    "send_whatsapp_image": lambda r: _send_confirm("send_whatsapp_image", r),
    "recall_contact_memory": _memory,
    "remember_contact_fact": _memory,
    "__pairing_qr": _pairing_qr,
}


def build_ui_envelope(tool_name: str, result: Any) -> dict[str, Any] | None:
    """Return an envelope dict, or None if no card applies.

    Non-dict results return None so the frontend falls back to plain JSON.
    Builder exceptions are swallowed — an envelope failure must never crash
    the run.
    """
    if not isinstance(result, dict):
        return None
    builder = _BUILDERS.get(tool_name)
    if builder is None:
        return None
    try:
        return builder(result)
    except Exception:  # noqa: BLE001
        return None
