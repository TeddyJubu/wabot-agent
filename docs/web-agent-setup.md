# Firecrawl web-agent sidecar

wabot-agent calls [Firecrawl web-agent](https://github.com/firecrawl/web-agent) over HTTP for deep scraping jobs (`start_web_research` tool). Results are saved under `data/media/research/` and sent to the requester on WhatsApp when complete.

## 1. Install web-agent (VPS or dev machine)

```bash
npx -y firecrawl-cli@latest init -y --browser
git clone https://github.com/firecrawl/web-agent.git /opt/web-agent
cd /opt/web-agent/agent-templates/express
cp .env.example .env
```

Set in `.env`:

- `FIRECRAWL_API_KEY=fc-...` — [firecrawl.dev](https://firecrawl.dev)
- `GOOGLE_GENERATIVE_AI_API_KEY=...` (or `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`)

**Ollama Cloud (OpenAI-compatible):** reuse your wabot `OLLAMA_API_KEY` and point the sidecar at Ollama’s API. Use the `openai:` provider (not `custom-openai:` — LangChain’s run path cannot infer that provider). Pick a model id without extra colons (e.g. `minimax-m2.5`, `deepseek-v3.2`); ids like `gemma4:31b` break `MODEL=provider:model` parsing.

```bash
MODEL=openai:minimax-m2.5
OPENAI_API_KEY=<OLLAMA_API_KEY>
OPENAI_BASE_URL=https://ollama.com/v1
```

`scripts/setup-firecrawl-vps.sh` writes this automatically when `OLLAMA_API_KEY` is present in wabot’s `.env`.

```bash
npm install
npm run doctor
npm run dev   # http://127.0.0.1:3000
```

Production: use the template Dockerfile or systemd to keep the process on loopback `:3000`.

## 2. Enable wabot-agent

In `wabot-agent/.env`:

```bash
WABOT_AGENT_WEB_AGENT_ENABLED=true
WABOT_AGENT_WEB_AGENT_URL=http://127.0.0.1:3000
WABOT_AGENT_WEB_AGENT_TIMEOUT_SEC=7200
WABOT_AGENT_WEB_AGENT_MAX_CONCURRENT=1
WABOT_AGENT_WEB_AGENT_MAX_PENDING_PER_CONTACT=3
WABOT_AGENT_WEB_AGENT_OWNER_ONLY=true
WABOT_AGENT_WEB_AGENT_NOTIFY_ON_COMPLETE=true
```

Restart wabot-agent so the scheduler picks up pending jobs.

## 3. Verify

```bash
curl http://127.0.0.1:3000/
```

From WhatsApp (owner number): ask the bot to run a small test scrape, or use dashboard chat with `web_research_health`.

## API used

- `GET /` — health
- `POST /v1/run` — `{ "prompt": "...", "format": "markdown"|"json", "stream": false }`

Long jobs run in the background; wabot-agent does not block the inbound webhook while waiting.
