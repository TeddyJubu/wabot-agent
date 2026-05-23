# SR-1: Promote `runtime_overrides` into a proper settings service

**Status:** Design (not yet implemented)
**Prereqs:** ME-1 Part 2 landed (AppDeps dataclass + `create_app` restructure)
**Effort estimate:** 3–4 days implementation + tests

---

## Decision

We will introduce a `SettingsService` class in a new module `src/wabot_agent/settings_service.py` that owns every read, write, and change-notification operation on the runtime-mutable settings layer. The service exposes exactly three public methods: `read()`, `patch(SettingsPatch)`, and `subscribe(callback)`. All callers that today touch `load_overrides`, `save_overrides`, or `apply_overrides` directly will route through this interface instead. The PATCH route handler at `api/routes/settings.py` (the ME-1 destination file) shrinks from roughly 120 lines of inline business logic to a 5-line delegation. The `wabot.endpoint`/`wabot.token` re-sync that today appears as bare attribute assignments immediately after `apply_overrides` becomes a registered subscriber, wired at app boot.

---

## Why now

The override machinery is currently duplicated across three distinct call sites. First, `config.py:get_settings()` (lines 779–795) calls `load_overrides` and `apply_overrides` to build the initial `Settings` instance from `.env` plus the persisted JSON. Second, `api/__init__.py:create_app()` (lines 297–310) runs the same load-then-apply pair independently on the already-constructed `Settings` object, including its own snapshot-validation try/except block — a near-identical guard to the one in the PATCH handler. Third, the `update_settings` handler (lines 1158–1276, approximately 120 lines of inline logic) re-implements override loading, merging, snapshot validation, `save_overrides`, `apply_overrides`, URL-safety checks, the `allow_all` confirmation gate, and secret-blanking semantics all in one closure. The URL-safety helpers live in `api/dependencies.py` and are already extracted, but they are still called ad hoc from within the handler rather than being composed behind a service boundary. The result is that three different layers of the stack must each know the correct sequencing of load → validate-on-snapshot → save → apply; a bug fix or new validation rule has to be applied in all three. That coherence cost is what SR-1 eliminates.

---

## Public API

The service's interface is intentionally narrow. `SettingsPatch` is the existing Pydantic model from `api/schemas.py`; it migrates unchanged into the service module (or is imported from schemas — the exact import direction is an implementation detail). `Unsubscribe` is a zero-argument callable returned by `subscribe` so callers can deregister without holding a reference to the service internals.

```python
# src/wabot_agent/settings_service.py

from collections.abc import Callable
from typing import Protocol

from .api.schemas import SettingsPatch
from .config import Settings

Unsubscribe = Callable[[], None]

class SettingsService:
    def __init__(self, settings: Settings) -> None: ...

    def read(self) -> Settings:
        """Return the live Settings instance (read-only by convention)."""
        ...

    def patch(self, patch: SettingsPatch) -> Settings:
        """Validate, persist, apply, and notify. Returns the updated Settings."""
        ...

    def subscribe(self, callback: Callable[[Settings], None]) -> Unsubscribe:
        """Register a callback invoked synchronously after every successful patch."""
        ...
```

`patch` is synchronous. The URL-safety checks (`_require_loopback_url`, `_require_safe_openrouter_url`, et al.) are called inside `patch` before any disk write, so a bad input raises `ValueError` or `HTTPException` with no side effects. The PATCH route handler catches those and re-raises as appropriate HTTP responses — that translation stays in the route layer.

---

## Where overrides live

`data/runtime_overrides.json` is not renamed, reformatted, or migrated. The path is derived from `settings.runtime_overrides_path` as it is today, and the existing `load_overrides` / `save_overrides` / `apply_overrides` functions in `runtime_overrides.py` remain the I/O primitives; the service composes them rather than rewriting them. The atomic-write guarantee — `tempfile.mkstemp` in the same directory, `os.chmod(tmp, 0o600)`, `os.replace(tmp, target)` — is already correct in `save_overrides` and must be preserved verbatim. Any refactor that replaces this with a non-atomic write (e.g., `path.write_text`) would introduce a window where a crash leaves a half-written file, losing all overrides on next boot. The `0o600` permission is also load-bearing: the file holds plaintext API keys at the same trust level as `.env`.

---

## How subscribe reaches the SSE hub without a circular import

The `subscribe` mechanism exists to let the SSE hub (and anything else) react to settings changes without the service needing to import the hub. The resolution is directional: at app boot — in `create_app`, or via the `AppDeps` dataclass that ME-1 Part 2 introduced — the hub (or the wabot client re-sync shim) calls `service.subscribe(callback)` to register itself. The `SettingsService` module therefore never imports from `api/`, `api/routes/`, or the event hub; all imports flow inward toward the domain, not outward toward the framework. This is the same pattern used throughout the codebase for dependency injection: the thing that depends on a service receives it at construction time rather than importing it directly. Concretely, `create_app` instantiates `SettingsService(settings)`, then immediately calls `service.subscribe(lambda s: _sync_wabot_client(wabot, s))` and, if the SSE hub needs to emit a `settings_updated` event, `service.subscribe(lambda s: hub.publish("settings_updated", _settings_view(s)))`. Neither callback introduces a new import at the module level; they close over objects already available in `create_app`'s local scope. If `SettingsService` were instead given a reference to the hub at construction (`SettingsService(settings, hub=hub)`), it would force a hub import into `settings_service.py`, and any future split of the hub into its own package would drag the service along. Keeping the coupling unidirectional — hub knows about the service, service is unaware of the hub — is the decision that makes both sides independently testable.

---

## Behaviors preserved verbatim

**URL safety.** `wabot_endpoint` must resolve to a loopback host; `ollama_base_url` likewise; `openrouter_base_url` and `openai_base_url` must use HTTPS for any non-loopback host; `ollama_cloud_base_url` must be HTTPS to `ollama.com`; changing a base URL without supplying the corresponding API key in the same patch is rejected. These checks live in `api/dependencies.py` today and will be called from inside `SettingsService.patch` before the first disk write. Tests: `test_settings_patch_rejects_non_loopback_wabot_endpoint`, `test_settings_patch_rejects_plain_http_remote_openrouter`, `test_settings_patch_base_url_change_requires_new_key` in `tests/test_api.py`.

**Secret blanking on GET.** `read()` returns the live `Settings` instance; the route handler for `GET /api/settings` calls `_settings_view(service.read())` which applies `mask_secret()` to every `SECRET_FIELDS` member before serializing. The service does not own the view-building step — that stays in the route or in `api/views.py`. CLAUDE.md rule #7 is categorical: raw key values never leave the server over the wire. Test: `test_settings_get_masks_secrets`.

**Empty input means no change.** `SettingsPatch` fields are all `None` by default. `patch` calls `model_dump(exclude_none=True)` to build the proposed delta; a field absent from the request body is simply not in the dict and is not written to disk or applied to live settings. An empty-string value for a secret field is treated as an explicit clear (sets the field to `None`), not as "no change" — this distinction is in the current handler at line 1172 and must survive the refactor.

**`allow_all` requires `confirm_allow_all=true`.** Before any disk write, `patch` checks `if proposed.get("send_policy") == "allow_all" and not patch.confirm_allow_all` and raises. The UI supplies a `window.confirm()` to generate the flag; the service enforces it on the server side. Test: `test_settings_patch_allow_all_requires_confirmation`.

**`MUTABLE_FIELDS` mass-assignment guard.** Keys in the request body that are not in `MUTABLE_FIELDS` are silently dropped when building `proposed`. The guard exists in `load_overrides` (strips non-mutable keys on read), `save_overrides` (skips non-mutable keys on write), and `apply_overrides` (skips non-mutable keys on apply). The service composes all three, so a field that somehow slips into the patch dict cannot reach disk or live settings.

**Atomic write to `runtime_overrides.json`.** As described above, `save_overrides` must be called before `apply_overrides` on live settings. If the disk write fails, live settings remain unchanged; if `apply_overrides` fails after a successful disk write, the disk is authoritative and a restart recovers cleanly. `patch` must preserve this sequencing: validate on snapshot, save to disk, apply to live, notify subscribers — in that order, with no mutation of live state before the snapshot validation succeeds.

**Env-var override precedence.** `Settings` is constructed from `.env` (and environment variables) by `get_settings()`; the overrides file is applied on top. The service does not change this layering. `.env` fields never appear in `runtime_overrides.json` and the file cannot override non-mutable fields. Fields set by env vars that are also in `MUTABLE_FIELDS` (e.g., `OPENAI_API_KEY` sets `openai_api_key`) will be overwritten at boot by the overrides file if the operator has patched them — this is existing behavior and intentional; the overrides file is the runtime-mutable source of truth for those fields.

**`wabot.endpoint`/`token` re-sync after PATCH.** Today lines 1269–1270 of `api/__init__.py` read `wabot.endpoint = settings.wabot_endpoint.rstrip("/"); wabot.token = settings.resolved_wabot_token` immediately after `apply_overrides`. Under SR-1 this becomes a subscriber registered at boot. The subscriber fires synchronously inside `patch` after the live settings are updated, so the wabot client is in sync before `patch` returns and before the route handler serializes the response. Tests that POST to `/api/settings` and then POST to `/api/settings/test/wabot` in the same test process implicitly depend on this synchrony; the subscriber model preserves it.

---

## Open questions

- Should `patch` be made async to allow async subscribers (e.g., publishing an SSE event via the hub's async `publish` method)? The current handler is `async def` but calls only sync `save_overrides`/`apply_overrides`. A sync `patch` with sync subscribers is simpler; an async alternative would require an event loop reference inside the service.
- Does `SettingsService` need a lock for concurrent PATCH requests? Today the PATCH handler is a single async def with no explicit lock; two concurrent PATCH calls could interleave. Asyncio's cooperative concurrency makes this unlikely in practice (no `await` between load and save in the current handler), but the service's sync implementation should document whether it's safe under concurrent async callers.
- Should `SettingsService` absorb the `_settings_view` / secret-masking step and expose a `read_view() -> dict` method, or should view building remain in the route layer? Keeping it in the route layer is simpler for SR-1; a `read_view()` method would be valuable if the SSE hub emits masked settings in broadcast events.
- `codex_base_url` validation in `patch` currently imports `require_safe_codex_url` from `codex_auth.py` inline at the call site (line 1230 of `api/__init__.py`). Should `settings_service.py` take that dependency directly, or should codex URL safety be folded into the `dependencies.py` URL-guard module for consistency?
- After SR-1, `get_settings()` still calls `load_overrides`/`apply_overrides` directly at boot (lines 779–795 of `config.py`). Should `get_settings` be updated to delegate to `SettingsService`, or should the boot path remain separate to avoid instantiating the service before the app is constructed?

---

## Pre-reqs

ME-1 Part 2 has already landed: `create_app` is refactored to pass an `AppDeps` dataclass into each `register_*_routes(router, deps)` call, and `app.state.deps` is wired. This matters for SR-1 because it gives the `subscribe` wiring a clean home: `AppDeps` holds the `SettingsService` instance, and each route registrar that needs to subscribe (the wabot re-sync, the SSE hub publisher) calls `deps.settings_service.subscribe(...)` at registration time rather than inside a closure over `create_app`'s local scope. Without ME-1 Part 2 the subscriber registration would still be possible but would require threading the service through every closure manually.

---

## Out of scope

This document describes the design only; no implementation is included here. There is no schema migration for `runtime_overrides.json` — the file format (a flat JSON object keyed by `MUTABLE_FIELDS` names) is unchanged. The file is not renamed. No new fields are added to `MUTABLE_FIELDS` as part of this refactor; that is a separate policy decision. The `SettingsPatch` Pydantic model in `api/schemas.py` is carried forward as-is into the service layer without modification.
