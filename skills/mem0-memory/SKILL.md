---
name: mem0-memory
description: Semantic long-term memory via Mem0 for WhatsApp contacts.
---

# Mem0 memory

Memory is **mandatory**, not optional. Use Mem0 plus SQLite contact facts every turn.

## Every inbound turn

1. **Recall** — `search_mem0_memories(query=…, user_id=…)` and `recall_contact_memory(contact=…)`.
2. **Answer** — use recalled facts naturally; do not claim you forgot without searching first.
3. **Persist** — before your final reply, `add_mem0_memory` and/or `remember_contact_fact` for
   anything important in this message or your commitments.

## What to save

- Preferences, names, roles, timezone, language
- Deadlines, reminders-in-text, ongoing projects
- Business context (company, goals, constraints)
- Corrections ("call me X", "I prefer Y")
- Standing instructions ("always…", "never…", "remember that…")

## What not to save

- Passwords, OTPs, API keys, payment card numbers
- Sensitive clinical patient data
- One-off tool output unless the user asks to keep it

## user_id

- DM: sender JID
- Group: **chat** JID (`@g.us`), not only the participant

## Tools

| Tool | Use |
|------|-----|
| `search_mem0_memories` | Semantic recall before answering |
| `add_mem0_memory` | Explicit durable facts (preferred for "remember this") |
| `remember_contact_fact` | Structured key/value (e.g. `timezone`, `company`) |
| `recall_contact_memory` | Read SQLite facts |
| `mem0_status` | Debugging |

Auto-capture may run when Mem0 is enabled — still call `add_mem0_memory` for facts you must not lose.
