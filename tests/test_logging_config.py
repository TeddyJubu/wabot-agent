from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from wabot_agent.logging_config import (
    ContextVarsFilter,
    JsonFormatter,
    TextFormatter,
    configure_logging,
    request_id_var,
    run_id_context,
    run_id_var,
)


def _make_stream_logger(level: int = logging.INFO) -> tuple[logging.Logger, StringIO]:
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextVarsFilter())
    logger = logging.getLogger(f"test_{id(buf)}")
    logger.handlers.clear()
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    return logger, buf


def test_json_formatter_emits_required_fields():
    logger, buf = _make_stream_logger()
    logger.info("hello_world", extra={"foo": "bar"})
    record = json.loads(buf.getvalue().strip())
    assert record["event"] == "hello_world"
    assert record["level"] == "info"
    assert record["logger"].startswith("test_")
    assert record["foo"] == "bar"
    assert "ts" in record
    assert record["request_id"] is None
    assert record["run_id"] is None


def test_json_formatter_missing_optional_extras():
    """When no extras are passed, the payload still has the required fields."""
    logger, buf = _make_stream_logger()
    logger.info("bare")
    record = json.loads(buf.getvalue().strip())
    assert record["event"] == "bare"
    assert set(record.keys()) >= {"ts", "level", "logger", "event", "request_id", "run_id"}


def test_contextvars_filter_stamps_request_id():
    logger, buf = _make_stream_logger()
    token = request_id_var.set("abc12345")
    try:
        logger.info("inside_request")
    finally:
        request_id_var.reset(token)
    record = json.loads(buf.getvalue().strip())
    assert record["request_id"] == "abc12345"
    assert record["run_id"] is None


def test_run_id_context_sets_and_resets():
    logger, buf = _make_stream_logger()
    logger.info("before_run")
    with run_id_context("run-xyz"):
        logger.info("inside_run")
    logger.info("after_run")
    lines = [json.loads(line) for line in buf.getvalue().strip().splitlines()]
    assert lines[0]["run_id"] is None
    assert lines[1]["run_id"] == "run-xyz"
    assert lines[2]["run_id"] is None
    assert run_id_var.get() is None


def test_run_id_context_restores_on_exception():
    """The contextmanager resets even when the wrapped body raises."""
    with pytest.raises(RuntimeError):
        with run_id_context("run-err"):
            assert run_id_var.get() == "run-err"
            raise RuntimeError("boom")
    assert run_id_var.get() is None


def test_json_formatter_redacts_extras():
    logger, buf = _make_stream_logger()
    logger.info("send", extra={"to": "+491701234567", "email": "operator@example.com"})
    record = json.loads(buf.getvalue().strip())
    assert "491701234567" not in record["to"]
    assert record["email"] == "o***r@example.com"


def test_json_formatter_redacts_secret_keys():
    logger, buf = _make_stream_logger()
    logger.info("auth", extra={"api_key": "sk-or-real-key-here", "ok": True})
    record = json.loads(buf.getvalue().strip())
    assert record["api_key"] == "[REDACTED]"
    assert record["ok"] is True


def test_json_formatter_includes_exc_info():
    logger, buf = _make_stream_logger()
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("oops")
    record = json.loads(buf.getvalue().strip())
    assert record["event"] == "oops"
    assert "exc_info" in record
    assert "ValueError" in record["exc_info"]
    assert "boom" in record["exc_info"]


def test_text_formatter_smoke():
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(TextFormatter())
    handler.addFilter(ContextVarsFilter())
    logger = logging.getLogger("test_text")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("hello", extra={"key": "value"})
    line = buf.getvalue().strip()
    assert "hello" in line
    # `key` is a SECRET_KEYS marker — should be redacted even in text mode.
    assert "key=[REDACTED]" in line


def test_text_formatter_preserves_non_secret_extras():
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(TextFormatter())
    handler.addFilter(ContextVarsFilter())
    logger = logging.getLogger("test_text_2")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("request", extra={"route": "/health", "status": 200})
    line = buf.getvalue().strip()
    assert "route=/health" in line
    assert "status=200" in line


def test_configure_logging_is_idempotent(capsys):
    """Calling configure_logging twice should not duplicate handlers."""
    configure_logging(level="INFO", fmt="json")
    configure_logging(level="INFO", fmt="json")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    # Reset for other tests.
    for h in list(root.handlers):
        root.removeHandler(h)
