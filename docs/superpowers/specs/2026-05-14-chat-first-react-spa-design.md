# wabot-agent — chat-first React SPA redesign

**Date:** 2026-05-14
**Branch:** `claude/nervous-burnell-0962fa`
**Status:** approved (user sign-off in brainstorm session 2026-05-14)
**Codename:** unchanged (`wabot-agent`)

## Goal

Replace the vanilla HTML/JS operator dashboard at `static/` with a chat-first React SPA built with Vite, Vercel AI Elements (`npx ai-elements`), and `vercel-labs/json-render`. Everything that is not chat collapses behind icon buttons or slash commands. Polish and clarity are the top success metrics; functional parity with the current dashboard is the floor, not the ceiling.

## Non-goals

- No change to the FastAPI service shape, auth model, send policy, or memory store.
- No Node runtime on the VPS — Vite builds to static assets that FastAPI keeps serving from `/`.
- No rebrand. Wordmark stays `wabot-agent`.
- No new tools added to the agent in this scope. Generative-UI cards render existing tool results, they don't expand the tool surface.

## Constraints (load-bearing rules from `CLAUDE.md`)

1. Send policy is fail-closed; the new send-confirmation card is a transparency layer, **not** the security boundary. Server-side `_is_send_allowed()` stays authoritative.
2. Image sends remain confined to `WABOT_AGENT_MEDIA_DIR`. No frontend bypass.
3. `GET /api/settings` keeps masking secrets. The settings slide-over reproduces today's "empty input = no change" semantics.
4. `wabot` daemon stays on loopback. Frontend talks to FastAPI only.
5. The `WABOT_AGENT_*` / `VIGNESH_*` dual-prefix alias contract in `config.py` is preserved.
6. Offline mode (`WABOT_AGENT_OFFLINE_MODE=true` or empty `OPENROUTER_API_KEY`) must boot, render, and test the new SPA without network creds.

## Architecture

### Stack

| Layer | Choice | Notes |
| --- | --- | --- |
| Build | Vite 5 + React 18 + TypeScript | Output to `static/` (replaces the existing files) |
| Styling | Tailwind CSS + CSS variables | ai-elements ships shadcn-style components that expect Tailwind |
| Components | `npx ai-elements` | Conversation, Message, PromptInput, Reasoning, Actions, Loader, Suggestion |
| Gen UI | `vercel-labs/json-render` | Drives the four `ToolCard` variants |
| State | Zustand (single store) | `messages`, `runs`, `readiness`, `sendIntents` |
| Streaming | Existing SSE `/api/stream` | Demuxed by `run_id` on the client |
| Routing | None — slide-overs + slash commands | No client router |

### Build pipeline

- Source moves to `web/` (new top-level dir): `web/src/`, `web/public/`, `web/index.html`, `web/vite.config.ts`, `web/package.json`.
- `web/dist/` → copied into `static/` so FastAPI's existing `StaticFiles` mount keeps working.
- A new `scripts/build-web.sh` runs `cd web && npm ci && npm run build && rsync -a --delete web/dist/ ../static/`. `scripts/deploy-to-vignesh.sh` calls it before the VPS rsync.
- For local development, FastAPI continues to serve `static/`; the developer runs `npm run dev` from `web/` on Vite's port for HMR, with proxy entries pointing `/api/*`, `/whatsapp/*`, and `/static/*` at `http://127.0.0.1:8787`.

### Design tokens

```
--bg-app:     #FAFAF7 (light) / #0F1115 (dark)
--bg-card:    #FFFFFF / #161A22
--fg-default: #0F1115 / #E6E8EE
--fg-muted:   #62656E / #9099AA
--border:     rgba(15,17,21,0.08) / rgba(255,255,255,0.08)
--accent:     #7c3aed (violet 600)
--accent-fg:  #FFFFFF
--ok:         #10b981
--warn:       #f59e0b
--bad:        #ef4444
--radius-card: 16px
--radius-pill: 999px
--shadow-sm:  0 1px 2px rgba(15,17,21,0.04)
--font-sans:  "Geist Sans", Inter, system-ui
--font-mono:  "Geist Mono", ui-monospace
--ease-out:   cubic-bezier(0.22, 1, 0.36, 1)
--dur:        200ms
```

## Layout

```
┌──────────────────────────────────────────────────────────┐
│  wabot-agent●  ready                     📱  ⏱  ⚙        │  56px floating header
│                                                          │
│              [agent: hi, what's up?]                     │  max-width 720,
│                                              [you: …]   │  vertically centered,
│              [tool card: wabot_status]                   │  edge-to-edge on mobile
│              [tool card: send_confirm]                   │
│              [agent: streaming…]                         │
│                                                          │
│   ┌──────────────────────────────────────────────────┐   │
│   │ Message wabot-agent…                       ⏎    │   │  sticky bottom composer
│   │ /skills  /runs  /qr  /policy        ⌘↵ to send   │   │
│   └──────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

- **Top bar** (`<TopBar />`): wordmark + live status dot, three icon buttons (QR, runs, settings). Status dot click opens a `<StatusPopover />` with four KPIs (model, wabot, send-policy, memory contact count).
- **Chat column** (`<Conversation />`): max-width 720px, centered, padding 24px sides on desktop / 12px on mobile. Bubbles use ai-elements `<Message>` primitive; assistant has avatar (small dot, not a logo), user has none.
- **Composer** (`<PromptInput />`): auto-grow textarea, multiline, `⌘↵` to send. `/`-typing opens a `<SlashMenu />` with command suggestions inline (`/skills`, `/runs`, `/qr`, `/policy`).
- **Slide-overs** (`<SlideOver side="right" width={420} />`):
  - 📱 → WhatsApp pairing (QR, linked-device status, refresh button)
  - ⏱ → Runs timeline (paginated, with per-run tool-event drill-down)
  - ⚙ → Settings (OpenRouter / wabot / send-policy / allowed-recipients form, identical contract to today)

## Information architecture

| Today's location | New location |
| --- | --- |
| Sidebar nav | **Removed** — all destinations are top-bar icons or slash commands |
| KPI grid (model/wabot/policy/memory) | StatusPopover (click status dot) |
| Chat panel | Full-width single column |
| Side-rail WhatsApp QR | 📱 slide-over, **and** inline gen-UI card on `/qr` |
| Side-rail runs | ⏱ slide-over, **and** mini timestamp/tool-icons row beside each assistant message |
| Settings drawer | ⚙ slide-over (unchanged form) |
| Mobile bottom tab bar | **Removed** — same icons in top bar, full-width chat |

## Generative UI

### Envelope contract

Tool events on the SSE stream gain an optional `ui` field:

```jsonc
{
  "type": "tool_result",
  "run_id": "01H…",
  "tool": "wabot_health",
  "ok": true,
  "result": { … existing payload … },
  "ui": {
    "kind": "wabot_status",
    "data": { "status": "ok", "version": "0.4.2", "uptime_s": 8420, "last_seen_s": 3 },
    "actions": [{ "id": "recheck", "label": "Recheck", "tool": "wabot_health", "args": {} }]
  }
}
```

When `ui` is absent the frontend renders the existing redacted-JSON pre-block (current behavior). When present, the frontend mounts `<ToolCard kind={ui.kind} data={ui.data} actions={ui.actions} />`. `<ToolCard>` is a switch on `kind`; each branch is a JSX skeleton with `<JsonRender schema={...} data={ui.data} />` filling the data-driven middle.

### Four kinds (v1 scope)

| `kind` | Trigger | Visual |
| --- | --- | --- |
| `wabot_status` | `wabot_health` result | Status dot + label, version, uptime, last-seen, **Recheck** button |
| `pairing_qr` | `/qr` slash, or model decides | Embedded `/api/whatsapp/pairing.svg`, linked-device label, **Refresh** button |
| `send_confirm` | About to send when `send_policy != dry_run` | Recipient (masked tail), preview (text or image thumbnail), policy badge, **Approve** / **Cancel** |
| `memory` | `recall_contact_memory` / `remember_contact_fact` | Contact header + fact chips (each with `× delete`, `✎ edit`) |

### Send-confirmation approval loop (client-side)

Server policy stays the authoritative gate. The UX layer is:

1. Operator asks: "send 'hello' to +1555…".
2. Model intends to call `send_whatsapp_text(to=…, body=…)`. If `send_policy == dry_run`, the tool runs as today (server returns dry-run note, card shows it).
3. If `send_policy != dry_run`, the model emits a `send_confirm` card **first** and pauses (achieved via a small prompt instruction: "for non-dry-run sends, emit a send_confirm card and wait for operator approval before calling the actual send tool").
4. Operator clicks **Approve** → frontend posts a new chat turn `__approved_send__:{intent_id}` → model retries the send tool with the approval token in context → server enforces `_is_send_allowed()` independently.
5. Cancel just drops the intent client-side; no server state.

This means **zero new backend routes**. Server policy code is untouched. The card is transparency.

## Component map

### From `npx ai-elements`

- `Conversation`, `Message`, `MessageContent`, `MessageAvatar`
- `PromptInput`, `PromptInputTextarea`, `PromptInputSubmit`
- `Reasoning`, `Actions`, `Loader`, `Suggestion`

### Custom

- `<TopBar />` — wordmark, status dot, three icon buttons
- `<StatusDot variant=ok|warn|bad|pending />` — used in wordmark, status popover, status card
- `<StatusPopover />` — four KPIs
- `<SlideOver side="right" width={420} />` — generic, used 3 times
- `<ToolCard kind="…">` + four child variants (each is a thin JSX skeleton over `<JsonRender />`)
- `<SlashMenu />` — popover anchored to the composer when `/` is typed
- `<EmptyState />` — three `<Suggestion />` chips for new operators

## Data flow & state

- Single Zustand store: `{ messages: Message[], runs: Run[], readiness: ReadinessSnapshot, sendIntents: Map<string, SendIntent>, slideOver: 'qr' | 'runs' | 'settings' | null }`.
- SSE subscriber lives in `useEventStream()` hook; mounts at app root, dispatches into the store.
- HTTP wrappers in `web/src/api/`: `chat.ts`, `settings.ts`, `pairing.ts`, `runs.ts`. Each wraps the existing endpoint, with `X-Operator-Token` injected from a cookie reader.
- No router. Slide-overs are state, not routes.

## Backend changes (minimal)

1. `src/wabot_agent/agent.py` — extend the tool-result event payload to include an optional `ui` field, computed by a new `src/wabot_agent/ui_envelopes.py` helper. Each tool's result is mapped to a `ui` shape (or no `ui` for tools without a card).
2. `src/wabot_agent/api.py` — `/whatsapp/inbound` and `/api/stream` carry the new `ui` field unchanged; no schema migration.
3. Prompt update in `agent.py`: a paragraph instructing the model to emit `send_confirm` UI hints (already free since `ui` is server-built — the model just needs to wait for operator approval text on non-dry-run sends).

The `ui_envelopes.py` helper is pure-Python, fully unit-testable, and isolated from the agent loop.

## File layout (new)

```
web/
  package.json            (standalone npm package: React 18 + Vite 5 + Tailwind + json-render)
  vite.config.ts          (proxy /api and /whatsapp → 127.0.0.1:8787)
  tsconfig.json
  tailwind.config.ts
  postcss.config.cjs
  index.html
  src/
    main.tsx
    App.tsx
    styles.css            (Tailwind base + tokens)
    components/
      ai-elements/        (output of `npx ai-elements add …`)
      tool-cards/
        ToolCard.tsx
        WabotStatusCard.tsx
        PairingQrCard.tsx
        SendConfirmCard.tsx
        MemoryCard.tsx
      TopBar.tsx
      StatusDot.tsx
      StatusPopover.tsx
      SlideOver.tsx
      SlashMenu.tsx
      EmptyState.tsx
    hooks/
      useEventStream.ts
      useSlashCommands.ts
    store/
      index.ts             (Zustand)
    api/
      chat.ts
      settings.ts
      pairing.ts
      runs.ts
    types/
      ui-envelope.ts       (mirror of the backend ui_envelopes shapes)

scripts/
  build-web.sh             (new — pnpm install + build + rsync into static/)

src/wabot_agent/
  ui_envelopes.py          (new — pure-Python helpers that build the `ui` field)
  agent.py                 (modified — call the helpers; prompt update)
  api.py                   (modified only if needed; should be untouched)

docs/superpowers/specs/
  2026-05-14-chat-first-react-spa-design.md   (this file)
```

## Testing & validation strategy

- **Offline tests (Python):** keep `tests/test_*.py` green. Add `tests/test_ui_envelopes.py` exercising each `kind` × tool result.
- **Frontend tests (Vitest + React Testing Library):** snapshot tests for each ToolCard variant against fixture data; one integration test that drives the SSE replay through the store and asserts messages + cards render in order.
- **Eval harness:** unchanged (`evals/run_local.py`), but a new case file `evals/cases.jsonl` entry for "operator asks for QR" verifying the model emits a `pairing_qr` card.
- **Haiku sub-agent — doc freshness:** after merge, reads `CLAUDE.md`, `README.md`, `docs/`, the `npm`/`pnpm` scripts, and the new `web/` tree. Cross-checks claims against current code. Reports drift inline.
- **Sub-agent — output testing:** runs `uv run pytest -m offline`, `uv run python evals/run_local.py`, then `cd web && npm ci && npm run build`. Starts `uv run python main.py` in offline mode, drives the served SPA in a browser, walks the four ToolCard scenarios, captures screenshots, asserts the send-confirm approval loop never invokes a real send in `dry_run`. Reports pass/fail with attachments.

## Migration & rollback

- Implementation lands in a single commit chain on `claude/nervous-burnell-0962fa`. The previous `static/` HTML/JS files are deleted in the same commit that adds the built React output. Rollback is `git revert <merge>`.
- Behind-the-scenes contract changes (the `ui` field on tool events) are additive and ignored by older clients, but the old dashboard is being deleted so this isn't a true compat concern.

## Open questions (none)

All open items closed during brainstorm. Spec is ready for an implementation plan.
