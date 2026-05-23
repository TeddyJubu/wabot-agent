# PLAN — Dynamic Subagents + Tool/Skill/MCP/Composio Dashboard

**Owner:** Tony  •  **Status:** Draft for review  •  **Date:** 2026-05-24

This plan turns the dashboard into the control surface for runtime-created subagents and their tools. Today the six subagents (`orchestrator`, `scraper`, `memory_keeper`, `comms`, `scheduler`, `inboxer`) are hardcoded as Python builders with module-level instruction strings. Tools, MCPs, and Composio are wired in code and configured via env vars. After this plan: users create, edit, and disable subagents from the UI; pick their tools from a catalog; install skills and MCPs from three sources; connect Composio without touching env files; and watch real-time operational data.

---

## 0. What changes, at a glance

| Area | Today | After |
|---|---|---|
| Subagent set | 6 hardcoded builders in `src/wabot_agent/agents/` | DB-backed, runtime-created; the 6 existing ones seed the table on first boot |
| Instructions | Constants in each `agents/*.py` | Editable text in DB, with optional template variables |
| Tool binding | Hardcoded list per builder | M:N join table; assignable in UI |
| Skills | `.md` files scanned and injected into prompt | Same files, plus installable `.skill` zips and a registry browser — all toggleable per agent |
| MCPs | `settings.mcp_config` JSON file, edited by hand | DB-backed `mcp_servers` table, edited via UI; JSON file becomes one-time import path |
| Composio | Env var only, no UI | Connect button, per-app status, per-contact session inspector |
| Dashboard | Status bar + slide-overs (`Pairing`, `Runs`, `Groups`, `Settings`) | Same shell + new tabs: `Agents`, `Tools`, `Integrations`, `Activity` |

Nothing in the existing slide-overs gets removed. The new surfaces are additive.

---

## 1. Architecture

### 1.1 Data model (new tables, sqlite3 via `memory/_db.py`)

Migrations added to `src/wabot_agent/memory/_migrations.py` (additive, idempotent — matches the file's existing style at lines 7–123).

```sql
-- Subagents
create table if not exists subagents (
  id              integer primary key autoincrement,
  slug            text not null unique,          -- e.g. "scraper", "my-researcher"
  display_name    text not null,
  description     text,
  instructions    text not null,                 -- system prompt body
  is_builtin      integer not null default 0,    -- 1 for the seed 6; UI still allows editing instructions
  is_enabled      integer not null default 1,
  parent_slug     text,                          -- null = top-level, "orchestrator" = handoff target
  handoff_filter  text,                          -- 'remove_all_tools' | null (mirrors current orchestrator wiring)
  created_at      text not null default current_timestamp,
  updated_at      text not null default current_timestamp
);

-- Catalog of every callable the agent can be given
create table if not exists tools (
  id              integer primary key autoincrement,
  kind            text not null,                 -- 'native' | 'mcp' | 'composio' | 'skill_action'
  source_ref      text not null,                 -- native: 'tools.list_whatsapp_inbound_messages'
                                                 -- mcp: 'mcp_server_id:tool_name'
                                                 -- composio: 'GMAIL_SEND_EMAIL'
                                                 -- skill: 'skill_id:action_name' (rare)
  name            text not null,                 -- display name
  description     text,
  is_enabled      integer not null default 1,
  metadata        text                           -- JSON: arg schema, tags, last_seen_at, etc.
);
create unique index if not exists idx_tools_kind_source on tools(kind, source_ref);

-- M:N: agent <-> tool
create table if not exists subagent_tools (
  subagent_id     integer not null references subagents(id) on delete cascade,
  tool_id         integer not null references tools(id) on delete cascade,
  primary key (subagent_id, tool_id)
);

-- Skill registry (extends current filesystem scan)
create table if not exists skills (
  id              integer primary key autoincrement,
  slug            text not null unique,
  display_name    text not null,
  description     text,
  source          text not null,                 -- 'local' | 'zip' | 'registry'
  install_path    text not null,                 -- absolute path under settings.skills_dir
  origin_url      text,                          -- for registry/zip provenance
  version         text,
  installed_at    text not null default current_timestamp,
  is_enabled      integer not null default 1
);
create table if not exists subagent_skills (
  subagent_id     integer not null references subagents(id) on delete cascade,
  skill_id        integer not null references skills(id) on delete cascade,
  primary key (subagent_id, skill_id)
);

-- MCP server registry (replaces editing settings.mcp_config by hand)
create table if not exists mcp_servers (
  id              integer primary key autoincrement,
  name            text not null unique,          -- maps to the JSON top-level key today
  transport       text not null,                 -- 'stdio' | 'http'
  config_json     text not null,                 -- {command, args, env, url, headers}
  is_enabled      integer not null default 1,
  health_status   text,                          -- 'ok' | 'error' | 'unknown'
  health_message  text,
  last_checked_at text
);

-- Composio connections (per-contact already exists in contact_facts;
-- this table caches the app-level connection state for the dashboard)
create table if not exists composio_connections (
  id              integer primary key autoincrement,
  app_slug        text not null,                 -- 'gmail', 'github'
  display_name    text not null,
  status          text not null,                 -- 'connected' | 'pending' | 'error'
  user_id         text,                          -- WABOT_AGENT_COMPOSIO_USER_ID or contact id
  last_checked_at text,
  metadata        text                           -- JSON
);
create unique index if not exists idx_composio_app_user on composio_connections(app_slug, user_id);
```

**Migration strategy.** Append to `_migrations.py::init_schema` (it's already additive). One-time seed function `seed_builtin_subagents()` reads from a static manifest mirroring today's six builders and inserts rows with `is_builtin=1`. Re-running is a no-op (`insert or ignore`). One-time `import_mcp_config_file()` reads `settings.mcp_config` and populates `mcp_servers` if the table is empty.

### 1.2 Runtime loading

Today's `agents/__init__.py` re-exports `SUBAGENT_NAMES` and the `build_*` functions. The orchestrator imports them directly (`agents/orchestrator.py:129–155`). We replace that import-time wiring with a **registry loaded at agent-build time**.

New module: `src/wabot_agent/agents/registry.py`

```python
def load_subagent_specs(settings) -> list[SubagentSpec]:
    """Read subagents + subagent_tools + subagent_skills from DB."""

def build_dynamic_agent(spec, settings, tools, mcp_servers, composio_tools):
    """Build an agents.Agent from a SubagentSpec, resolving tool IDs to callables."""

def build_orchestrator_from_db(settings, mcp_servers, composio_tools):
    """Replaces build_orchestrator(); finds the row with slug='orchestrator',
    builds each child, wires handoffs per spec.parent_slug + handoff_filter."""
```

`agent.py:550–556` currently picks the orchestrator path based on `settings.subagents_enabled`. We add a third path: if a DB row exists for `slug='orchestrator'`, use `build_orchestrator_from_db`. Otherwise fall back to current behavior. This keeps the legacy single-agent and the hardcoded-orchestrator paths intact while the new path takes over.

**Tool resolution.** `tools.kind` decides the resolver:

- `native` → look up by dotted path in a registry built from `tools/__init__.py::core_tools()` keyed on `tool.name`.
- `mcp` → server is already in `mcp_servers` arg; we pass the server through and the agent uses its tools. (We do *not* per-tool filter MCPs in v1 — that requires shimming the SDK. We toggle whole servers.)
- `composio` → filter `composio_tools` list (returned by `composio_tools.load_composio_tools`) to just the slugs assigned to this agent.
- `skill_action` → out of scope for v1; skills remain prompt-injected via `cached_render_skill_summary`.

### 1.3 Caching

`instructions_cache.py::cached_build_agent_instructions` already keys on mem0/composio flags + skills mtime + knowledge mtime + agent-notes version. Add `subagents_updated_at` (max `updated_at` from `subagents` and `subagent_tools`) to the cache key. When the UI saves, bump it.

---

## 2. API surface (FastAPI)

New route files under `src/wabot_agent/api/routes/`. Each is registered in `api/__init__.py` (currently a 1-line file per survey).

### 2.1 `agents.py`

| Method | Path | Body / returns |
|---|---|---|
| GET | `/api/agents` | List of subagents with tool counts, skill counts, enabled state |
| POST | `/api/agents` | `{slug, display_name, description, instructions, parent_slug, handoff_filter}` → 201 |
| GET | `/api/agents/{slug}` | Full spec including tool IDs and skill IDs |
| PATCH | `/api/agents/{slug}` | Partial update; bumps `updated_at`, invalidates instruction cache |
| DELETE | `/api/agents/{slug}` | 409 if `is_builtin=1`; else cascade-deletes joins |
| PUT | `/api/agents/{slug}/tools` | `{tool_ids: [int]}` → replaces the set |
| PUT | `/api/agents/{slug}/skills` | `{skill_ids: [int]}` → replaces the set |
| POST | `/api/agents/{slug}/test` | `{prompt: str}` → runs one turn against this agent in isolation, returns transcript |

### 2.2 `tools_catalog.py`

| Method | Path | Returns |
|---|---|---|
| GET | `/api/tools` | All rows in `tools`, grouped by `kind`, with `is_assigned_to: [slug]` |
| POST | `/api/tools/refresh` | Re-scans native tools, MCP servers, Composio tools; upserts rows |
| PATCH | `/api/tools/{id}` | Toggle `is_enabled` |

### 2.3 `skills_admin.py`

| Method | Path | Body / returns |
|---|---|---|
| GET | `/api/skills` | All installed skills with source + version |
| POST | `/api/skills/scan` | Rescan `settings.skills_dir`; insert any new `SKILL.md` |
| POST | `/api/skills/install/zip` | multipart upload of `.skill` zip → extract under `skills_dir/<slug>/` → insert row |
| POST | `/api/skills/install/registry` | `{registry_url, slug}` → fetch tarball/zip → install |
| DELETE | `/api/skills/{slug}` | Disable (soft-delete) and remove from agents |
| GET | `/api/skills/registry/search?q=` | Proxy to a configured registry index (Anthropic skills catalog and/or custom) |

### 2.4 `mcp_admin.py`

| Method | Path | Body / returns |
|---|---|---|
| GET | `/api/mcp/servers` | All `mcp_servers` with health |
| POST | `/api/mcp/servers` | `{name, transport, config_json}` → insert |
| PATCH | `/api/mcp/servers/{id}` | Edit config / toggle enabled |
| DELETE | `/api/mcp/servers/{id}` | Remove |
| POST | `/api/mcp/servers/{id}/check` | Open the server once, list tools, update `health_status` |
| GET | `/api/mcp/registry/search?q=` | Proxy to MCP registry (Composio-hosted registry, Anthropic registry, or a static curated JSON shipped with the app) |
| POST | `/api/mcp/registry/install` | `{registry_id}` → builds the `config_json` from the registry entry |

### 2.5 `composio.py`

| Method | Path | Body / returns |
|---|---|---|
| GET | `/api/composio/status` | `{enabled, api_key_present, user_id, last_error}` |
| POST | `/api/composio/api-key` | `{api_key}` → writes to runtime overrides + `.env` (gated; see §2.7) |
| GET | `/api/composio/apps` | Calls `composio.toolkits.list()` → cached for 5min |
| GET | `/api/composio/connections` | All rows in `composio_connections` |
| POST | `/api/composio/connections` | `{app_slug, user_id?}` → calls `COMPOSIO_MANAGE_CONNECTIONS` and returns redirect URL |
| POST | `/api/composio/connections/{id}/refresh` | Re-checks status |
| DELETE | `/api/composio/connections/{id}` | Disconnect via Composio SDK |

### 2.6 `metrics.py`

| Method | Path | Returns |
|---|---|---|
| GET | `/api/metrics/overview` | KPI tiles: messages today, runs today, avg latency, $ today |
| GET | `/api/metrics/runs?window=24h` | Time-bucketed runs from `runs` table |
| GET | `/api/metrics/tools?window=24h` | Top tools used (from `tool_events`) |
| GET | `/api/metrics/costs?window=24h` | LLM cost rollup (new — see §4.4) |
| GET | `/api/metrics/health` | Per-integration health summary |

### 2.7 Secret handling

`COMPOSIO_API_KEY` (and other write-back secrets) live in `.env` today. We must avoid round-tripping secrets through DB columns. Approach:

- New file `data/runtime_secrets.json` (chmod 600, gitignored) — written via a single `secrets_service.py` module that **also** writes to `.env` if `WABOT_AGENT_ALLOW_ENV_WRITE=true`.
- `settings.py` reads `runtime_secrets.json` last so it overrides env on next reload.
- `POST /api/composio/api-key` triggers a soft settings reload (already supported via `settings_service.py`) and a Composio client re-init.

---

## 3. Dashboard UX

The existing shell is a status bar + slash-command composer + slide-overs (`App.tsx`). We keep that shell and add a left-rail nav for full-screen views, switched in-place. Slide-overs stay for quick actions.

### 3.1 Top-level navigation

```
┌────────────────────────────────────────────────────────────────┐
│  Wabot   [Overview] [Agents] [Tools] [Integrations] [Activity] │
│                                                  ⚙  👤  ⏻      │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│                    <active view here>                          │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

The status pill, pair button, and slide-over launchers move into the top-right cluster so the existing flows are preserved.

### 3.2 Overview (default landing)

Four KPI cards over four widget rows:

```
┌─ Messages today ──┐  ┌─ Agent runs ─────┐  ┌─ LLM cost (24h) ─┐  ┌─ Integrations ──┐
│   1,284  ↑ 12%    │  │  342  ↑ 4%       │  │   $3.81  ↓ 8%    │  │  7 OK · 1 error │
└───────────────────┘  └──────────────────┘  └──────────────────┘  └─────────────────┘

[ Inbox volume (line chart, 24h) ]    [ Top tools used (bar) ]
[ Runs by subagent (stacked) ]        [ Recent errors (list)  ]
```

Data sources:
- **Messages today** — `inbound_messages` row count where `received_at >= today`.
- **Agent runs** — `runs` row count for today (already populated).
- **LLM cost** — see §4.4.
- **Integrations** — `mcp_servers.health_status` + `composio_connections.status` + Wabot daemon health.

### 3.3 Agents view

```
┌─ Agents ───────────────────────────────────────────────┬─ Editor ──────────────────┐
│  + New agent                                           │ name: scraper             │
│  ● orchestrator      (builtin · root)                  │ instructions:             │
│  ● scraper           (builtin · 12 tools)              │ ┌───────────────────────┐ │
│  ● memory_keeper     (builtin · 7 tools)               │ │ You are the web      ▲│ │
│  ● comms             (builtin · 22 tools)              │ │ research specialist… ▼│ │
│  ● scheduler         (builtin · 9 tools)               │ └───────────────────────┘ │
│  ● inboxer           (builtin · 6 tools)               │                           │
│  ● my-researcher     (custom · 3 tools)                │ Tools  [ + add from cat.] │
│                                                        │   ✓ search_web            │
│                                                        │   ✓ fetch_url_to_media    │
│                                                        │   ✓ search_images         │
│                                                        │                           │
│                                                        │ Skills [ + install ]      │
│                                                        │   ✓ web-research          │
│                                                        │                           │
│                                                        │ Parent: orchestrator      │
│                                                        │ Handoff filter: none      │
│                                                        │                           │
│                                                        │ [ Test run ]  [ Save  ]   │
└────────────────────────────────────────────────────────┴───────────────────────────┘
```

**Test run** opens a side panel with a single prompt input, posts to `POST /api/agents/{slug}/test`, and streams the transcript. This lets the user validate instructions before flipping `is_enabled`.

### 3.4 Tools catalog

Tabs: `Native`  ·  `MCP`  ·  `Composio`  ·  `Skills`.

Each row shows: name, source ref, description, "assigned to" pill list, last-used timestamp, enable toggle. Clicking a row opens a drawer with full schema + a multiselect of agents.

### 3.5 Integrations view

Three sections:

1. **Skills** — list of installed skills, "Install from zip" upload zone, "Browse registry" button → modal with search results.
2. **MCP servers** — list with health dots, "Add server" form (transport, command/args/env or url/headers), "Browse registry" button. Per-server `Check` button calls `POST /api/mcp/servers/{id}/check`.
3. **Composio** — API key status, `Connect` flow:
   - If no key: prompts for API key (POST `/api/composio/api-key`).
   - If key present: lists toolkits with current connection status; clicking `Connect` for an app calls `POST /api/composio/connections` and opens the returned redirect in a new tab; polls `/api/composio/status` and `/api/composio/connections` until it resolves.

### 3.6 Activity view

Reuses the existing `RunsPanel` data plus three new tabs:

- **Runs** — table with filter by agent, status, time window.
- **Inbox** — recent `inbound_messages` with reply previews from `outbound_tasks`.
- **Tool events** — drawn from `tool_events` (already populated).
- **Costs** — per-day stacked area by provider/model.

### 3.7 Component scaffolding

Mirror the existing patterns (`SettingsPanel.tsx` + `settings/*.tsx` for subsections):

```
web/src/
  pages/
    OverviewPage.tsx
    AgentsPage.tsx
    ToolsPage.tsx
    IntegrationsPage.tsx
    ActivityPage.tsx
  components/
    nav/
      AppNav.tsx
    agents/
      AgentList.tsx
      AgentEditor.tsx
      InstructionsEditor.tsx
      ToolAssignment.tsx
      TestRunDrawer.tsx
    tools/
      ToolCatalogTabs.tsx
      ToolDetailDrawer.tsx
    integrations/
      SkillsSection.tsx
      McpServersSection.tsx
      ComposioSection.tsx
      RegistryBrowserModal.tsx
    metrics/
      KpiCard.tsx
      RunsChart.tsx
      ToolUsageChart.tsx
      CostChart.tsx
  api/
    agents.ts
    tools.ts
    skills.ts
    mcp.ts
    composio.ts
    metrics.ts
```

---

## 4. Important data — sourcing

### 4.1 WhatsApp inbox & sends

- **Inbox** — `inbound_messages` table (already exists). `/api/metrics/overview` selects today's count; `/api/metrics/runs` provides time-bucketed series via `strftime('%Y-%m-%d %H:00', received_at)`.
- **Sends** — `outbound_tasks` table (already exists) joined with `processed_messages` for ack state. Compute success rate as `count(status='delivered') / count(*)`.
- **Queue depth** — `select count(*) from outbound_tasks where status='pending'`.

### 4.2 Agent activity

- `runs` table already records each turn; we add columns (`subagent_slug`, `prompt_tokens`, `completion_tokens`, `cost_usd`) via additive migration. Backfill is unnecessary — these are new fields.
- `tool_events` already records tool calls; the dashboard reads it directly for "top tools used".

### 4.3 Integration health

- **MCP** — `/api/mcp/servers/{id}/check` opens the server once via existing `connected_mcp_servers` plumbing (`mcp.py:89–106`), lists tools, writes `health_status` + `last_checked_at`. A scheduled background task runs all enabled servers every 10 minutes.
- **Composio** — `composio.toolkits.get(app)` to verify each row in `composio_connections`. Same 10-minute cadence.
- **Wabot daemon** — reuses existing `wabot_health` tool via the routes that already proxy it.

### 4.4 Cost & usage

New module `src/wabot_agent/usage_tracking.py`:

- Hook into the agents SDK's `on_response` callback to record `prompt_tokens`, `completion_tokens`, `model`, `provider` per turn.
- Maintain a static price table (`data/llm_prices.json`, editable in UI under Settings → Costs) with `$/1M prompt`, `$/1M completion` per model.
- Compute `cost_usd` at write time so historic queries don't need to re-price.
- `/api/metrics/costs` aggregates by `date_trunc('day', ...)` (sqlite `strftime`) grouped by provider/model.

---

## 5. Phased delivery

Six phases, each independently shippable. Each phase ends with the dashboard still fully usable.

### Phase 1 — Schema + seed (1–2 days)

- Append migrations to `_migrations.py`.
- Write `seed_builtin_subagents()`, `import_mcp_config_file()`, `seed_tools_catalog()` (scans `core_tools()` to populate `tools` rows for native).
- Unit tests for migration idempotency + seed determinism under `tests/test_agents_registry_migrations.py`.

**Acceptance:** fresh DB and existing DB both end up with the same 6 builtin subagents + native tool catalog after boot.

### Phase 2 — Runtime registry (2–3 days)

- New `agents/registry.py` with `load_subagent_specs`, `build_dynamic_agent`, `build_orchestrator_from_db`.
- Wire `agent.py:550–556` to prefer the DB path when `settings.subagents_db_enabled` is true; default false during rollout.
- Update `instructions_cache` cache key.
- Test: orchestrator built from DB with default seed produces same behavior as today (snapshot test on the resolved Agent's instruction string + tool list).

**Acceptance:** with the new flag on, behavior is byte-identical to today's hardcoded orchestrator.

### Phase 3 — Agents + Tools API + UI (3–5 days)

- Routes: `agents.py`, `tools_catalog.py`.
- React: `AgentsPage`, `ToolsPage`, supporting components.
- `POST /api/agents/{slug}/test` runs the agent in a temporary one-shot loop without going through wabot — useful for instruction iteration.

**Acceptance:** user can create a new agent in the UI, assign 3 native tools to it, set it as a child of `orchestrator`, save, and see it routed to when invoking from WhatsApp.

### Phase 4 — Skills + MCP install (3–4 days)

- Routes: `skills_admin.py`, `mcp_admin.py`.
- React: `IntegrationsPage` skills + MCP sections + `RegistryBrowserModal`.
- Registry sources: ship a curated `data/mcp_registry.json` and `data/skills_registry.json` in v1; add Anthropic/Composio registry adapters in v1.1.

**Acceptance:** user uploads a `.skill` zip and a curated MCP, assigns them to an agent, restarts is not required.

### Phase 5 — Composio UI (2–3 days)

- Route: `composio.py`. Reuses `composio_tools.py:38–185` plumbing.
- React: `ComposioSection` with API key form + per-app connect flow.
- `secrets_service.py` for `.env`/`runtime_secrets.json` write-back.

**Acceptance:** user pastes a Composio API key, sees 100+ toolkits listed, connects Gmail, sees a row appear in `composio_connections` with status `connected`.

### Phase 6 — Overview + Activity + Costs (2–3 days)

- Route: `metrics.py`.
- New `usage_tracking.py` and price table.
- React: `OverviewPage`, `ActivityPage`, KPI cards, charts. **Add `recharts` to `web/package.json`** — no charting lib is installed today (stack is Blocknote + Clerk + Lucide + Zustand + Tailwind).
- Background task runner for the 10-minute health checks.

**Acceptance:** Overview shows live KPIs; Activity tab shows the last 100 runs with filters.

---

## 6. Risks & open questions

| Risk | Mitigation |
|---|---|
| Per-tool MCP filtering needs SDK changes | v1 scope = enable/disable at server level. Add per-tool filter in v1.1 once we shim `MCPServer.list_tools()`. |
| Secrets in DB | Keep secrets in `runtime_secrets.json` + `.env`; only opaque metadata in DB. |
| Custom agent loops/hallucinated handoffs | Validate at save time that `parent_slug` exists; disallow cycles. |
| Composio rate limits on toolkit listing | 5-min server-side cache; refresh button. |
| `.skill` zip sandbox | Reject zips with absolute paths or symlinks; extract into `skills_dir/<slug>/` and refuse overwrite. |
| Cache invalidation on edit | Bump `subagents_updated_at` in the existing `instructions_cache` key (already mtime-based — pattern proven). |

### Open questions for Tony before Phase 1

1. **Auth.** Should the new admin endpoints require the operator token (same as today's `/api/settings`), or do you want a separate role? My default: same operator token.
2. **`.skill` zip format.** Anthropic's Cowork ships `.skill` as a zip of `SKILL.md` + scripts. Are we matching that exactly, or do you want a wabot-specific manifest (e.g. tool exports declared in `SKILL.toml`)?
3. **MCP registry source.** Curated JSON shipped in-repo is the simplest v1. Do you also want to plug into the Composio MCP registry (`mcp.composio.dev`) as a second source, or wait?
4. **Cost prices.** Are you OK with us shipping a default price table you can edit, or do you want to source live from each provider's pricing API?

---

## 7. Out of scope (v1)

- Multi-tenant agent configs (one user / one workspace today).
- Programmatic skill-as-tool (skills remain prompt-injected).
- Visual flow builder for handoffs (we expose `parent_slug` + `handoff_filter` as form fields, not a canvas).
- Tool sandboxing beyond what the agents SDK already provides.
- Rollback/versioning of agent edits — we can add an `agent_revisions` table in v1.1 if you want history.
