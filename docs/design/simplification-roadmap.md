# Simplification Roadmap — plain-language plan

**Author:** Teddy, with Claude as drafting partner
**Date:** 2026-05-23
**Status:** Proposed
**Doc validation:** Model names + OpenAI Agents SDK API verified against current vendor docs on 2026-05-23. See "Validation citations" at the bottom for sources.

This document is the plain-language plan for tightening up `wabot-agent` after the May 2026 split refactors landed. It also introduces a new user-facing feature — per-purpose model selection — and an optional architectural upgrade (specialized subagents). It's written so a non-coding stakeholder can follow it.

---

## What you'll have at the end

**Today** the bot has one model setting that applies to everything. Every WhatsApp reply, every memory operation, every web scrape — all go through the same model. Settings live in three different places that can disagree with each other (we saw that break the deploy this morning). The main agent has 50+ tools attached to a single prompt. Half the code in `api/__init__.py` is wiring boilerplate.

**After this roadmap:**

1. **One settings table** that picks a different model for each kind of work. Chat reply: cheap fast model. Web scraping: smart model. Memory extraction: tiny local model. You mix and match.
2. **Specialized subagents** (optional but recommended) that each own one slice of the tools. The bot has a "scraper" subagent that uses your scraping-grade model, a "memory keeper" that uses your cheap model, a "comms" subagent that handles outbound messages with the right send-policy gating, and so on.
3. **One source of truth for settings** — the kind of mismatch that broke today's deploy can't happen.
4. **Half the code in `api/__init__.py` gone**, split into per-family route files.
5. **The race-condition bugs CodeRabbit flagged** are fixed.

---

## The new feature: pick a model per purpose

The settings panel grows a new section. Something like this:

| What it does | Provider | Suggested model (verified May 2026) | Default if unset |
|---|---|---|---|
| Reply to WhatsApp messages | OpenAI | `gpt-5.5-mini` | the global default |
| Decide which tool to call | OpenAI | `gpt-5.5` (flagship) | the global default |
| Extract memories (Mem0) | Ollama | `gemma4:e4b` (or `gemma4:26b` MoE) | the global default |
| Web scraping & research | OpenRouter | `anthropic/claude-sonnet-4-6` | the global default |
| Transcribe voice messages | OpenAI | `gpt-4o-transcribe` (cheap: `gpt-4o-mini-transcribe`) | the global default |
| Look at images you send | OpenAI | `gpt-5.5` (cheap: `gpt-5.5-mini`) | the global default |
| Slow background research jobs | OpenRouter | `deepseek/deepseek-v4-pro` (cheap: `deepseek/deepseek-v4-flash`) | the global default |

Each row is independent. Leave a row on "default" and it falls back to whatever the global `model_provider` is. Switch one row to a different provider and only that purpose changes. The bot decides which row to use based on what it's doing — you don't have to think about it.

Behind the scenes, every place in the code that needs a model calls `get_model_for(purpose='chat')` or `get_model_for(purpose='scraping')`. The registry hands back the right provider client. Adding a new purpose later (e.g. "OCR") is one row.

**Additional models the registry should expose in the dropdowns** (verified May 2026):
- **OpenAI:** `gpt-5.5`, `gpt-5.5-mini`, `gpt-5.4-mini`, `gpt-5.4-nano`, plus dated snapshots like `gpt-5.5-2026-04-23` for reproducibility-critical work.
- **Anthropic** (via OpenRouter): `anthropic/claude-opus-4-7`, `anthropic/claude-sonnet-4-6`, `anthropic/claude-haiku-4-5`. (Note: Anthropic moved to a "pinned dateless snapshot" convention — IDs without dates are now valid pins.)
- **DeepSeek** (via OpenRouter): `deepseek/deepseek-v4-pro`, `deepseek/deepseek-v4-flash`. The V3 series is deprecated.
- **Mistral** (via OpenRouter): `mistralai/mistral-large` (Large 3 2512), `mistralai/mistral-small-2603` (Small 4) — 262K context, $0.15/$0.60 per MTok.
- **Embeddings (Mem0 vector layer):** `text-embedding-3-small` (Mem0 default), `text-embedding-3-large` (higher precision). No `text-embedding-4` exists as of May 2026.

These were all verified against the vendor docs as of 2026-05-23. The roadmap previously listed `gpt-4o`, `claude-sonnet-4-5`, `gemma3-12b`, `whisper-1`, and `deepseek-v3` — all stale or non-existent. If you're pinning to a dated snapshot in production, use OpenAI's `gpt-5.5-2026-04-23`-style format; otherwise the rolling alias is fine for non-reproducibility-critical work.

---

## The optional upgrade: subagents

**Are subagents "too much"?** Short answer: no, they're a clean fit because the tools already cluster by family (we just split them in ME-2). But they're the biggest lift in this plan, so they're framed as **optional Phase 5** — the per-purpose feature works fine without them.

**What they are.** Right now there's one big agent with 53 tools attached to a single prompt. Every inbound message asks that agent. Subagents split this into a small "orchestrator" that reads the message and **hands off** to a specialist:

- **Scraper** — owns `search_web`, `search_images`, `fetch_url_to_media`, `web_research_*`, `process_vps_file`. Uses your scraping-grade model.
- **Memory keeper** — owns `recall_*`, `remember_*`, `mem0_*`. Uses your cheap model.
- **Comms** — owns `send_whatsapp_*`, react/edit/revoke, typing/read, group management. Uses your chat model (and inherits the send-policy chokepoint).
- **Scheduler** — owns reminders + outbound tracking + progress updates. Cheap model is fine.
- **Inboxer** — owns inbox + contact lookup + profile-pic download. Read-only.

**The orchestrator has zero domain tools** — only a handoff tool per subagent. Its job is "read the message, pick the specialist".

**Why this is worth doing:**

- Cheaper inference. The scraper agent doesn't need to know about WhatsApp send rules; the comms agent doesn't need to know about web fetching. Smaller tool list per agent = smaller context window = lower cost per call.
- Better matching. Use a smart model only where smartness pays off (research), and a cheap model where it doesn't (memory writes).
- Easier evolution. You can rewrite "how the scraper thinks" without touching messaging.
- Easier testing. Eval cases can target one subagent.

**The honest tradeoff:** subagents add moving parts. There's now an "orchestrator picks the right subagent" decision that can fail. The OpenAI Agents SDK handles this cleanly with handoffs, but it's still more surface area than today's one-big-agent design. Phase 5 is where you decide whether to take it on.

---

## The plan, in 6 phases

Each phase is a discrete chunk of work. They're ordered so each one stands on the previous, but the dependencies are loose — you can stop after any phase and the system is in a strictly better state than today.

### Phase 1 — Provider Registry (1-2 days)

**What it is.** One file (`src/wabot_agent/providers.py`) that lists every model provider as a row in a registry. Each row says: this provider's name, its secret-key field, its base-URL field, its URL safety rule, its test endpoint.

**Why.** Adding OpenAI in PR #57 touched 11 different files. After this phase, adding (say) Anthropic touches 1 file + 1 TSX component. The same registry feeds the per-purpose dropdowns in Phase 2 — if you add Mistral to the registry, it automatically shows up as an option for every purpose row.

**What you can do after.** Adding a new provider is ~50 lines instead of ~300. The dashboard's allowed providers always match the code's allowed providers — the bug class that broke today's deploy goes away.

**Risk.** Very low. Pure refactor, no behavior change.

### Phase 2 — Per-Purpose Model Selection (2-3 days)

**What it is.** Replace the single `model_provider` setting with a `ModelRouting` table keyed by purpose. Add a `get_model_for(purpose)` helper. Update the 5-8 places in code that need a model to call that helper. Build the table UI in the settings panel.

**Why.** This is the headline new feature. It also makes the bot cheaper — most purposes don't need a top-tier model.

**What you can do after.** Switch web scraping to Claude without affecting chat. Use a free local model for memory extraction. Run a vision-capable model only for image messages.

**Risk.** Low. If a purpose has no entry in the table, it falls back to the global default (today's behavior). So old configurations keep working.

### Phase 3 — SettingsService (1 week)

**What it is.** A `SettingsService` class with three methods: `read()`, `patch(changes)`, `subscribe(callback)`. Every settings mutation goes through it. The 137-line PATCH handler in `api/__init__.py` shrinks to ~5 lines. The `runtime_overrides.json` file becomes an implementation detail of the service.

**Why.** Today's deploy broke because `runtime_overrides.json` held a value the code didn't accept (`model_provider: 'openai'` before OpenAI was a valid Literal). With SettingsService, every PATCH is schema-validated against the live `Settings` class — drift becomes impossible.

**What you can do after.** Reactive settings. The wabot endpoint resync (currently inline in the PATCH handler) becomes a subscriber. The settings service can broadcast over the SSE hub so the dashboard reflects changes from any source.

**Risk.** Medium. Touches every settings flow. The design doc is already at `docs/design/sr-1-settings-service.md`.

### Phase 4 — Finish the route extraction (1-2 weeks, in parallel)

**What it is.** Continue what ME-1 Part 2 started. `api/__init__.py` still has ~50 inline route closures in `create_app`. Extract them into `api/routes/{auth,pages,chat,inbound,memory,settings,groups,pairing}.py`, one PR per family.

**Why.** `api/__init__.py` is currently 1500 LOC and absorbs every new endpoint. After this it's ~250 LOC of just lifespan + state wiring.

**What you can do after.** A new contributor reads one 200-LOC file to understand "the groups API" instead of grepping a monolith. Each route file is independently testable. Each PR is small and reviewable.

**Risk.** Very low. Mechanical moves with stable re-exports — same pattern that worked for ME-2 and ME-3.

### Phase 5 — Subagents (1-2 weeks, *optional*)

**What it is.** Refactor `agent.py` into an orchestrator + 4-5 specialized subagents. Each subagent picks its model via `get_model_for(purpose=...)` from Phase 2. The orchestrator has handoff tools instead of domain tools.

**Why.** The cost and clarity wins described above.

**What you can do after.** Test each specialty in isolation. Swap models per specialty without rebuilding the agent loop. Add new specialties (e.g., a "code-review" agent for engineering channels) without growing the main agent's tool list.

**Risk.** Medium-high. Agent routing behavior changes shape. Run behavioral eval cases (`evals/cases.jsonl`) before and after to confirm no regression. Start with two subagents (scraper + comms) and grow from there.

**SDK stability caveat (May 2026):** the OpenAI Agents SDK is on `0.Y.Z` semver and OpenAI's release docs explicitly reserve the right to make breaking changes between minor versions. Their April 2026 "next evolution" post flags subagents/code-mode as still-evolving. Pin the SDK version in `pyproject.toml` and review the changelog before bumping. None of this blocks Phase 5 — but plan for a minor migration each time you upgrade.

**Skip-if.** Phase 2 already delivers the user-facing "different model per purpose" win. Phase 5 layers in cost optimization + clean tool routing on top. If the cost savings don't matter to you, skip Phase 5 and stop after Phase 4.

### Phase 6 — Small cleanup PRs (2-3 days)

Three independent small wins:

- **Fix the three race conditions** CodeRabbit flagged (#51, #52, #53). SQL one-liners. Real correctness bugs under load.
- **Delete the dashboard chat path.** The roadmap (`plan.md` P2) already says it's deprecated; deleting it removes `/api/chat`, `/api/chat/stream`, and a fair chunk of `App.tsx` + the Zustand store.
- **Audit and prune unused @function_tool entries.** A grep across recent agent runs would surface tools that haven't been invoked in 30 days. If any cluster of tools is dead, it goes.

**Risk.** Very low. Each is independently revertable.

---

## Suggested orderings

| You have | Do these phases | What you get |
|---|---|---|
| One week | 1 + 2 | The new per-purpose UI works end to end |
| Three weeks | 1 + 2 + 3 + 6 | Plus settings consolidation + bug fixes |
| Six weeks | All six | Subagents + finished route extraction + everything above |

Phases 4 (route extraction) and 6 (cleanup) can run **in parallel** with the others — they don't touch the same files. If you delegate Phase 4 to a contractor and work Phases 1→2→3→5 yourself, the wall-clock time is ~3 weeks for the full plan.

---

## What I'd start with right now

**Phase 1 (Provider Registry).** Two reasons:

1. It's the lowest-risk piece of work in the plan. Pure refactor, no user-visible change.
2. It de-risks every later phase. Phase 2's dropdowns iterate the registry. Phase 3's settings schema reads from the registry. Phase 5's subagents pick their model from a `get_model_for(purpose)` call that reads the per-purpose map keyed against the registry.

After Phase 1 lands, Phase 2 is a ~2-day ride: add the `ModelRouting` field, add the table UI, change ~6 call sites to use `get_model_for(...)`.

---

## What NOT to do

- **Don't start subagents (Phase 5) before the registry + per-purpose map.** Subagents are useful because they pick the right model per specialty. Without the registry, you'd hard-code model strings into each subagent, which defeats the point.
- **Don't deprecate the `VIGNESH_*` env aliases.** 96 occurrences, intentional, no benefit. The MASTER doc explicitly keeps them.
- **Don't replace SQLite with Postgres.** Single-VPS deploy is the right architecture for this product.
- **Don't bundle in-flight work into mechanical-refactor PRs.** That's exactly what bit us this morning — the OpenAI provider work was sitting in the unstaged tree of a "no behavior change" PR, leaked into the deploy, then the cleanup deploy broke because the live config depended on the leaked work. Use feature branches.
- **Don't ship Phase 3 (SettingsService) without behavioral eval coverage.** Settings PATCH is the load-bearing interface for the entire ops surface. Make sure the existing test_api.py tests pass without modification before merging.

---

## Where this fits with the existing SR design docs

- **SR-1 (SettingsService)** = Phase 3 of this plan. Design doc already at `docs/design/sr-1-settings-service.md`.
- **SR-2 (Domain layer extraction)** = a future evolution after Phase 5. The "domain" idea naturally collapses into subagents — once each subagent has a focused tool set, its tools become the domain. Re-evaluate SR-2 after Phase 5.
- **SR-3 (useChatStream hook)** = unrelated, frontend-only. Land independently.
- **SR-4 (DB migrations)** = wait until you need a non-additive schema change. `_ensure_column` handles every change you're doing today.

---

## Design decisions (resolved 2026-05-23)

1. **Per-purpose UI surface — show only the 3-4 the operator actually cares about.**
   The default settings view shows four rows: **Chat reply**, **Web scraping**, **Memory extraction**, **Vision**. Other purposes (tool reasoning, transcription, background research) sit behind a "Show advanced" toggle. Each row defaults to the global model — the operator only configures a row when they want it to differ.
2. **Default purpose mapping on a fresh install — every purpose falls back to the global default.**
   This preserves today's behavior. New operators discover the feature when they want to optimize.
3. **Subagent handoff — pass only the context the specialist needs, not the full conversation.**
   The orchestrator's handoff tool builds a focused payload per subagent: the inbound message, the sender JID, the conversation summary, and the specific instruction (e.g., "scrape https://example.com and summarize"). The subagent does not see unrelated parts of the conversation.

   The OpenAI Agents SDK exposes this through the `handoff(...)` helper's **`input_filter`** parameter — a callable with signature `(HandoffInputData) -> HandoffInputData` that rewrites the history before the specialist sees it. `HandoffInputData` is a dataclass with `input_history`, `pre_handoff_items`, `new_items`, and `input_items` fields, so the filter has full visibility into what to strip.

   The SDK ships prebuilt filters in `agents.extensions.handoff_filters` — `remove_all_tools` is the one we'll start with for the scraper and inboxer specialists (they don't need to see the orchestrator's tool history). Custom filters per subagent live next to their definition in `src/wabot_agent/agents/<name>.py`.

   A global default filter can be set on `RunConfig.handoff_input_filter` if we want a project-wide baseline (e.g., always strip tool history) that individual `handoff(...)` calls override.
4. **Each subagent owns its identity, prompt, and tool set.**
   One file per subagent under `src/wabot_agent/agents/`:
   - `agents/scraper.py` — name="scraper", prompt focused on "you fetch and summarize web content", tools = web family + media.process_vps_file.
   - `agents/memory_keeper.py` — name="memory_keeper", prompt focused on "you write and recall facts", tools = memory family.
   - `agents/comms.py` — name="comms", prompt focused on "you send messages within send-policy", tools = messaging + groups.
   - `agents/scheduler.py` — name="scheduler", prompt focused on "you schedule reminders and track outbound", tools = scheduling + progress.
   - `agents/inboxer.py` — name="inboxer", prompt focused on "you read inbox and look up contacts", tools = inbox.
   - `agents/orchestrator.py` — name="orchestrator", prompt focused on "you read inbound messages and hand off to the right specialist", tools = handoff tool per subagent (no domain tools).

   Each subagent registers itself in `agents/__init__.py:registry` (analogous to the provider registry from Phase 1). The orchestrator iterates the registry to build its handoff tools — adding a new specialist is one file + one registry entry.

   **Prompt-side discipline:** every subagent's instructions should be prefixed with `agents.extensions.handoff_prompt.RECOMMENDED_PROMPT_PREFIX` (a short SDK-provided preamble that tells the agent it can be handed off to and how to behave). Skipping this is a common bug source where the specialist forgets it's part of a multi-agent system.

---

## Validation citations (as of 2026-05-23)

All model names and SDK API references in this document were verified against vendor docs by a research pass on 2026-05-23. Sources:

**OpenAI**
- Models: https://platform.openai.com/docs/models
- GPT-5.5 launch: https://openai.com/index/introducing-gpt-5-5/
- GPT-5.5 API: https://developers.openai.com/api/docs/models/gpt-5.5
- Transcription (gpt-4o-transcribe): https://developers.openai.com/api/docs/models/gpt-4o-transcribe
- Speech-to-text guide: https://developers.openai.com/api/docs/guides/speech-to-text
- Images & vision: https://developers.openai.com/api/docs/guides/images-vision
- Embeddings: https://openai.com/index/new-embedding-models-and-api-updates/

**Anthropic**
- Model IDs and versions: https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions
- Lineup (third-party summary): https://www.knightli.com/en/2026/05/08/anthropic-claude-model-lineup/

**Google / Gemma**
- Gemma 4 launch: https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/
- Ollama library: https://ollama.com/library/gemma4

**DeepSeek**
- V4-Pro on OpenRouter: https://openrouter.ai/deepseek/deepseek-v4-pro
- V4 writeup: https://simonwillison.net/2026/apr/24/deepseek-v4/

**Mistral**
- OpenRouter listings: https://openrouter.ai/mistralai

**OpenAI Agents SDK (Python)**
- Agent reference: https://openai.github.io/openai-agents-python/agents/
- Handoffs reference: https://openai.github.io/openai-agents-python/handoffs/
- Handoff filters extension: https://openai.github.io/openai-agents-python/ref/extensions/handoff_filters/
- Release process / stability notes: https://openai.github.io/openai-agents-python/release/
- "Next evolution" 2026-04 post: https://openai.com/index/the-next-evolution-of-the-agents-sdk/

**Mem0**
- LLM config: https://docs.mem0.ai/components/llms/config

The prior version of this document (drafted before the validation pass) listed `gpt-4o`, `claude-sonnet-4-5`, `gemma3-12b`, `whisper-1`, and `deepseek-v3` — all stale or non-existent. The model table and Agents SDK API references in this version are the corrected set. If you're revising this doc more than 60 days after 2026-05-23, re-run the validation against the URLs above before treating any specific model string as current.
