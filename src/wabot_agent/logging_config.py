"""Stdlib logging configuration for wabot_agent.

One JSON object per log line goes to stdout — journalctl on the VPS and ``jq``
locally both grok this without any glue. ``ContextVar``s named
``request_id_var`` and ``run_id_var`` carry correlation IDs across ``await``
boundaries; a :class:`ContextVarsFilter` stamps them onto every ``LogRecord``.

Call sites use stdlib logging normally:

    logger = logging.getLogger("wabot_agent.middleware")
    logger.info(
        "request",
        extra={"route": "/health", "status": 200, "latency_ms": 3},
    )

Every ``extra`` dict is passed through :func:`wabot_agent.redaction.redact`
before serialization so callers cannot accidentally leak a secret by putting it
into a field they forgot to scrub. Caller-side hygiene still matters: the
formatter cannot redact the message string itself (use snake_case slugs, never
sentences with embedded values).

Restart-required. ``log_level`` and ``log_format`` are NOT in ``MUTABLE_FIELDS``
— editing them via ``/api/settings`` would only confuse the on-disk
``runtime_overrides.json`` file without changing the live formatter.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from .redaction import redact

# --- ContextVars -----------------------------------------------------------

# Correlation IDs flow across ``await`` boundaries via ``contextvars``. The
# middleware sets ``request_id_var`` on every HTTP request; ``run_agent`` /
# ``run_agent_streamed`` set ``run_id_var`` for the duration of an agent run.
request_id_var: ContextVar[str | None] = ContextVar("wabot_agent_request_id", default=None)
run_id_var: ContextVar[str | None] = ContextVar("wabot_agent_run_id", default=None)


@contextmanager
def run_id_context(run_id: str):
    """Bind ``run_id_var`` for the duration of an agent run.

    Restores the prior value on exit even when the wrapped body raises. The
    ``ContextVar`` mechanism is async-safe; ``asyncio.create_task`` calls made
    inside the ``with`` block inherit the value automatically (each task runs
    in a copied context).
    """
    token = run_id_var.set(run_id)
    try:
        yield
    finally:
        run_id_var.reset(token)


# --- Filter ----------------------------------------------------------------

# Attribute names we inject onto every ``LogRecord``. Kept in sync with
# ``_STANDARD_LR_ATTRS`` below: anything that's neither a standard attr nor an
# injected field is treated as caller-supplied ``extra`` and serialized.
_INJECTED_FIELDS = ("request_id", "run_id")


class ContextVarsFilter(logging.Filter):
    """Stamp ``request_id`` and ``run_id`` onto every ``LogRecord``.

    Filters never reject records here — they only enrich. An explicit kwarg
    passed by the caller (via ``extra={"request_id": ...}``) wins, so test
    fixtures can pre-stamp records without the contextvar leaking in.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        if not hasattr(record, "run_id"):
            record.run_id = run_id_var.get()
        return True


# --- Formatters ------------------------------------------------------------

# Standard ``LogRecord`` attributes; anything else on the record was supplied
# via ``extra={...}`` (or by ``ContextVarsFilter``) and should be serialized
# into the JSON payload.
_STANDARD_LR_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)


def _record_extras(record: logging.LogRecord) -> dict[str, Any]:
    """Pull caller-supplied ``extra`` fields off a ``LogRecord``.

    Excludes both standard ``LogRecord`` attributes and the fields we inject
    (``request_id``, ``run_id``) — those land in top-level keys via the
    formatter rather than getting flattened into the extras dict.
    """
    extras: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _STANDARD_LR_ATTRS or key in _INJECTED_FIELDS:
            continue
        extras[key] = value
    return extras


class JsonFormatter(logging.Formatter):
    """One JSON object per record on a single line.

    ASCII-safe (``ensure_ascii=True``) so journalctl pipelines that aren't
    UTF-8-clean still parse. ``extra`` dicts run through ``redact()`` before
    serialization as defence in depth.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "run_id": getattr(record, "run_id", None),
        }
        extras = _record_extras(record)
        if extras:
            redacted = redact(extras)
            if isinstance(redacted, dict):
                payload.update(redacted)
        if record.exc_info:
            payload["exc_info"] = "".join(
                traceback.format_exception(*record.exc_info)
            ).rstrip()
        return json.dumps(payload, ensure_ascii=True, sort_keys=False, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable single-line format for local dev.

    Activated by ``WABOT_AGENT_LOG_FORMAT=text``. Not for production — the JSON
    formatter is journalctl-friendly and structured.
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        rid = getattr(record, "request_id", None) or "-"
        run = getattr(record, "run_id", None) or "-"
        head = (
            f"{ts} {record.levelname:<7} {record.name} "
            f"rid={rid} run={run} {record.getMessage()}"
        )
        extras = _record_extras(record)
        if extras:
            redacted = redact(extras)
            if isinstance(redacted, dict):
                head += " " + " ".join(f"{k}={v}" for k, v in redacted.items())
        if record.exc_info:
            head += "\n" + "".join(
                traceback.format_exception(*record.exc_info)
            ).rstrip()
        return head


# --- Public entry point ----------------------------------------------------


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Wire stdout JSON (or text) logging with the contextvars filter.

    Idempotent: safe to call from ``create_app`` at every boot — the root
    logger's handlers are replaced rather than appended to. Uvicorn's
    ``uvicorn.access`` logger is silenced because :class:`RequestIdMiddleware`
    emits the canonical access record with correlation IDs; the default
    uvicorn access log would duplicate that record without the IDs.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextVarsFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())

    root.addHandler(handler)
    root.setLevel(level)

    # Silence uvicorn's own access log — the middleware emits the canonical
    # access record with `request_id` and `latency_ms`. Leaving uvicorn's
    # access log on would generate a noisy duplicate per request.
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.setLevel(logging.WARNING)

    # uvicorn.error carries startup/shutdown diagnostics — we want those, just
    # routed through the same root handler so they pick up the JSON formatter.
    uerr = logging.getLogger("uvicorn.error")
    uerr.handlers = []
    uerr.propagate = True
