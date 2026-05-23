"""Orchestrator — routes inbound messages to specialist subagents.

The orchestrator has NO domain tools of its own. Its primary job is to read
each inbound message, decide which specialist should handle it, and hand off
via the SDK handoff mechanism. It may answer simple factual questions directly
without delegating.

MCP servers and Composio tools are attached to the orchestrator (not the
specialists) so that:
  - MCP tool capabilities remain available for turns that do not require a
    specialist handoff (e.g. direct answers from an MCP server).
  - Composio tools (Gmail, Google Calendar, etc.) are accessible at the
    routing layer; the orchestrator can call them before deciding whether a
    specialist is needed, or can delegate to comms/inboxer with full context.
  - Specialists stay narrowly focused on their own native tool sets.

The five specialists it can delegate to:
- scraper: web search, URL fetch, file processing, image search
- memory_keeper: recall facts, remember new facts, Mem0 operations
- comms: send messages, react/edit/revoke, group management
- scheduler: create reminders, track outbound, list scheduled work
- inboxer: look up contacts, read recent inbox, list skills, check wabot health
"""

from __future__ import annotations

from typing import Any

from agents import Agent, handoff
from agents.extensions.handoff_filters import remove_all_tools
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from ..config import Settings
from ..model_routing import ModelPurpose
from ..models import build_model, model_settings
from .comms import build_comms
from .inboxer import build_inboxer
from .memory_keeper import build_memory_keeper
from .scheduler import build_scheduler
from .scraper import build_scraper

ORCHESTRATOR_INSTRUCTIONS = f"""{RECOMMENDED_PROMPT_PREFIX}

You are the orchestrator for a WhatsApp bot (wabot-agent). You read each
inbound message and decide who should handle it.

You have NO direct domain tools. You cannot send messages, fetch URLs, write
to memory, or look up contacts yourself. Instead, you delegate to one of five
specialists using the appropriate transfer_to_X handoff:

- **transfer_to_scraper**: web search, URL fetch, image search, file processing,
  Firecrawl research jobs, processing WhatsApp attachments
- **transfer_to_memory_keeper**: recall facts about a contact, remember new
  facts, Mem0 semantic memory operations
- **transfer_to_comms**: send WhatsApp messages (text/image/audio/video/doc),
  react/edit/revoke messages, typing indicators, read receipts, group management
- **transfer_to_scheduler**: create reminders, track outbound follow-up
  conversations, report multi-step task progress
- **transfer_to_inboxer**: look up contacts, read recent inbox messages,
  list installed skills, check wabot daemon health

## When to answer directly (no handoff)
For pure small talk, greetings, or factual questions you can answer from
training data — reply with text directly. No handoff needed for:
- "Hi", "Thanks", "What time is it?" (answer from knowledge)
- Clarifying questions back to the operator

## How to delegate
When you delegate, give the specialist a concise, specific instruction.
Examples:
- "Scrape https://example.com and summarise the headline product."
- "Remember that the user prefers replies in Bengali."
- "Send 'on my way' to +14155551234."
- "Create a reminder for 2026-06-01T09:00:00Z: 'Call Alice.'"
- "Look up contact info for +447700900123."

## Routing rules
- A message mentioning a URL or asking to search the web → scraper
- A message saying "remember", "forget", "do you recall" → memory_keeper
- A message asking to send, message someone, or react → comms
- A message mentioning a reminder, schedule, or "follow up" → scheduler
- A message asking about recent messages, contacts, or bot health → inboxer
- Multi-step tasks: consider whether multiple specialists are needed in sequence;
  complete each step before handing off to the next.

## Never delegate to a specialist for a task they cannot do.
If the right specialist is unclear, ask the operator a clarifying question.
"""


def build_orchestrator_instructions(settings: Settings) -> str:
    """Compose operator customisations onto the static routing prompt.

    Imports ``build_agent_instructions`` lazily (function-local) to avoid a
    circular import: agents/orchestrator.py -> agent.py -> agents/__init__.py.

    Order: operator's persona / knowledge first (establishes "who you are"),
    then the routing rules (defines "what you do with each message").
    """
    # Lazy import to break the circular dependency:
    # agents/orchestrator.py -> agent.py -> agents/__init__.py -> orchestrator.py
    from ..agent import build_agent_instructions  # noqa: PLC0415
    from ..instructions_cache import cached_render_skill_summary  # noqa: PLC0415

    skill_summary = cached_render_skill_summary(settings.skills_dir)
    dynamic = build_agent_instructions(settings, skill_summary)
    return dynamic + "\n\n" + ORCHESTRATOR_INSTRUCTIONS


def build_orchestrator(
    settings: Settings,
    *,
    mcp_servers: list[Any] | None = None,
    composio_tools: list[Any] | None = None,
) -> Agent:
    """Build the orchestrator with handoffs to all 5 specialist subagents.

    Args:
        settings: Application settings.
        mcp_servers: Live MCP server connections prepared by _prepare_agent_turn.
            Attached to the orchestrator so MCP tool capabilities are available
            for turns that do not require a specialist handoff, and so the
            orchestrator has full context before routing.
        composio_tools: Composio tool callables (Gmail, Calendar, etc.) prepared
            by _prepare_agent_turn. Attached to the orchestrator rather than a
            specialist so all Composio integrations remain accessible at the
            routing layer regardless of which specialist ultimately handles a turn.
    """
    scraper = build_scraper(settings)
    memory_keeper = build_memory_keeper(settings)
    comms = build_comms(settings)
    scheduler = build_scheduler(settings)
    inboxer = build_inboxer(settings)

    return Agent(
        name="orchestrator",
        instructions=build_orchestrator_instructions(settings),
        model=build_model(settings, purpose=ModelPurpose.CHAT),
        model_settings=model_settings(settings, purpose=ModelPurpose.CHAT),
        # MCP servers + Composio tools live on the orchestrator.
        # Specialists stay narrowly focused on their own native tool sets.
        tools=composio_tools or [],
        mcp_servers=mcp_servers or [],
        handoffs=[
            # Scraper: strip tool history — it doesn't need orchestrator's tool context
            handoff(agent=scraper, input_filter=remove_all_tools),
            # Memory keeper: preserve conversation context (needs to know what was said)
            handoff(agent=memory_keeper),
            # Comms: preserve conversation context (needs to know who to message and what)
            handoff(agent=comms),
            # Scheduler: preserve conversation context (needs timing and task details)
            handoff(agent=scheduler),
            # Inboxer: strip tool history — read-only, only needs the question
            handoff(agent=inboxer, input_filter=remove_all_tools),
        ],
    )
