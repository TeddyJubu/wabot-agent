# SR-3: Frontend chat-stream state machine — `useChatStream()` hook

**Status:** proposed  
**Author:** architecture review  
**Pairs with:** ME-6 (SettingsPanel split + `useCodexLogin`)

---

## 1. Decision

Extract a `useChatStream()` hook under `web/src/hooks/` that owns the chat stream state machine and dispatches into the existing Zustand store. The hook encapsulates the four-state lifecycle (idle → submitting → streaming → final / error), the NDJSON event dispatch loop, and the `requestAnimationFrame`-based delta batching. Consumers — initially `App.tsx` — call the hook and read the result `{ submit, pending, error }`; they continue to read the rendered message list directly from the Zustand store. The store remains the persistence and rendering source of truth; the hook is the coordinator that drives it.

---

## 2. Why now

The current shape is load-bearing in a brittle way. `App.tsx:81–138` (the `submit` function) acts as an inline state machine: it calls `addUser`, lazily creates the assistant message via the `ensureAssistant()` closure, dispatches into `appendDeltaBatched` / `attachCard` / `finishAssistant` / `flushDeltaBatch`, manages a `deltaSeen` flag, and handles both a `catch` block and a `finally` block that each call `flushDeltaBatch()` and `finishAssistant()`. That double-call in `finally` is already defensive redundancy — a sign the invariants are not enforced in one place.

Two concrete bug surfaces follow from this shape. First, the RAF leak: `appendDeltaBatched` in `store/index.ts:114–118` schedules a `requestAnimationFrame` via the module-level `scheduleDeltaFlush` helper. If any code path reaches an error or early return before calling `flushDeltaBatch()`, that RAF fires after the stream ends, writing accumulated delta text into a message that may already be finalized. The `finally` block at `App.tsx:135` is the guard, but it runs unconditionally — meaning a success path calls `flushDeltaBatch()` twice (once at `final` in line 118, once in `finally`), and a future refactor that removes the `final`-path flush while forgetting the `finally` guard will silently drop the last partial delta on errors. Second, the `ensureAssistant` ordering issue: the `deltaSeen` flag and the lazy `assistantId` are local variables in `submit`, so any caller (a retry wrapper, a test harness, a second invocation before the first resolves) that bypasses `submit` directly would need to reconstruct this ordering from scratch. There is no unit-testable seam between "parse one NDJSON event" and "drive the store" — they are fused into a single closure.

---

## 3. Public API

The hook exposes exactly this surface:

```typescript
interface UseChatStreamResult {
  submit: (prompt: string) => Promise<void>;
  pending: boolean;
  error: string | null;
}

function useChatStream(): UseChatStreamResult;
```

`messages` does not come back from the hook. Consumers read the message list directly from the Zustand store via `useStore((s) => s.messages)`, exactly as they do today. The hook drives store mutations; it does not replicate or mirror state. This keeps the hook's own re-render surface minimal — only `pending` and `error` are local state inside the hook, so the hook only re-renders its consumer when those two values change, not on every delta.

---

## 4. State machine

The hook's internal machine has four named states. Transitions are explicit and sequenced; no state is reachable by surprise.

```
State         Trigger to leave               Next state
──────────────────────────────────────────────────────
idle          submit(prompt) called          submitting
submitting    first delta event received     streaming
submitting    final / error event            final / error
streaming     final event received           final
streaming     error event received           error
final         submit(prompt) called again    submitting
error         submit(prompt) called again    submitting
```

`submitting → streaming` is the only transition that creates the assistant message in the store (via `startAssistant()`). Any state can transition to `error` on an unhandled network exception in the `catch` block. `final` and `error` are terminal for a given submission; the next `submit()` call resets to `submitting`.

---

## 5. Where the store fits

The boundary is clean: the hook is the state machine, the store is the persistence and rendering layer. The hook is the only writer during a stream; no other component calls `startAssistant`, `appendDeltaBatched`, `finishAssistant`, or `attachCard` during an active submission. The store retains its full action API — nothing is removed from the `State` interface in `store/index.ts` during SR-3. If the hook needs to read store state inside a callback (for example, to check whether an assistant message already exists), it calls `useStore.getState()` synchronously rather than subscribing via a selector. Using `useStore.getState()` inside async callbacks avoids stale-closure bugs that arise when a callback closes over a selector's return value from the last render before the `await`.

The `ensureAssistant`, `deltaSeen`, and RAF batching mechanics move into the hook body, which means consumers can no longer forget them. `ensureAssistant` becomes a `useRef`-held value (the assistant message ID) scoped to a single invocation of `submit`; it is cleared to `null` when the hook resets to idle. `deltaSeen` becomes a similar `useRef`. Because both are refs rather than state, updating them does not trigger re-renders. The store's `appendDeltaBatched` and `flushDeltaBatch` actions remain but are now called only from inside the hook — in step 3 of the migration (see §7), the internal `deltaBatch` map in `store/index.ts` may be simplified or inlined into the hook, but that is deferred to keep the blast radius of this PR small.

---

## 6. NDJSON parser and RAF batching

The hook owns the NDJSON parser as a small async generator that reads `ReadableStream` chunks from the `fetch` response body, buffers incomplete lines across chunk boundaries, and yields typed event objects (`{ type: "delta", text: string }`, `{ type: "tool_result", ui?: UiEnvelope }`, `{ type: "final", output?: string }`, `{ type: "error", message: string }`). The parser is the correct home for the "partial chunk" problem: a single `TextDecoder` chunk may contain half a JSON line, and the generator holds the incomplete fragment in a local buffer until the next chunk completes the line. This logic currently lives implicitly inside `postChatStream` in `web/src/api/chat.ts` (which provides an `onEvent` callback). The migration keeps `postChatStream` as a thin transport layer but lets the hook's generator drive iteration, giving tests a seam to inject a synthetic `ReadableStream` without touching the fetch layer.

RAF batching moves from the module-level `scheduleDeltaFlush` in `store/index.ts:61–84` into the hook's own `useRef`-managed timer. A `rafRef = useRef<number | null>(null)` holds the pending animation frame handle. When the hook receives a delta event, it appends to a `useRef`-held accumulator map and, if no RAF is already scheduled, calls `requestAnimationFrame` and stores the handle. The RAF callback flushes the accumulator into `appendDelta` (or directly calls `flushDeltaBatch`) and clears the handle. The hook's `useEffect` cleanup function — and the start of each new `submit` call — runs `cancelAnimationFrame(rafRef.current)` before doing anything else. This eliminates the leak described in §2: there is now exactly one place that schedules the RAF and exactly one place that cancels it, and both are inside the hook.

---

## 7. Migration plan

The migration runs in three sequential PRs over 2–3 days total, with no behavior change visible to the user at any step.

**Step 1** — Build `useChatStream()` and the NDJSON async generator as new files (`web/src/hooks/useChatStream.ts`, `web/src/hooks/parseChatStream.ts`) alongside the existing `usePairingStream.ts`. No consumer changes. The hook can be instantiated in isolation and tested against a synthetic `ReadableStream` without a running server.

**Step 2** — Replace the inlined `submit` function in `App.tsx:81–138` with a single call to `useChatStream()`. The local `pending` state (`useState` at `App.tsx:43`) is deleted; `pending` comes from the hook. The six store action selectors pulled from `useStore` at `App.tsx:31–35` (`appendDeltaBatched`, `flushDeltaBatch`, `appendDelta`, `finishAssistant`, `attachCard`, `startAssistant`) are deleted from `App.tsx`; the hook holds those references internally. This is a single-file change to `App.tsx`.

**Step 3** — Once the hook is the sole driver of `appendDeltaBatched` and `flushDeltaBatch`, the module-level `deltaBatch` map and `scheduleDeltaFlush` helper in `store/index.ts:58–84` can be simplified. The `flushDeltaBatch` action remains on the store interface (it is part of the public `State` type) but its implementation may be reduced to a no-op stub or removed entirely if the RAF accumulator now lives in the hook. This is the only step that touches `store/index.ts`, and it is purely a simplification — no new behavior, no API surface change.

---

## 8. Test seams unlocked

Three vitest specs become straightforward once the hook exists as a standalone module.

First: feed a synthetic `ReadableStream` of NDJSON events directly to the hook's async generator (bypassing `fetch` entirely), render the hook with `renderHook` from `@testing-library/react`, and assert that the Zustand store transitions through the expected states: `startAssistant` called once, `appendDelta` called with the right text, `finishAssistant` called exactly once, `pending` false on completion. This test requires no server, no `App.tsx`, and no component tree beyond the hook itself.

Second: feed N delta events in rapid succession and assert that the Zustand store receives at most one write per animation frame. This requires mocking `requestAnimationFrame` with a manual-advance fake timer (`vi.useFakeTimers()` plus `vi.spyOn(globalThis, 'requestAnimationFrame')`). After injecting 20 delta events without advancing the fake timer, assert that the store's `messages[last].text` has not changed; then advance one frame and assert it has been updated with all 20 concatenated deltas collapsed into one write.

Third: assert that a pending RAF is cancelled on early unmount. Render the hook, start a `submit` call, inject one delta event (which schedules a RAF), unmount the component before the RAF fires, advance the fake timer, and assert that the store's message text has not been updated — confirming `cancelAnimationFrame` was called during cleanup.

---

## 9. Risks

- **RAF mock pattern in vitest.** `requestAnimationFrame` is not defined in jsdom by default. Tests that exercise the batching path must install a mock before the hook module loads — pin `vi.stubGlobal('requestAnimationFrame', vi.fn((cb) => { ... }))` in a `beforeEach` and `afterEach` block in the test file. Failing to do this will cause the hook to fall through to the `setTimeout(runFlush, 50)` fallback that already exists in `store/index.ts:81–83`, making the RAF-cancellation test pass vacuously. The mock must be installed at the test level, not the module level, to avoid polluting other test files.

- **Stale closures from selector-based store reads inside async callbacks.** Any async callback inside the hook (the NDJSON generator's `for await` body, the RAF flush callback) that needs to read store state must call `useStore.getState()` rather than closing over a value retrieved from `useStore(selector)` at render time. The selector value is frozen at the moment of the last render; `getState()` is always current. This is especially relevant for the assistant message ID ref — use `rafAccumulatorRef.current` (a local ref) rather than trying to read back from the store.

- **Partial-chunk NDJSON tolerance.** The async generator must handle the case where a `TextDecoder` chunk ends mid-JSON-line. Pin this in tests by constructing a `ReadableStream` whose chunks split a single JSON object across two pushes (e.g., `'{"type":"del'` then `'ta","text":"hello"}\n'`) and asserting the parser emits exactly one well-formed delta event. Without this test, a fast-path optimization that assumes one chunk equals one line will silently drop or corrupt events on slow connections.

---

## 10. Pairs with ME-6

ME-6 splits `SettingsPanel` into per-provider sections and extracts a `useCodexLogin` custom hook. Both SR-3 and ME-6 introduce new files under `web/src/hooks/` and both establish the convention that side-effectful stream or async logic lives in a hook rather than inline in a component. They are independent PRs with no shared code — SR-3 can land before, after, or concurrently with ME-6 — but they share the folder layout decision and should agree on naming conventions (camelCase hook names, one hook per file, `use` prefix throughout). If they land in the same sprint, coordinate on `web/src/hooks/index.ts` if a barrel export file is introduced.

---

## 11. Out of scope

- No change to the Zustand store's public `State` interface in this PR. Action signatures (`addUser`, `startAssistant`, `appendDelta`, `appendDeltaBatched`, `flushDeltaBatch`, `finishAssistant`, `attachCard`, `setReadiness`, `setPairing`, `openSlideOver`, `closeSlideOver`) are all preserved. Internal implementations may simplify in migration step 3 but the exported type does not change.
- No change to the NDJSON wire format between the Python backend and the browser. The parser consumes the existing `delta` / `tool_result` / `final` / `error` event types without modification.
- No change to status-dot or readiness logic. `setReadiness`, `deriveOverall`, and the `Readiness` / `ReadinessRow` types in `store/index.ts` are untouched. The `useEffect` at `App.tsx:52–79` that calls `fetchSettings` and populates readiness remains in `App.tsx` as-is.
- No replacement of Zustand with another state library. The hook drives Zustand store actions; it does not introduce a second state primitive (no `useReducer` wrapping the store, no React Context shadowing it).
