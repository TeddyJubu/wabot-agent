from __future__ import annotations

from types import SimpleNamespace

from wabot_agent.codex_model import (
    _filter_codex_response_output,
    _is_nonreplayable_output_item,
)


def test_is_nonreplayable_reasoning_item() -> None:
    assert _is_nonreplayable_output_item(SimpleNamespace(type="reasoning", id="rs_abc"))
    assert not _is_nonreplayable_output_item(
        SimpleNamespace(type="message", id="msg_abc")
    )


def test_filter_codex_response_output_drops_reasoning() -> None:
    items = [
        SimpleNamespace(type="reasoning", id="rs_abc"),
        SimpleNamespace(type="message", id="msg_1"),
    ]
    filtered = _filter_codex_response_output(items)
    assert len(filtered) == 1
    assert filtered[0].type == "message"
