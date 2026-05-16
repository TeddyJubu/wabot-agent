# wabot-agent roadmap

Handoff doc for what shipped, how to run production, and what to build next.

## Production snapshot (2026-05-17)

| Item | Status |
|------|--------|
| **Git** | `main` — feature branches merged; use PRs for new work |
| **VPS stack** | `wabot` @ loopback `:7777`, `wabot-agent` @ `:8787`, Caddy HTTPS |
| **Public URLs** | `/login`, `/pair`, `/` (dashboard) on your configured hostname |
| **Auth** | Dashboard password + operator cookie; optional CF Access later |
| **Send policy** | `allowlist` + `scripts/apply-production-hygiene.py` |
| **History** | `WABOT_HISTORY_*` webhooks → `inbound_messages` backfill |
| **Repos** | [wabot-agent](https://github.com/TeddyJubu/wabot-agent), [wabot](https://github.com/TeddyJubu/wabot) |

**Operator onboarding (e.g. new device):** reset old link → `/login` → `/pair` → scan QR → add JID to allowlist.

---

## Shipped (phases 1–5)

- **Core:** Agents SDK, OpenRouter, offline mode, SQLite memory, send policies
- **Dashboard:** React SPA, chat stream, settings, pairing panel, tool cards
- **Public pairing:** `/pair`, SSE `pairing_changed`, `/login` password gate
- **wabot integration:** inbox, contacts, groups, media, reactions, app state, user info
- **Webhooks:** inbound, receipt, presence, history-sync + batched history
- **Production:** hygiene scripts, VPS deploy, inbound persists on model failure
- **CI:** ruff, pytest (offline), evals, Vitest + web build

Details per phase remain in git history and `docs/superpowers/specs/`.

---

## Next priorities

### P0 — Production hardening (do first)

- [ ] Set `WABOT_AGENT_WABOT_HOME=/opt/wabot` on VPS (enables **New QR**)
- [ ] Document operator password rotation (`WABOT_AGENT_DASHBOARD_PASSWORD`)
- [ ] Ensure `OPENROUTER_API_KEY` in `.env` (not only `runtime_overrides.json`)
- [ ] Add operator JIDs to allowlist after pairing smoke test
- [ ] Optional: `scripts/backfill-inbound.sh` for one-off history from `WABOT_HISTORY_DB`

### P1 — Operator experience

- [ ] **Inbox panel** in dashboard (table of `inbound_messages`, not only chat tool cards)
- [ ] **Conversation thread** per contact (session_id = sender JID)
- [ ] Clear “linked / needs QR” banner on dashboard home
- [ ] Runbook doc: “hand off to a new operator” (1 page, link from README)

### P2 — whatsmeow gaps (daemon + tools)

- [ ] Polls (`/polls/*`)
- [ ] Blocklist / privacy settings
- [ ] Newsletters (if needed)

### P3 — Edge auth (optional)

- [ ] Cloudflare Tunnel + Access instead of or in addition to `/login`
- [ ] Audit logging for operator sign-in and sends

### P4 — Multi-tenant / product (later)

- Accounts, billing, per-user instances — **out of scope** for current single-VPS setup (see design spec).

---

## Conventions for new features

1. **wabot** HTTP route first (`X-Token`, ready-gate).
2. **WabotClient** method in `src/wabot_agent/wabot.py`.
3. **`@function_tool`** + `core_tools()` registration.
4. Update **`agent.py`** instructions + `skills/whatsapp-operator/SKILL.md`.
5. Tests in `tests/` (wabot: `go test ./cmd/wabot/...`).
6. `./scripts/build-web.sh` if UI changes.
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
./scripts/build-web.sh
uv run python scripts/apply-production-hygiene.py
```

---

## Security reminders

- wabot and webhooks stay on `127.0.0.1`.
- Production: `allowlist`, strong dashboard password, separate operator token for API.
- Do not commit `data/`, `.env`, or WhatsApp `store.db`.
