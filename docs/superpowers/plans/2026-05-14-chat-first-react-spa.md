# Chat-first React SPA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the vanilla HTML/JS dashboard at `static/` with a chat-first Vite + React + ai-elements SPA, with generative-UI tool cards via `vercel-labs/json-render`.

**Architecture:** Single FastAPI process keeps serving `static/`. Vite builds React app from `web/` → emits to `web/dist/` → mirrored into `static/`. Server emits an optional `ui` envelope on tool-result SSE events; frontend renders four ToolCard variants. Send-policy stays fail-closed server-side; the new send-confirmation card is a transparency layer.

**Tech Stack:** Vite 5, React 18, TypeScript, Tailwind CSS, `ai-elements` (shadcn-style copy-in components), `@vercel-labs/json-render`, Zustand, Vitest. Backend stays Python 3.12 / FastAPI / OpenAI Agents SDK.

**Spec:** [docs/superpowers/specs/2026-05-14-chat-first-react-spa-design.md](../specs/2026-05-14-chat-first-react-spa-design.md)

---

## File map (full picture)

**New files (backend):**
- `src/wabot_agent/ui_envelopes.py`
- `tests/test_ui_envelopes.py`

**Modified files (backend):**
- `src/wabot_agent/agent.py` (tool_output event enrichment + small prompt addition)

**New files (frontend):**
- `web/package.json`, `web/tsconfig.json`, `web/tsconfig.node.json`
- `web/vite.config.ts`, `web/tailwind.config.ts`, `web/postcss.config.cjs`
- `web/index.html`
- `web/src/main.tsx`, `web/src/App.tsx`, `web/src/styles.css`
- `web/src/components/ai-elements/*` (output of `npx ai-elements add`)
- `web/src/components/TopBar.tsx`
- `web/src/components/StatusDot.tsx`
- `web/src/components/StatusPopover.tsx`
- `web/src/components/SlideOver.tsx`
- `web/src/components/SlashMenu.tsx`
- `web/src/components/EmptyState.tsx`
- `web/src/components/tool-cards/ToolCard.tsx`
- `web/src/components/tool-cards/WabotStatusCard.tsx`
- `web/src/components/tool-cards/PairingQrCard.tsx`
- `web/src/components/tool-cards/SendConfirmCard.tsx`
- `web/src/components/tool-cards/MemoryCard.tsx`
- `web/src/components/slide-overs/PairingPanel.tsx`
- `web/src/components/slide-overs/RunsPanel.tsx`
- `web/src/components/slide-overs/SettingsPanel.tsx`
- `web/src/hooks/useEventStream.ts`
- `web/src/hooks/useSlashCommands.ts`
- `web/src/store/index.ts`
- `web/src/api/chat.ts`
- `web/src/api/settings.ts`
- `web/src/api/pairing.ts`
- `web/src/api/runs.ts`
- `web/src/types/ui-envelope.ts`
- `web/src/__tests__/tool-cards.test.tsx`
- `web/src/__tests__/event-stream.test.ts`

**New scripts:**
- `scripts/build-web.sh`

**Modified scripts:**
- `scripts/deploy-to-vignesh.sh` (call `build-web.sh` first)

**Deleted files (after the SPA is verified):**
- `static/app.js`, `static/styles.css`, `static/index.html` (`favicon.svg` survives)

**Modified docs:**
- `CLAUDE.md` (frontend section added)
- `README.md` (build/dev commands)
- `.gitignore` (`web/node_modules`, `web/dist`)

---

## Phase A — Backend: UI envelopes

### Task A1: Pure helper `ui_envelopes.py` (TDD)

**Files:**
- Create: `tests/test_ui_envelopes.py`
- Create: `src/wabot_agent/ui_envelopes.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ui_envelopes.py
from __future__ import annotations

from wabot_agent.ui_envelopes import build_ui_envelope


def test_unknown_tool_returns_none() -> None:
    assert build_ui_envelope("not_a_tool", {"foo": 1}) is None


def test_wabot_health_ok() -> None:
    env = build_ui_envelope(
        "wabot_health",
        {"ok": True, "version": "0.4.2", "uptime_s": 8420, "last_seen_s": 3},
    )
    assert env == {
        "kind": "wabot_status",
        "data": {
            "status": "ok",
            "version": "0.4.2",
            "uptime_s": 8420,
            "last_seen_s": 3,
        },
        "actions": [
            {"id": "recheck", "label": "Recheck", "tool": "wabot_health", "args": {}}
        ],
    }


def test_wabot_health_degraded() -> None:
    env = build_ui_envelope("wabot_health", {"ok": False, "error": "connect refused"})
    assert env is not None
    assert env["kind"] == "wabot_status"
    assert env["data"]["status"] == "bad"
    assert env["data"]["error"] == "connect refused"


def test_send_text_dry_run_emits_send_confirm() -> None:
    env = build_ui_envelope(
        "send_whatsapp_text",
        {
            "policy": "dry_run",
            "to": "+15551234567",
            "body": "hello",
            "delivered": False,
        },
    )
    assert env is not None
    assert env["kind"] == "send_confirm"
    assert env["data"]["policy"] == "dry_run"
    assert env["data"]["recipient_masked"].endswith("4567")
    assert env["data"]["recipient_masked"].startswith("+1")
    assert "***" in env["data"]["recipient_masked"]
    assert env["data"]["body_preview"] == "hello"
    assert env["data"]["needs_approval"] is False


def test_send_text_allowlist_needs_approval() -> None:
    env = build_ui_envelope(
        "send_whatsapp_text",
        {"policy": "allowlist", "to": "+15551234567", "body": "x" * 200},
    )
    assert env is not None
    assert env["data"]["needs_approval"] is True
    # Body preview is truncated to 140 chars + ellipsis
    assert len(env["data"]["body_preview"]) <= 141
    assert env["data"]["body_preview"].endswith("…")
    assert [a["id"] for a in env["actions"]] == ["approve", "cancel"]


def test_recall_contact_memory_emits_memory_card() -> None:
    env = build_ui_envelope(
        "recall_contact_memory",
        {
            "contact": "+15551234567",
            "facts": [
                {"id": "f1", "text": "prefers async"},
                {"id": "f2", "text": "PT timezone"},
            ],
        },
    )
    assert env is not None
    assert env["kind"] == "memory"
    assert env["data"]["contact_masked"].endswith("4567")
    assert len(env["data"]["facts"]) == 2
    assert env["data"]["facts"][0]["text"] == "prefers async"


def test_pairing_emits_qr_card() -> None:
    # The QR-card envelope is emitted for the slash command, not a tool;
    # but the helper exposes a `pairing_qr` builder for the agent prompt path.
    env = build_ui_envelope("__pairing_qr", {"available": True, "linked_device": "iPhone"})
    assert env == {
        "kind": "pairing_qr",
        "data": {"available": True, "linked_device": "iPhone"},
        "actions": [{"id": "refresh", "label": "Refresh", "tool": "__pairing_qr", "args": {}}],
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --with '.[dev]' python -m pytest tests/test_ui_envelopes.py -v
```

Expected: all FAIL with `ModuleNotFoundError: No module named 'wabot_agent.ui_envelopes'`.

- [ ] **Step 3: Implement the helper**

```python
# src/wabot_agent/ui_envelopes.py
"""Build polished UI envelopes for tool results.

The agent's tool_output stream events carry an optional `ui` field. The
frontend reads that field and renders the matching ToolCard variant. This
module owns the mapping from (tool_name, raw_result) to the envelope shape.

Server-side construction (rather than letting the model emit UI specs) keeps
the surface area small and predictable. The model picks tools; the harness
picks the card.
"""
from __future__ import annotations

from typing import Any

_BODY_PREVIEW_MAX = 140


def _mask_recipient(value: str | None) -> str:
    """Return a phone-number-style masked tail, e.g. `+1***4567`.

    Inputs that don't look like phone numbers are returned as `***` to avoid
    leaking partial identifiers.
    """
    if not value or not isinstance(value, str):
        return "***"
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return "***"
    tail = digits[-4:]
    prefix = "+" + digits[0] if value.startswith("+") else ""
    return f"{prefix}***{tail}"


def _truncate(body: str | None, limit: int = _BODY_PREVIEW_MAX) -> str:
    if not body:
        return ""
    if len(body) <= limit:
        return body
    return body[:limit] + "…"


def _wabot_status(result: dict[str, Any]) -> dict[str, Any]:
    ok = bool(result.get("ok"))
    status = "ok" if ok else "bad"
    data: dict[str, Any] = {"status": status}
    for key in ("version", "uptime_s", "last_seen_s", "error"):
        if key in result:
            data[key] = result[key]
    return {
        "kind": "wabot_status",
        "data": data,
        "actions": [
            {"id": "recheck", "label": "Recheck", "tool": "wabot_health", "args": {}}
        ],
    }


def _send_confirm(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    policy = result.get("policy", "dry_run")
    needs_approval = policy != "dry_run" and not result.get("delivered", False)
    data: dict[str, Any] = {
        "policy": policy,
        "recipient_masked": _mask_recipient(result.get("to")),
        "body_preview": _truncate(result.get("body")),
        "needs_approval": needs_approval,
        "delivered": bool(result.get("delivered", False)),
    }
    if tool_name == "send_whatsapp_image":
        data["image_path"] = result.get("path")
        data["caption_preview"] = _truncate(result.get("caption"))
    if needs_approval:
        actions = [
            {"id": "approve", "label": "Approve", "tool": tool_name, "args": {}},
            {"id": "cancel", "label": "Cancel", "tool": None, "args": {}},
        ]
    else:
        actions = []
    return {"kind": "send_confirm", "data": data, "actions": actions}


def _memory(result: dict[str, Any]) -> dict[str, Any]:
    contact = result.get("contact")
    facts = result.get("facts") or []
    safe_facts = [
        {"id": str(f.get("id", "")), "text": str(f.get("text", ""))}
        for f in facts
        if isinstance(f, dict)
    ]
    return {
        "kind": "memory",
        "data": {
            "contact_masked": _mask_recipient(contact),
            "facts": safe_facts,
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


_BUILDERS = {
    "wabot_health": _wabot_status,
    "send_whatsapp_text": lambda r: _send_confirm("send_whatsapp_text", r),
    "send_whatsapp_image": lambda r: _send_confirm("send_whatsapp_image", r),
    "recall_contact_memory": _memory,
    "remember_contact_fact": _memory,
    "__pairing_qr": _pairing_qr,
}


def build_ui_envelope(tool_name: str, result: Any) -> dict[str, Any] | None:
    """Return an envelope dict, or None if no card applies.

    `result` must be a dict; anything else returns None so the frontend falls
    back to the plain redacted-JSON view.
    """
    if not isinstance(result, dict):
        return None
    builder = _BUILDERS.get(tool_name)
    if builder is None:
        return None
    try:
        return builder(result)
    except Exception:  # noqa: BLE001 - envelope failure must never crash the run
        return None
```

- [ ] **Step 4: Run tests, verify pass**

```bash
uv run --with '.[dev]' python -m pytest tests/test_ui_envelopes.py -v
```

Expected: all PASS.

- [ ] **Step 5: Lint & commit**

```bash
uv run --with '.[dev]' ruff check src/wabot_agent/ui_envelopes.py tests/test_ui_envelopes.py
git add src/wabot_agent/ui_envelopes.py tests/test_ui_envelopes.py
git -c commit.gpgsign=false commit -m "feat(backend): ui_envelopes helper for polished tool-result cards"
```

---

### Task A2: Wire `ui_envelopes` into tool-output events

The current `_normalize_events()` in `src/wabot_agent/agent.py` emits a thin `{"type":"tool_result","ok":...,"call_id":...}`. We need it to also (a) carry the redacted tool output and (b) optionally include the `ui` envelope.

**Files:**
- Modify: `src/wabot_agent/agent.py`
- Modify: `tests/test_agent_events.py` (create if missing — add a focused test)

- [ ] **Step 1: Inspect current event-normalization region**

Open `src/wabot_agent/agent.py` lines 280-310 to confirm shape. The `_normalize_events` function returns a list of payload dicts.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_agent_events.py  (append if file exists, else create)
from __future__ import annotations

from typing import Any

from wabot_agent.agent import _normalize_events  # type: ignore[attr-defined]


class _Item:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _Event:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_tool_output_event_includes_ui_envelope_when_known(monkeypatch: Any) -> None:
    # Simulate a tool_called event followed by a tool_output for wabot_health.
    call_event = _Event(
        type="run_item_stream_event",
        name="tool_called",
        item=_Item(
            tool_name="wabot_health",
            raw_item={"arguments": "{}"},
            call_id="call_1",
        ),
    )
    out_event = _Event(
        type="run_item_stream_event",
        name="tool_output",
        item=_Item(
            call_id="call_1",
            output={"ok": True, "version": "0.4.2", "uptime_s": 10, "last_seen_s": 1},
        ),
    )
    state: dict[str, str] = {}
    a = _normalize_events(call_event, state)
    b = _normalize_events(out_event, state)
    assert a[0]["type"] == "tool_call"
    assert b[0]["type"] == "tool_result"
    assert b[0]["ui"]["kind"] == "wabot_status"
    assert b[0]["ui"]["data"]["status"] == "ok"
```

- [ ] **Step 3: Run test, verify it fails**

```bash
uv run --with '.[dev]' python -m pytest tests/test_agent_events.py::test_tool_output_event_includes_ui_envelope_when_known -v
```

Expected: FAIL — either because `_normalize_events` doesn't accept a state dict yet or because no `ui` key is emitted.

- [ ] **Step 4: Modify `_normalize_events` to thread state and emit `ui`**

Open `src/wabot_agent/agent.py`. Locate the `_normalize_events` function (around line 260). Replace its signature and tool-call/tool-output branches:

```python
# add at the top of the file, with existing imports
from .redaction import redact
from .ui_envelopes import build_ui_envelope


def _normalize_events(event: Any, state: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Translate Agents-SDK stream events into the dashboard wire format.

    `state` maps call_id → tool_name across successive events of a single run,
    so tool_output events can attach the correct UI envelope. Callers that
    don't care about UI envelopes can omit it.
    """
    if state is None:
        state = {}
    out: list[dict[str, Any]] = []
    etype = getattr(event, "type", None)
    # ... existing response.output_text.delta branch unchanged ...
```

Then in the `tool_called` branch (currently around line 287), after building `payload`, record the call_id → tool_name mapping:

```python
        if name == "tool_called" and item is not None:
            tool_name = getattr(item, "tool_name", None) or "<unknown>"
            raw = getattr(item, "raw_item", None)
            args = _extract_tool_args(raw)
            payload: dict[str, Any] = {
                "type": "tool_call",
                "name": str(tool_name),
                "args_redacted": redact(args) if args is not None else None,
            }
            call_id = getattr(item, "call_id", None)
            if call_id:
                payload["call_id"] = str(call_id)
                state[str(call_id)] = str(tool_name)
            out.append(payload)
```

And in the `tool_output` branch, look up the tool name, extract the output, and attach `ui`:

```python
        elif name == "tool_output" and item is not None:
            call_id = getattr(item, "call_id", None)
            tool_name = state.get(str(call_id)) if call_id else None
            raw_output = getattr(item, "output", None)
            redacted_output = redact(raw_output) if isinstance(raw_output, (dict, list)) else raw_output
            payload2: dict[str, Any] = {
                "type": "tool_result",
                "ok": _tool_output_ok(item),
            }
            if call_id:
                payload2["call_id"] = str(call_id)
            if tool_name:
                payload2["name"] = tool_name
            if isinstance(raw_output, dict):
                envelope = build_ui_envelope(tool_name or "", raw_output)
                if envelope is not None:
                    payload2["ui"] = envelope
            # Always include the redacted raw output for fallback rendering.
            if redacted_output is not None:
                payload2["result"] = redacted_output
            out.append(payload2)
        return out
```

- [ ] **Step 5: Update the call site to thread `state`**

Locate the caller of `_normalize_events` (the `run_agent` async loop). It iterates the agent stream once per event. Initialize a `state = {}` dict once per `run_agent` invocation and pass it on every call:

```python
# search for "for event in result.stream_events()" or similar in run_agent
        state: dict[str, str] = {}
        async for event in result.stream_events():
            for payload in _normalize_events(event, state):
                ...
```

If the actual loop body uses a sync iterator helper, apply the same pattern there.

- [ ] **Step 6: Run the new test + the offline suite, verify pass**

```bash
uv run --with '.[dev]' python -m pytest tests/test_agent_events.py -v
uv run --with '.[dev]' python -m pytest -m offline -q
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/wabot_agent/agent.py tests/test_agent_events.py
git -c commit.gpgsign=false commit -m "feat(backend): attach ui envelope + redacted result to tool_output events"
```

---

### Task A3: Prompt update for `send_confirm` approval flow

The model needs to know to pause for operator confirmation when send-policy != dry_run.

**Files:**
- Modify: `src/wabot_agent/agent.py` (instructions string)

- [ ] **Step 1: Locate the instructions string**

Open `src/wabot_agent/agent.py` and find the `instructions = """..."""` block (top-of-file constant). It already lists the fail-closed rule.

- [ ] **Step 2: Append a paragraph**

Add (inside the existing instructions string, after the fail-closed rule):

```
- For any send_whatsapp_text or send_whatsapp_image call when the active
  send_policy is not dry_run, you MUST first reply with a brief one-line
  explanation of the intended send (recipient + a short summary) and stop.
  Wait for the operator to reply with "approved" before invoking the send
  tool. If the operator declines or doesn't approve, do not send.
- The frontend renders a confirmation card from your tool result; do not
  describe the JSON of the card to the user.
```

- [ ] **Step 3: Run the offline suite to confirm no regression**

```bash
uv run --with '.[dev]' python -m pytest -m offline -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/wabot_agent/agent.py
git -c commit.gpgsign=false commit -m "feat(agent): instruct model to pause before non-dry-run sends"
```

---

## Phase B — Frontend scaffolding

### Task B1: Initialize Vite + React + TS + Tailwind in `web/`

**Files:**
- Create: `web/package.json`, `web/tsconfig.json`, `web/tsconfig.node.json`, `web/vite.config.ts`
- Create: `web/index.html`, `web/postcss.config.cjs`, `web/tailwind.config.ts`
- Create: `web/src/main.tsx`, `web/src/App.tsx`, `web/src/styles.css`
- Modify: `.gitignore`

- [ ] **Step 1: Create `web/package.json`**

```json
{
  "name": "wabot-agent-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@vercel-labs/json-render": "^0.1.0",
    "clsx": "^2.1.0",
    "lucide-react": "^0.428.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zustand": "^4.5.4"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.8",
    "@testing-library/react": "^16.0.0",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.19",
    "jsdom": "^24.1.0",
    "postcss": "^8.4.39",
    "tailwindcss": "^3.4.7",
    "typescript": "^5.5.4",
    "vite": "^5.4.0",
    "vitest": "^2.0.5"
  }
}
```

> If `@vercel-labs/json-render` is unavailable on the npm registry under that exact name, fall back to copying the source from `https://github.com/vercel-labs/json-render` into `web/src/lib/json-render/` and adjust imports. The component contract used in this plan: `<JsonRender schema={...} data={...} />`.

- [ ] **Step 2: Create `web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "resolveJsonModule": true,
    "allowImportingTsExtensions": false,
    "verbatimModuleSyntax": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"],
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 3: Create `web/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 4: Create `web/vite.config.ts`**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  base: "/static/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8787",
      "/whatsapp": "http://127.0.0.1:8787",
      "/health": "http://127.0.0.1:8787",
      "/ready": "http://127.0.0.1:8787",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.ts"],
  },
});
```

- [ ] **Step 5: Create `web/tailwind.config.ts`**

```ts
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: { app: "hsl(var(--bg-app))", card: "hsl(var(--bg-card))" },
        fg: { DEFAULT: "hsl(var(--fg-default))", muted: "hsl(var(--fg-muted))" },
        border: "hsl(var(--border))",
        accent: { DEFAULT: "hsl(var(--accent))", fg: "hsl(var(--accent-fg))" },
        ok: "hsl(var(--ok))",
        warn: "hsl(var(--warn))",
        bad: "hsl(var(--bad))",
      },
      fontFamily: {
        sans: ["Geist Sans", "Inter", "system-ui", "sans-serif"],
        mono: ["Geist Mono", "ui-monospace", "monospace"],
      },
      borderRadius: { card: "16px", pill: "999px" },
      boxShadow: { sm: "0 1px 2px rgba(15,17,21,0.04)" },
      transitionTimingFunction: { out: "cubic-bezier(0.22, 1, 0.36, 1)" },
    },
  },
  plugins: [],
} satisfies Config;
```

- [ ] **Step 6: Create `web/postcss.config.cjs`**

```js
module.exports = {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
```

- [ ] **Step 7: Create `web/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="color-scheme" content="light dark" />
    <title>wabot-agent</title>
    <link rel="icon" href="/static/favicon.svg" type="image/svg+xml" />
  </head>
  <body class="bg-bg-app text-fg font-sans">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 8: Create `web/src/styles.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --bg-app: 60 12% 97%;
  --bg-card: 0 0% 100%;
  --fg-default: 222 17% 9%;
  --fg-muted: 225 5% 41%;
  --border: 222 17% 9% / 0.08;
  --accent: 262 83% 58%;
  --accent-fg: 0 0% 100%;
  --ok: 160 84% 39%;
  --warn: 38 92% 50%;
  --bad: 0 84% 60%;
}

.dark {
  --bg-app: 222 17% 8%;
  --bg-card: 222 17% 12%;
  --fg-default: 226 15% 91%;
  --fg-muted: 222 8% 64%;
  --border: 0 0% 100% / 0.08;
  --accent: 262 83% 65%;
  --accent-fg: 0 0% 100%;
  --ok: 160 84% 45%;
  --warn: 38 92% 55%;
  --bad: 0 84% 65%;
}

html, body, #root { height: 100%; }
body { font-feature-settings: "cv11", "ss01"; }

@keyframes shimmer {
  0% { opacity: 0.55; }
  50% { opacity: 1; }
  100% { opacity: 0.55; }
}
.shimmer { animation: shimmer 1.4s ease-in-out infinite; }
```

- [ ] **Step 9: Create `web/src/main.tsx`**

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 10: Create `web/src/App.tsx` (placeholder)**

```tsx
export default function App() {
  return (
    <div className="grid min-h-full place-items-center">
      <p className="text-fg-muted">wabot-agent — loading…</p>
    </div>
  );
}
```

- [ ] **Step 11: Update `.gitignore`**

Append:

```
web/node_modules/
web/dist/
web/.vite/
```

- [ ] **Step 12: Install + build smoke test**

```bash
cd web && npm install && npm run build && cd ..
```

Expected: `web/dist/index.html`, `web/dist/assets/*.js`, `web/dist/assets/*.css` exist. The `npm install` may warn about peer dependencies — that's fine, the build is the gate.

- [ ] **Step 13: Commit**

```bash
git add web/package.json web/package-lock.json web/tsconfig.json web/tsconfig.node.json web/vite.config.ts web/tailwind.config.ts web/postcss.config.cjs web/index.html web/src/main.tsx web/src/App.tsx web/src/styles.css .gitignore
git -c commit.gpgsign=false commit -m "feat(web): bootstrap Vite + React + Tailwind in web/"
```

---

### Task B2: Build script + serve from `static/`

**Files:**
- Create: `scripts/build-web.sh`
- Modify: `scripts/deploy-to-vignesh.sh`

- [ ] **Step 1: Create `scripts/build-web.sh`**

```bash
#!/usr/bin/env bash
# Build the React SPA in web/ and mirror the output into static/.
# FastAPI serves static/ at /static/*; index.html is also served at /.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d web ]]; then
  echo "web/ not found" >&2; exit 1
fi

pushd web >/dev/null
if [[ ! -d node_modules ]] || [[ package-lock.json -nt node_modules ]]; then
  npm ci
fi
npm run build
popd >/dev/null

# Preserve favicon.svg; mirror everything else.
mkdir -p static
find static -mindepth 1 ! -name favicon.svg -delete
cp -R web/dist/. static/
echo "static/ updated from web/dist/"
```

Make executable:

```bash
chmod +x scripts/build-web.sh
```

- [ ] **Step 2: Verify the script works**

```bash
./scripts/build-web.sh
ls -la static/
```

Expected: `static/index.html`, `static/assets/*.js`, `static/assets/*.css`, `static/favicon.svg`.

- [ ] **Step 3: Wire into `scripts/deploy-to-vignesh.sh`**

Open `scripts/deploy-to-vignesh.sh` and add near the top, right after the safety checks but before any rsync:

```bash
# Build the SPA before shipping
"$(dirname "$0")/build-web.sh"
```

- [ ] **Step 4: Commit**

```bash
git add scripts/build-web.sh scripts/deploy-to-vignesh.sh static/
git -c commit.gpgsign=false commit -m "build(web): static/ now sourced from web/dist via build-web.sh"
```

---

## Phase C — ai-elements + tool cards

### Task C1: Add ai-elements components

**Files:**
- Create: `web/src/components/ai-elements/*` (via CLI)

- [ ] **Step 1: Run the ai-elements CLI**

```bash
cd web && npx ai-elements@latest add conversation message prompt-input reasoning actions loader suggestion
```

If the CLI prompts for a components dir, choose `src/components/ai-elements`. If it prompts for shadcn primitives (button, scroll-area, etc.), accept the defaults — these get copied alongside.

If `npx ai-elements` is not available under that exact package name, the alternative install path is shadcn-ui pulling from the Vercel registry; the components are documented at `https://ai-sdk.dev/elements`. Use one of: `npx shadcn@latest add https://elements.vercel.com/r/conversation.json` (one per component). Either way the result should be a folder `web/src/components/ai-elements/` exporting the listed component names.

- [ ] **Step 2: Verify imports work**

Create a throwaway check by editing `web/src/App.tsx`:

```tsx
import { Conversation, Message, MessageContent } from "@/components/ai-elements/conversation";
import { PromptInput, PromptInputTextarea, PromptInputSubmit } from "@/components/ai-elements/prompt-input";

export default function App() {
  return (
    <div className="grid min-h-full place-items-center p-6">
      <div className="w-full max-w-[720px]">
        <Conversation>
          <Message from="assistant">
            <MessageContent>hello, operator</MessageContent>
          </Message>
        </Conversation>
        <PromptInput>
          <PromptInputTextarea placeholder="Message wabot-agent…" />
          <PromptInputSubmit />
        </PromptInput>
      </div>
    </div>
  );
}
```

```bash
cd web && npm run build
```

Expected: success, no module-not-found errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/ai-elements web/src/App.tsx web/package.json web/package-lock.json
git -c commit.gpgsign=false commit -m "feat(web): scaffold ai-elements components (conversation, prompt-input, etc.)"
```

---

### Task C2: UI-envelope types & ToolCard shell

**Files:**
- Create: `web/src/types/ui-envelope.ts`
- Create: `web/src/components/tool-cards/ToolCard.tsx`

- [ ] **Step 1: Create `web/src/types/ui-envelope.ts`**

```ts
export type ToolKind =
  | "wabot_status"
  | "pairing_qr"
  | "send_confirm"
  | "memory";

export interface ToolAction {
  id: string;
  label: string;
  tool: string | null;
  args: Record<string, unknown>;
}

export interface UiEnvelope {
  kind: ToolKind;
  data: Record<string, unknown>;
  actions: ToolAction[];
}

export interface WabotStatusData {
  status: "ok" | "warn" | "bad";
  version?: string;
  uptime_s?: number;
  last_seen_s?: number;
  error?: string;
}

export interface PairingQrData {
  available: boolean;
  linked_device?: string | null;
}

export interface SendConfirmData {
  policy: "dry_run" | "allowlist" | "allow_all";
  recipient_masked: string;
  body_preview: string;
  needs_approval: boolean;
  delivered: boolean;
  image_path?: string;
  caption_preview?: string;
}

export interface MemoryFact {
  id: string;
  text: string;
}

export interface MemoryData {
  contact_masked: string;
  facts: MemoryFact[];
}
```

- [ ] **Step 2: Create `web/src/components/tool-cards/ToolCard.tsx`**

```tsx
import type { UiEnvelope } from "@/types/ui-envelope";
import WabotStatusCard from "./WabotStatusCard";
import PairingQrCard from "./PairingQrCard";
import SendConfirmCard from "./SendConfirmCard";
import MemoryCard from "./MemoryCard";

interface Props {
  envelope: UiEnvelope;
  onAction: (actionId: string) => void;
}

export default function ToolCard({ envelope, onAction }: Props) {
  switch (envelope.kind) {
    case "wabot_status":
      return <WabotStatusCard data={envelope.data as never} actions={envelope.actions} onAction={onAction} />;
    case "pairing_qr":
      return <PairingQrCard data={envelope.data as never} actions={envelope.actions} onAction={onAction} />;
    case "send_confirm":
      return <SendConfirmCard data={envelope.data as never} actions={envelope.actions} onAction={onAction} />;
    case "memory":
      return <MemoryCard data={envelope.data as never} actions={envelope.actions} onAction={onAction} />;
    default:
      return null;
  }
}
```

- [ ] **Step 3: Build smoke check**

```bash
cd web && npm run build
```

Expected: build fails with "Cannot find module './WabotStatusCard'" — that's fine, we add them next. (If you want a clean build now, comment out the imports temporarily; restore in next task.)

- [ ] **Step 4: Commit (after C3-C6 land — leave uncommitted for now or use --allow-empty)**

Skip commit until the four child components exist. Move to C3.

---

### Task C3: `WabotStatusCard`

**Files:**
- Create: `web/src/components/tool-cards/WabotStatusCard.tsx`

- [ ] **Step 1: Create the component**

```tsx
import { CheckCircle2, AlertCircle, XCircle, RefreshCw } from "lucide-react";
import type { ToolAction, WabotStatusData } from "@/types/ui-envelope";

interface Props {
  data: WabotStatusData;
  actions: ToolAction[];
  onAction: (id: string) => void;
}

const ICONS: Record<WabotStatusData["status"], typeof CheckCircle2> = {
  ok: CheckCircle2,
  warn: AlertCircle,
  bad: XCircle,
};

const COLORS: Record<WabotStatusData["status"], string> = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
};

function fmtUptime(seconds?: number): string {
  if (!seconds || seconds < 0) return "—";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export default function WabotStatusCard({ data, actions, onAction }: Props) {
  const Icon = ICONS[data.status];
  return (
    <div className="rounded-card border border-border bg-bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <Icon className={`mt-0.5 size-5 ${COLORS[data.status]}`} aria-hidden />
        <div className="flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-medium">wabot daemon</h3>
            <span className="font-mono text-xs text-fg-muted">{data.version ?? "—"}</span>
          </div>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-fg-muted">
            <div><dt className="inline">uptime </dt><dd className="inline font-mono text-fg">{fmtUptime(data.uptime_s)}</dd></div>
            <div><dt className="inline">last seen </dt><dd className="inline font-mono text-fg">{data.last_seen_s ?? "—"}s ago</dd></div>
          </dl>
          {data.error && <p className="mt-2 text-xs text-bad">{data.error}</p>}
          {actions.length > 0 && (
            <div className="mt-3 flex gap-2">
              {actions.map((a) => (
                <button
                  key={a.id}
                  onClick={() => onAction(a.id)}
                  className="inline-flex items-center gap-1.5 rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app"
                >
                  <RefreshCw className="size-3" aria-hidden /> {a.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

---

### Task C4: `PairingQrCard`

**Files:**
- Create: `web/src/components/tool-cards/PairingQrCard.tsx`

- [ ] **Step 1: Create the component**

```tsx
import { useState } from "react";
import { RefreshCw, Smartphone } from "lucide-react";
import type { ToolAction, PairingQrData } from "@/types/ui-envelope";

interface Props {
  data: PairingQrData;
  actions: ToolAction[];
  onAction: (id: string) => void;
}

export default function PairingQrCard({ data, actions, onAction }: Props) {
  const [bust, setBust] = useState(0);
  const src = data.available ? `/api/whatsapp/pairing.svg?b=${bust}` : null;
  return (
    <div className="rounded-card border border-border bg-bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <Smartphone className="mt-0.5 size-5 text-accent" aria-hidden />
        <div className="flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-medium">WhatsApp pairing</h3>
            <span className="text-xs text-fg-muted">{data.linked_device ?? "not linked"}</span>
          </div>
          <div className="mt-3 grid place-items-center rounded-card bg-bg-app p-4">
            {src ? (
              <img src={src} alt="WhatsApp pairing QR code" className="size-48 [image-rendering:pixelated]" />
            ) : (
              <p className="text-xs text-fg-muted">No QR available right now.</p>
            )}
          </div>
          {actions.length > 0 && (
            <div className="mt-3 flex gap-2">
              {actions.map((a) => (
                <button
                  key={a.id}
                  onClick={() => { setBust((b) => b + 1); onAction(a.id); }}
                  className="inline-flex items-center gap-1.5 rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app"
                >
                  <RefreshCw className="size-3" aria-hidden /> {a.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

---

### Task C5: `SendConfirmCard` — client-side approve loop

**Files:**
- Create: `web/src/components/tool-cards/SendConfirmCard.tsx`

- [ ] **Step 1: Create the component**

```tsx
import { Send, Image as ImageIcon, ShieldAlert } from "lucide-react";
import type { ToolAction, SendConfirmData } from "@/types/ui-envelope";

interface Props {
  data: SendConfirmData;
  actions: ToolAction[];
  onAction: (id: string) => void;
}

const POLICY_LABEL: Record<SendConfirmData["policy"], string> = {
  dry_run: "Dry run",
  allowlist: "Allowlisted",
  allow_all: "Allow all",
};

export default function SendConfirmCard({ data, actions, onAction }: Props) {
  const isImage = Boolean(data.image_path);
  const Icon = isImage ? ImageIcon : Send;
  const policyTone =
    data.policy === "allow_all" ? "text-warn" :
    data.policy === "dry_run" ? "text-fg-muted" : "text-accent";

  return (
    <div className="rounded-card border border-border bg-bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 size-5 text-accent" aria-hidden />
        <div className="flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-medium">
              {data.delivered ? "Sent" : data.needs_approval ? "Awaiting your approval" : "Send drafted"}
            </h3>
            <span className={`text-xs ${policyTone}`}>{POLICY_LABEL[data.policy]}</span>
          </div>
          <p className="mt-1 font-mono text-xs text-fg-muted">to {data.recipient_masked}</p>
          <p className="mt-2 whitespace-pre-wrap rounded-lg bg-bg-app p-2.5 text-sm">
            {isImage ? <em className="text-fg-muted">[image] </em> : null}
            {data.body_preview || data.caption_preview || <span className="text-fg-muted">(no body)</span>}
          </p>
          {data.policy === "allow_all" && data.needs_approval && (
            <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-warn">
              <ShieldAlert className="size-3.5" aria-hidden /> Allow-all bypasses the recipient guard.
            </p>
          )}
          {actions.length > 0 && (
            <div className="mt-3 flex gap-2">
              {actions.map((a) => (
                <button
                  key={a.id}
                  onClick={() => onAction(a.id)}
                  className={
                    a.id === "approve"
                      ? "rounded-pill bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg hover:opacity-90"
                      : "rounded-pill border border-border px-3 py-1.5 text-xs hover:bg-bg-app"
                  }
                >
                  {a.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

---

### Task C6: `MemoryCard`

**Files:**
- Create: `web/src/components/tool-cards/MemoryCard.tsx`

- [ ] **Step 1: Create the component**

```tsx
import { Brain } from "lucide-react";
import type { ToolAction, MemoryData } from "@/types/ui-envelope";

interface Props {
  data: MemoryData;
  actions: ToolAction[];
  onAction: (id: string) => void;
}

export default function MemoryCard({ data, actions, onAction }: Props) {
  return (
    <div className="rounded-card border border-border bg-bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <Brain className="mt-0.5 size-5 text-accent" aria-hidden />
        <div className="flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-medium">Contact memory</h3>
            <span className="font-mono text-xs text-fg-muted">{data.contact_masked}</span>
          </div>
          {data.facts.length === 0 ? (
            <p className="mt-2 text-xs text-fg-muted">No facts recorded yet.</p>
          ) : (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {data.facts.map((f) => (
                <li
                  key={f.id}
                  className="rounded-pill border border-border bg-bg-app px-2.5 py-1 text-xs"
                >
                  {f.text}
                </li>
              ))}
            </ul>
          )}
          {actions.length > 0 && (
            <div className="mt-3 flex gap-2">
              {actions.map((a) => (
                <button
                  key={a.id}
                  onClick={() => onAction(a.id)}
                  className="rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app"
                >
                  {a.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build smoke check for Phase C**

```bash
cd web && npm run build
```

Expected: build passes.

- [ ] **Step 3: Commit Phase C**

```bash
git add web/src/types web/src/components/tool-cards
git -c commit.gpgsign=false commit -m "feat(web): ToolCard variants (wabot_status, pairing_qr, send_confirm, memory)"
```

---

## Phase D — Shell components

### Task D1: `StatusDot`, `TopBar`, `StatusPopover`

**Files:**
- Create: `web/src/components/StatusDot.tsx`
- Create: `web/src/components/TopBar.tsx`
- Create: `web/src/components/StatusPopover.tsx`

- [ ] **Step 1: `StatusDot`**

```tsx
// web/src/components/StatusDot.tsx
import { clsx } from "clsx";

type Variant = "ok" | "warn" | "bad" | "pending";

const TONE: Record<Variant, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  pending: "bg-fg-muted",
};

export default function StatusDot({ variant, className, animated = true }: {
  variant: Variant;
  className?: string;
  animated?: boolean;
}) {
  return (
    <span className={clsx("relative inline-flex size-2 items-center justify-center", className)} aria-hidden>
      <span className={clsx("absolute inline-flex size-2 rounded-full", TONE[variant], animated && variant === "ok" && "shimmer")} />
    </span>
  );
}
```

- [ ] **Step 2: `StatusPopover`**

```tsx
// web/src/components/StatusPopover.tsx
import { useStore } from "@/store";
import StatusDot from "./StatusDot";

export default function StatusPopover({ onClose }: { onClose: () => void }) {
  const readiness = useStore((s) => s.readiness);

  return (
    <div
      className="absolute left-0 top-full mt-2 w-72 rounded-card border border-border bg-bg-card p-3 shadow-sm"
      onMouseLeave={onClose}
    >
      <ul className="divide-y divide-border">
        <Row label="Model" value={readiness.model.label} variant={readiness.model.variant} />
        <Row label="wabot" value={readiness.wabot.label} variant={readiness.wabot.variant} />
        <Row label="Send policy" value={readiness.policy.label} variant={readiness.policy.variant} />
        <Row label="Memory" value={readiness.memory.label} variant={readiness.memory.variant} />
      </ul>
    </div>
  );
}

function Row({ label, value, variant }: { label: string; value: string; variant: "ok" | "warn" | "bad" | "pending" }) {
  return (
    <li className="flex items-center justify-between py-2 text-xs">
      <span className="text-fg-muted">{label}</span>
      <span className="inline-flex items-center gap-2"><StatusDot variant={variant} /> <span>{value}</span></span>
    </li>
  );
}
```

- [ ] **Step 3: `TopBar`**

```tsx
// web/src/components/TopBar.tsx
import { useState } from "react";
import { Smartphone, Clock, Settings } from "lucide-react";
import StatusDot from "./StatusDot";
import StatusPopover from "./StatusPopover";
import { useStore } from "@/store";

export default function TopBar() {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const open = useStore((s) => s.openSlideOver);
  const overall = useStore((s) => s.readiness.overall);

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-bg-app/80 px-4 backdrop-blur">
      <div className="relative">
        <button
          onClick={() => setPopoverOpen((o) => !o)}
          className="inline-flex items-center gap-2 font-medium tracking-tight"
          aria-haspopup="dialog"
          aria-expanded={popoverOpen}
        >
          <span>wabot-agent</span>
          <StatusDot variant={overall} />
        </button>
        {popoverOpen && <StatusPopover onClose={() => setPopoverOpen(false)} />}
      </div>
      <nav className="flex items-center gap-1" aria-label="Workspace">
        <IconBtn onClick={() => open("qr")} label="WhatsApp pairing"><Smartphone className="size-4" /></IconBtn>
        <IconBtn onClick={() => open("runs")} label="Runs history"><Clock className="size-4" /></IconBtn>
        <IconBtn onClick={() => open("settings")} label="Settings"><Settings className="size-4" /></IconBtn>
      </nav>
    </header>
  );
}

function IconBtn({ children, onClick, label }: { children: React.ReactNode; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className="grid size-9 place-items-center rounded-pill text-fg-muted hover:bg-bg-card hover:text-fg"
    >
      {children}
    </button>
  );
}
```

---

### Task D2: `SlideOver` primitive + three panels

**Files:**
- Create: `web/src/components/SlideOver.tsx`
- Create: `web/src/components/slide-overs/PairingPanel.tsx`
- Create: `web/src/components/slide-overs/RunsPanel.tsx`
- Create: `web/src/components/slide-overs/SettingsPanel.tsx`

- [ ] **Step 1: `SlideOver` primitive**

```tsx
// web/src/components/SlideOver.tsx
import { useEffect } from "react";
import { X } from "lucide-react";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}

export default function SlideOver({ open, onClose, title, children }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <div aria-hidden={!open} className="pointer-events-none fixed inset-0 z-40">
      <div
        className={`absolute inset-0 bg-fg/20 transition-opacity duration-200 ease-out ${open ? "opacity-100 pointer-events-auto" : "opacity-0"}`}
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-label={title}
        className={`pointer-events-auto absolute right-0 top-0 h-full w-[420px] max-w-[92vw] border-l border-border bg-bg-card shadow-sm transition-transform duration-200 ease-out ${open ? "translate-x-0" : "translate-x-full"}`}
      >
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-medium">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="grid size-8 place-items-center rounded-pill text-fg-muted hover:bg-bg-app hover:text-fg">
            <X className="size-4" />
          </button>
        </header>
        <div className="h-[calc(100%-49px)] overflow-y-auto p-4">{children}</div>
      </aside>
    </div>
  );
}
```

- [ ] **Step 2: `PairingPanel`** — wraps `PairingQrCard` with a fetched envelope

```tsx
// web/src/components/slide-overs/PairingPanel.tsx
import { useEffect, useState } from "react";
import PairingQrCard from "../tool-cards/PairingQrCard";
import { fetchPairing } from "@/api/pairing";

export default function PairingPanel() {
  const [available, setAvailable] = useState<boolean>(false);
  const [device, setDevice] = useState<string | null>(null);

  const reload = () => fetchPairing().then((p) => {
    setAvailable(p.available);
    setDevice(p.linked_device ?? null);
  });

  useEffect(() => { reload(); }, []);

  return (
    <PairingQrCard
      data={{ available, linked_device: device }}
      actions={[{ id: "refresh", label: "Refresh", tool: "__pairing_qr", args: {} }]}
      onAction={() => { void reload(); }}
    />
  );
}
```

- [ ] **Step 3: `RunsPanel`**

```tsx
// web/src/components/slide-overs/RunsPanel.tsx
import { useEffect, useState } from "react";
import { fetchRuns, type Run } from "@/api/runs";

export default function RunsPanel() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchRuns().then((r) => { setRuns(r); setLoading(false); });
  }, []);

  if (loading) return <p className="text-xs text-fg-muted">Loading runs…</p>;
  if (runs.length === 0) return <p className="text-xs text-fg-muted">No runs yet.</p>;

  return (
    <ul className="space-y-2">
      {runs.map((r) => (
        <li key={r.id} className="rounded-card border border-border p-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-mono text-fg-muted">{r.id.slice(0, 8)}</span>
            <span className="text-fg-muted">{new Date(r.started_at).toLocaleTimeString()}</span>
          </div>
          <p className="mt-1 truncate text-sm">{r.summary ?? "(no summary)"}</p>
          {r.tool_count != null && (
            <p className="mt-1 text-xs text-fg-muted">{r.tool_count} tool call{r.tool_count === 1 ? "" : "s"}</p>
          )}
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 4: `SettingsPanel`** — straight port of today's form

```tsx
// web/src/components/slide-overs/SettingsPanel.tsx
import { useEffect, useState } from "react";
import { fetchSettings, patchSettings, type SettingsView } from "@/api/settings";

export default function SettingsPanel() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [policy, setPolicy] = useState<"dry_run" | "allowlist" | "allow_all">("dry_run");
  const [recipients, setRecipients] = useState<string>("");
  const [status, setStatus] = useState<string>("");

  useEffect(() => {
    fetchSettings().then((v) => {
      setView(v);
      setPolicy(v.send_policy);
      setRecipients(v.allowed_recipients.join(", "));
    });
  }, []);

  if (!view) return <p className="text-xs text-fg-muted">Loading…</p>;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus("Saving…");
    const body: Record<string, unknown> = { send_policy: policy };
    if (recipients !== view.allowed_recipients.join(", ")) {
      body.allowed_recipients = recipients.split(/[,\n]+/).map((s) => s.trim()).filter(Boolean);
    }
    for (const [key, value] of Object.entries(draft)) {
      if (value !== "") body[key] = value;
    }
    if (policy === "allow_all") body.confirm_allow_all = true;
    try {
      await patchSettings(body);
      setStatus("Saved.");
      setDraft({});
    } catch (err) {
      setStatus(`Error: ${String(err)}`);
    }
  };

  return (
    <form className="space-y-4" onSubmit={submit}>
      <fieldset className="space-y-2">
        <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">OpenRouter</legend>
        <Field label="API key" type="password" placeholder={view.openrouter_api_key.preview ?? "sk-or-…"}
               onChange={(v) => setDraft({ ...draft, openrouter_api_key: v })} />
        <Field label="Model" defaultValue={view.openrouter_model.preview ?? ""}
               onChange={(v) => setDraft({ ...draft, openrouter_model: v })} />
        <Field label="Base URL" defaultValue={view.openrouter_base_url.preview ?? ""}
               onChange={(v) => setDraft({ ...draft, openrouter_base_url: v })} />
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">wabot</legend>
        <Field label="Endpoint" defaultValue={view.wabot_endpoint.preview ?? ""}
               onChange={(v) => setDraft({ ...draft, wabot_endpoint: v })} />
        <Field label="Token" type="password" placeholder={view.wabot_token.preview ?? ""}
               onChange={(v) => setDraft({ ...draft, wabot_token: v })} />
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">Send policy</legend>
        <div className="flex flex-wrap gap-2">
          {(["dry_run", "allowlist", "allow_all"] as const).map((p) => (
            <label key={p} className={`cursor-pointer rounded-pill border px-2.5 py-1 text-xs ${policy === p ? "border-accent bg-accent/10 text-accent" : "border-border"}`}>
              <input type="radio" name="policy" className="sr-only" checked={policy === p}
                     onChange={() => {
                       if (p === "allow_all" && !window.confirm("Allow-all removes the recipient guard. Continue?")) return;
                       setPolicy(p);
                     }} />
              {p}
            </label>
          ))}
        </div>
        <label className="block">
          <span className="text-xs text-fg-muted">Allowed recipients</span>
          <textarea
            rows={3}
            value={recipients}
            onChange={(e) => setRecipients(e.target.value)}
            placeholder="+15550001111, +15550002222"
            className="mt-1 w-full rounded-card border border-border bg-bg-card px-3 py-2 text-sm font-mono"
          />
        </label>
      </fieldset>

      <div className="flex items-center justify-between">
        <span className="text-xs text-fg-muted">{status}</span>
        <button type="submit" className="rounded-pill bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg hover:opacity-90">
          Save changes
        </button>
      </div>
    </form>
  );
}

function Field({ label, defaultValue, placeholder, type = "text", onChange }: {
  label: string; defaultValue?: string; placeholder?: string; type?: string; onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="text-xs text-fg-muted">{label}</span>
      <input
        type={type}
        defaultValue={defaultValue}
        placeholder={placeholder}
        autoComplete="off"
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-card border border-border bg-bg-card px-3 py-2 text-sm font-mono"
      />
    </label>
  );
}
```

---

### Task D3: `SlashMenu`

**Files:**
- Create: `web/src/hooks/useSlashCommands.ts`
- Create: `web/src/components/SlashMenu.tsx`

- [ ] **Step 1: `useSlashCommands`**

```ts
// web/src/hooks/useSlashCommands.ts
export interface SlashCommand {
  name: string;
  description: string;
  /** Expand into the message text that will be sent to the agent. */
  expand: () => string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: "/qr", description: "Show the WhatsApp pairing QR", expand: () => "show me the WhatsApp pairing QR" },
  { name: "/skills", description: "List local skills", expand: () => "list local skills" },
  { name: "/runs", description: "Open recent runs", expand: () => "__open_slide_over__:runs" },
  { name: "/policy", description: "Show current send policy", expand: () => "what is the current send policy and allowed recipients?" },
];

export function matchSlash(input: string): SlashCommand[] {
  if (!input.startsWith("/")) return [];
  const q = input.slice(1).toLowerCase();
  return SLASH_COMMANDS.filter((c) => c.name.slice(1).startsWith(q));
}
```

- [ ] **Step 2: `SlashMenu`**

```tsx
// web/src/components/SlashMenu.tsx
import type { SlashCommand } from "@/hooks/useSlashCommands";

interface Props {
  commands: SlashCommand[];
  activeIdx: number;
  onPick: (c: SlashCommand) => void;
}

export default function SlashMenu({ commands, activeIdx, onPick }: Props) {
  if (commands.length === 0) return null;
  return (
    <ul className="absolute bottom-full mb-2 w-full overflow-hidden rounded-card border border-border bg-bg-card shadow-sm">
      {commands.map((c, i) => (
        <li key={c.name}>
          <button
            onClick={() => onPick(c)}
            className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm ${i === activeIdx ? "bg-bg-app" : ""}`}
          >
            <span className="font-mono text-accent">{c.name}</span>
            <span className="text-xs text-fg-muted">{c.description}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
```

---

### Task D4: `EmptyState`

**Files:**
- Create: `web/src/components/EmptyState.tsx`

- [ ] **Step 1: Create**

```tsx
// web/src/components/EmptyState.tsx
import { Suggestion } from "@/components/ai-elements/suggestion";

const SUGGESTIONS = [
  "show me the WhatsApp pairing QR",
  "is wabot healthy?",
  "what's the send policy and which recipients are allowed?",
];

export default function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex flex-col items-center gap-6 py-16">
      <p className="text-fg-muted">What would you like to ask the agent?</p>
      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((s) => (
          <Suggestion key={s} onClick={() => onPick(s)}>{s}</Suggestion>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build smoke check + commit Phase D**

```bash
cd web && npm run build
```

```bash
git add web/src/components web/src/hooks
git -c commit.gpgsign=false commit -m "feat(web): TopBar, SlideOver + 3 panels, SlashMenu, EmptyState"
```

---

## Phase E — State, data flow, app wiring

### Task E1: Zustand store

**Files:**
- Create: `web/src/store/index.ts`

- [ ] **Step 1: Create the store**

```ts
// web/src/store/index.ts
import { create } from "zustand";
import type { UiEnvelope } from "@/types/ui-envelope";

export type ReadinessVariant = "ok" | "warn" | "bad" | "pending";
export interface ReadinessRow { label: string; variant: ReadinessVariant }
export interface Readiness {
  overall: ReadinessVariant;
  model: ReadinessRow;
  wabot: ReadinessRow;
  policy: ReadinessRow;
  memory: ReadinessRow;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
  cards?: UiEnvelope[];
}

type SlideOverId = "qr" | "runs" | "settings" | null;

interface State {
  messages: ChatMessage[];
  readiness: Readiness;
  slideOver: SlideOverId;

  addUser: (text: string) => string;
  startAssistant: () => string;
  appendDelta: (id: string, delta: string) => void;
  finishAssistant: (id: string) => void;
  attachCard: (id: string, envelope: UiEnvelope) => void;
  openSlideOver: (which: Exclude<SlideOverId, null>) => void;
  closeSlideOver: () => void;
  setReadiness: (r: Partial<Readiness>) => void;
}

const emptyRow: ReadinessRow = { label: "Checking…", variant: "pending" };

export const useStore = create<State>((set) => ({
  messages: [],
  slideOver: null,
  readiness: { overall: "pending", model: emptyRow, wabot: emptyRow, policy: emptyRow, memory: emptyRow },

  addUser: (text) => {
    const id = crypto.randomUUID();
    set((s) => ({ messages: [...s.messages, { id, role: "user", text }] }));
    return id;
  },
  startAssistant: () => {
    const id = crypto.randomUUID();
    set((s) => ({ messages: [...s.messages, { id, role: "assistant", text: "", streaming: true, cards: [] }] }));
    return id;
  },
  appendDelta: (id, delta) =>
    set((s) => ({
      messages: s.messages.map((m) => m.id === id ? { ...m, text: m.text + delta } : m),
    })),
  finishAssistant: (id) =>
    set((s) => ({
      messages: s.messages.map((m) => m.id === id ? { ...m, streaming: false } : m),
    })),
  attachCard: (id, envelope) =>
    set((s) => ({
      messages: s.messages.map((m) => m.id === id ? { ...m, cards: [...(m.cards ?? []), envelope] } : m),
    })),
  openSlideOver: (which) => set({ slideOver: which }),
  closeSlideOver: () => set({ slideOver: null }),
  setReadiness: (r) => set((s) => ({
    readiness: { ...s.readiness, ...r, overall: deriveOverall({ ...s.readiness, ...r }) },
  })),
}));

function deriveOverall(r: Readiness): ReadinessVariant {
  const rows = [r.model, r.wabot, r.policy, r.memory];
  if (rows.some((x) => x.variant === "bad")) return "bad";
  if (rows.some((x) => x.variant === "warn" || x.variant === "pending")) return "warn";
  return "ok";
}
```

---

### Task E2: API wrappers

**Files:**
- Create: `web/src/api/chat.ts`, `web/src/api/settings.ts`, `web/src/api/pairing.ts`, `web/src/api/runs.ts`

- [ ] **Step 1: `chat.ts`**

```ts
// web/src/api/chat.ts
export interface ChatResponse {
  text: string;
  run_id?: string;
}

export async function postChat(message: string): Promise<ChatResponse> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error(`chat failed: ${res.status}`);
  return res.json();
}
```

- [ ] **Step 2: `settings.ts`**

```ts
// web/src/api/settings.ts
export interface MaskedField { set: boolean; preview: string | null }
export interface SettingsView {
  openrouter_api_key: MaskedField;
  openrouter_model: MaskedField;
  openrouter_base_url: MaskedField;
  wabot_endpoint: MaskedField;
  wabot_token: MaskedField;
  send_policy: "dry_run" | "allowlist" | "allow_all";
  allowed_recipients: string[];
}

export async function fetchSettings(): Promise<SettingsView> {
  const res = await fetch("/api/settings", { credentials: "include" });
  if (!res.ok) throw new Error(`settings: ${res.status}`);
  return res.json();
}

export async function patchSettings(body: Record<string, unknown>): Promise<void> {
  const res = await fetch("/api/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `settings PATCH failed: ${res.status}`);
  }
}
```

- [ ] **Step 3: `pairing.ts`**

```ts
// web/src/api/pairing.ts
export interface PairingState { available: boolean; linked_device?: string | null }

export async function fetchPairing(): Promise<PairingState> {
  const res = await fetch("/api/whatsapp/pairing", { credentials: "include" });
  if (!res.ok) return { available: false };
  return res.json();
}
```

- [ ] **Step 4: `runs.ts`**

```ts
// web/src/api/runs.ts
export interface Run {
  id: string;
  started_at: string;
  summary?: string;
  tool_count?: number;
}

export async function fetchRuns(): Promise<Run[]> {
  const res = await fetch("/api/runs", { credentials: "include" });
  if (!res.ok) throw new Error(`runs: ${res.status}`);
  const data = await res.json();
  return Array.isArray(data) ? data : (data.runs ?? []);
}
```

---

### Task E3: `useEventStream` hook

**Files:**
- Create: `web/src/hooks/useEventStream.ts`

- [ ] **Step 1: Create**

```ts
// web/src/hooks/useEventStream.ts
import { useEffect, useRef } from "react";
import { useStore } from "@/store";
import type { UiEnvelope } from "@/types/ui-envelope";

interface ServerEvent {
  id?: number;
  name?: string;
  payload?: any;
}

export function useEventStream(): void {
  const startAssistant = useStore((s) => s.startAssistant);
  const appendDelta = useStore((s) => s.appendDelta);
  const finishAssistant = useStore((s) => s.finishAssistant);
  const attachCard = useStore((s) => s.attachCard);
  const activeAssistantId = useRef<string | null>(null);

  useEffect(() => {
    const es = new EventSource("/api/stream", { withCredentials: true });

    es.onmessage = (evt) => {
      let data: ServerEvent;
      try { data = JSON.parse(evt.data); } catch { return; }
      const payload = data.payload ?? {};
      const type = payload.type;
      if (type === "delta") {
        if (activeAssistantId.current == null) {
          activeAssistantId.current = startAssistant();
        }
        appendDelta(activeAssistantId.current, payload.text ?? "");
      } else if (type === "tool_result" && payload.ui) {
        if (activeAssistantId.current == null) {
          activeAssistantId.current = startAssistant();
        }
        attachCard(activeAssistantId.current, payload.ui as UiEnvelope);
      } else if (data.name === "run.finished" || type === "run_finished") {
        if (activeAssistantId.current) {
          finishAssistant(activeAssistantId.current);
          activeAssistantId.current = null;
        }
      }
    };

    es.onerror = () => { /* EventSource auto-reconnects */ };
    return () => es.close();
  }, [startAssistant, appendDelta, finishAssistant, attachCard]);
}
```

---

### Task E4: Wire `App.tsx`

**Files:**
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Rewrite `App.tsx`**

```tsx
// web/src/App.tsx
import { useEffect, useRef, useState } from "react";
import { Conversation, Message, MessageContent } from "@/components/ai-elements/conversation";
import { PromptInput, PromptInputTextarea, PromptInputSubmit } from "@/components/ai-elements/prompt-input";
import TopBar from "@/components/TopBar";
import SlideOver from "@/components/SlideOver";
import EmptyState from "@/components/EmptyState";
import SlashMenu from "@/components/SlashMenu";
import ToolCard from "@/components/tool-cards/ToolCard";
import PairingPanel from "@/components/slide-overs/PairingPanel";
import RunsPanel from "@/components/slide-overs/RunsPanel";
import SettingsPanel from "@/components/slide-overs/SettingsPanel";
import { useStore } from "@/store";
import { useEventStream } from "@/hooks/useEventStream";
import { matchSlash, SLASH_COMMANDS } from "@/hooks/useSlashCommands";
import { postChat } from "@/api/chat";
import { fetchSettings } from "@/api/settings";

export default function App() {
  useEventStream();

  const messages = useStore((s) => s.messages);
  const addUser = useStore((s) => s.addUser);
  const slideOver = useStore((s) => s.slideOver);
  const close = useStore((s) => s.closeSlideOver);
  const open = useStore((s) => s.openSlideOver);
  const setReadiness = useStore((s) => s.setReadiness);

  const [input, setInput] = useState("");
  const [slashIdx, setSlashIdx] = useState(0);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const slashMatches = matchSlash(input.split(/\s/)[0] ?? "");

  useEffect(() => {
    fetchSettings().then((v) => {
      setReadiness({
        policy: { label: v.send_policy, variant: v.send_policy === "allow_all" ? "warn" : "ok" },
        model: { label: v.openrouter_model.set ? "configured" : "offline", variant: v.openrouter_model.set ? "ok" : "warn" },
        wabot: { label: v.wabot_endpoint.set ? "configured" : "missing", variant: v.wabot_endpoint.set ? "ok" : "warn" },
        memory: { label: "ready", variant: "ok" },
      });
    }).catch(() => undefined);
  }, [setReadiness]);

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    setInput("");
    // Handle slide-over expansions client-side without bothering the agent.
    if (trimmed.startsWith("__open_slide_over__:")) {
      open(trimmed.split(":")[1] as never);
      return;
    }
    addUser(trimmed);
    try { await postChat(trimmed); } catch (err) { console.error(err); }
  }

  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (slashMatches.length > 0) {
      if (e.key === "ArrowDown") { e.preventDefault(); setSlashIdx((i) => Math.min(i + 1, slashMatches.length - 1)); return; }
      if (e.key === "ArrowUp")   { e.preventDefault(); setSlashIdx((i) => Math.max(i - 1, 0)); return; }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey && !(e.metaKey || e.ctrlKey))) {
        e.preventDefault();
        const cmd = slashMatches[slashIdx];
        void submit(cmd.expand());
        return;
      }
    }
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void submit(input);
    }
  }

  return (
    <div className="flex min-h-full flex-col">
      <TopBar />
      <main className="mx-auto flex w-full max-w-[720px] flex-1 flex-col px-4 pb-32 pt-6">
        {messages.length === 0 ? (
          <EmptyState onPick={(t) => void submit(t)} />
        ) : (
          <Conversation>
            {messages.map((m) => (
              <Message key={m.id} from={m.role}>
                <MessageContent>
                  <p className={m.streaming ? "shimmer" : undefined}>{m.text}</p>
                  {m.cards && m.cards.length > 0 && (
                    <div className="mt-3 space-y-2">
                      {m.cards.map((env, idx) => (
                        <ToolCard
                          key={idx}
                          envelope={env}
                          onAction={(actionId) => {
                            if (env.kind === "send_confirm" && actionId === "approve") {
                              void submit("approved");
                            } else if (env.kind === "send_confirm" && actionId === "cancel") {
                              void submit("cancel — do not send");
                            } else if (env.kind === "wabot_status" && actionId === "recheck") {
                              void submit("recheck wabot health");
                            }
                          }}
                        />
                      ))}
                    </div>
                  )}
                </MessageContent>
              </Message>
            ))}
          </Conversation>
        )}
      </main>

      <div className="fixed bottom-0 left-1/2 w-full max-w-[720px] -translate-x-1/2 px-4 pb-4">
        <div className="relative">
          {slashMatches.length > 0 && (
            <SlashMenu
              commands={slashMatches}
              activeIdx={slashIdx}
              onPick={(c) => void submit(c.expand())}
            />
          )}
          <PromptInput onSubmit={(e) => { e.preventDefault(); void submit(input); }}>
            <PromptInputTextarea
              ref={composerRef as never}
              value={input}
              onChange={(e) => { setInput(e.target.value); setSlashIdx(0); }}
              onKeyDown={onKey}
              placeholder="Message wabot-agent…   /  for commands   ⌘↵ to send"
            />
            <PromptInputSubmit disabled={!input.trim()} />
          </PromptInput>
        </div>
      </div>

      <SlideOver open={slideOver === "qr"} onClose={close} title="WhatsApp pairing">
        <PairingPanel />
      </SlideOver>
      <SlideOver open={slideOver === "runs"} onClose={close} title="Recent runs">
        <RunsPanel />
      </SlideOver>
      <SlideOver open={slideOver === "settings"} onClose={close} title="Settings">
        <SettingsPanel />
      </SlideOver>
    </div>
  );
}
```

- [ ] **Step 2: Build smoke check + commit**

```bash
cd web && npm run build
```

```bash
git add web/src
git -c commit.gpgsign=false commit -m "feat(web): wire Zustand + SSE + slash commands + slide-overs into App"
```

---

## Phase F — Tests, cleanup, docs

### Task F1: Vitest setup + ToolCard snapshot tests

**Files:**
- Create: `web/src/__tests__/setup.ts`
- Create: `web/src/__tests__/tool-cards.test.tsx`

- [ ] **Step 1: `setup.ts`**

```ts
// web/src/__tests__/setup.ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 2: `tool-cards.test.tsx`**

```tsx
// web/src/__tests__/tool-cards.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import WabotStatusCard from "@/components/tool-cards/WabotStatusCard";
import SendConfirmCard from "@/components/tool-cards/SendConfirmCard";
import MemoryCard from "@/components/tool-cards/MemoryCard";

describe("WabotStatusCard", () => {
  it("renders ok state with version + uptime + recheck action", () => {
    const onAction = vi.fn();
    render(
      <WabotStatusCard
        data={{ status: "ok", version: "0.4.2", uptime_s: 65, last_seen_s: 1 }}
        actions={[{ id: "recheck", label: "Recheck", tool: "wabot_health", args: {} }]}
        onAction={onAction}
      />,
    );
    expect(screen.getByText("wabot daemon")).toBeInTheDocument();
    expect(screen.getByText("0.4.2")).toBeInTheDocument();
    expect(screen.getByText("1m")).toBeInTheDocument();
  });

  it("renders bad state with error", () => {
    render(
      <WabotStatusCard
        data={{ status: "bad", error: "connect refused" }}
        actions={[]}
        onAction={vi.fn()}
      />,
    );
    expect(screen.getByText("connect refused")).toBeInTheDocument();
  });
});

describe("SendConfirmCard", () => {
  it("shows Approve/Cancel when needs_approval is true", () => {
    const onAction = vi.fn();
    render(
      <SendConfirmCard
        data={{ policy: "allowlist", recipient_masked: "+1***4567", body_preview: "hi", needs_approval: true, delivered: false }}
        actions={[
          { id: "approve", label: "Approve", tool: "send_whatsapp_text", args: {} },
          { id: "cancel", label: "Cancel", tool: null, args: {} },
        ]}
        onAction={onAction}
      />,
    );
    expect(screen.getByText("Approve")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
    expect(screen.getByText("to +1***4567")).toBeInTheDocument();
  });

  it("hides actions for delivered dry-run sends", () => {
    render(
      <SendConfirmCard
        data={{ policy: "dry_run", recipient_masked: "+1***4567", body_preview: "hi", needs_approval: false, delivered: false }}
        actions={[]}
        onAction={vi.fn()}
      />,
    );
    expect(screen.queryByText("Approve")).not.toBeInTheDocument();
  });
});

describe("MemoryCard", () => {
  it("renders contact + facts as chips", () => {
    render(
      <MemoryCard
        data={{ contact_masked: "+1***4567", facts: [{ id: "f1", text: "prefers async" }] }}
        actions={[]}
        onAction={vi.fn()}
      />,
    );
    expect(screen.getByText("+1***4567")).toBeInTheDocument();
    expect(screen.getByText("prefers async")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run tests**

```bash
cd web && npm run test
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/__tests__
git -c commit.gpgsign=false commit -m "test(web): snapshot tests for tool cards"
```

---

### Task F2: Delete legacy `static/` source, regenerate from build

**Files:**
- Delete: `static/app.js`, `static/styles.css`, `static/index.html` (regenerated by build)

- [ ] **Step 1: Run the build to populate `static/`**

```bash
./scripts/build-web.sh
```

- [ ] **Step 2: Verify the new `static/` is the React build**

```bash
ls -la static/
grep -c "vite" static/index.html || true
```

Expected: `static/index.html` is a Vite-built HTML referencing `/static/assets/*`.

- [ ] **Step 3: Confirm FastAPI still serves correctly**

Open one terminal:

```bash
uv run python main.py
```

Open another:

```bash
curl -s http://127.0.0.1:8787/ | head -20
```

Expected: HTML body with `<div id="root">`.

- [ ] **Step 4: Run the offline Python suite**

```bash
uv run --with '.[dev]' python -m pytest -m offline -q
uv run python evals/run_local.py
uv run --with '.[dev]' ruff check .
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add static/
git -c commit.gpgsign=false commit -m "build: regenerate static/ from web/dist"
```

---

### Task F3: Update `CLAUDE.md` + `README.md`

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: `CLAUDE.md`** — add a new "Frontend" section before the "Repository Layout" section

```markdown
## Frontend

The operator dashboard is a Vite + React SPA in `web/`. FastAPI keeps serving the *built* assets from `static/`; the build pipeline is:

```bash
./scripts/build-web.sh        # cd web && npm ci && npm run build && rsync into static/
```

For local development with hot module reload:

```bash
cd web && npm install      # one-time
cd web && npm run dev      # Vite at http://127.0.0.1:5173, proxies /api → 8787
```

Key modules in `web/src/`:

- `App.tsx` — wires `<TopBar />`, `<Conversation />`, `<PromptInput />`, three `<SlideOver />` panels, and the `useEventStream` SSE hook.
- `store/index.ts` — single Zustand store for messages, readiness, slide-over state.
- `hooks/useEventStream.ts` — subscribes to `/api/stream`, demuxes deltas + tool results + ui envelopes into the store.
- `components/tool-cards/` — `ToolCard` switches on `kind` and renders one of four polished card variants driven by the server-side `ui` envelope (`wabot_status`, `pairing_qr`, `send_confirm`, `memory`).
- `components/ai-elements/` — shadcn-style copy-in components from `npx ai-elements` (Conversation, Message, PromptInput, Suggestion, etc.). These live in the repo and may be edited.

The `ui` field on tool-result SSE events is built server-side by `src/wabot_agent/ui_envelopes.py`. Adding a new card means: register a builder in `_BUILDERS`, add a TS type in `web/src/types/ui-envelope.ts`, add a child component under `tool-cards/`, and add the case to `ToolCard.tsx`.

The send-confirmation card is **not** the security boundary. Server-side `_is_send_allowed()` remains authoritative; the card is a transparency layer that pauses the model on non-dry-run sends and lets the operator type "approved" to continue.
```

- [ ] **Step 2: `README.md`** — replace the dev-server section

Find the section that mentions `uv run python main.py` and the operator dashboard and add an immediately-following block:

```markdown
### Frontend dev

```bash
cd web && npm install         # one-time
cd web && npm run dev         # http://127.0.0.1:5173
# in another terminal:
uv run python main.py         # FastAPI at http://127.0.0.1:8787
```

To ship the SPA into the static bundle (also called automatically by `deploy-to-vignesh.sh`):

```bash
./scripts/build-web.sh
```
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git -c commit.gpgsign=false commit -m "docs: document web/ build + dev flow and ui envelope contract"
```

---

### Task F4: Final verification

- [ ] **Step 1: Re-run full offline gate**

```bash
uv run --with '.[dev]' ruff check .
uv run --with '.[dev]' python -m pytest -m offline -q
uv run python evals/run_local.py
cd web && npm run build && npm run test && cd ..
```

Expected: all green.

- [ ] **Step 2: Boot end-to-end**

```bash
uv run python main.py
```

In a browser at `http://127.0.0.1:8787`:
- Confirm wordmark + status dot render.
- Click each icon — slide-overs open and load (or show empty states gracefully in offline mode).
- Type `/` in the composer — slash menu appears.
- Type `is wabot healthy?` and submit — assistant streams a reply (offline echo in offline mode).

- [ ] **Step 3: Commit any final polish**

```bash
git status
# if anything changed:
git -c commit.gpgsign=false commit -am "chore: final polish from end-to-end verification"
```

---

## Post-implementation sub-agent dispatch

These two are dispatched **after** the plan completes, by the orchestrator (not in-task):

1. **Haiku — documentation freshness:** reads `CLAUDE.md`, `README.md`, every file under `docs/`, the `web/package.json` scripts section, and the new `web/src/` tree. Cross-checks against the actual code. Reports stale lines and proposes patches inline.

2. **Sonnet/Opus — output testing:** runs `uv run pytest -m offline`, `uv run python evals/run_local.py`, then `cd web && npm run build && npm run test`. Starts `uv run python main.py` in offline mode, drives the served SPA in a real browser (Claude Preview), exercises the four ToolCard scenarios, captures screenshots, verifies the send-confirmation approval loop never invokes a real send. Reports pass/fail with attachments.
