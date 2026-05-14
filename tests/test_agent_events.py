"""Tests for the SSE event normalization in agent.py.

These tests live alongside the streaming agent rather than the static
ui_envelopes module so they capture both the tool-name correlation
(call_id -> tool_name) and the envelope attachment behavior.
"""
from __future__ import annotations

from typing import Any

from wabot_agent.agent import _translate_stream_event


class _Item:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _Event:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def _call(tool_name: str, call_id: str, args: str = "{}") -> _Event:
    return _Event(
        type="run_item_stream_event",
        name="tool_called",
        item=_Item(
            tool_name=tool_name,
            raw_item={"arguments": args},
            call_id=call_id,
        ),
    )


def _output(call_id: str, output: Any) -> _Event:
    return _Event(
        type="run_item_stream_event",
        name="tool_output",
        item=_Item(call_id=call_id, output=output),
    )


def test_tool_output_attaches_ui_envelope_for_wabot_health() -> None:
    state: dict[str, str] = {}
    a = _translate_stream_event(_call("wabot_health", "c1"), state)
    b = _translate_stream_event(
        _output("c1", {"ok": True, "version": "0.4.2", "uptime_s": 10, "last_seen_s": 1}),
        state,
    )
    assert a[0]["type"] == "tool_call"
    assert a[0]["name"] == "wabot_health"
    assert b[0]["type"] == "tool_result"
    assert b[0]["name"] == "wabot_health"
    assert b[0]["ui"]["kind"] == "wabot_status"
    assert b[0]["ui"]["data"]["status"] == "ok"


def test_tool_output_with_no_known_kind_omits_ui_field() -> None:
    state: dict[str, str] = {}
    _translate_stream_event(_call("list_local_skills", "c2"), state)
    out = _translate_stream_event(_output("c2", {"skills": ["a", "b"]}), state)
    assert out[0]["type"] == "tool_result"
    assert "ui" not in out[0]
    # Redacted raw output is still passed through for fallback rendering.
    assert out[0]["result"] == {"skills": ["a", "b"]}


def test_tool_output_without_prior_call_still_emits_result() -> None:
    state: dict[str, str] = {}
    out = _translate_stream_event(_output("c3", {"ok": True}), state)
    # No prior tool_called for c3 — we don't crash, we just can't attach ui.
    assert out[0]["type"] == "tool_result"
    assert "ui" not in out[0]


def test_default_state_is_optional() -> None:
    # The function works without a state dict for callers that don't care.
    out = _translate_stream_event(_output("c4", {"ok": True}))
    assert out[0]["type"] == "tool_result"
    assert "ui" not in out[0]
