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
    """Build a wabot_status card from a `wabot_health` tool result.

    `wabot_health` returns `{reachable, logged_in, connected, ready, detail}`.
    Tri-state mapping:
      - ready (all three flags healthy) → ok
      - reachable but not ready          → warn (daemon up, WhatsApp not linked)
      - not reachable                    → bad  (daemon down)
    `detail` surfaces the failure reason whenever status != ok.
    """
    ready = bool(result.get("ready"))
    reachable = bool(result.get("reachable"))
    if ready:
        status = "ok"
    elif reachable:
        status = "warn"
    else:
        status = "bad"
    data: dict[str, Any] = {"status": status}
    detail = result.get("detail")
    if status != "ok" and isinstance(detail, str) and detail:
        data["error"] = detail
    return {
        "kind": "wabot_status",
        "data": data,
        "actions": [
            {"id": "recheck", "label": "Recheck", "tool": "wabot_health", "args": {}}
        ],
    }


_POLICY_NAMES = {"dry_run", "allowlist", "allow_all"}


def _send_confirm(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Build a send_confirm card from a `send_whatsapp_*` tool result.

    By the time a tool_result event fires, the send already either succeeded
    (`sent=True`) or was blocked (`sent=False`) — nothing to approve. The
    pre-send approval prompt is emitted by the model's text channel per the
    system prompt; this builder only reflects the *outcome*.

    Policy resolution is best-effort because the tool only echoes back
    `policy` on the success path. On the blocked path it echoes `reason`,
    which is sometimes a policy name (dry_run/allow_all/allowlist) and
    sometimes a different sentinel like `recipient_not_allowlisted`.
    """
    sent = bool(result.get("sent"))
    raw_policy = result.get("policy")
    if not isinstance(raw_policy, str) or raw_policy not in _POLICY_NAMES:
        reason = result.get("reason")
        raw_policy = reason if isinstance(reason, str) and reason in _POLICY_NAMES else "dry_run"
    data: dict[str, Any] = {
        "policy": raw_policy,
        "recipient_masked": _mask_recipient(result.get("to")),
        # Tools don't currently echo the message body; prefer an explicit
        # `body_preview` if a future tool version adds one.
        "body_preview": _truncate(result.get("body_preview") or result.get("body")),
        "needs_approval": False,
        "delivered": sent,
    }
    if tool_name == "send_whatsapp_image":
        data["image_path"] = result.get("path")
        data["caption_preview"] = _truncate(
            result.get("caption_preview") or result.get("caption")
        )
    return {"kind": "send_confirm", "data": data, "actions": []}


def _memory(result: dict[str, Any]) -> dict[str, Any]:
    """Build a memory card from a `recall_contact_memory` tool result.

    Stored facts are `{key, value, source, updated_at}` per the SQLite
    schema. The frontend `MemoryCard` consumes `{id, text}` per fact, so
    derive `id=key` (unique per contact, stable across re-fetches) and
    `text="key: value"` for a human-readable rendering.
    """
    raw_facts = result.get("facts")
    facts_iter: list[Any] = raw_facts if isinstance(raw_facts, list) else []
    safe_facts: list[dict[str, str]] = []
    for f in facts_iter:
        if not isinstance(f, dict):
            continue
        key = str(f.get("key", "") or "")
        value = str(f.get("value", "") or "")
        if not key and not value:
            continue
        text = f"{key}: {value}" if key and value else (key or value)
        safe_facts.append({"id": key or text, "text": text})
    return {
        "kind": "memory",
        "data": {
            "contact_masked": _mask_recipient(result.get("contact")),
            "facts": safe_facts,
        },
        "actions": [],
    }


def _inbox_message(result: dict[str, Any]) -> dict[str, Any]:
    """Compact card for inbox read tools — never dump raw JSON in chat."""
    messages: list[dict[str, Any]] = []
    if isinstance(result.get("message"), dict):
        messages = [result["message"]]
    elif isinstance(result.get("messages"), list):
        messages = [m for m in result["messages"] if isinstance(m, dict)]
    preview: list[dict[str, str]] = []
    for msg in messages[-5:]:
        sender = str(msg.get("push_name") or msg.get("from") or msg.get("sender") or "unknown")
        text = _truncate(msg.get("text") or "", 120)
        preview.append({"sender": sender, "text": text or "(no text)"})
    return {
        "kind": "inbox_message",
        "data": {
            "count": len(messages) if messages else int(result.get("count") or 0),
            "found": bool(result.get("found", messages)),
            "messages": preview,
            "source": result.get("source"),
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
    "send_whatsapp_document": lambda r: _send_confirm("send_whatsapp_document", r),
    "send_whatsapp_audio": lambda r: _send_confirm("send_whatsapp_audio", r),
    "send_whatsapp_video": lambda r: _send_confirm("send_whatsapp_video", r),
    "recall_contact_memory": _memory,
    "remember_contact_fact": _memory,
    "get_last_whatsapp_inbound_message": _inbox_message,
    "list_whatsapp_inbound_messages": _inbox_message,
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
