# Mini test scenarios

Quick checks after deploy. Use your **owner** WhatsApp number unless noted. Dashboard: `https://wabot.srv943071.hstgr.cloud/` (log in via `/login` first).

**Pass** = you get the expected behavior within ~2 minutes (web research may take longer).

---

## 1. OpenAI chat (main LLM)

**Where:** Dashboard → Chat, or WhatsApp to the bot.

**Send:**
```
Reply with exactly one word: pong
```

**Expect:** A single-word reply `pong` (or very close). No OpenRouter/Ollama error text.

**Fail signs:** “model provider”, “401”, “rate limit”, or a long apology with no `pong`.

---

## 2. OpenAI settings

**Where:** Dashboard → Settings.

**Check:**
- Model provider = **OpenAI API**
- Shows the OpenAI key as configured (green active status)
- Model field shows your OpenAI model (e.g. `gpt-4.1-mini`)

**Optional:** Switch to another provider → Save → send test #1 again (should still work).

---

## 3. WhatsApp connectivity

**Where:** WhatsApp (owner).

**Send:**
```
Are you connected to WhatsApp? Answer yes or no only.
```

**Expect:** `yes` if wabot is linked; agent may call `wabot_health` internally.

**Fail signs:** “not ready”, “not logged in”, or instructions to use `/pair`.

---

## 4. Multi-step progress pings

**Where:** WhatsApp (owner). Needs `WABOT_AGENT_TASK_PROGRESS_UPDATES=true` (default).

**Send** (one message, copy as-is):
```
I need a short test plan only — do not actually browse the web. First, list three fruits. Then list three colors. Then say done. Post your plan in chat before you start, and tell me after each step finishes.
```

**Expect (in order):**
1. Short ack that this is multi-step (within a few seconds)
2. Numbered plan (📋 …)
3. Step-complete messages (✅ Step 1/2/3 …)
4. Final summary mentioning “done”

**Fail signs:** Only one long reply at the end, no plan, no step pings.

---

## 5. Firecrawl sidecar health

**Where:** Dashboard Chat or WhatsApp (owner).

**Send:**
```
Run web research health check only — report ok, model name, and whether the sidecar is reachable. Do not start a scrape.
```

**Expect:** `ok: true`, model like `openai:minimax-m2.5`, sidecar reachable.

**Fail signs:** `disabled`, `unreachable`, or HTTP 500 from web-agent.

**VPS one-liner (optional):**
```bash
ssh vignesh 'curl -fsS http://127.0.0.1:3000/ | jq .status,.model'
```

---

## 6. Firecrawl mini scrape (owner only)

**Where:** WhatsApp (owner). `web_agent_owner_only` must allow your number.

**Send:**
```
Start a small web research job: scrape https://example.com and return only the page title in one sentence. Tell me the job id, then notify me when it completes.
```

**Expect:**
1. Job queued message with an id
2. Later: completion WhatsApp (or status showing done)
3. Result mentions **Example Domain** (or similar)

**Fail signs:** `owner_only`, `web_agent_disabled`, or 500 / “Unable to infer model provider”.

**Time:** Often 1–5 minutes; do not send another research job until this finishes.

---

## 7. Non-owner web research (negative)

**Where:** WhatsApp from a **non-owner** number (if you have one).

**Send:**
```
Start web research on example.com
```

**Expect:** Polite refusal or `owner_only` — job **not** created.

---

## 8. Session memory (light)

**Where:** WhatsApp (owner), same thread.

**Message A:**
```
For this chat only: my test codename is BLUEFIN-7. Confirm you stored it.
```

**Message B** (new message, same chat):
```
What was my test codename? One word only.
```

**Expect:** `BLUEFIN-7` (or exact codename you used).

---

## 9. Dashboard operator chat

**Where:** Dashboard → Chat (no WhatsApp).

**Send:**
```
What model provider are you using right now? Reply with provider name only.
```

**Expect:** `openai` (or OpenAI API wording).

---

## 10. Post-deploy smoke (server)

**Where:** SSH on VPS.

```bash
systemctl is-active wabot-agent firecrawl-web-agent
cd /opt/wabot-agent && sudo -u wabotagent uv run python -c "
from wabot_agent.config import get_settings
from wabot_agent.web_agent import web_agent_health
import asyncio
s = get_settings()
print('provider:', s.model_provider)
print(asyncio.run(web_agent_health(s)))
"
```

**Expect:** Both services `active`, `provider: openai`, web health `ok: True`.

---

## Quick matrix

| # | Feature              | Channel    | ~Time   |
|---|----------------------|------------|---------|
| 1 | Codex reply          | WA / UI    | &lt;30s |
| 2 | Codex settings       | UI         | 1 min   |
| 3 | WhatsApp link        | WA         | &lt;30s |
| 4 | Task progress        | WA         | 1–3 min |
| 5 | Firecrawl health     | WA / UI    | &lt;30s |
| 6 | Firecrawl job        | WA (owner) | 1–5 min |
| 7 | Owner gate           | WA (other) | &lt;30s |
| 8 | Session memory       | WA         | 1 min   |
| 9 | Dashboard chat       | UI         | &lt;30s |
| 10| Server smoke         | SSH        | 1 min   |

Run **1 → 2 → 5 → 6** for a minimal post-deploy path; add **4** if you care about step-by-step WhatsApp updates.
