---
name: mem0-memory
description: Semantic long-term memory via Mem0 for WhatsApp contacts.
---

# Mem0 memory

Use Mem0 for preferences, history, and facts that benefit from semantic search — not for secrets or one-off tool output.

## When to use

- `search_mem0_memories` — before answering questions about past conversations, preferences, or "do you remember…"
- `add_mem0_memory` — when the user states a durable preference you should remember across sessions
- `recall_contact_memory` — explicit key/value facts (SQLite); use both when helpful
- `mem0_status` — if memory seems empty or misconfigured

## Rules

- `user_id` is the WhatsApp sender JID (or group `chat` JID for group sessions).
- Never store API keys, passwords, OTPs, or private medical data.
- Mem0 auto-captures each turn when enabled; use `add_mem0_memory` only for clear facts worth emphasizing.
