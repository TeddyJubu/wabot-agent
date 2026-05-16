from __future__ import annotations

import json
import logging
from io import StringIO
from types import SimpleNamespace

import pytest

from wabot_agent.agent_hooks import RunObservabilityHooks
from wabot_agent.logging_config import (
    ContextVarsFilter,
    JsonFormatter,
    run_id_context,
)


@pytest.fixture()
def capture_logs():
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextVarsFilter())
    logger = logging.getLogger("wabot_agent.agent_hooks")
    saved = list(logger.handlers)
    saved_level = logger.level
    saved_propagate = logger.propagate
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield buf
    logger.handlers.clear()
    for h in saved:
        logger.addHandler(h)
    logger.setLevel(saved_level)
    logger.propagate = saved_propagate


def _lines(buf: StringIO) -> list[dict]:
    return [json.loads(line) for line in buf.getvalue().strip().splitlines() if line]


def _tool_ctx(name: str, call_id: str, args: str | None = None) -> SimpleNamespace:
    """ToolContext-shaped duck type for the SDK's on_tool_start/end signature."""
    return SimpleNamespace(
        tool_name=name,
        tool_call_id=call_id,
        tool_arguments=args if args is not None else "{}",
    )


async def test_tool_start_logs_redacted_args(capture_logs):
    hooks = RunObservabilityHooks()
    ctx = _tool_ctx(
        "send_whatsapp_text",
        "call_123",
        '{"to":"+491701234567","text":"hi"}',
    )
    tool = SimpleNamespace(name="send_whatsapp_text")
    with run_id_context("run-1"):
        await hooks.on_tool_start(ctx, agent=SimpleNamespace(name="a"), tool=tool)
    records = _lines(capture_logs)
    assert records[0]["event"] == "tool_call"
    assert records[0]["tool_name"] == "send_whatsapp_text"
    assert records[0]["call_id"] == "call_123"
    assert records[0]["run_id"] == "run-1"
    # Phone number redacted in the args dict:
    assert "491701234567" not in json.dumps(records[0]["args_redacted"])


async def test_tool_end_logs_ok_and_latency(capture_logs):
    hooks = RunObservabilityHooks()
    ctx = _tool_ctx("wabot_health", "call_xyz", "{}")
    tool = SimpleNamespace(name="wabot_health")
    with run_id_context("run-2"):
        await hooks.on_tool_start(ctx, agent=SimpleNamespace(name="a"), tool=tool)
        await hooks.on_tool_end(
            ctx,
            agent=SimpleNamespace(name="a"),
            tool=tool,
            result={"ready": True},
        )
    end = _lines(capture_logs)[-1]
    assert end["event"] == "tool_result"
    assert end["tool_name"] == "wabot_health"
    assert end["call_id"] == "call_xyz"
    assert end["ok"] is True
    assert end["result_kind"] == "dict"
    assert isinstance(end["latency_ms"], int)


async def test_tool_end_marks_blocked_send_as_ok(capture_logs):
    """`sent: False` from send_whatsapp_text is a policy block, not a tool error.

    The tool_result `ok` field must stay True so the operator UI does not
    red-flag a healthy policy-block as a tool failure.
    """
    hooks = RunObservabilityHooks()
    ctx = _tool_ctx("send_whatsapp_text", "cid", "{}")
    tool = SimpleNamespace(name="send_whatsapp_text")
    await hooks.on_tool_start(ctx, agent=SimpleNamespace(name="a"), tool=tool)
    await hooks.on_tool_end(
        ctx,
        agent=SimpleNamespace(name="a"),
        tool=tool,
        result={"sent": False, "reason": "dry_run"},
    )
    end = _lines(capture_logs)[-1]
    assert end["ok"] is True


async def test_tool_end_marks_explicit_error_not_ok(capture_logs):
    hooks = RunObservabilityHooks()
    ctx = _tool_ctx("any_tool", "cid", "{}")
    tool = SimpleNamespace(name="any_tool")
    await hooks.on_tool_start(ctx, agent=SimpleNamespace(name="a"), tool=tool)
    await hooks.on_tool_end(
        ctx,
        agent=SimpleNamespace(name="a"),
        tool=tool,
        result={"error": "oh no"},
    )
    end = _lines(capture_logs)[-1]
    assert end["ok"] is False


async def test_llm_start_end_emits_records(capture_logs):
    hooks = RunObservabilityHooks()
    ctx = SimpleNamespace()
    agent = SimpleNamespace(name="a", model="openrouter/test")
    await hooks.on_llm_start(ctx, agent=agent, system_prompt=None, input_items=[])
    await hooks.on_llm_end(ctx, agent=agent, response=SimpleNamespace())
    records = _lines(capture_logs)
    events = [r["event"] for r in records]
    assert "llm_start" in events
    assert "llm_end" in events
    end_rec = next(r for r in records if r["event"] == "llm_end")
    assert end_rec["model"] == "openrouter/test"
    assert isinstance(end_rec["latency_ms"], int)


async def test_tool_args_redacted_handles_invalid_json(capture_logs):
    """A malformed JSON arguments string is wrapped, not lost."""
    hooks = RunObservabilityHooks()
    ctx = _tool_ctx("any_tool", "cid", "{not valid json")
    await hooks.on_tool_start(
        ctx, agent=SimpleNamespace(name="a"), tool=SimpleNamespace(name="any_tool")
    )
    record = _lines(capture_logs)[0]
    assert "_raw" in record["args_redacted"]
