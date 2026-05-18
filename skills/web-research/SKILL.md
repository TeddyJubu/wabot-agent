---
name: web-research
description: Deep web scraping and structured lead research via Firecrawl web-agent.
---

# Web research (Firecrawl web-agent)

Use this skill when the operator asks for lead lists, market research, competitor scraping, or any task that needs many pages searched and structured output (CSV).

## Prerequisites

1. Firecrawl web-agent Express sidecar running (see `docs/web-agent-setup.md`).
2. `WABOT_AGENT_WEB_AGENT_ENABLED=true` on wabot-agent.
3. Call `web_research_health` before queueing a job.

## Workflow

1. Confirm the brief (targets, geography, exclusions, columns, minimum row count).
2. Call `start_web_research` with the **full** research prompt in `prompt` (do not shorten exclusion rules or column headers).
3. Tell the operator the job id and that results will arrive on WhatsApp when finished (may take 30–120+ minutes for 500+ leads).
4. Use `get_web_research_status` if they ask for progress.

## Output format

- Prefer `output_format=csv` and require CSV headers in the prompt.
- For strict JSON, use `output_format=json` and pass `output_schema_json` (JSON Schema string).

### Standard lead CSV headers

```
businessName,businessCategory,websiteUrl,googleMapsUrl,googleRating,googleReviewCount,address,phoneNumber,businessEmail,ownerName,ownerEmail,doctorOrPractitionerName,ownerLinkedInUrl,companyLinkedInUrl,facebookUrl,instagramUrl,bookingUrl,whatsappUrl,fitReason,personalisationLine,sourceUrl,notes
```

## Lead-gen prompt checklist

Include in every `start_web_research` prompt:

- **Target types** — clinic categories and geography (e.g. Singapore).
- **Exclusions** — hospital groups, government, major chains, franchises.
- **Research method** — Google Maps keywords, regions, directories; no guessed emails.
- **Quality** — dedupe, validate emails, source URL per row, no patient data.
- **Goal row count** — e.g. at least 500 independent clinics.

Pass the operator’s full brief verbatim when they provide one; do not drop exclusion lists or column definitions.

## Owner-only

`start_web_research` is restricted to owner WhatsApp numbers when `WABOT_AGENT_WEB_AGENT_OWNER_ONLY=true` (default).
