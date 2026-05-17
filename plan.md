# wabot-agent roadmap

Handoff doc for what shipped, current production shape, and next work.

## Direction update (2026-05-17)

**Product direction is now WhatsApp-first control.** Operators should trigger actions by messaging the WhatsApp number, not by using the web dashboard chat UI.

### Why this direction (based on current docs)

1. WhatsApp linked-device model still centers on a single primary account with limited companion links; operationally this favors one bot instance and clear operator access controls, not a dashboard-led workflow.
2. OpenAI Agents SDK current guidance still supports persistent per-session memory cleanly (`SQLiteSession` / session ids), so chat-driven control can remain stateful without a dashboard.
3. Managed auth platforms (Clerk / WorkOS) provide current JWKS-backed token verification, so account login can be added without building auth from scratch.

This keeps the stack on one VPS and avoids premature full SaaS complexity.

---

## Production snapshot (current)

| Item | Status |
|------|--------|
| **Git** | `main` — feature branches merged; use PRs for new work |
| **VPS stack** | `wabot` @ loopback `:7777`, `wabot-agent` @ `:8787`, Caddy HTTPS |
| **Primary operator UX** | WhatsApp chat to the linked bot number |
| **Web surface** | Keep minimal: pairing + admin/ops only (no primary chat control) |
| **Send policy** | `allowlist` + `scripts/apply-production-hygiene.py` |
| **History** | `WABOT_HISTORY_*` webhooks → `inbound_messages` backfill |
| **Repos** | [wabot-agent](https://github.com/TeddyJubu/wabot-agent), [wabot](https://github.com/TeddyJubu/wabot) |

---

## Shipped baseline

- Core agent loop (Agents SDK + OpenRouter + offline mode)
- wabot integration + webhook pipeline
- Pairing UX (`/pair`) and dashboard app
- Production scripts + CI

The dashboard remains available for now, but no longer drives roadmap priorities.

---

## Next priorities

### P0 — WhatsApp-first reliability (do first)

- [ ] Set `WABOT_AGENT_WABOT_HOME=/opt/wabot` on VPS (ensures reliable QR restart path)
- [ ] Ensure `OPENROUTER_API_KEY` in `.env` (not only `runtime_overrides.json`)
- [ ] Enforce operator command guardrails in WhatsApp flows (confirmation for risky actions, explicit deny paths)
- [ ] Keep inbound durable when model/tools fail (store inbound, retry strategy, clear failure messages)
- [ ] Add audit events for command source (`sender`, tool invoked, allow/deny reason)
- [ ] Add runbook: "operator control from WhatsApp only"

### P1 — Multi-user access with hosted auth (single VPS)

- [ ] Integrate **Clerk or WorkOS** for account creation/login (no custom auth stack)
- [ ] Add invite-only or domain-restricted signup for operator safety
- [ ] Link each app user to one or more allowed WhatsApp JIDs
- [ ] Define role model (`admin`, `operator`, `viewer`) for non-chat admin actions
- [ ] Keep `/whatsapp/inbound` auth unchanged (`WABOT_INBOUND_TOKEN`, loopback)

### P2 — De-emphasize dashboard chat path

- [ ] Make web dashboard chat read-only or remove it from default navigation
- [ ] Keep only operational pages required on web (pairing, health/status, settings)
- [ ] Update docs and onboarding to "message WhatsApp number for actions"
- [ ] Add migration note for existing operators used to `/` chat UI

### P3 — WhatsApp capability gaps (daemon + tools)

- [ ] Polls (`/polls/*`)
- [ ] Blocklist / privacy settings
- [ ] Newsletters (if needed)

### P4 — Product expansion (later, not now)

- Billing, per-tenant bot instances, full SaaS isolation remain out of scope for this single-VPS phase.

---

## Decision log (for this phase)

- **Control plane:** WhatsApp chat is primary, web is secondary ops surface.
- **Auth:** Use managed auth (Clerk/WorkOS), validate tokens server-side via JWKS.
- **Instance model:** one bot instance on one VPS for now; no per-tenant process split.
- **Safety:** maintain allowlist and explicit confirmation for high-impact actions.

---

## Conventions for new features

1. Start from inbound WhatsApp user journey first, then add web fallback only if required.
2. **wabot** HTTP route first (`X-Token`, ready-gate).
3. **WabotClient** method in `src/wabot_agent/wabot.py`.
4. **`@function_tool`** + `core_tools()` registration.
5. Update **`agent.py`** instructions + `skills/whatsapp-operator/SKILL.md`.
6. Tests in `tests/` (wabot: `go test ./cmd/wabot/...`).
7. Restart **wabot** then **wabot-agent**.

---

## PR workflow

```bash
git checkout main && git pull
git checkout -b feat/short-topic
# commit, push
gh pr create --base main
```

Required: backend + evals + web CI; one approving review; linear history.

---

## Local ops

```bash
cd wabot-agent && uv run python main.py
cd ../wabot && set -a && source ./wabot.env && set +a && ./wabot
uv run python scripts/apply-production-hygiene.py
```

Use `./scripts/build-web.sh` only when changing web ops pages.

---

## Security reminders

- wabot and webhooks stay on `127.0.0.1`.
- `/whatsapp/inbound` continues to rely on `WABOT_INBOUND_TOKEN` and must not be internet-exposed directly.
- Keep production send policy on `allowlist` unless explicitly justified.
- Do not commit `data/`, `.env`, or WhatsApp `store.db`.
