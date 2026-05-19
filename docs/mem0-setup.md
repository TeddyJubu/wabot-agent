# Mem0 long-term memory

wabot-agent integrates [Mem0](https://github.com/mem0ai/mem0) for semantic, per-contact memory alongside the existing SQLite `contact_facts` store.

## How it works

| Layer | Role |
|-------|------|
| **SQLite** (`contact_facts`, `agent_notes`) | Explicit key/value facts the agent stores via tools |
| **Mem0** (`data/mem0_qdrant/`) | Semantic search + automatic learning from each turn |

On each agent run (when enabled):

1. **Retrieve** — Mem0 searches by **sender JID** (same person in DMs and groups). In group chats it also searches the group JID for thread-specific facts.
2. **Inject** — Top matches are prepended to the prompt.
3. **Capture** — After the reply, turns are stored under the **sender** so facts follow the person across chats.

Agent conversation history stays **per chat thread** (group JID vs DM); only long-term memory is person-scoped.

## Enable (OSS, recommended for VPS)

Uses local **Qdrant** on disk, your active chat provider for Mem0 **fact extraction**, and **FastEmbed** (local ONNX) for embeddings.

| Chat provider | Mem0 LLM (extraction) | Mem0 embeddings |
|---------------|----------------------|-----------------|
| `ollama_cloud` | Ollama Cloud `/v1` + `OLLAMA_API_KEY` | FastEmbed (no API key) |
| `ollama` (local) | Local Ollama `/v1` | FastEmbed |
| `openrouter` | OpenRouter `/v1` | OpenRouter embeddings API |

Ollama Cloud does not expose `/v1/embeddings`, so embeddings are always local FastEmbed when using Ollama.

```bash
# In wabot-agent/.env
WABOT_AGENT_MEM0_ENABLED=true
WABOT_AGENT_MODEL_PROVIDER=ollama_cloud
OLLAMA_API_KEY=...
OLLAMA_MODEL=gemma4:31b-cloud

# Optional
WABOT_AGENT_MEM0_PATH=./data/mem0_qdrant
WABOT_AGENT_MEM0_TOP_K=5
WABOT_AGENT_MEM0_AUTO_CAPTURE=true
WABOT_AGENT_MEM0_INJECT_ON_RUN=true
# FastEmbed model (default BAAI/bge-small-en-v1.5 when unset or text-embedding-3-small)
# WABOT_AGENT_MEM0_EMBED_MODEL=BAAI/bge-small-en-v1.5
```

Restart `wabot-agent`. Data persists under `WABOT_AGENT_MEM0_PATH`.

**Note:** Mem0’s upstream OpenAI client prefers OpenRouter when `OPENROUTER_API_KEY` is set in the environment, even if chat uses Ollama. wabot-agent clears that variable while initializing Mem0 unless `WABOT_AGENT_MODEL_PROVIDER=openrouter`. Remove unused `OPENROUTER_*` from `.env` when you have fully migrated to Ollama.

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
- With `openrouter`, the embedding model must be supported on OpenRouter (default `text-embedding-3-small`). With Ollama providers, embeddings use FastEmbed and do not call OpenRouter.
