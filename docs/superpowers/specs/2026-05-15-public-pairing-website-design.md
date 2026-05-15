# Public Live-Pairing Website — Design

**Date:** 2026-05-15
**Status:** Approved (autonomous brainstorming, decisions locked by author per user request)
**Author:** Claude (autonomous)
**Tracking sub-project:** #1 of an eventual multi-tenant SaaS. Sub-projects #2 (accounts), #3 (per-user wabot instances), and #4 (billing) are explicitly out of scope.

## Problem

Today the only way to pair WhatsApp with `wabot-agent` is to SSH into the `vignesh` VPS, port-forward 8787, and open the dashboard locally. The user wants to pair from any phone or laptop browser by visiting a public URL, with the QR code updating live as `wabot` produces new pairing codes.

Two unstated constraints make this non-trivial:

1. **The QR is the WhatsApp linked-device identity.** Whoever scans the QR first becomes the WhatsApp account the bot speaks as. The endpoint that serves it must be locked down against the internet.
2. **`wabot` must stay on loopback.** `CLAUDE.md` explicitly forbids exposing the `wabot` daemon publicly. Any solution must keep the agent → `wabot` call path on `127.0.0.1`.

## Goals

- Operator can open a stable public URL on a phone, authenticate, and see a live-updating WhatsApp pairing QR.
- The QR re-renders without user action whenever `wabot` rotates the pairing code or transitions states.
- The dashboard's slide-over `PairingPanel` also becomes live, restoring an SSE behavior that was lost when the React SPA replaced the static dashboard.
- The full design slots cleanly into a future multi-tenant SaaS layer (sub-projects #2–#4): nothing in this PR locks out per-user routing later.
- A CI pipeline runs ruff, the offline pytest suite, the web tests, the web build, and the eval harness on every push and PR.

## Non-goals

- Account creation, login forms, password reset, email sending. (Sub-project #2.)
- Per-user `wabot` instances or tenant-scoped storage. (Sub-project #3.)
- Billing or plan limits. (Sub-project #4.)
- Marketing pages or onboarding flow. (Sub-project #5.)
- New tools, new agent capabilities, or any change to the agent loop.
- Changes to `tools.py`, `memory.py`, `agent.py`, `wabot.py`, `models.py`, `redaction.py`, `mcp.py`, or `skills.py`.

## Decisions locked in

| Topic | Decision | Reason |
|---|---|---|
| Public exposure | Cloudflare Tunnel from VPS to FastAPI on 127.0.0.1:8787 | No inbound ports opened, automatic TLS, preserves wabot loopback invariant. |
| Human auth | Cloudflare Access (Google or one-time-PIN email) + operator token as defense-in-depth | Identity-based auth without writing it. Token survives Access misconfiguration. |
| Webhook auth | `WABOT_INBOUND_TOKEN` (unchanged) — does NOT pass through Cloudflare | `wabot` POSTs `/whatsapp/inbound` over loopback. Cloudflare Access would break it. |
| Page model | Single React bundle. `/pair` and `/` serve the same `index.html`; `main.tsx` switches between `<App />` and `<PairView />` based on `window.location.pathname`. | Reuses Tailwind/components/store. No second build target, no router lib. |
| Live updates | New Zustand `pairing` slice fed by a single `EventSource` opened in a `usePairingStream` hook. Both `PairView` and `PairingPanel` subscribe via the store. | Single source of truth. Restores the SSE behavior lost in the React migration. |
| Public endpoints | `/health` stays public (uptime probes). `/ready`, `/api/*`, `/`, `/pair` all behind `verify_human`. `/whatsapp/inbound` keeps its own inbound-token check. | Minimal public surface. No behavior change to `/ready`. |
| JWT library | `PyJWT[crypto]>=2.8` | Maintained, well-known, supports JWKS fetch + RS256 verification. |
| Default | `cf_access_required=False` | Offline tests and fresh checkouts must keep passing with no CF setup. |
| Tenant-id seam | Carry through an `AuthIdentity` value object from `verify_human` that exposes `tenant_id` (default `"operator"` today, email-derived under CF Access). Reserve `session_id` use in the agent runner to pass through this id. | Sub-project #3 swaps `tenant_id` → real account id without rewriting routes. |

## Architecture

### Request paths

```
Human (phone or laptop)
  → https://wabot.<your-domain>/{pair,/,api/...}
    → Cloudflare Edge
      → Cloudflare Access policy (Google OAuth / email OTP)
        → cloudflared (outbound tunnel from vignesh VPS, systemd-managed)
          → 127.0.0.1:8787 FastAPI
            → verify_human dep:
                1. verify Cf-Access-Jwt-Assertion against JWKS (cached)
                2. set operator cookie if missing (only when token configured)
                3. emit AuthIdentity{tenant_id="operator", email, sub}
            → serve /pair (SPA shell) or /api/whatsapp/pairing(.svg) or SSE
              → server-side EventHub publishes pairing_changed
                → cloudflared streams SSE back to client
                  → PairView re-renders QR card

wabot daemon (loopback only, never via Cloudflare)
  → http://127.0.0.1:8787/whatsapp/inbound
    → _verify_inbound_auth (WABOT_INBOUND_TOKEN) — unchanged
```

### Key properties

1. The webhook never leaves the VPS. Cloudflare can't see it, can't gate it. The operator token and Cloudflare Access are irrelevant to inbound — the inbound-token machinery stays as the single auth for that path.
2. Human routes are doubly protected: Access (identity) and operator cookie (defense-in-depth). If either secret leaks alone, the bot's identity is safe. The operator cookie is auto-minted on first successful Access verification, so the operator never types it on their phone.
3. The agent → `wabot` call path is unchanged. Cloudflare sits *only* in front of the human-facing FastAPI routes.

## Components & files

### New files

| Path | Purpose |
|---|---|
| `src/wabot_agent/cf_access.py` | JWKS-based Cloudflare Access JWT verifier. Caches keys with TTL. Exposes `verify_access_jwt(token, settings) -> AccessIdentity`. |
| `src/wabot_agent/auth.py` | New `AuthIdentity` dataclass + `verify_human` dependency. Wraps the existing `verify_operator` logic and the new Access path. |
| `web/src/components/PairView.tsx` | Full-page mobile-first pairing view. Subscribes to the pairing slice. Shows status pill, large QR, "Connected" state, last-updated timestamp, link to full dashboard. |
| `web/src/hooks/usePairingStream.ts` | Opens a single `EventSource('/api/stream')`. On `pairing_changed` and `ready_snapshot.pairing`, updates `useStore.setPairing(...)`. Auto-reconnects on error with capped backoff. |
| `tests/test_cf_access.py` | Unit tests with a mock JWKS. Covers valid token, wrong `aud`, expired `exp`, missing header, malformed JWT, unknown `kid`. |
| `tests/test_pair_route.py` | Pytest for `/pair` route: serves SPA shell, sets cookie when Access JWT valid, 401 when Access required but JWT missing. |
| `deploy/cloudflared/config.yml.example` | Cloudflare tunnel config template (tunnel id, hostname → http://localhost:8787 ingress, plus `health-check` rule for `/health`). |
| `deploy/systemd/cloudflared.service` | Systemd unit to run `cloudflared tunnel run` at boot. Includes `After=network.target wabot-agent.service`. |
| `scripts/setup-cloudflared.sh` | Idempotent. Installs cloudflared (via official apt repo if missing), prompts for tunnel name + hostname, runs `cloudflared tunnel login`/`create`/`route dns`, installs the systemd unit, starts it. |
| `.github/workflows/ci.yml` | GitHub Actions: ruff, offline pytest, web vitest, web build, eval harness. Runs on push + PR. |
| `docs/superpowers/specs/2026-05-15-public-pairing-website-design.md` | This file. |
| `docs/superpowers/plans/2026-05-15-public-pairing-website-plan.md` | Implementation plan (next document). |

### Modified files

| Path | Change |
|---|---|
| `src/wabot_agent/config.py` | Add `cf_access_team_domain: str \| None`, `cf_access_aud: str \| None`, `cf_access_required: bool = False`. All under `WABOT_AGENT_*` with `VIGNESH_*` aliases for consistency. |
| `src/wabot_agent/api.py` | (a) Replace `operator_dependency` with `human_dependency = Depends(verify_human)` on all human routes. (b) Add `GET /pair` returning the SPA shell with the same cookie-minting logic as `GET /`. (c) Pass `AuthIdentity.tenant_id` through to `run_agent(session_id=...)` for the chat APIs (today's behavior preserved when identity is `"operator"`). (d) `GET /api/stream` keeps emitting `pairing_changed` — the React side now subscribes. |
| `src/wabot_agent/runtime_overrides.py` | Extend `MUTABLE_FIELDS` to include `cf_access_team_domain`, `cf_access_aud`, `cf_access_required`. They're config, not secrets, but only the operator should change them. |
| `pyproject.toml` | Add `pyjwt[crypto]>=2.8` to `dependencies`. |
| `web/src/main.tsx` | Path-based render: if `window.location.pathname.replace(/\/$/, "") === "/pair"` render `<PairView />`, else `<App />`. Both wrapped in `<StrictMode>`. |
| `web/src/store/index.ts` | Add `pairing` slice: `pairing: PairingState \| null`, `setPairing(p)`. Re-uses the existing `PairingState` type from `web/src/api/pairing.ts`. |
| `web/src/components/slide-overs/PairingPanel.tsx` | Drop one-shot `fetchPairing()` on mount. Read from `useStore(s => s.pairing)`. Keep a manual "Refresh" that calls `fetchPairing()` and updates the store. |
| `web/src/App.tsx` | Mount `usePairingStream()` once at the top of `App` so the dashboard is also live. |
| `web/src/api/pairing.ts` | Export `subscribePairing(onState)` — the implementation that `usePairingStream` uses. Keeps `fetchPairing()` for the manual refresh button. |
| `.env.example` | Document `WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN`, `WABOT_AGENT_CF_ACCESS_AUD`, `WABOT_AGENT_CF_ACCESS_REQUIRED`, plus a paragraph pointing to `scripts/setup-cloudflared.sh`. |
| `CLAUDE.md` | Append a "Public access" subsection under "Architecture" describing: (a) Cloudflare Tunnel layout, (b) Access JWT path, (c) reminder that wabot stays loopback and the inbound webhook bypasses CF. |
| `README.md` | New "Public access" section under "VPS deploy" linking to `scripts/setup-cloudflared.sh` and listing the three CF Access env vars. |

### Files NOT touched

`tools.py`, `memory.py`, `agent.py`, `wabot.py`, `models.py`, `redaction.py`, `mcp.py`, `skills.py`, `evals/`, MCP configs, the systemd unit for `wabot-agent` itself.

## Data flow — live pairing

```
wabot daemon (rotates QR every ~30s)
  ←─ HTTP GET /pairing/qr (loopback) ── _pairing_poll_loop() every 5s
  └─ poll result → _pairing_payload() → hub.publish("pairing_changed", payload)
                                        │
EventHub ring buffer + per-subscriber queue
                                        │
GET /api/stream (verify_human gate, then SSE generator)
                                        │
   ┌────────────────────────────────────┴───────────────────────────────────┐
   │                                                                        │
PairView page                                                       PairingPanel slide-over
   │                                                                        │
usePairingStream() opens EventSource                            useStore(s => s.pairing) reads
   │                                                            shared store slice
named event "pairing_changed" → setPairing(payload)
named event "ready_snapshot" → if payload.pairing, setPairing(payload.pairing)
   │
PairingQrCard renders the new QR (cache-busted src)
```

Reconnection: `EventSource` auto-reconnects on error. We add a 1-second initial delay and cap retries at 30s exponential backoff via a wrapper, because Cloudflare Tunnel may briefly drop on cold start.

## Error handling & edge cases

| Case | Behavior |
|---|---|
| `WABOT_AGENT_CF_ACCESS_REQUIRED=false` and no operator token set | Auth bypassed (today's behavior preserved for local dev). |
| `WABOT_AGENT_CF_ACCESS_REQUIRED=true` and no `Cf-Access-Jwt-Assertion` header | 401, `{"detail": "Cloudflare Access required"}`. |
| Access JWT has wrong `aud` | 401, `{"detail": "Invalid Cloudflare Access audience"}`. Logged at WARN. |
| Access JWT expired | 401, `{"detail": "Cloudflare Access token expired"}`. |
| JWKS fetch fails on first call | 503, `{"detail": "Auth provider temporarily unavailable"}`. Retried on next request. JWKS cached for ~6h on success. |
| Access valid but no operator token configured | Allow. `tenant_id` set from email. Operator cookie NOT minted (nothing to mint). |
| Access valid and operator token configured but cookie missing | Mint cookie (`HttpOnly`, `SameSite=Strict`, `Secure=True` when behind HTTPS — same flags as today's `?token=` flow on `GET /`). |
| wabot daemon unreachable | `/api/whatsapp/pairing` returns `{supported, reachable:false, detail:"…"}`. `PairView` shows "wabot unreachable" status pill, hides QR. No error toast. |
| SSE stream disconnects mid-session | `EventSource` reconnects automatically. `PairView` shows a small "reconnecting…" pill until the next event arrives, then clears it. |
| Two phones scan within the same window | Whoever's WhatsApp processes the link first wins; the other gets an error in the WhatsApp app. The bot's `store.db` reflects the winner. This is unchanged WhatsApp behavior. |

Why `SameSite=Strict` still works under Access: Cloudflare's OAuth redirect sends the user from `wabot.<domain>` to `*.cloudflareaccess.com` and back. The cookie is *minted* on the same-site request that follows the redirect-back, and is only ever consumed on subsequent same-site requests to `/api/*` from the SPA. Strict never blocks the mint and never blocks the consume.

## Security boundary changes

**Newly public (reachable from the internet through Cloudflare):**
- `GET /` (SPA shell)
- `GET /pair` (SPA shell, with PairView rendering)
- `GET /favicon.ico`
- `GET /static/*`
- `GET /health` (no auth — uptime probes)
- All `/api/*` routes (gated by `verify_human`: Access JWT required when `cf_access_required=true`)

**Still loopback-only:**
- `POST /whatsapp/inbound` (only `wabot` calls this; Cloudflare doesn't even route it)
- The `wabot` daemon at `127.0.0.1:7777`
- The OpenRouter call path

**Defense-in-depth posture:**
- Access JWT (signed by Cloudflare, audience-checked)
- Operator cookie (signed-ish via secret comparison)
- Inbound token (separate from operator token)
- `_is_send_allowed` in `tools.py` (unchanged — still the chokepoint for actual WhatsApp sends)
- `_media_path_allowed` in `tools.py` (unchanged)
- Inbound idempotency by `message.id` (unchanged)
- Send policy default `dry_run` (unchanged)

The send policy and media path checks remain authoritative for *what the bot can do*. Cloudflare Access changes *who can reach the dashboard*, not what tools the agent can run.

## Tenant-id seam

`verify_human` returns an `AuthIdentity` dataclass:

```python
@dataclass(frozen=True)
class AuthIdentity:
    tenant_id: str            # "operator" today; future: account UUID
    email: str | None         # set under CF Access; None under operator-token-only
    sub: str | None           # Access "sub" claim; None under operator-token-only
    source: Literal["operator-cookie", "operator-header", "cf-access"]
```

Routes that today pass `session_id` to `run_agent` will pass `identity.tenant_id` as the `session_id` namespace (today this resolves to `"operator"` exactly as before). The agent's memory store keys by `session_id`, so swapping to a real account id in sub-project #3 won't require touching any route handler — only the `verify_human` body that produces the identity.

## Testing

### Backend (pytest, offline mode, no creds)

Add the following cases to `tests/test_cf_access.py` and `tests/test_pair_route.py` (split for clarity):

1. `verify_access_jwt` accepts a valid RS256 token signed by a key in the mock JWKS.
2. `verify_access_jwt` rejects a token with wrong `aud` (401).
3. `verify_access_jwt` rejects an expired token (401).
4. `verify_access_jwt` rejects a token signed by an unknown `kid` (401).
5. `verify_access_jwt` raises a fetch error (503) when JWKS endpoint is unreachable on cold cache.
6. `verify_access_jwt` reuses JWKS within TTL (asserts only one HTTP call across N verifications).
7. `GET /pair` returns 200 with HTML when `cf_access_required=false` and `operator_token=None` (local dev).
8. `GET /pair` returns 401 when `cf_access_required=true` and no Access header.
9. `GET /pair` returns 200 and `Set-Cookie: wabot_agent_operator_token=...` when Access header valid and operator token configured.
10. `GET /api/stream` (SSE) returns 401 when `cf_access_required=true` and no Access header.
11. `/whatsapp/inbound` is **unaffected** by CF Access settings — covered by extending the existing inbound test to flip `cf_access_required=true` and confirm the inbound-token path still works.

### Frontend (vitest)

12. `<PairView />` mounts, opens an EventSource, paints the "checking" state, then renders QR when a `pairing_changed` event arrives via the store.
13. `<PairView />` renders "Connected" when `pairing.logged_in && pairing.connected`.
14. `<PairView />` renders "wabot unreachable" when `pairing.reachable === false`.
15. `<PairingPanel />` reads from the store (no fetch on mount when store already has a value).
16. `usePairingStream` re-subscribes after a simulated EventSource error.

### Manual verification (operator post-deploy, documented in PR description)

- Open `https://wabot.<domain>/pair` on a phone → Google login → see QR → scan with WhatsApp → "Connected" within 5 seconds.
- Rotate phone offline / online → QR live-refreshes via SSE.
- Open `https://wabot.<domain>/` on desktop → dashboard works as before, PairingPanel is live.
- Hit `/whatsapp/inbound` with the inbound token from `wabot` (loopback) — must succeed (CF Access does not intercept).

## CI workflow

New `.github/workflows/ci.yml`:

- `lint`: `uv run --with '.[dev]' ruff check .`
- `pytest`: `uv run --with '.[dev]' python -m pytest -m offline -q`
- `evals`: `uv run python evals/run_local.py`
- `web-test`: `cd web && npm ci && npm run test -- --run`
- `web-build`: `cd web && npm ci && npm run build`

Three jobs (`backend`, `web`, `evals`) on a `ubuntu-latest` matrix. Triggered on `push` to any branch and `pull_request`. Caches uv (`~/.cache/uv`) and node (`web/node_modules`) for speed.

## Open questions

None. All decisions locked above per user's explicit instruction to decide autonomously.

## Migration / rollout

Single PR. No data migration. The new auth dep defaults to `cf_access_required=false`, so existing deployments behave identically until the operator opts in by setting the three CF Access env vars and re-running `scripts/setup-cloudflared.sh`.

Rollback: revert the PR. No schema changes, no data changes.

## Out of scope (deferred to later sub-projects)

- Accounts, login, sessions, password reset.
- Per-user `wabot` instances and process lifecycle.
- Stripe billing / plan limits.
- Marketing site.
- Email transactional sending.
- Rate limiting (Cloudflare WAF Free tier already provides baseline).
- Audit log persistence of Access identities (Cloudflare Access logs cover this for now).
