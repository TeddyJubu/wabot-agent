# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`wabot-agent` is a VPS-ready WhatsApp automation agent built on the OpenAI Agents SDK, OpenRouter (OpenAI-compatible Chat Completions), and the [`wabot`](https://github.com/TeddyJubu/wabot) daemon. It runs as a FastAPI service with a small operator dashboard and exposes a webhook for inbound WhatsApp messages.

The current SSH deployment target is the host named `vignesh` — this is the historical project name and explains the legacy `VIGNESH_*` env-var aliases that still exist alongside the canonical `WABOT_AGENT_*` ones.

## Common Commands

Dependency / environment setup uses **`uv`** (not pip):

```bash
uv sync --all-extras                      # install runtime + dev deps
cp .env.example .env                      # then edit secrets
uv run python main.py                     # run dashboard at http://127.0.0.1:8787
```

Offline checks (no credentials required — they should always pass on a fresh checkout):

```bash
uv run --with '.[dev]' ruff check .
uv run --with '.[dev]' python -m pytest -q
uv run python evals/run_local.py
```

Run a single test:

```bash
uv run --with '.[dev]' python -m pytest tests/test_tools.py::test_send_dry_run -q
```

Pytest defines two markers in `pyproject.toml`: `offline` (default, no creds) and `live` (needs real OpenRouter / `wabot`). Filter with `-m offline` or `-m "not live"`.

VPS deploy from local machine (after the VPS is bootstrapped):

```bash
SSH_HOST=vignesh ./scripts/deploy-to-vignesh.sh
```

## Architecture

The high-level flow is **operator/inbound → FastAPI → Agents SDK runner → OpenRouter model → guarded tools → local wabot daemon → WhatsApp linked device**. The model can plan and choose tools, but the Python harness owns execution; this fail-closed split is intentional and load-bearing.

Key modules in [src/wabot_agent/](src/wabot_agent/):

- [agent.py](src/wabot_agent/agent.py) — builds the `Agent[RuntimeContext]` with instructions, model, tools, and MCP servers; `run_agent()` is the single entry point used by both the chat API and the inbound webhook. Tracing is disabled globally (`set_tracing_disabled(True)`).
- [api.py](src/wabot_agent/api.py) — FastAPI app. Routes: `/health`, `/ready`, `/api/chat`, `/api/runs`, `/api/memory/{contact}`, `/api/whatsapp/pairing(.svg)`, `/api/settings` (GET/PATCH), `/api/settings/test/{openrouter,wabot}`, `/whatsapp/inbound`. Auth uses `WABOT_AGENT_OPERATOR_TOKEN` via HTTP-only same-site cookie for dashboard, or `X-Operator-Token` / `Authorization: Bearer` for direct callers. The inbound webhook checks `WABOT_INBOUND_TOKEN` separately. `/api/settings` always masks secrets in GET responses (returns `{set, preview}` records via `mask_secret()`) — raw key values never round-trip back over the wire.
- [config.py](src/wabot_agent/config.py) — Pydantic `Settings`. **Internal** settings (env, host, port, paths, send_policy, allowed_recipients, max_agent_turns, operator_token, etc.) accept both `WABOT_AGENT_*` and legacy `VIGNESH_*` via `AliasChoices` — **do not "clean up" the dual prefixes**, they're an explicit backward-compat migration aid. **External-system** settings keep the names of the systems they configure: `OPENROUTER_*` for the model provider and `WABOT_*` (e.g. `WABOT_TOKEN`, `WABOT_ENDPOINT`) for the wabot daemon — these have single aliases, no `WABOT_AGENT_` prefix and no `VIGNESH_` alias. `validate_assignment=True` is enabled so runtime mutations (via [runtime_overrides.py](src/wabot_agent/runtime_overrides.py)) are validated by Pydantic on every `setattr`.
- [runtime_overrides.py](src/wabot_agent/runtime_overrides.py) — operator-mutable settings layer on top of `.env`. Loads `data/runtime_overrides.json` at boot and applies to live `Settings`. The `/api/settings` PATCH endpoint writes here. `MUTABLE_FIELDS` is an allowlist — anything outside it is silently dropped on read/write (defends against mass-assignment via the API). `.env` remains the immutable VPS-bootstrap source of truth; overrides take precedence at runtime.
- [tools.py](src/wabot_agent/tools.py) — the narrow tool set exposed to the model: `wabot_health`, `send_whatsapp_text`, `send_whatsapp_image`, `recall_contact_memory`, `remember_contact_fact`, `recall_agent_notes`, `remember_agent_note`, `list_local_skills`, `read_local_skill`. **All send-policy and media-path enforcement lives here**, not in the prompt.
- [memory.py](src/wabot_agent/memory.py) — SQLite store for contact facts, agent notes, processed inbound IDs (idempotency), runs, and tool events. `store.db` *is* the WhatsApp linked-device identity when held by wabot; back it up, never commit it.
- [models.py](src/wabot_agent/models.py) — OpenRouter wiring through the OpenAI Python client; falls back to an offline echo model when `OPENROUTER_API_KEY` is empty or `WABOT_AGENT_OFFLINE_MODE=true`. Offline mode is intentional — the app must boot, render, and test without network creds.
- [wabot.py](src/wabot_agent/wabot.py) — thin HTTP client for the wabot daemon (`/health`, `/send`, `/send-image`, `/pairing/qr`). Includes a `FakeWabotClient` for tests/evals. The real client must hit loopback only.
- [redaction.py](src/wabot_agent/redaction.py) — applied before persisting tool results and logs. Use `redact()` / `mask_phone()` consistently.
- [mcp.py](src/wabot_agent/mcp.py), [skills.py](src/wabot_agent/skills.py) — optional MCP server connectors (configured by `WABOT_AGENT_MCP_CONFIG`) and local skill loading from `skills/<name>/SKILL.md`. Every example MCP server in [configs/mcp.example.json](configs/mcp.example.json) is disabled by default.

The Agents SDK `SQLiteSession` reuses `WABOT_AGENT_DB_PATH`, keyed by `session_id` (defaults to the sender's phone for inbound, or `"operator"` for the dashboard). Cross-contact memory leaks are prevented by this keying — preserve it.

## Safety Rules That Affect Code Changes

These constraints are non-obvious and should shape any change:

1. **Send policy is fail-closed.** Default is `dry_run`. `_is_send_allowed()` in [tools.py](src/wabot_agent/tools.py) is the single chokepoint — every new send-like tool must route through an equivalent check. `allow_all` exists but should never be the test default.
2. **Image sends are confined to `WABOT_AGENT_MEDIA_DIR`.** `_media_path_allowed()` resolves paths and rejects anything outside the media root. Don't bypass this for "convenience" features.
3. **Inbound dedup by message `id`.** The `/whatsapp/inbound` handler relies on the memory store's processed-id set; breaking that guarantee can cause duplicate replies on webhook retries.
4. **`wabot` stays on loopback** (`WABOT_HTTP_ADDR=127.0.0.1:7777`). The agent does not authenticate `wabot` requests beyond a bearer token; never expose the daemon publicly or proxy it.
5. **Never log or persist secrets.** Pass tool results through `redact()` before they hit `events.jsonl` or the DB. The agent prompt explicitly forbids asking for API keys, tokens, or session DBs — keep it that way.
6. **`store.db`, `.env`, `wabot.env`, `sends.log`, `data/*.json` are never committed** (see `.gitignore`). `store.db` is the WhatsApp linked-device identity. `data/runtime_overrides.json` holds operator-edited secrets at the same trust level as `.env`.
7. **Settings PATCH never echoes back secrets.** `GET /api/settings` returns `{set, preview}` records via `mask_secret()`. Saved values stay server-side; the UI's password inputs are intentionally blank on load — empty input means "no change."
8. **`send_policy=allow_all` requires `confirm_allow_all=true`** in the PATCH body and a UI `window.confirm()`. This is the only policy that removes the recipient guard; the explicit step is intentional friction.

## Conventions

- Python 3.12+, type hints everywhere (`from __future__ import annotations` at top of every module).
- Ruff config in `pyproject.toml`: line length 100, rules `E,F,I,UP,B`. Run `ruff check .` before committing.
- Tests use `pytest-asyncio` in `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed.
- Use the existing fixtures in [tests/conftest.py](tests/conftest.py) (`settings`, `memory`, etc.) which already wire offline mode and a temp dir; don't construct `Settings()` ad hoc in new tests.
- The eval harness ([evals/run_local.py](evals/run_local.py)) reads [evals/cases.jsonl](evals/cases.jsonl) and writes `evals/results/latest.jsonl`. Add new cases there rather than inventing a parallel harness.

## Repository Layout

```text
src/wabot_agent/   # application code (see module map above)
static/            # operator dashboard (vanilla HTML/JS)
skills/            # local agent skills as SKILL.md files
configs/           # MCP config examples (disabled by default)
deploy/systemd/    # wabot-agent.service unit
scripts/           # bootstrap-vps.sh, deploy-to-vignesh.sh, generate_diagrams.py
tests/             # offline test suite
evals/             # local eval harness + cases
docs/              # architecture diagrams + prompt notes
```
