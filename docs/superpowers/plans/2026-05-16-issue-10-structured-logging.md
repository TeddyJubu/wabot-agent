# Structured JSON Logging With Request/Run Correlation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make end-to-end debugging of `wabot-agent` flows (HTTP → run → tools → outbound) practical by emitting redacted, correlated, JSON log records to stdout (journalctl) at every meaningful boundary, with `request_id` and `run_id` propagated through `contextvars` so every layer — middleware, agent runner, tools, wabot client, memory writes — stamps the same identifiers.

**Architecture:** Stdlib `logging` with a hand-rolled JSON formatter and a `contextvars` filter (no new dependency). One new ASGI middleware mints/honors `X-Request-ID`, sets the contextvar, and emits an access record on exit. The OpenAI Agents SDK already exposes a `RunHooks` interface — we attach a `RunObservabilityHooks` subclass at `Runner.run(..., hooks=...)` so tool-call / tool-result lifecycle records come from the SDK's stable hook surface rather than from instrumenting `tools.py` directly. The existing `events.EventLog` (JSONL + SSE fan-out) and `MemoryStore.record_run` / `record_tool_event` (SQLite, queried by `/api/runs`) are **untouched** — the new stdout JSON log is an additional sink for ops, not a replacement for the operator-UI feeds.

**Tech Stack:** Python 3.12 stdlib `logging`, `contextvars`, FastAPI middleware (pure ASGI), OpenAI Agents SDK `RunHooks`, existing `wabot_agent.redaction` module, pytest with `caplog` / a custom in-memory log capture.

**Spec:** No standalone spec doc — this plan is self-contained. The five design decisions made up-front are:

1. **Logging library: stdlib `logging` + custom JSON formatter.** Zero new deps; the project deliberately keeps its dependency surface small; journalctl handles JSON stdout natively; uvicorn's own logging is also stdlib so co-existence is trivial. (Operator may still prefer `structlog` for ergonomics — flagged as the one library decision worth sign-off.)
2. **Propagation: two `ContextVar`s set by middleware and by `run_agent*`.** A `logging.Filter` stamps both onto every record. No threading-locals; no per-call kwarg plumbing.
3. **DB-vs-stdout overlap: mirror, do not supersede.** `events.jsonl` + SQLite `runs` / `tool_events` remain authoritative for the dashboard. The new stdout JSON log is an additional sink that gains correlation IDs the DB records don't carry today.
4. **Inbound webhook: honor `X-Request-ID` if present, mint otherwise.** Same middleware logic as every other route; no special-case. The handler additionally logs `message_id` and `mask_phone`'d sender on the dedicated inbound boundary.
5. **Cloudflare Access email: hashed + truncated `sub` on every record, full email only on a single `auth_login` event.** Adds an `email` redaction rule to `redaction.py` (mask to `local***@domain`), introduces an `email_hash = sha256(sub)[:16]` field on auth events. (Worth operator sign-off — single-tenant deployments may genuinely want raw email.)

---

## File map

**New files:**

| Path | Purpose |
|---|---|
| `src/wabot_agent/logging_setup.py` | Stdlib logging configuration: JSON formatter, contextvars (`request_id_var`, `run_id_var`), `ContextVarsFilter`, `configure_logging()` entry point, `run_id_context()` helper. |
| `src/wabot_agent/middleware.py` | Pure-ASGI `RequestIdMiddleware` that mints/honors `X-Request-ID`, sets the contextvar, records latency, and emits the access log record on exit (including for long-lived SSE/NDJSON streams). |
| `src/wabot_agent/agent_hooks.py` | `RunObservabilityHooks(agents.RunHooks)` subclass that emits `tool_call` / `tool_result` / `agent_start` / `agent_end` / `llm_start` / `llm_end` log records, with redacted tool args. |
| `tests/test_logging_setup.py` | Unit tests for JSON formatter, contextvars filter, redaction integration. |
| `tests/test_middleware.py` | Tests for `X-Request-ID` honor/mint, response header echo, latency_ms field, access log emission. |
| `tests/test_agent_hooks.py` | Tests for `RunObservabilityHooks` against a fake SDK lifecycle. |
| `tests/test_auth_logging.py` | Tests that auth success/failure log records carry the right fields and that email is redacted by default. |

**Modified files:**

| Path | Change |
|---|---|
| `src/wabot_agent/config.py` | Add `log_level` (default `"INFO"`) and `log_format` (default `"json"`, also `"text"` for local dev). Both with `AliasChoices(WABOT_AGENT_*, VIGNESH_*)`. **Not added to `MUTABLE_FIELDS`** — restart-required, same pattern as `cf_access_*`. |
| `src/wabot_agent/redaction.py` | Add `EMAIL_RE` and an `email` key-match rule that masks values to `local***@domain`. Existing `SECRET_KEYS` tuple grows to include `"email"` with a special-cased mask. Preserve current `redact()` semantics for everything else. |
| `src/wabot_agent/api.py` | (a) Call `configure_logging(settings)` in `create_app`. (b) Register `RequestIdMiddleware`. (c) Disable uvicorn's access log in `main()` (the middleware is now canonical). (d) Add explicit `auth_login` / `auth_failed` log emission inside `verify_human_factory` callers — see auth.py change for placement. (e) `/whatsapp/inbound` logs an `inbound_message_received` record with `message_id`, `sender` (mask_phone'd), `is_group`. |
| `src/wabot_agent/auth.py` | After verifying CF Access or operator token, log `auth_login` once per request (source + `email_hash` for CF Access). On failure, log `auth_failed` with the reason. |
| `src/wabot_agent/agent.py` | (a) Wrap the body of `run_agent` and `run_agent_streamed` in `run_id_context(run_id)`. (b) Pass `hooks=RunObservabilityHooks()` to both `Runner.run(...)` and `Runner.run_streamed(...)`. (c) Replace `event_log.write("agent_run_start", ...)` and `event_log.write("agent_run_complete", ...)` with a logger.info call **in addition to** the existing event_log.write (keep both — EventLog feeds the dashboard SSE). |
| `src/wabot_agent/tools.py` | Add a `logger = logging.getLogger("wabot_agent.tools")` and a single `logger.info("send_blocked", extra={...})` inside `_is_send_allowed` failure paths — the policy decision deserves its own log record beyond the existing `event_log.write("send_blocked", ...)`. No other changes; tool args correlate via the contextvar. |
| `src/wabot_agent/wabot.py` | Add a logger and an `outbound_http` log record on each `send_text` / `send_image` call (latency_ms + status_code + redacted result). |
| `README.md` | New "Observability" section under "Verification" with field reference and "Trace a run" workflow. |
| `CLAUDE.md` | One-paragraph note pointing to README's Observability section so future Claude sessions know the convention. |
| `.env.example` | Two new vars: `WABOT_AGENT_LOG_LEVEL=INFO` and `WABOT_AGENT_LOG_FORMAT=json`. |

---

## Log event schema

Every record is a single JSON object on one line. Fields below are the union of all event types; many records carry only a subset. Field names are stable contract.

### Always present (stamped by `ContextVarsFilter` + formatter)

| Field | Type | Source | Notes |
|---|---|---|---|
| `ts` | string | formatter | ISO-8601 UTC with microseconds (`datetime.now(UTC).isoformat()`). |
| `level` | string | formatter | `DEBUG` / `INFO` / `WARNING` / `ERROR`. |
| `logger` | string | formatter | `record.name`, e.g. `wabot_agent.middleware`. |
| `event` | string | formatter | `record.message` — short snake_case slug (`request`, `tool_call`, etc.). Never a sentence. |
| `request_id` | string \| null | filter | Set by `RequestIdMiddleware`. Null on records emitted outside a request (e.g. `lifespan` startup). |
| `run_id` | string \| null | filter | Set by `run_id_context()`. Null outside an agent run. |
| `auth_sub_short` | string \| null | filter | First 8 chars of CF Access `sub` if set; null otherwise. |

### Event-specific

| `event` | Logger | Extra fields | Emitted by |
|---|---|---|---|
| `request` | `wabot_agent.middleware` | `route`, `method`, `status`, `latency_ms`, `phase` (`start` / `end` for long streams, omitted for unary), `client_ip` (loopback flag only — never the real IP), `request_id_source` (`header` / `minted`). | RequestIdMiddleware |
| `auth_login` | `wabot_agent.auth` | `source` (`cf-access` / `operator-cookie` / `operator-header` / `operator-query` / `open`), `email_hash` (CF only), `tenant_id`. | auth.py after success |
| `auth_failed` | `wabot_agent.auth` | `source_attempted`, `reason`. | auth.py on HTTPException |
| `inbound_message_received` | `wabot_agent.api` | `message_id`, `sender` (mask_phone), `is_group`, `duplicate` (bool). | `POST /whatsapp/inbound` handler |
| `agent_run_start` | `wabot_agent.agent` | `session_id`, `sender` (mask_phone, optional), `live_model` (bool), `model`. | `run_agent` / `run_agent_streamed` |
| `agent_run_end` | `wabot_agent.agent` | `session_id`, `latency_ms`, `live_model`, `final_output_len`, `turns`. | `run_agent` / `run_agent_streamed` |
| `agent_run_error` | `wabot_agent.agent` | `session_id`, `error_class`, `error_message` (redacted), `exc_info` (traceback string). | `run_agent_streamed` errored branch |
| `tool_call` | `wabot_agent.agent_hooks` | `tool_name`, `call_id`, `args_redacted` (dict). | `RunObservabilityHooks.on_tool_start` |
| `tool_result` | `wabot_agent.agent_hooks` | `tool_name`, `call_id`, `ok` (bool), `latency_ms`, `result_kind` (`dict` / `list` / `str` / `scalar`). | `RunObservabilityHooks.on_tool_end` |
| `llm_start` | `wabot_agent.agent_hooks` | `model`. | `RunObservabilityHooks.on_llm_start` |
| `llm_end` | `wabot_agent.agent_hooks` | `model`, `latency_ms`, `usage` (if SDK exposes it; else omitted). | `RunObservabilityHooks.on_llm_end` |
| `outbound_http` | `wabot_agent.wabot` | `endpoint_path` (e.g. `/send`), `status_code`, `latency_ms`, `ok` (bool). | `WabotClient.send_text` / `send_image` |
| `send_blocked` | `wabot_agent.tools` | `policy`, `reason`, `to` (mask_phone). | `_is_send_allowed` failure paths |
| `settings_updated` | `wabot_agent.api` | `fields` (sorted list of field names — never values). | `PATCH /api/settings` handler |

### Example records

```json
{"ts":"2026-05-16T14:22:03.412091+00:00","level":"INFO","logger":"wabot_agent.middleware","event":"request","request_id":"a1b2c3d4e5f6","run_id":null,"auth_sub_short":"cf9f2117","route":"/api/chat","method":"POST","status":200,"latency_ms":1842,"client_ip":"loopback","request_id_source":"minted"}
```

```json
{"ts":"2026-05-16T14:22:01.602417+00:00","level":"INFO","logger":"wabot_agent.agent_hooks","event":"tool_call","request_id":"a1b2c3d4e5f6","run_id":"5e7f9b22-3a44-4cd1-9d50-1f9e0fb33df1","auth_sub_short":"cf9f2117","tool_name":"send_whatsapp_text","call_id":"call_017Hf...","args_redacted":{"to":"49***91","text":"Hello"}}
```

```json
{"ts":"2026-05-16T14:22:01.118903+00:00","level":"WARNING","logger":"wabot_agent.auth","event":"auth_failed","request_id":"f00bd17c1234","run_id":null,"auth_sub_short":null,"source_attempted":"operator-header","reason":"token_mismatch"}
```

---

## Redaction integration points

1. **`redaction.py`** gains an email-mask rule and key-match. Every existing `redact()` call site automatically benefits — no caller changes needed for `event_log.write`, `record_tool_event`, `recall_*`, etc.
2. **JSON formatter** runs `redact()` on every `extra` dict before serializing. This catches free-form fields callers pass via `logger.info("...", extra={...})` without forcing each call site to remember.
3. **`tool_call.args_redacted`** is produced by the hooks using `redact()` on the raw arguments dict.
4. **`agent_run_error.error_message`** is produced via `redact(str(exc))` — mirrors what `run_agent_streamed` already does for the SSE payload.
5. **`outbound_http`** does NOT log request/response bodies; only path + status + latency. Bodies might contain user message text and recipient phone — out of scope for ops logs.

---

## Task 1: Add log_level and log_format settings, .env.example entries

**Files:**
- Modify: `src/wabot_agent/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add `log_level` and `log_format` fields to `Settings`**

In `config.py`, after the `cf_access_required` field (around line 120), add:

```python
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        validation_alias=AliasChoices("WABOT_AGENT_LOG_LEVEL", "VIGNESH_LOG_LEVEL"),
    )
    log_format: Literal["json", "text"] = Field(
        default="json",
        validation_alias=AliasChoices("WABOT_AGENT_LOG_FORMAT", "VIGNESH_LOG_FORMAT"),
    )
```

- [ ] **Step 2: Add example env entries**

In `.env.example`, append:

```
# Observability
# Log level: DEBUG | INFO | WARNING | ERROR (default INFO)
WABOT_AGENT_LOG_LEVEL=INFO
# Log format: json (journalctl-friendly) | text (human dev) (default json)
WABOT_AGENT_LOG_FORMAT=json
```

- [ ] **Step 3: Add a config test asserting defaults and aliases**

In `tests/test_config.py`, add:

```python
def test_log_level_defaults_to_info(monkeypatch):
    monkeypatch.delenv("WABOT_AGENT_LOG_LEVEL", raising=False)
    monkeypatch.delenv("VIGNESH_LOG_LEVEL", raising=False)
    s = Settings()
    assert s.log_level == "INFO"
    assert s.log_format == "json"


def test_log_level_legacy_alias(monkeypatch):
    monkeypatch.delenv("WABOT_AGENT_LOG_LEVEL", raising=False)
    monkeypatch.setenv("VIGNESH_LOG_LEVEL", "DEBUG")
    s = Settings()
    assert s.log_level == "DEBUG"
```

- [ ] **Step 4: Run the test**

Run: `uv run --with '.[dev]' python -m pytest tests/test_config.py -v -k log_level`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wabot_agent/config.py .env.example tests/test_config.py
git commit -m "feat(config): add log_level and log_format settings"
```

---

## Task 2: Extend redaction.py with email masking

**Files:**
- Modify: `src/wabot_agent/redaction.py`
- Modify: `tests/` (add a new test or extend existing — there is no test_redaction.py today; create one).

- [ ] **Step 1: Write failing tests**

Create `tests/test_redaction.py`:

```python
from __future__ import annotations

import pytest

from wabot_agent.redaction import mask_email, redact, redact_text


def test_mask_email_basic():
    assert mask_email("operator@example.com") == "o***r@example.com"


def test_mask_email_short_local_part():
    # Local parts <=2 chars get fully masked
    assert mask_email("a@x.io") == "***@x.io"


def test_mask_email_invalid_returns_input():
    assert mask_email("not-an-email") == "not-an-email"


def test_redact_dict_email_key():
    payload = {"email": "operator@example.com", "ok": True}
    out = redact(payload)
    assert out == {"email": "o***r@example.com", "ok": True}


def test_redact_text_finds_email_inline():
    s = "user operator@example.com just logged in"
    out = redact_text(s)
    assert "operator@example.com" not in out
    assert "o***r@example.com" in out


def test_redact_preserves_bearer_and_phone_behavior():
    # Regression guard for existing behavior — issue #10 must not regress redaction.
    assert "Bearer [REDACTED]" in redact_text("Authorization: Bearer abc.def-ghi")
    assert redact("sk-or-ABCDEF") == "sk-or-[REDACTED]"
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `uv run --with '.[dev]' python -m pytest tests/test_redaction.py -v`
Expected: 5 failures (mask_email missing, email key not masked, etc.). The regression test should still pass.

- [ ] **Step 3: Implement `mask_email` and integrate**

Edit `src/wabot_agent/redaction.py`. Replace its contents with:

```python
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SECRET_KEYS = ("key", "token", "secret", "password", "authorization", "cookie")
EMAIL_KEYS = ("email",)  # keys whose value is masked via mask_email, not [REDACTED]

PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{6,}\d)(?!\d)")
BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
OPENROUTER_KEY_RE = re.compile(r"sk-or-[A-Za-z0-9._-]+")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 7:
        return value
    return f"{digits[:2]}***{digits[-2:]}"


def mask_email(value: str) -> str:
    """Mask an email to `local_first***local_last@domain`.

    Local parts <=2 chars become `***`. Strings that don't look like an email
    are returned unchanged.
    """
    m = EMAIL_RE.fullmatch(value.strip()) if value else None
    if not m:
        return value
    local, _, domain = value.strip().partition("@")
    if len(local) <= 2:
        masked_local = "***"
    else:
        masked_local = f"{local[0]}***{local[-1]}"
    return f"{masked_local}@{domain}"


def redact_text(value: str) -> str:
    value = BEARER_RE.sub("Bearer [REDACTED]", value)
    value = OPENROUTER_KEY_RE.sub("sk-or-[REDACTED]", value)
    value = EMAIL_RE.sub(lambda m: mask_email(m.group(0)), value)
    return PHONE_RE.sub(lambda m: mask_phone(m.group(1)), value)


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            lower = key_s.lower()
            if any(marker in lower for marker in SECRET_KEYS):
                out[key_s] = "[REDACTED]"
            elif any(marker == lower for marker in EMAIL_KEYS) and isinstance(item, str):
                out[key_s] = mask_email(item)
            else:
                out[key_s] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


def looks_sensitive(value: str) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in SECRET_KEYS):
        return True
    if OPENROUTER_KEY_RE.search(value) or BEARER_RE.search(value):
        return True
    return False
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `uv run --with '.[dev]' python -m pytest tests/test_redaction.py tests/test_api.py tests/test_memory.py -v`
Expected: All pass. Critical — the existing redaction-dependent tests must still pass.

- [ ] **Step 5: Commit**

```bash
git add src/wabot_agent/redaction.py tests/test_redaction.py
git commit -m "feat(redaction): add email masking to redact() and redact_text()"
```

---

## Task 3: Build `logging_setup.py` (formatter, contextvars, filter, configure)

**Files:**
- Create: `src/wabot_agent/logging_setup.py`
- Test: `tests/test_logging_setup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_logging_setup.py`:

```python
from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from wabot_agent.logging_setup import (
    ContextVarsFilter,
    JsonFormatter,
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
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    return logger, buf


def test_json_formatter_emits_required_fields():
    logger, buf = _make_stream_logger()
    logger.info("hello_world", extra={"foo": "bar"})
    record = json.loads(buf.getvalue().strip())
    assert record["event"] == "hello_world"
    assert record["level"] == "INFO"
    assert record["logger"].startswith("test_")
    assert record["foo"] == "bar"
    assert "ts" in record
    assert record["request_id"] is None
    assert record["run_id"] is None


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
    lines = [json.loads(l) for l in buf.getvalue().strip().splitlines()]
    assert lines[0]["run_id"] is None
    assert lines[1]["run_id"] == "run-xyz"
    assert lines[2]["run_id"] is None


def test_json_formatter_redacts_extra():
    logger, buf = _make_stream_logger()
    logger.info("send", extra={"to": "+491701234567", "email": "x@y.com"})
    record = json.loads(buf.getvalue().strip())
    assert record["to"] != "+491701234567"
    assert record["email"] == "x***@y.com" or record["email"] == "***@y.com"


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


def test_text_formatter_smoke(monkeypatch):
    from wabot_agent.logging_setup import TextFormatter

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
    assert "key=value" in line
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `uv run --with '.[dev]' python -m pytest tests/test_logging_setup.py -v`
Expected: 6 failures, ImportError.

- [ ] **Step 3: Create `logging_setup.py`**

Create `src/wabot_agent/logging_setup.py`:

```python
"""Stdlib logging configuration for wabot_agent.

Two formatters: JSON (default, journalctl-friendly) and text (human dev).
Two ContextVars (`request_id_var`, `run_id_var`) carry correlation IDs across
async boundaries; a `ContextVarsFilter` stamps them onto every LogRecord.

Callers emit records the normal way:

    logger = logging.getLogger("wabot_agent.middleware")
    logger.info("request", extra={"route": "/health", "status": 200, "latency_ms": 3})

`extra` dicts are passed through `redact()` before serialization, so call sites
do not need to redact defensively — they just must not put unredacted secrets
into the message string itself.
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

request_id_var: ContextVar[str | None] = ContextVar("request_id_var", default=None)
run_id_var: ContextVar[str | None] = ContextVar("run_id_var", default=None)
auth_sub_var: ContextVar[str | None] = ContextVar("auth_sub_var", default=None)


@contextmanager
def run_id_context(run_id: str):
    """Bind `run_id_var` for the duration of an agent run. Idempotent on the
    reset: even if the body raises, the var is restored to its prior value.
    """
    token = run_id_var.set(run_id)
    try:
        yield
    finally:
        run_id_var.reset(token)


# --- Filter ----------------------------------------------------------------

# These attribute names are part of the public LogRecord surface we add. They
# are read by both formatters. Keep this list in sync with `_STANDARD_LR_ATTRS`
# below — anything else on the record is considered caller-supplied `extra`.
_INJECTED_FIELDS = ("request_id", "run_id", "auth_sub_short")


class ContextVarsFilter(logging.Filter):
    """Stamp request_id / run_id / auth_sub_short on every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Only set if missing — a caller's explicit kwargs win, so we don't
        # clobber an intentionally-overridden value.
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        if not hasattr(record, "run_id"):
            record.run_id = run_id_var.get()
        if not hasattr(record, "auth_sub_short"):
            sub = auth_sub_var.get()
            record.auth_sub_short = sub[:8] if sub else None
        return True


# --- Formatters ------------------------------------------------------------

# LogRecord's standard attributes; anything else on the record was supplied
# via `extra={...}` and should be serialized into the JSON payload.
_STANDARD_LR_ATTRS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime",
    }
)


class JsonFormatter(logging.Formatter):
    """One JSON object per record, on a single line. ASCII-safe so journalctl
    pipelines that aren't UTF-8-clean still parse.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "run_id": getattr(record, "run_id", None),
            "auth_sub_short": getattr(record, "auth_sub_short", None),
        }
        # Caller-supplied extras: everything on the record we didn't inject.
        extras: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in _STANDARD_LR_ATTRS or key in _INJECTED_FIELDS:
                continue
            extras[key] = value
        if extras:
            # Single pass through redact() — defense in depth for callers that
            # forgot to redact an `extra` field themselves.
            redacted = redact(extras)
            if isinstance(redacted, dict):
                payload.update(redacted)
        if record.exc_info:
            payload["exc_info"] = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        return json.dumps(payload, ensure_ascii=True, sort_keys=False, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable single-line format for local dev (WABOT_AGENT_LOG_FORMAT=text)."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        rid = getattr(record, "request_id", None) or "-"
        run = getattr(record, "run_id", None) or "-"
        head = f"{ts} {record.levelname:<5} {record.name} rid={rid} run={run} {record.getMessage()}"
        extras = []
        for key, value in record.__dict__.items():
            if key in _STANDARD_LR_ATTRS or key in _INJECTED_FIELDS:
                continue
            extras.append(f"{key}={value}")
        if extras:
            head += " " + " ".join(extras)
        if record.exc_info:
            head += "\n" + "".join(traceback.format_exception(*record.exc_info)).rstrip()
        return head


# --- Public entry point ----------------------------------------------------


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Idempotent: safe to call from create_app() at every boot. Wipes the
    root logger's handlers and installs ours. Uvicorn's `uvicorn.access` logger
    is silenced — RequestIdMiddleware emits the canonical access record.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextVarsFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())

    root.addHandler(handler)
    root.setLevel(level)

    # Silence uvicorn's own access log; our middleware emits the access record.
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False

    # uvicorn.error stays — it's startup/shutdown diagnostics we want.
    uerr = logging.getLogger("uvicorn.error")
    uerr.handlers = []
    uerr.propagate = True
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `uv run --with '.[dev]' python -m pytest tests/test_logging_setup.py -v`
Expected: all 6 pass.

- [ ] **Step 5: Lint**

Run: `uv run --with '.[dev]' ruff check src/wabot_agent/logging_setup.py tests/test_logging_setup.py`
Expected: All checks passed.

- [ ] **Step 6: Commit**

```bash
git add src/wabot_agent/logging_setup.py tests/test_logging_setup.py
git commit -m "feat(logging): add JSON/text formatters, contextvars filter, configure_logging"
```

---

## Task 4: Build `RequestIdMiddleware` (pure ASGI)

**Files:**
- Create: `src/wabot_agent/middleware.py`
- Test: `tests/test_middleware.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_middleware.py`:

```python
from __future__ import annotations

import json
import logging
import re
from io import StringIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wabot_agent.logging_setup import (
    ContextVarsFilter,
    JsonFormatter,
    request_id_var,
)
from wabot_agent.middleware import RequestIdMiddleware


@pytest.fixture()
def app_with_middleware():
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True, "rid": request_id_var.get()}

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
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    yield buf
    logger.handlers.clear()


def _last_json_line(buf: StringIO) -> dict:
    return json.loads(buf.getvalue().strip().splitlines()[-1])


def test_request_id_minted_when_absent(app_with_middleware, capture_logs):
    client = TestClient(app_with_middleware)
    resp = client.get("/ping")
    assert resp.status_code == 200
    rid = resp.headers["X-Request-ID"]
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


def test_request_id_honored_when_valid(app_with_middleware, capture_logs):
    client = TestClient(app_with_middleware)
    resp = client.get("/ping", headers={"X-Request-ID": "abc-DEF_123"})
    assert resp.headers["X-Request-ID"] == "abc-DEF_123"
    log = _last_json_line(capture_logs)
    assert log["request_id"] == "abc-DEF_123"
    assert log["request_id_source"] == "header"


def test_request_id_rejected_when_invalid(app_with_middleware, capture_logs):
    """Bad inbound IDs (too short, illegal chars, too long) are dropped — we
    mint a fresh one rather than letting an attacker pollute correlation."""
    client = TestClient(app_with_middleware)
    # Too short:
    resp = client.get("/ping", headers={"X-Request-ID": "a"})
    assert resp.headers["X-Request-ID"] != "a"
    log = _last_json_line(capture_logs)
    assert log["request_id_source"] == "minted"

    # Illegal characters:
    capture_logs.truncate(0)
    capture_logs.seek(0)
    resp = client.get("/ping", headers={"X-Request-ID": "bad rid<script>"})
    assert "<" not in resp.headers["X-Request-ID"]
    log = _last_json_line(capture_logs)
    assert log["request_id_source"] == "minted"


def test_5xx_still_emits_log(app_with_middleware, capture_logs):
    client = TestClient(app_with_middleware, raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    log = _last_json_line(capture_logs)
    assert log["status"] == 500
    assert log["route"] == "/boom"
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `uv run --with '.[dev]' python -m pytest tests/test_middleware.py -v`
Expected: ImportError on `RequestIdMiddleware`.

- [ ] **Step 3: Implement `RequestIdMiddleware`**

Create `src/wabot_agent/middleware.py`:

```python
"""Pure-ASGI request_id middleware.

Honors an inbound `X-Request-ID` header when it matches a safe character class
and length bound; otherwise mints a fresh `uuid4().hex[:12]`. Sets the
`request_id_var` ContextVar for the lifetime of the request so downstream code
— route handlers, the agent runner, tools, the wabot client — emits log records
correlated by `request_id`. Echoes the header on the response.

Emits one `request` log record on completion with `route`, `method`, `status`,
`latency_ms`. For long-lived streaming responses, callers can additionally emit
phase=`start`/`end` records inside the handler if they want sub-request
timing — the middleware itself emits one record at the end of the response.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .logging_setup import request_id_var

logger = logging.getLogger("wabot_agent.middleware")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{12,64}$")


def _mint_request_id() -> str:
    return uuid.uuid4().hex[:12]


def _is_valid_request_id(value: str) -> bool:
    return bool(_REQUEST_ID_RE.fullmatch(value))


def _client_ip_label(scope: Scope) -> str:
    """Return 'loopback' for 127.0.0.1/::1, 'remote' otherwise. We never log
    the raw remote IP — when Cloudflare Tunnel fronts us, it's the tunnel's
    address, which is uninteresting; for direct loopback access there's only
    one possible value."""
    client = scope.get("client")
    if not client:
        return "unknown"
    host = client[0] if isinstance(client, tuple | list) else None
    if host in ("127.0.0.1", "::1", "localhost"):
        return "loopback"
    return "remote"


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Extract X-Request-ID, validate.
        inbound: str | None = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                try:
                    inbound = value.decode("latin-1")
                except UnicodeDecodeError:
                    inbound = None
                break

        if inbound and _is_valid_request_id(inbound):
            request_id = inbound
            source = "header"
        else:
            request_id = _mint_request_id()
            source = "minted"

        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status_code: int = 500  # default if the response never starts

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 500))
                headers: list[tuple[bytes, bytes]] = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "request",
                extra={
                    "route": scope.get("path", ""),
                    "method": scope.get("method", ""),
                    "status": 500,
                    "latency_ms": latency_ms,
                    "client_ip": _client_ip_label(scope),
                    "request_id_source": source,
                },
            )
            request_id_var.reset(token)
            raise
        else:
            latency_ms = int((time.perf_counter() - start) * 1000)
            level = logging.WARNING if status_code >= 500 else logging.INFO
            logger.log(
                level,
                "request",
                extra={
                    "route": scope.get("path", ""),
                    "method": scope.get("method", ""),
                    "status": status_code,
                    "latency_ms": latency_ms,
                    "client_ip": _client_ip_label(scope),
                    "request_id_source": source,
                },
            )
        finally:
            request_id_var.reset(token)
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `uv run --with '.[dev]' python -m pytest tests/test_middleware.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint**

Run: `uv run --with '.[dev]' ruff check src/wabot_agent/middleware.py tests/test_middleware.py`

- [ ] **Step 6: Commit**

```bash
git add src/wabot_agent/middleware.py tests/test_middleware.py
git commit -m "feat(middleware): add RequestIdMiddleware with X-Request-ID honor/mint"
```

---

## Task 5: Build `RunObservabilityHooks` for tool-call/result correlation

**Files:**
- Create: `src/wabot_agent/agent_hooks.py`
- Test: `tests/test_agent_hooks.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agent_hooks.py`:

```python
from __future__ import annotations

import json
import logging
from io import StringIO
from types import SimpleNamespace
from typing import Any

import pytest

from wabot_agent.agent_hooks import RunObservabilityHooks
from wabot_agent.logging_setup import (
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
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield buf
    logger.handlers.clear()


def _lines(buf: StringIO) -> list[dict]:
    return [json.loads(l) for l in buf.getvalue().strip().splitlines()]


async def test_tool_start_logs_redacted_args(capture_logs):
    hooks = RunObservabilityHooks()
    ctx = SimpleNamespace(context=None)  # AgentHookContext is duck-typed here
    tool = SimpleNamespace(name="send_whatsapp_text")
    raw_call = SimpleNamespace(
        call_id="call_123",
        arguments='{"to":"+491701234567","text":"hi"}',
    )
    with run_id_context("run-1"):
        await hooks.on_tool_start(ctx, agent=SimpleNamespace(name="a"), tool=tool, raw_call=raw_call)
    records = _lines(capture_logs)
    assert records[0]["event"] == "tool_call"
    assert records[0]["tool_name"] == "send_whatsapp_text"
    assert records[0]["call_id"] == "call_123"
    assert records[0]["run_id"] == "run-1"
    # Phone number redacted:
    assert "491701234567" not in json.dumps(records[0]["args_redacted"])


async def test_tool_end_logs_ok_and_latency(capture_logs):
    hooks = RunObservabilityHooks()
    ctx = SimpleNamespace(context=None)
    tool = SimpleNamespace(name="wabot_health")
    raw_call = SimpleNamespace(call_id="call_xyz", arguments="{}")
    with run_id_context("run-2"):
        await hooks.on_tool_start(ctx, agent=SimpleNamespace(name="a"), tool=tool, raw_call=raw_call)
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


async def test_tool_end_marks_failure_on_error_key(capture_logs):
    hooks = RunObservabilityHooks()
    ctx = SimpleNamespace(context=None)
    tool = SimpleNamespace(name="send_whatsapp_text")
    raw_call = SimpleNamespace(call_id="cid", arguments="{}")
    await hooks.on_tool_start(ctx, agent=SimpleNamespace(name="a"), tool=tool, raw_call=raw_call)
    await hooks.on_tool_end(
        ctx,
        agent=SimpleNamespace(name="a"),
        tool=tool,
        result={"sent": False, "reason": "wabot_not_ready"},
    )
    end = _lines(capture_logs)[-1]
    # `sent: false` is a policy-blocked send, not a tool error. ok stays True.
    assert end["ok"] is True


async def test_llm_start_end_emits_records(capture_logs):
    hooks = RunObservabilityHooks()
    ctx = SimpleNamespace(context=None)
    await hooks.on_llm_start(ctx, agent=SimpleNamespace(name="a", model="m/x"), system_prompt=None, input_items=[])
    await hooks.on_llm_end(ctx, agent=SimpleNamespace(name="a", model="m/x"), response=SimpleNamespace())
    records = _lines(capture_logs)
    events = [r["event"] for r in records]
    assert "llm_start" in events
    assert "llm_end" in events
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `uv run --with '.[dev]' python -m pytest tests/test_agent_hooks.py -v`
Expected: ImportError.

- [ ] **Step 3: Inspect the installed SDK to confirm the hook signature**

The Agents SDK's `RunHooksBase` is defined at `.venv/lib/python3.12/site-packages/agents/lifecycle.py`. Skim it:

```bash
sed -n '1,180p' .venv/lib/python3.12/site-packages/agents/lifecycle.py
```

Confirm method signatures for `on_tool_start`, `on_tool_end`, `on_agent_start`, `on_agent_end`, `on_llm_start`, `on_llm_end`. They take an `AgentHookContext` first; subsequent kwargs vary slightly across SDK 0.17 versions. Our hooks must be robust to attribute presence — use `getattr(..., default)` not direct attribute access.

- [ ] **Step 4: Implement `agent_hooks.py`**

Create `src/wabot_agent/agent_hooks.py`:

```python
"""OpenAI Agents SDK RunHooks subclass that emits structured log records.

We attach this at Runner.run(..., hooks=RunObservabilityHooks()). The SDK
calls into us at every lifecycle boundary — agent start/end, tool start/end,
LLM start/end, handoffs — and we turn each into a redacted, correlated log
record. Tool argument redaction is critical because the LLM can pass user
input as a tool argument (e.g. send_whatsapp_text(text="...sensitive...")).

We are intentionally defensive about attribute shape — the SDK has evolved
field names across 0.17.x; treat every getattr as best-effort.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

try:
    from agents import RunHooks  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover — covered by tests that bypass the SDK
    RunHooks = object  # fallback so tests can subclass without the SDK installed

from .redaction import redact

logger = logging.getLogger("wabot_agent.agent_hooks")


class RunObservabilityHooks(RunHooks):  # type: ignore[misc, valid-type]
    """Emit structured log records at every Agents-SDK lifecycle boundary."""

    def __init__(self) -> None:
        # Per-call_id start times for latency_ms on tool_end.
        self._tool_starts: dict[str, float] = {}
        self._llm_starts: dict[int, float] = {}

    # --- Tool boundary ----------------------------------------------------

    async def on_tool_start(self, context, agent, tool, raw_call=None, **_):  # noqa: ANN001
        tool_name = getattr(tool, "name", None) or "<unknown>"
        call_id = getattr(raw_call, "call_id", None) or getattr(raw_call, "id", None)
        args = _safe_args(raw_call)
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

    async def on_tool_end(self, context, agent, tool, result, **kwargs):  # noqa: ANN001
        tool_name = getattr(tool, "name", None) or "<unknown>"
        call_id = (
            getattr(kwargs.get("raw_call", None), "call_id", None)
            or kwargs.get("call_id")
        )
        latency_ms = None
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

    async def on_llm_start(self, context, agent, system_prompt=None, input_items=None, **_):  # noqa: ANN001
        self._llm_starts[id(context)] = time.perf_counter()
        logger.debug(
            "llm_start",
            extra={"model": getattr(agent, "model", None)},
        )

    async def on_llm_end(self, context, agent, response=None, **_):  # noqa: ANN001
        start = self._llm_starts.pop(id(context), None)
        latency_ms = int((time.perf_counter() - start) * 1000) if start is not None else None
        usage = None
        for attr in ("usage", "token_usage"):
            candidate = getattr(response, attr, None)
            if candidate is not None:
                try:
                    usage = dict(candidate) if not isinstance(candidate, dict) else candidate
                except (TypeError, ValueError):
                    usage = None
                break
        extra: dict[str, Any] = {
            "model": getattr(agent, "model", None),
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

    async def on_agent_end(self, context, agent, output=None):  # noqa: ANN001
        logger.debug(
            "agent_end",
            extra={"agent_name": getattr(agent, "name", None)},
        )

    # --- Handoffs ---------------------------------------------------------

    async def on_handoff(self, context, from_agent=None, to_agent=None, **_):  # noqa: ANN001
        logger.info(
            "agent_handoff",
            extra={
                "from": getattr(from_agent, "name", None),
                "to": getattr(to_agent, "name", None),
            },
        )


# --- helpers ---------------------------------------------------------------


def _safe_args(raw_call) -> Any:  # noqa: ANN001
    if raw_call is None:
        return None
    args = getattr(raw_call, "arguments", None)
    if args is None and isinstance(raw_call, dict):
        args = raw_call.get("arguments")
    if args is None:
        return None
    if isinstance(args, str):
        try:
            return json.loads(args)
        except (ValueError, TypeError):
            return {"_raw": args}
    return args


def _looks_ok(result: Any) -> bool:
    """A tool result is `ok` unless it carries an explicit failure signal.

    `sent: False` from send_whatsapp_text is NOT a tool error — it's a
    successful policy-block. The send_blocked event captures that separately.
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
```

- [ ] **Step 5: Run tests, confirm pass**

Run: `uv run --with '.[dev]' python -m pytest tests/test_agent_hooks.py -v`
Expected: 4 passed.

- [ ] **Step 6: Lint**

Run: `uv run --with '.[dev]' ruff check src/wabot_agent/agent_hooks.py tests/test_agent_hooks.py`

- [ ] **Step 7: Commit**

```bash
git add src/wabot_agent/agent_hooks.py tests/test_agent_hooks.py
git commit -m "feat(agent_hooks): emit structured logs at every Agents SDK lifecycle boundary"
```

---

## Task 6: Wire `run_id_context` and hooks into `run_agent` / `run_agent_streamed`

**Files:**
- Modify: `src/wabot_agent/agent.py`
- Test: extend `tests/test_agent.py` and `tests/test_agent_events.py`

- [ ] **Step 1: Write a failing test in `tests/test_agent.py`**

Append to `tests/test_agent.py`:

```python
import json
import logging
from io import StringIO

from wabot_agent.logging_setup import ContextVarsFilter, JsonFormatter, run_id_var


async def test_run_agent_sets_run_id_context(settings, memory):
    """While run_agent is executing, run_id_var is set; after, it's None."""
    buf = StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(JsonFormatter())
    h.addFilter(ContextVarsFilter())
    logger = logging.getLogger("wabot_agent.agent")
    logger.handlers.clear()
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    from wabot_agent.agent import run_agent
    from wabot_agent.events import EventLog

    event_log = EventLog(settings.log_path)
    # offline echo model — no network — see conftest.settings fixture
    result = await run_agent("hi", settings=settings, memory=memory, event_log=event_log)
    lines = [json.loads(l) for l in buf.getvalue().strip().splitlines() if l]
    starts = [l for l in lines if l["event"] == "agent_run_start"]
    ends = [l for l in lines if l["event"] == "agent_run_end"]
    assert len(starts) == 1 and starts[0]["run_id"] == result.run_id
    assert len(ends) == 1 and ends[0]["run_id"] == result.run_id
    assert run_id_var.get() is None  # cleared on exit
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run --with '.[dev]' python -m pytest tests/test_agent.py::test_run_agent_sets_run_id_context -v`
Expected: assertion failure (no `agent_run_start` log record yet).

- [ ] **Step 3: Modify `src/wabot_agent/agent.py`**

At the top, add imports:

```python
import logging
import time
```

and:

```python
from .agent_hooks import RunObservabilityHooks
from .logging_setup import run_id_context
```

Define a module logger near the top, after `set_tracing_disabled(True)`:

```python
logger = logging.getLogger("wabot_agent.agent")
```

Modify `run_agent` — wrap the body in `run_id_context` and emit the new structured records (keep the existing `event_log.write` calls, do NOT remove them):

```python
async def run_agent(
    prompt: str,
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    wabot: WabotClient | None = None,
    inbound: InboundMessage | None = None,
    session_id: str | None = None,
) -> AgentRunResult:
    run_id = str(uuid.uuid4())
    session_key = session_id or (inbound.sender if inbound else "operator")
    sqlite_session = SQLiteSession(
        session_id=session_key,
        db_path=Path(settings.db_path),
    )
    context = RuntimeContext(
        settings=settings,
        memory=memory,
        wabot=wabot or WabotClient(settings.wabot_endpoint, settings.resolved_wabot_token),
        event_log=event_log,
        run_id=run_id,
        inbound=inbound,
    )
    event_log.write("agent_run_start", {"run_id": run_id, "session_id": session_key})

    with run_id_context(run_id):
        logger.info(
            "agent_run_start",
            extra={
                "session_id": session_key,
                "sender": inbound.sender if inbound else None,
                "live_model": settings.live_model_enabled,
                "model": settings.openrouter_model if settings.live_model_enabled else "offline",
            },
        )
        start = time.perf_counter()
        try:
            async with connected_mcp_servers(settings.mcp_config) as mcp_servers:
                agent = build_agent(settings, mcp_servers=mcp_servers)
                result = await Runner.run(
                    agent,
                    _augment_prompt(prompt, inbound),
                    context=context,
                    max_turns=settings.max_agent_turns,
                    run_config=RunConfig(tracing_disabled=True, workflow_name="wabot-agent"),
                    session=sqlite_session,
                    hooks=RunObservabilityHooks(),
                )
        except Exception as exc:
            logger.exception(
                "agent_run_error",
                extra={
                    "session_id": session_key,
                    "error_class": type(exc).__name__,
                    "error_message": redact(str(exc)),
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                },
            )
            raise

        final_output = str(result.final_output)
        memory.record_run(run_id, inbound.sender if inbound else None, prompt, final_output)
        event_log.write(
            "agent_run_complete",
            {
                "run_id": run_id,
                "session_id": session_key,
                "live_model": settings.live_model_enabled,
                "sender": inbound.sender if inbound else None,
                "user_input": prompt,
                "final_output": final_output,
            },
        )
        logger.info(
            "agent_run_end",
            extra={
                "session_id": session_key,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "live_model": settings.live_model_enabled,
                "final_output_len": len(final_output),
            },
        )

    return AgentRunResult(
        run_id=run_id,
        final_output=final_output,
        session_id=session_key,
        live_model=settings.live_model_enabled,
    )
```

Apply the same pattern to `run_agent_streamed`: wrap the body in `with run_id_context(run_id):`, emit `agent_run_start` / `agent_run_end` / `agent_run_error` via the logger, pass `hooks=RunObservabilityHooks()` to both `Runner.run_streamed(...)` and the fallback `Runner.run(...)`.

- [ ] **Step 4: Run tests, confirm pass**

Run: `uv run --with '.[dev]' python -m pytest tests/test_agent.py tests/test_agent_events.py -v`
Expected: All pass.

- [ ] **Step 5: Lint**

Run: `uv run --with '.[dev]' ruff check src/wabot_agent/agent.py`

- [ ] **Step 6: Commit**

```bash
git add src/wabot_agent/agent.py tests/test_agent.py
git commit -m "feat(agent): wrap run_agent in run_id_context and attach RunObservabilityHooks"
```

---

## Task 7: Wire middleware and configure_logging into FastAPI app

**Files:**
- Modify: `src/wabot_agent/api.py`

- [ ] **Step 1: Add a failing test**

Append to `tests/test_api.py`:

```python
def test_x_request_id_header_echoed(client):
    """The middleware must add X-Request-ID to every response."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "X-Request-ID" in resp.headers
    assert len(resp.headers["X-Request-ID"]) >= 12


def test_x_request_id_honored(client):
    resp = client.get("/health", headers={"X-Request-ID": "honored-rid-1234"})
    assert resp.headers["X-Request-ID"] == "honored-rid-1234"
```

(`client` fixture in `tests/conftest.py` may need an exported version — verify; if not, use `TestClient(create_app(settings))`.)

- [ ] **Step 2: Run, confirm failure**

Run: `uv run --with '.[dev]' python -m pytest tests/test_api.py -v -k request_id`
Expected: Header missing.

- [ ] **Step 3: Modify `src/wabot_agent/api.py`**

Add imports at the top:

```python
from .logging_setup import configure_logging
from .middleware import RequestIdMiddleware
```

In `create_app(settings)`, immediately after `settings.ensure_dirs()`:

```python
    configure_logging(level=settings.log_level, fmt=settings.log_format)
```

After the line `app = FastAPI(title="wabot-agent", version="0.1.0", lifespan=lifespan)`:

```python
    app.add_middleware(RequestIdMiddleware)
```

In `main()`, set `access_log=False`:

```python
def main() -> None:
    settings = get_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        reload=False,
        access_log=False,
    )
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `uv run --with '.[dev]' python -m pytest tests/test_api.py -v`
Expected: All pass (request_id tests pass; everything else still passes).

- [ ] **Step 5: Lint**

Run: `uv run --with '.[dev]' ruff check src/wabot_agent/api.py`

- [ ] **Step 6: Commit**

```bash
git add src/wabot_agent/api.py tests/test_api.py
git commit -m "feat(api): register RequestIdMiddleware and configure structured logging"
```

---

## Task 8: Log auth events (login success/failure) with email redaction

**Files:**
- Modify: `src/wabot_agent/auth.py`
- Test: `tests/test_auth_logging.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_auth_logging.py`:

```python
from __future__ import annotations

import hashlib
import json
import logging
from io import StringIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wabot_agent.auth import verify_human_factory
from wabot_agent.config import Settings
from wabot_agent.logging_setup import ContextVarsFilter, JsonFormatter
from wabot_agent.middleware import RequestIdMiddleware


@pytest.fixture()
def capture_auth_logs():
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextVarsFilter())
    logger = logging.getLogger("wabot_agent.auth")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    yield buf
    logger.handlers.clear()


def _lines(buf):
    return [json.loads(l) for l in buf.getvalue().strip().splitlines() if l]


def _client_with_auth(operator_token: str | None = None) -> TestClient:
    settings = Settings(
        operator_token=operator_token,
        cf_access_required=False,
    )
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    dep = verify_human_factory(settings)
    @app.get("/secret")
    async def secret(_=__import__("fastapi").Depends(dep)):
        return {"ok": True}
    return TestClient(app)


def test_auth_success_logs_auth_login(capture_auth_logs):
    client = _client_with_auth(operator_token="t0p-s3cret-token")
    resp = client.get("/secret", headers={"X-Operator-Token": "t0p-s3cret-token"})
    assert resp.status_code == 200
    rec = [l for l in _lines(capture_auth_logs) if l["event"] == "auth_login"]
    assert rec, "expected an auth_login record"
    assert rec[0]["source"] == "operator-header"
    assert rec[0]["tenant_id"] == "operator"
    # No raw email/sub in operator-token mode:
    assert rec[0].get("email_hash") is None


def test_auth_failure_logs_auth_failed(capture_auth_logs):
    client = _client_with_auth(operator_token="real-token")
    resp = client.get("/secret", headers={"X-Operator-Token": "wrong-token"})
    assert resp.status_code == 401
    rec = [l for l in _lines(capture_auth_logs) if l["event"] == "auth_failed"]
    assert rec
    assert rec[0]["reason"] == "no_credential_matched"


def test_auth_open_path_logged(capture_auth_logs):
    """If operator_token is unset, auth_login records source=open."""
    client = _client_with_auth(operator_token=None)
    resp = client.get("/secret")
    assert resp.status_code == 200
    rec = [l for l in _lines(capture_auth_logs) if l["event"] == "auth_login"]
    assert rec and rec[0]["source"] == "open"
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run --with '.[dev]' python -m pytest tests/test_auth_logging.py -v`
Expected: 3 failures (no `auth_login` / `auth_failed` records emitted).

- [ ] **Step 3: Modify `src/wabot_agent/auth.py`**

Add at the top, after the docstring imports:

```python
import hashlib
import logging

from .logging_setup import auth_sub_var

logger = logging.getLogger("wabot_agent.auth")


def _hash_sub(sub: str | None) -> str | None:
    if not sub:
        return None
    return hashlib.sha256(sub.encode("utf-8")).hexdigest()[:16]
```

In `verify_human` (inside `verify_human_factory`), at every point where the function returns an `AuthIdentity`, emit `auth_login`. At every `raise HTTPException(401)` point emit `auth_failed`. Concretely, replace each return / raise:

```python
            # CF Access success:
            sub_hash = _hash_sub(access.sub)
            if access.sub:
                auth_sub_var.set(access.sub)
            logger.info(
                "auth_login",
                extra={
                    "source": "cf-access",
                    "tenant_id": _OPERATOR_TENANT_ID,
                    "email_hash": sub_hash,
                },
            )
            return AuthIdentity(...)
```

```python
            # CF Access failure:
            logger.warning(
                "auth_failed",
                extra={"source_attempted": "cf-access", "reason": str(exc)[:200]},
            )
            raise HTTPException(...)
```

```python
            # Operator failure (no source matched):
            logger.warning(
                "auth_failed",
                extra={"source_attempted": "operator", "reason": "no_credential_matched"},
            )
            raise HTTPException(...)
```

```python
            # Operator success / open path:
            logger.info(
                "auth_login",
                extra={"source": source, "tenant_id": _OPERATOR_TENANT_ID, "email_hash": None},
            )
            return AuthIdentity(...)
```

Note: `auth_sub_var` is set on success — subsequent log records in the same request automatically carry `auth_sub_short`. There's no `reset()`; the var goes out of scope when the request completes (FastAPI's contextvars-aware request handling).

Actually — for cleanliness, reset on response. Move the `auth_sub_var.set(...)` into the `verify_human` dependency, but the request-scoped lifecycle is hard to hook. Acceptable trade-off: rely on the middleware's `request_id_var.reset(token)` finally block; for `auth_sub_var` we accept that it leaks slightly into the next request unless we also bind/unbind in middleware. **Simpler: skip stamping auth_sub on every record.** Drop `auth_sub_var` for the v1 implementation and put `email_hash` directly on `auth_login` only. Update the spec accordingly.

(Revisit: remove `auth_sub_var` from `logging_setup.py` and the filter. The `request_id`+`run_id` pair is enough for v1 correlation.)

- [ ] **Step 4: Simplify logging_setup.py — remove auth_sub_var**

In `src/wabot_agent/logging_setup.py`, delete the `auth_sub_var` definition, remove the `auth_sub_short` line from `JsonFormatter.format`, remove the `auth_sub_short` line from `_INJECTED_FIELDS`, and remove the corresponding assignment in `ContextVarsFilter.filter`. Also delete `auth_sub_short` mentions from `TextFormatter` and remove the import in `auth.py`.

Update `tests/test_logging_setup.py` to drop the `auth_sub_short` assertion.

- [ ] **Step 5: Run tests, confirm pass**

Run: `uv run --with '.[dev]' python -m pytest tests/test_auth_logging.py tests/test_logging_setup.py -v`
Expected: All pass.

- [ ] **Step 6: Lint**

Run: `uv run --with '.[dev]' ruff check src/wabot_agent/auth.py src/wabot_agent/logging_setup.py`

- [ ] **Step 7: Commit**

```bash
git add src/wabot_agent/auth.py src/wabot_agent/logging_setup.py tests/test_auth_logging.py tests/test_logging_setup.py
git commit -m "feat(auth): emit auth_login/auth_failed structured log records"
```

---

## Task 9: Log inbound webhook + outbound wabot calls + send-blocked

**Files:**
- Modify: `src/wabot_agent/api.py` (inbound handler)
- Modify: `src/wabot_agent/wabot.py`
- Modify: `src/wabot_agent/tools.py`

- [ ] **Step 1: Add a failing test in `tests/test_api.py`**

```python
import json
import logging
from io import StringIO

from wabot_agent.logging_setup import ContextVarsFilter, JsonFormatter


def test_inbound_emits_log_record(client_with_inbound_token, monkeypatch):
    buf = StringIO()
    h = logging.StreamHandler(buf); h.setFormatter(JsonFormatter()); h.addFilter(ContextVarsFilter())
    logging.getLogger("wabot_agent.api").handlers = [h]
    logging.getLogger("wabot_agent.api").setLevel(logging.INFO)
    logging.getLogger("wabot_agent.api").propagate = False

    resp = client_with_inbound_token.post(
        "/whatsapp/inbound",
        json={"id": "msg-1", "from": "+491701234567", "text": "hi"},
        headers={"Authorization": "Bearer test-inbound-token"},
    )
    assert resp.status_code == 200
    records = [json.loads(l) for l in buf.getvalue().strip().splitlines() if l]
    rec = [r for r in records if r["event"] == "inbound_message_received"]
    assert rec
    assert rec[0]["message_id"] == "msg-1"
    assert "491701234567" not in json.dumps(rec[0])  # phone masked
```

(Where `client_with_inbound_token` is a fixture using existing `tests/conftest.py` patterns — see test_api.py for parallels.)

- [ ] **Step 2: Run, confirm failure.**

- [ ] **Step 3: In `src/wabot_agent/api.py`**, add a module logger and emit:

```python
logger = logging.getLogger("wabot_agent.api")

# Inside `whatsapp_inbound` handler, after `claim_message`:
logger.info(
    "inbound_message_received",
    extra={
        "message_id": inbound.id,
        "sender": mask_phone(inbound.sender),
        "is_group": inbound.is_group,
        "duplicate": False,  # if we got here, it's not a dup
    },
)
```

For the duplicate-path early return, emit with `duplicate=True`. Import `mask_phone` from `.redaction` at the top.

- [ ] **Step 4: In `src/wabot_agent/wabot.py`**, add a logger and wrap `send_text` / `send_image` with latency timing:

```python
import logging
import time

logger = logging.getLogger("wabot_agent.wabot")

# inside send_text, replace the existing request with:
start = time.perf_counter()
try:
    response = await self._client.post(...)
except Exception as exc:
    logger.warning(
        "outbound_http",
        extra={
            "endpoint_path": "/send",
            "ok": False,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "error_class": type(exc).__name__,
        },
    )
    raise
logger.info(
    "outbound_http",
    extra={
        "endpoint_path": "/send",
        "status_code": response.status_code,
        "ok": response.is_success,
        "latency_ms": int((time.perf_counter() - start) * 1000),
    },
)
```

Same pattern for `send_image` with `"endpoint_path": "/send-image"`.

- [ ] **Step 5: In `src/wabot_agent/tools.py`**, emit a `send_blocked` log on every policy failure:

```python
import logging
logger = logging.getLogger("wabot_agent.tools")

# inside send_whatsapp_text after _is_send_allowed returns False:
logger.info(
    "send_blocked",
    extra={"policy": ctx.context.settings.send_policy, "reason": reason, "to": mask_phone(to)},
)
```

Same in `send_whatsapp_image`.

- [ ] **Step 6: Run all tests**

Run: `uv run --with '.[dev]' python -m pytest -q`
Expected: All offline tests pass.

- [ ] **Step 7: Lint**

Run: `uv run --with '.[dev]' ruff check src/wabot_agent/api.py src/wabot_agent/wabot.py src/wabot_agent/tools.py`

- [ ] **Step 8: Commit**

```bash
git add src/wabot_agent/api.py src/wabot_agent/wabot.py src/wabot_agent/tools.py tests/test_api.py
git commit -m "feat(observability): log inbound webhook, outbound http, send-blocked"
```

---

## Task 10: README + CLAUDE.md docs — "Observability" section + "Trace a run" walkthrough

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a new "Observability" section to README.md**

Insert after the "Verification" section (~line 273), before "Continuous Integration":

````markdown
## Observability

`wabot-agent` emits structured JSON log records to stdout (one object per
line) at every meaningful boundary — HTTP request, agent run, tool call,
outbound HTTP, auth event. The records are designed to be journalctl-friendly
on the VPS and `jq`-pipeable locally.

### Configuration

Two env vars:

```
WABOT_AGENT_LOG_LEVEL=INFO   # DEBUG | INFO | WARNING | ERROR
WABOT_AGENT_LOG_FORMAT=json  # json (default) | text (human dev)
```

Both have `VIGNESH_*` aliases. Changes are restart-required — `log_level` is
deliberately not exposed via `/api/settings`.

### Record schema

Every record carries:

| Field | Notes |
|---|---|
| `ts` | ISO-8601 UTC. |
| `level` | `INFO` etc. |
| `logger` | e.g. `wabot_agent.middleware`, `wabot_agent.agent`. |
| `event` | Short snake_case slug (`request`, `tool_call`, etc.). |
| `request_id` | Set on every record emitted inside a request. |
| `run_id` | Set on every record emitted inside an agent run. |

Event-specific fields:

- `request` — `route`, `method`, `status`, `latency_ms`, `request_id_source` (`header` / `minted`), `client_ip` (`loopback` / `remote`).
- `auth_login` — `source`, `tenant_id`, `email_hash` (sha256[:16] of CF Access `sub`, only on CF path).
- `auth_failed` — `source_attempted`, `reason`.
- `inbound_message_received` — `message_id`, `sender` (masked), `is_group`, `duplicate`.
- `agent_run_start` — `session_id`, `sender` (masked), `live_model`, `model`.
- `agent_run_end` — `session_id`, `latency_ms`, `live_model`, `final_output_len`.
- `agent_run_error` — `session_id`, `error_class`, `error_message` (redacted), `exc_info`.
- `tool_call` — `tool_name`, `call_id`, `args_redacted`.
- `tool_result` — `tool_name`, `call_id`, `ok`, `latency_ms`, `result_kind`.
- `outbound_http` — `endpoint_path`, `status_code`, `ok`, `latency_ms`.
- `send_blocked` — `policy`, `reason`, `to` (masked).
- `settings_updated` — `fields`.

### Redaction

Every field name containing `key`, `token`, `secret`, `password`,
`authorization`, or `cookie` is replaced with `[REDACTED]`. `email` keys
are masked to `local_first***local_last@domain`. Phone numbers, bearer
tokens, and OpenRouter API keys are masked in any string value.
`tool_call.args_redacted` is the full argument dict run through `redact()`
before logging.

### Correlation IDs

- **`request_id`** — minted per HTTP request by `RequestIdMiddleware`, or
  honored from an inbound `X-Request-ID` header when it matches
  `^[A-Za-z0-9_-]{12,64}$`. Echoed on the response.
- **`run_id`** — minted by `run_agent()` / `run_agent_streamed()`. Stamped
  via `ContextVar` on every log record emitted inside that run, including
  tool calls (via `RunObservabilityHooks`) and any wabot client HTTP calls
  made on behalf of the agent.

Both flow across `await` boundaries via `contextvars`.

### Trace a run end-to-end

```bash
# 1. Grab the request_id from the response header — or read it from the request log.
$ curl -sH 'X-Operator-Token: ...' -X POST http://127.0.0.1:8787/api/chat \
    -H 'content-type: application/json' \
    -d '{"message":"check wabot health"}' -i | grep -i 'x-request-id'

X-Request-ID: a1b2c3d4e5f6

# 2. Follow that request through the logs:
$ journalctl -u wabot-agent -o cat | jq -c '. | select(.request_id == "a1b2c3d4e5f6")'

# 3. The run_id appears on the agent_run_start record. Pivot:
$ journalctl -u wabot-agent -o cat \
    | jq -c '. | select(.run_id == "5e7f9b22-3a44-4cd1-9d50-1f9e0fb33df1")'

# 4. The same run_id lives in the dashboard's /api/runs response. Both surfaces correlate.
```

For local dev set `WABOT_AGENT_LOG_FORMAT=text` and pipe to less:

```
$ uv run python main.py 2>&1 | less -R
14:22:03 INFO  wabot_agent.middleware rid=a1b2c3d4e5f6 run=- request route=/api/chat method=POST status=200 latency_ms=1842
14:22:01 INFO  wabot_agent.agent      rid=a1b2c3d4e5f6 run=5e7f9b22 agent_run_start session_id=operator live_model=true
14:22:02 INFO  wabot_agent.agent_hooks rid=a1b2c3d4e5f6 run=5e7f9b22 tool_call tool_name=wabot_health
...
```

### Relationship with `events.jsonl` and `/api/runs`

The new stdout JSON log is an **additional** sink for ops debugging via
journalctl. It does NOT replace:

- `data/events.jsonl` — the operator-UI feed for the SSE dashboard.
- The SQLite `runs` and `tool_events` tables — queried by `/api/runs`.

Both remain unchanged. The new logs gain `request_id` and `latency_ms` that
the DB events don't carry today; the DB events have the full result payloads
that we deliberately keep out of stdout logs.
````

- [ ] **Step 2: Append a one-paragraph pointer to CLAUDE.md**

Append under "Conventions" (or near the bottom under "Repository Layout"):

```markdown
### Observability

Structured JSON logs are emitted to stdout via stdlib `logging` configured in
[src/wabot_agent/logging_setup.py](src/wabot_agent/logging_setup.py). Every
record carries `request_id` and (inside an agent run) `run_id` via
`contextvars`. New log call sites should use `logging.getLogger("wabot_agent.<module>")`
and pass structured fields via `extra={...}` — never format secrets into the
message string. The JSON formatter passes `extra` through `redact()` as
defense-in-depth, but caller-side discipline still matters. See the
"Observability" section in the README for the full schema and trace workflow.
```

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document structured logging fields and 'trace a run' workflow"
```

---

## Task 11: Full offline test suite + ruff + final smoke

**Files:** none (verification).

- [ ] **Step 1: Run full offline pytest**

Run: `uv run --with '.[dev]' python -m pytest -q`
Expected: All offline tests pass.

- [ ] **Step 2: Run ruff over the whole tree**

Run: `uv run --with '.[dev]' ruff check .`
Expected: All checks passed.

- [ ] **Step 3: Run the local eval harness**

Run: `uv run python evals/run_local.py`
Expected: All cases pass.

- [ ] **Step 4: Manual smoke — boot, hit /health, follow the logs**

Run in one terminal:

```bash
WABOT_AGENT_LOG_FORMAT=text uv run python main.py
```

In another:

```bash
curl -i http://127.0.0.1:8787/health
```

Expected: A `200 OK` with `X-Request-ID:` header; the server window shows one
`request` line with matching `rid=...`.

```bash
curl -H 'X-Request-ID: traceme-12345abc' -i http://127.0.0.1:8787/health
```

Expected: response echoes `X-Request-ID: traceme-12345abc`; log line shows
`rid=traceme-12345abc` and `request_id_source=header`.

- [ ] **Step 5: Tag the work and push (optional, by user request)**

```bash
# Only if explicitly requested by the operator
git log --oneline -n 12
```

---

## Self-Review

**1. Spec coverage** — Walking the issue's acceptance criteria:

- [x] _"Every request log includes `request_id` and status"_ — Task 4 (middleware) + Task 7 (wiring) + Task 10 (docs).
- [x] _"Run logs include `run_id` and sender (when available)"_ — Task 6 (`agent_run_start` / `agent_run_end` emit `session_id`, `sender`).
- [x] _"Sensitive fields are redacted"_ — Task 2 (email redaction in `redact()`), Task 3 (formatter runs `extra` through `redact()`), tool args via Task 5 hooks, error messages via Task 6.
- [x] _"Docs include 'trace a run' steps"_ — Task 10 (README "Trace a run end-to-end" walkthrough).

Issue tasks:
- [x] Add structured logging configuration — Task 1 + Task 3.
- [x] Add request middleware (`request_id`, `latency_ms`, route/status) — Task 4.
- [x] Emit run lifecycle logs (`start`, `tool_call`, `tool_result`, `end`, `error`) — Task 5 + Task 6.
- [x] Emit auth/security event logs — Task 8 + Task 9 (`send_blocked`).
- [x] Document log fields and tracing workflow in README — Task 10.

**2. Placeholder scan** — searched for `TBD`, `TODO`, `implement later`, `appropriate error handling`. None present. All code blocks are complete; all referenced functions are defined in the same plan.

**3. Type consistency** — `request_id_var` / `run_id_var` named consistently across Tasks 3, 4, 6, 8. `RunObservabilityHooks` named the same in Tasks 5, 6. `mask_phone` / `mask_email` consistent across Tasks 2, 8, 9.

**4. Known nuance flagged inline** — Task 8 Step 3 includes a self-correction: `auth_sub_var` was originally proposed in Task 3 but removed in Task 8 Step 4 because its lifecycle is hard to bound to a single request without an extra middleware layer. The plan reflects the simpler v1 (no `auth_sub_var`); future work can add a `BindAuthMiddleware` if desired.

**5. Scope check** — One coherent feature: structured logging + correlation IDs across the FastAPI/Agents-SDK pipeline. No subsystems to split out.

---

## Decisions still needing operator sign-off

1. **Logging library — stdlib vs structlog.** The plan picks stdlib for zero new deps and uvicorn-friendliness. structlog would buy nicer ergonomics at the cost of a top-level dependency. If sign-off is "use structlog," Tasks 3 / 4 / 5 / 6 / 8 / 9 swap formatter + filter for structlog processors; the schema and call sites are otherwise identical.
2. **Cloudflare Access email in audit logs.** The plan emits `email_hash = sha256(sub)[:16]` on `auth_login` only, with full email never written. For single-tenant deployments the operator may want the raw email on auth events — change is local to `auth.py` Task 8 Step 3.
3. **`/api/runs` overlap with stdout logs.** The plan keeps both. If the operator wants to consolidate (drop the SQLite tables or stop appending to `events.jsonl`), that's a separate follow-up — issue #10 doesn't require it.
4. **DEBUG vs INFO for `/health` and `/ready` access records.** The plan emits at INFO. `/health` is hit every minute by uptime checks and will dominate the log volume. If that's a problem on the VPS, log filter `/health` to DEBUG in Task 7. Default-INFO is the safer initial behavior.
5. **`auth_sub_var` (per-record `auth_sub_short`).** Dropped from v1 in Task 8 to avoid request-lifecycle leakage. If the operator wants every record stamped with the authenticated user, we need an extra binding hook (small middleware layer or a dependency that sets and resets a var).
