# SR-2: Tool implementations — extract domain layer

**Status:** Draft  
**Date:** 2026-05-23  
**Pre-req:** ME-2 (tools.py → tools/ package by family) — confirmed as the immediate upstream gate  
**Depends on (soft):** SR-1 design drafted before implementation starts (see section 10)

---

## 1. Decision

Extract a `src/wabot_agent/domain/` package that owns the substance of every tool call — validation, execution, and persistence — leaving `tools/` as a thin layer of `@function_tool` wrappers that do nothing except unpack SDK context and dispatch to domain functions. The fail-closed send-policy check, currently the load-bearing single chokepoint identified in `CLAUDE.md`, moves into a `SendPolicy` class in `domain/policy.py` with one definition and no inline copies. The `record_tool_event` side effect, which today appears 73 times across `tools.py`, becomes a `@audit` decorator in `domain/audit.py` that wraps any domain function and records success or failure without the domain function knowing it exists. After SR-2 lands, the domain layer is importable and unit-testable with plain mocks; no Agents SDK installation is required in the test environment for domain-level assertions.

---

## 2. Why now

ME-2 is the pre-req for SR-2 because SR-2 refactors into a stable family taxonomy that does not yet exist at the source level. Once ME-2 establishes `tools/messaging.py`, `tools/inbox.py`, and the rest, the family boundaries are fixed and the domain mirror can be cut cleanly. Attempting SR-2 against the 1807-line `tools.py` monolith would produce a migration branch that conflicts with ME-2 in progress.

Every `@function_tool` in `tools.py` currently conflates three responsibilities in a single function body. Taking `send_whatsapp_text` as the canonical example: validation runs at lines 585–586, where `_apply_send_policy_gate` checks media-path confinement, policy allowance, and daemon readiness in sequence; execution runs at line 589, where `ctx.context.wabot.send_text(to=to, text=text)` is called; and persistence runs at lines 593–594, where `ctx.context.memory.record_tool_event(...)` and `ctx.context.event_log.write(...)` are called directly inside the tool function. In `tools.py` (pre-ME-2 or equivalently in `tools/_common.py` post-ME-2), the gate itself is in `_apply_send_policy_gate` (lines 484–577), which duplicates the `_is_send_allowed` call pattern that also appears standalone in `auto_reply.py:55,101,144` and `web_research.py:224`. The mixing of these three concerns in every tool function is the structural problem SR-2 addresses.

---

## 3. Target layout

After SR-2, `src/wabot_agent/` gains a `domain/` package with the following modules:

- `domain/policy.py` — the `SendPolicy` class and all allow/deny logic; the single owner of the send-policy check.
- `domain/audit.py` — the `@audit` decorator that wraps domain functions and drives `record_tool_event` and `event_log.write` as a side effect.
- `domain/messaging.py` — validate + execute + persist for text sends, media sends, reactions, edits, revocations, typing presence, and read receipts.
- `domain/inbox.py` — validate + execute + persist for inbox listing, last-message lookup, and contact lookup.
- `domain/groups.py` — validate + execute + persist for all twelve group management operations.
- `domain/media.py` — validate + execute + persist for media download, profile-picture download, VPS file processing, and attachment processing.
- `domain/memory.py` — validate + execute + persist for contact memory recall, fact storage, agent notes, and Mem0 operations.
- `domain/scheduling.py` — validate + execute + persist for reminders, outbound task tracking, and web research job management.
- `domain/progress.py` — validate + execute + persist for task plan sends, step-complete pings, and progress updates.

`domain/skills.py` is intentionally omitted. The two skills tools (`list_local_skills`, `read_local_skill`) do no I/O against `wabot`, carry no send-policy gate, and have negligible validation logic — they are pure reads from the filesystem via `skills.py`. Wrapping them in a domain module would add indirection without adding testability or safety value. They stay as thin `@function_tool` wrappers calling `skills.list_skills` and `skills.read_skill` directly. `domain/web.py` is similarly lightweight but is included because `start_web_research` does carry an owner-session check and a `_is_send_allowed` call on the result destination; that check must route through `SendPolicy`.

`tools/health.py` (`wabot_health`) follows the same pattern as skills — no send gate, one wabot call, one `record_tool_event` — and may reasonably be left as a direct wrapper. This is a judgment call for the implementer; the guiding principle is that a domain twin earns its place when it has a policy check or when unit-testing the logic requires isolating from the Agents SDK runtime.

---

## 4. The SendPolicy class

`domain/policy.py` becomes the single location for all send-allow logic. `CLAUDE.md`, safety rule 1, states: "`_is_send_allowed()` in `tools.py` is the single chokepoint — every new send-like tool must route through an equivalent check." After SR-2, that sentence becomes: every new send-like domain function must instantiate or receive a `SendPolicy` and call `policy.check(to)`. The class signature is:

```python
from dataclasses import dataclass
from wabot_agent.config import Settings
from wabot_agent.memory import InboundMessage

@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    reason: str  # "dry_run" | "allow_all" | "allowlist" | "owner" |
                 # "reply_to_sender" | "reply_to_group_chat" |
                 # "recipient_not_allowed_for_non_owner" | "recipient_not_allowlisted"

class SendPolicy:
    def __init__(self, settings: Settings, inbound: InboundMessage | None = None) -> None: ...
    def check(self, to: str) -> PolicyResult: ...
    def is_owner_session(self) -> bool: ...
```

The body of `check` is a direct port of `_is_send_allowed` (currently `tools.py:73–98`). The `reason` strings are pinned as the exact literals already tested in `test_owner_policy.py` — changing them is a breaking change to the test contract and must be treated as such. No other module may implement send-allow logic independently. Callers in `auto_reply.py` and `web_research.py` that today import `_is_send_allowed` directly from `tools` will instead instantiate `SendPolicy` or receive it as a parameter.

---

## 5. Worked example: send_whatsapp_text

**Before SR-2** (`tools/messaging.py` after ME-2, shape identical to `tools.py:580–595` today):

```python
@function_tool
async def send_whatsapp_text(
    ctx: RunContextWrapper[RuntimeContext], to: str, text: str
) -> dict[str, Any]:
    """Send a WhatsApp text message through wabot when the send policy allows it."""
    _, reason, block = await _apply_send_policy_gate(ctx, "send_whatsapp_text", to)
    if block is not None:
        return block
    result = await ctx.context.wabot.send_text(to=to, text=text)
    ctx.context.record_sent(to)
    payload = {"sent": True, "policy": reason, "to": mask_phone(to), "result": redact(result)}
    _maybe_auto_track_outbound(ctx, to=to, send_result={"result": result})
    ctx.context.memory.record_tool_event(ctx.context.run_id, "send_whatsapp_text", payload)
    ctx.context.event_log.write("send_text", payload)
    return payload
```

**After SR-2** — the `@function_tool` wrapper in `tools/messaging.py` becomes:

```python
@function_tool
async def send_whatsapp_text(
    ctx: RunContextWrapper[RuntimeContext], to: str, text: str
) -> dict[str, Any]:
    """Send a WhatsApp text message through wabot when the send policy allows it."""
    return await domain.messaging.send_text(
        to=to,
        text=text,
        settings=ctx.context.settings,
        wabot=ctx.context.wabot,
        memory=ctx.context.memory,
        event_log=ctx.context.event_log,
        run_id=ctx.context.run_id,
        inbound=ctx.context.inbound,
        record_sent=ctx.context.record_sent,
    )
```

The domain function in `domain/messaging.py`:

```python
@audit("send_whatsapp_text", log_event="send_text")
async def send_text(
    *,
    to: str,
    text: str,
    settings: Settings,
    wabot: WabotClient,
    memory: MemoryStore,
    event_log: EventLog,
    run_id: str,
    inbound: InboundMessage | None,
    record_sent: Callable[[str], None],
) -> dict[str, Any]:
    policy = SendPolicy(settings, inbound)
    result = policy.check(to)
    if not result.allowed:
        return {"sent": False, "reason": result.reason, "to": mask_phone(to)}
    health = await wabot.health()
    if not health.ready:
        return {"sent": False, "reason": "wabot_not_ready", "to": mask_phone(to)}
    raw = await wabot.send_text(to=to, text=text)
    record_sent(to)
    return {"sent": True, "policy": result.reason, "to": mask_phone(to), "result": redact(raw)}
```

The `@audit` decorator (see section 6) intercepts the return value and drives `memory.record_tool_event` and `event_log.write` so the domain function does not call either directly.

---

## 6. The record_tool_event decorator

`domain/audit.py` defines `@audit(tool_name, *, log_event=None)`. It wraps a domain async function and, on normal return, captures the result dict and calls `memory.record_tool_event(run_id, tool_name, result)` plus, when `log_event` is not `None`, `event_log.write(log_event, result)`. On exception, it catches the exception, builds a failure payload — `{"ok": False, "reason": "internal_error", "detail": str(exc)}` — records it, and re-raises. The set of exception types it catches must be explicit and narrow: `WabotError` and `httpx.HTTPError` are caught and recorded; `BaseException` subclasses that signal interpreter state (`KeyboardInterrupt`, `SystemExit`, `GeneratorExit`) are never caught. This boundary is critical: today some tools bubble exceptions to the Agents SDK runner, which decides whether to retry; the decorator must preserve that behavior for exceptions outside its catch list. After SR-2, no domain function calls `memory.record_tool_event` directly; that call lives exclusively in the decorator.

---

## 7. Test seams unlocked

Domain functions take `settings`, `wabot`, `memory`, `event_log`, and `run_id` as plain arguments. They carry no `RunContextWrapper`, no `ToolContext`, no Agents SDK import. A unit test for `domain.messaging.send_text` needs only `unittest.mock.AsyncMock` for `wabot`, a real or stub `MemoryStore`, and a `Settings` object built from test values — the Agents SDK does not need to be importable in the test process at all. This matters because the Agents SDK runner currently bleeds into tests that should be pure policy assertions.

The most direct beneficiary is `tests/test_owner_policy.py`. Today it imports `_is_send_allowed` directly from `wabot_agent.tools` (line 6: `from wabot_agent.tools import _is_send_allowed`) and calls it as a pure function — which already works because `_is_send_allowed` has no I/O. After SR-2, the same tests import `SendPolicy` from `wabot_agent.domain.policy` and call `policy.check(to)`, with identical assertion bodies. The test gets simpler because it no longer depends on the tools module at all, and the import makes the test's intent clearer: it is a policy test, not a tool test. The send-policy tests scattered across `tests/test_tools.py`, `tests/test_phase4_tools.py`, `tests/test_phase5_tools.py`, and `tests/test_task_progress.py` can similarly migrate to direct domain-function calls, eliminating the `ToolContext` boilerplate that today accounts for roughly half the test setup in those files.

---

## 8. Migration plan

Phase 1 (2–3 days): Stand up `domain/policy.py` and `domain/audit.py` only. Move the `_is_send_allowed` body into `SendPolicy.check` with no behavioral change. Update `tools/_common.py:_apply_send_policy_gate` to instantiate `SendPolicy` internally and delegate — callers see no change. Update `auto_reply.py` and `web_research.py` to import from `domain.policy` instead of `tools`. Update `test_owner_policy.py` to import from `domain.policy`. Run the full offline suite; it must be green before Phase 2 starts.

Phase 2 (5–8 days): Migrate one family per PR, starting with `messaging` because it carries the highest safety value — the text-send path is the most exercised boundary in both production and tests. Then `media`, which has the second-most send-policy surface. Then `groups`, `inbox`, `scheduling`, `progress`. Each PR follows the same pattern: write the domain function, attach `@audit`, rewrite the `@function_tool` wrapper to dispatch, add a direct unit test for the domain function, confirm the existing integration test still passes. The PR should touch exactly two files: `tools/<family>.py` and `domain/<family>.py` — no other files.

Phase 3 (1–2 days): Delete `_apply_send_policy_gate` from `tools/_common.py`. Delete the per-tool `record_tool_event` calls from any remaining wrappers. Delete `_dry_run_block` and `_wabot_ready_or_block` from `_common.py` — their logic now lives inside `SendPolicy.check` and in the domain functions that call `wabot.health()`. Confirm that `tools/_common.py` no longer imports from `memory` directly (it should only import `MemoryStore` as a type for `RuntimeContext`). Total elapsed: 2–3 weeks.

---

## 9. Risks

- **Reason-string drift breaks the test contract.** `test_owner_policy.py` asserts exact string equality on reason values like `"recipient_not_allowed_for_non_owner"` and `"reply_to_sender"`. The move from `_is_send_allowed` to `SendPolicy.check` must preserve every string exactly. Before Phase 2 starts, grep all test files for these literals and add them to a `POLICY_REASONS` constants module that both `SendPolicy` and the tests import from. That way a rename fails at the constants definition, not silently at the assertion.

- **The @audit decorator could swallow exceptions that the Agents SDK runner uses for retry decisions.** The decorator must explicitly list the exception types it catches (`WabotError`, `httpx.HTTPError`) and re-raise everything else. Add a test that verifies an unexpected `RuntimeError` from a domain function propagates through the decorator to the caller without being converted to a failure dict.

- **Test patches on `wabot_agent.tools.X` will break.** Several tests use `unittest.mock.patch("wabot_agent.tools.send_whatsapp_text")` or similar. After SR-2, those patches need to point at `wabot_agent.domain.messaging.send_text` (for domain-level isolation) or at `wabot_agent.tools.messaging.send_whatsapp_text` (for integration-level isolation). Grep for `mock.patch.*tools` before Phase 2 starts and catalogue which layer each test is actually trying to isolate, then update the patch targets accordingly. This is unlikely to be a large number of sites, but failing to update them produces tests that silently stop exercising the real code path.

---

## 10. Pre-reqs

ME-2 must be complete before implementation begins. The family boundaries defined in ME-2 are the unit of work in SR-2 Phase 2; attempting Phase 2 against the monolithic `tools.py` would require the same split to happen twice.

SR-1 (`SettingsService.subscribe`) is not a hard blocker for SR-2, but the design of `SendPolicy` touches the same `settings` object that SR-1 proposes to manage through a subscriber model. Specifically, after SR-1, `wabot.endpoint` and `wabot.token` update via a subscriber rather than through direct mutation of the live `Settings` instance. `SendPolicy` reads `settings.send_policy`, `settings.allowed_recipients`, and `settings.owner_numbers` — all fields that SR-1 does not propose to make subscriber-driven. There is no direct conflict. However, if SR-1's `SettingsService` changes how the `Settings` object is passed to domain functions (for example, by introducing a `SettingsService.read()` call at function entry rather than passing the object at construction time), the `SendPolicy` constructor signature will need revisiting. Start SR-2 Phase 1 only after SR-1's design is at least drafted and the `SettingsService` public API is known; starting implementation before that risks a domain API that SR-1 immediately forces to change.

---

## 11. Out of scope

This document does not contain any implementation. No code changes accompany it.

The `_is_send_allowed` function name in `tools.py` (or `tools/_common.py` after ME-2) is not renamed for external callers outside the domain layer during this work. The re-export from `tools/__init__.py` that `api.py:70` depends on remains in place; removing it is a separate cleanup that can happen after all callers have been confirmed to route through `SendPolicy`.

The `@function_tool` registration order inside `core_tools()` is not changed. The Agents SDK presents tools to the model in registration order, and that ordering has been tuned for prompt-efficiency. SR-2 changes where tool bodies live, not which tools exist or what order they are registered.
