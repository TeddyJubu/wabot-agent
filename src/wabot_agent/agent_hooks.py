"""OpenAI Agents SDK ``RunHooks`` subclass that emits structured log records.

Attached at ``Runner.run(..., hooks=RunObservabilityHooks())`` and the
streaming equivalent. The SDK calls into us at every lifecycle boundary —
agent start/end, tool start/end, LLM start/end, handoffs — and we turn each
into a redacted, correlated log record on the ``wabot_agent.agent_hooks``
logger.

Tool argument redaction is critical because the LLM can pass user input as a
tool argument (e.g. ``send_whatsapp_text(text="...sensitive...")``). The
formatter also re-runs every ``extra`` dict through :func:`redact`, but
redacting here means the local dev (text-format) view is already scrubbed.

The Agents SDK ``RunHooksBase`` signature in this repo's pinned version is::

    on_tool_start(context, agent, tool) -> None
    on_tool_end(context, agent, tool, result) -> None
    on_llm_start(context, agent, system_prompt, input_items) -> None
    on_llm_end(context, agent, response) -> None
    on_agent_start(context, agent) -> None
    on_agent_end(context, agent, output) -> None
    on_handoff(context, from_agent, to_agent) -> None

``context`` for tool callbacks is a ``ToolContext`` exposing ``tool_name``,
``tool_call_id``, and ``tool_arguments``. We treat every attribute access as
best-effort (``getattr(..., default)``) to survive SDK version drift — past
0.17.x releases have rearranged these field names.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

try:
    from agents import RunHooks  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover — SDK should always be present in this repo
    RunHooks = object  # fallback so tests can subclass without the SDK installed

from .redaction import redact

logger = logging.getLogger("wabot_agent.agent_hooks")


class RunObservabilityHooks(RunHooks):  # type: ignore[misc, valid-type]
    """Emit structured log records at every Agents-SDK lifecycle boundary."""

    def __init__(self) -> None:
        # Per-call_id start times so on_tool_end can emit a real latency.
        self._tool_starts: dict[str, float] = {}
        self._llm_starts: dict[int, float] = {}

    # --- Tool boundary ----------------------------------------------------

    async def on_tool_start(self, context, agent, tool):  # noqa: ANN001
        tool_name = (
            getattr(context, "tool_name", None)
            or getattr(tool, "name", None)
            or "<unknown>"
        )
        call_id = getattr(context, "tool_call_id", None)
        args = _safe_args(context)
        if call_id:
            self._tool_starts[str(call_id)] = time.perf_counter()
        logger.info(
            "tool_call",
            extra={
                "tool_name": tool_name,
                "call_id": str(call_id) if call_id else None,
                "args_redacted": redact(args) if args is not None else None,
            },
        )

    async def on_tool_end(self, context, agent, tool, result):  # noqa: ANN001
        tool_name = (
            getattr(context, "tool_name", None)
            or getattr(tool, "name", None)
            or "<unknown>"
        )
        call_id = getattr(context, "tool_call_id", None)
        latency_ms: int | None = None
        if call_id and str(call_id) in self._tool_starts:
            latency_ms = int(
                (time.perf_counter() - self._tool_starts.pop(str(call_id))) * 1000
            )
        logger.info(
            "tool_result",
            extra={
                "tool_name": tool_name,
                "call_id": str(call_id) if call_id else None,
                "ok": _looks_ok(result),
                "result_kind": _kind(result),
                "latency_ms": latency_ms,
            },
        )

    # --- LLM boundary -----------------------------------------------------

    async def on_llm_start(self, context, agent, system_prompt, input_items):  # noqa: ANN001
        self._llm_starts[id(context)] = time.perf_counter()
        logger.debug(
            "llm_start",
            extra={"model": _stringify_model(getattr(agent, "model", None))},
        )

    async def on_llm_end(self, context, agent, response):  # noqa: ANN001
        start = self._llm_starts.pop(id(context), None)
        latency_ms = int((time.perf_counter() - start) * 1000) if start is not None else None
        usage = _safe_usage(response)
        extra: dict[str, Any] = {
            "model": _stringify_model(getattr(agent, "model", None)),
            "latency_ms": latency_ms,
        }
        if usage is not None:
            extra["usage"] = usage
        logger.debug("llm_end", extra=extra)

    # --- Agent boundary ---------------------------------------------------

    async def on_agent_start(self, context, agent):  # noqa: ANN001
        logger.debug(
            "agent_start",
            extra={"agent_name": getattr(agent, "name", None)},
        )

    async def on_agent_end(self, context, agent, output):  # noqa: ANN001
        logger.debug(
            "agent_end",
            extra={"agent_name": getattr(agent, "name", None)},
        )

    # --- Handoffs ---------------------------------------------------------

    async def on_handoff(self, context, from_agent, to_agent):  # noqa: ANN001
        logger.info(
            "agent_handoff",
            extra={
                "from": getattr(from_agent, "name", None),
                "to": getattr(to_agent, "name", None),
            },
        )


# --- helpers ---------------------------------------------------------------


def _safe_args(context: Any) -> Any:
    """Best-effort extraction of tool arguments from a ``ToolContext``.

    The Agents SDK passes ``tool_arguments`` as a raw JSON string. We try to
    parse it; on failure we wrap in ``{"_raw": ...}`` so callers can still see
    the literal string after redaction. Returns ``None`` only when no arguments
    attribute is present at all.
    """
    args = getattr(context, "tool_arguments", None)
    if args is None:
        return None
    if isinstance(args, str):
        if not args:
            return {}
        try:
            return json.loads(args)
        except (ValueError, TypeError):
            return {"_raw": args}
    return args


def _looks_ok(result: Any) -> bool:
    """A tool result is ``ok`` unless it carries an explicit failure signal.

    ``sent: False`` from ``send_whatsapp_text`` is NOT a tool error — it's a
    successful policy-block. The ``send_blocked`` log record captures that
    separately. We only mark the result not-ok when we see an explicit error
    field or a status string that names failure.
    """
    if isinstance(result, dict):
        if result.get("error") or result.get("is_error"):
            return False
        status = result.get("status")
        if isinstance(status, str) and status.lower() in {"error", "failed", "failure"}:
            return False
    return True


def _kind(result: Any) -> str:
    if isinstance(result, dict):
        return "dict"
    if isinstance(result, list):
        return "list"
    if isinstance(result, str):
        return "str"
    return "scalar"


def _stringify_model(model: Any) -> str | None:
    """The SDK can expose ``Agent.model`` as either a string or a Model object.

    We stringify either form so the log field is always a serializable scalar.
    """
    if model is None:
        return None
    if isinstance(model, str):
        return model
    # Common attribute on Model objects in this SDK.
    name = getattr(model, "model", None)
    if isinstance(name, str):
        return name
    return str(model)


def _safe_usage(response: Any) -> dict[str, Any] | None:
    """Pull a usage dict off a ``ModelResponse`` if the SDK exposes one.

    Field names have varied across SDK 0.17.x — try the two common ones and
    fall back to ``None`` when neither is dict-able.
    """
    for attr in ("usage", "token_usage"):
        candidate = getattr(response, attr, None)
        if candidate is None:
            continue
        if isinstance(candidate, dict):
            return candidate
        try:
            return dict(candidate)
        except (TypeError, ValueError):
            continue
    return None
