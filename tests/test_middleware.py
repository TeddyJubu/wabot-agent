from __future__ import annotations

import json
import logging
import re
from io import StringIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wabot_agent.logging_config import (
    ContextVarsFilter,
    JsonFormatter,
    request_id_var,
)
from wabot_agent.middleware import RequestIdMiddleware


@pytest.fixture()
def app_with_middleware() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True, "rid": request_id_var.get()}

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/ready")
    async def ready():
        return {"ok": True}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    return app


@pytest.fixture()
def capture_logs():
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextVarsFilter())
    logger = logging.getLogger("wabot_agent.middleware")
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


def _all_json_lines(buf: StringIO) -> list[dict]:
    return [json.loads(line) for line in buf.getvalue().strip().splitlines() if line]


def _last_json_line(buf: StringIO) -> dict:
    return _all_json_lines(buf)[-1]


def test_request_id_minted_when_absent(app_with_middleware, capture_logs):
    client = TestClient(app_with_middleware)
    resp = client.get("/ping")
    assert resp.status_code == 200
    rid = resp.headers["x-request-id"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{12,64}", rid)
    body = resp.json()
    assert body["rid"] == rid
    log = _last_json_line(capture_logs)
    assert log["event"] == "request"
    assert log["request_id"] == rid
    assert log["status"] == 200
    assert log["route"] == "/ping"
    assert log["method"] == "GET"
    assert log["request_id_source"] == "minted"
    assert isinstance(log["latency_ms"], int)
    assert log["level"] == "info"


def test_request_id_honored_when_valid(app_with_middleware, capture_logs):
    client = TestClient(app_with_middleware)
    resp = client.get("/ping", headers={"X-Request-ID": "abc-DEF_123XYZ"})
    assert resp.headers["x-request-id"] == "abc-DEF_123XYZ"
    log = _last_json_line(capture_logs)
    assert log["request_id"] == "abc-DEF_123XYZ"
    assert log["request_id_source"] == "header"


def test_request_id_rejected_when_too_short(app_with_middleware, capture_logs):
    """Bad inbound IDs are dropped — we mint a fresh one rather than letting an
    attacker pollute correlation."""
    client = TestClient(app_with_middleware)
    resp = client.get("/ping", headers={"X-Request-ID": "tooshort"})
    assert resp.headers["x-request-id"] != "tooshort"
    log = _last_json_line(capture_logs)
    assert log["request_id_source"] == "minted"


def test_request_id_rejected_when_illegal_chars(app_with_middleware, capture_logs):
    client = TestClient(app_with_middleware)
    resp = client.get("/ping", headers={"X-Request-ID": "bad rid<script>"})
    assert "<" not in resp.headers["x-request-id"]
    log = _last_json_line(capture_logs)
    assert log["request_id_source"] == "minted"


def test_5xx_still_emits_log(app_with_middleware, capture_logs):
    client = TestClient(app_with_middleware, raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    log = _last_json_line(capture_logs)
    assert log["status"] == 500
    assert log["route"] == "/boom"
    # `logger.exception()` is ERROR-level — uncaught middleware paths emit at
    # ERROR with the stack trace, so jq filters on level=error catch them.
    assert log["level"] == "error"
    assert "exc_info" in log
    # Note: response header may be missing because Starlette's default 500
    # handler runs above this middleware. The log record is the source of
    # truth on the error path.


def test_health_logged_at_debug(app_with_middleware, capture_logs):
    """/health is hit every minute by uptime checks — log at DEBUG to keep
    INFO journalctl streams quiet."""
    client = TestClient(app_with_middleware)
    resp = client.get("/health")
    assert resp.status_code == 200
    log = _last_json_line(capture_logs)
    assert log["route"] == "/health"
    assert log["level"] == "debug"


def test_ready_logged_at_debug(app_with_middleware, capture_logs):
    client = TestClient(app_with_middleware)
    resp = client.get("/ready")
    assert resp.status_code == 200
    log = _last_json_line(capture_logs)
    assert log["route"] == "/ready"
    assert log["level"] == "debug"


def test_request_id_var_resets_after_request(app_with_middleware, capture_logs):
    """The contextvar is reset on response — no leak into the next request."""
    client = TestClient(app_with_middleware)
    client.get("/ping")
    assert request_id_var.get() is None
