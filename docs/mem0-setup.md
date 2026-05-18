# Mem0 long-term memory

wabot-agent integrates [Mem0](https://github.com/mem0ai/mem0) for semantic, per-contact memory alongside the existing SQLite `contact_facts` store.

## How it works

| Layer | Role |
|-------|------|
| **SQLite** (`contact_facts`, `agent_notes`) | Explicit key/value facts the agent stores via tools |
| **Mem0** (`data/mem0_qdrant/`) | Semantic search + automatic learning from each turn |

On each agent run (when enabled):

1. **Retrieve** — Mem0 searches memories for the session `user_id` (WhatsApp sender or group `chat` JID).
2. **Inject** — Top matches are prepended to the prompt.
3. **Capture** — After the reply, user + assistant messages are added to Mem0.

## Enable (OSS, recommended for VPS)

Uses local **Qdrant** on disk and your existing **OpenRouter** key for LLM extraction + embeddings.

```bash
# In wabot-agent/.env
WABOT_AGENT_MEM0_ENABLED=true
OPENROUTER_API_KEY=sk-or-...

# Optional
WABOT_AGENT_MEM0_PATH=./data/mem0_qdrant
WABOT_AGENT_MEM0_TOP_K=5
WABOT_AGENT_MEM0_AUTO_CAPTURE=true
WABOT_AGENT_MEM0_INJECT_ON_RUN=true
WABOT_AGENT_MEM0_EMBED_MODEL=text-embedding-3-small
```

Restart `wabot-agent`. Data persists under `WABOT_AGENT_MEM0_PATH`.

## Mem0 Cloud (optional)

```bash
WABOT_AGENT_MEM0_ENABLED=true
WABOT_AGENT_MEM0_USE_PLATFORM=true
MEM0_API_KEY=m0-...
```

## Agent tools

- `mem0_status` — config check
- `search_mem0_memories(query, user_id?)` — semantic recall
- `add_mem0_memory(text, user_id?)` — store an explicit fact

## Notes

- Disabled when `WABOT_AGENT_OFFLINE_MODE=true` or `WABOT_AGENT_MEM0_ENABLED=false`.
- Do not store secrets; `looks_sensitive` blocks obvious credential patterns.
- OpenRouter must support the embedding model you configure (default `text-embedding-3-small`).
