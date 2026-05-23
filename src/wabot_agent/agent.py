from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from agents import Agent, RunConfig, Runner
from agents.tracing import set_tracing_disabled

from .composio_tools import (
    build_composio_prompt_context,
    composio_enabled,
    load_composio_tools,
)
from .config import Settings
from .context_management import (
    build_agent_run_config,
    build_agent_session,
    cap_turn_prompt,
    clear_agent_session,
    is_recoverable_codex_session_error,
    maybe_prune_audit_tables,
    maybe_prune_codex_session_storage,
    prune_session_storage,
)
from .events import EventLog
from .inbound_media import build_inbound_file_context, voice_transcript_from_context
from .instructions_cache import cached_build_agent_instructions, cached_render_skill_summary
from .knowledge_store import (
    format_contact_facts,
    load_global_memory,
    load_instructions,
)
from .mcp import connected_mcp_servers
from .media_download import download_inbound_media
from .mem0_store import capture_turn_mem0, inject_mem0_context, mem0_enabled
from .memory import (
    InboundMessage,
    MemoryStore,
    inbound_chat_session_id,
    inbound_memory_contact_id,
    inbound_memory_user_ids,
    inbound_person_memory_id,
)
from .models import build_model, model_settings
from .output_sanitize import strip_model_thinking
from .redaction import redact
from .task_progress import looks_like_multi_step_task
from .tools import RuntimeContext, core_tools, maybe_send_task_started_ack
from .ui_envelopes import build_ui_envelope
from .vision_input import prepare_runner_input
from .wabot import WabotClient

set_tracing_disabled(True)
logger = logging.getLogger(__name__)


INSTRUCTIONS = """You are wabot-agent, a capable WhatsApp operations agent on a VPS.

You are not a passive chatbot. Think step by step, use tools when they improve accuracy,
and make reasonable decisions with the capabilities you have. Do not guess facts you can
look up. Do not give one-line non-answers when the user needs help.

## How to work (every turn)

1. **Understand** — What is the user asking? What outcome do they need?
2. **Recall** — Before answering, check memory for this contact (see Memory below).
3. **Gather** — Call other tools when you lack facts (inbox, health, contacts, media).
4. **Decide** — Pick the best action; explain trade-offs only when they matter.
5. **Act** — Use send/read/typing/memory tools when policy allows and the task needs it.
6. **Persist** — After acting, save anything important they said or you committed to (Memory).
7. **Respond** — Give a clear, human answer. For WhatsApp auto-replies, your final message
   is what the person reads (no tool names, no JSON, no <thinking> blocks).
"""

INSTRUCTIONS_MEMORY_SQLITE = """## Memory (structured facts)

Before answering, call `recall_contact_memory` when prior context may matter.
Before your final reply, call `remember_contact_fact` for crisp key/value items
(e.g. `timezone`, `preferred_name`) and `remember_agent_note` only for global operator rules.

**What counts as important:** names and roles, preferences, recurring requests, open tasks,
relationships ("message John when…"), business details, and corrections to prior mistakes.
**Do not store:** passwords, OTPs, API keys, full card numbers, or clinical patient records.
In group chats, use `contact` = the **sender** JID (memory follows the person, not only the group).
"""

INSTRUCTIONS_MEMORY_MEM0 = """## Memory (mandatory — do not skip)

You must **actively** maintain long-term memory. Do not rely on the current thread alone.

**Before you answer (every inbound turn):**
- Call `search_mem0_memories` with a short query (defaults to the sender — includes
  memories from other chats with this person).
- Call `recall_contact_memory` with `contact` = sender (not the group JID).
- Use what you find; if memory is empty, say so only when they explicitly ask "do you remember…"

**After you understand the message — save important facts before your final reply:**
- Call `add_mem0_memory` for preferences, names, deadlines, business context, ongoing projects,
  how they want to be addressed, and anything they say "remember" or "don't forget".
- Call `remember_contact_fact` for crisp key/value items (e.g. `timezone`, `preferred_name`).
- Call `remember_agent_note` only for global operator-wide rules (not per-contact secrets).

Mem0 may auto-capture the conversation when enabled — still call `add_mem0_memory` or
`remember_contact_fact` for facts you must not lose, so they are explicit and searchable.
"""

INSTRUCTIONS_TOOLS = """## Tools (use them proactively)

- wabot_health — before assuming WhatsApp is linked.
- list_whatsapp_inbound_messages / get_last_whatsapp_inbound_message — who messaged, context.
- recall_contact_memory / remember_contact_fact — per-contact key/value facts (SQLite).
- lookup_whatsapp_contacts — before messaging unknown numbers.
- WhatsApp is native `wabot` only in this product. Never search for, execute, or
  manage a Composio `whatsapp` toolkit. Never tell the operator to connect
  WhatsApp through Composio. If WhatsApp is not ready, use wabot_health/pairing
  status and report the native wabot readiness issue.
- Inbound files are downloaded and processed on the VPS automatically (text/PDF/zip excerpts).
- process_vps_file / process_whatsapp_attachment — re-read or process attachments on demand.
- search_web / search_images — find pages or image URLs on the public web (no API key).
- fetch_url_to_media — download a public http(s) URL into the VPS media dir.
- send_whatsapp_file — send any allowed file type from the media dir (routes image/video/audio/doc).
- send_whatsapp_* — specific send tools; do not ask the operator to type "approved".
- To find and send an image: search_images → fetch_url_to_media → send_whatsapp_file to the
  requester. Do not claim you cannot browse the web without trying these tools first.
- mark_whatsapp_read, send_whatsapp_typing — when appropriate for the conversation.
- send_task_plan / report_task_step_complete / send_task_progress — multi-step tasks:
  post a plan and WhatsApp updates per step (see Multi-step tasks section).
- create_reminder / list_reminders / cancel_reminder — schedule WhatsApp reminders (ISO due_at).
- track_outbound_conversation / list_outbound_tasks / get_outbound_task_status — owner outreach
  follow-up; successful owner sends auto-track; you are notified when the target replies.
- Appointment booking — keep it simple but real: identify the attendee/contact, duration,
  timezone, and requested window; check the owner's live calendar with Composio when connected
  (or ask the owner for available windows if not connected); then contact the attendee on
  WhatsApp with 2-4 concrete options. Use lookup_whatsapp_contacts for unknown numbers and
  send_whatsapp_text only when policy allows. Track the outreach, wait for the attendee's
  availability/choice, re-check the owner's slot before confirming, and only create a calendar
  event after both sides have agreed.
- web_research_health / start_web_research / get_web_research_status / list_web_research_jobs /
  cancel_web_research — Firecrawl web-agent deep scraping (owner-only). Queue long research jobs;
  results are delivered on WhatsApp as text + CSV/document when complete. Read skills/web-research
  for lead-gen briefs.
- Groups: list_whatsapp_groups, create_whatsapp_group, get_whatsapp_group,
  update_whatsapp_group (name/topic/announce/locked), update_whatsapp_group_participants
  (add/remove/promote/demote), set_whatsapp_group_picture (JPEG path or remove=true),
  get_whatsapp_group_invite, join_whatsapp_group, leave_whatsapp_group — when the task
  requires them.
- Reactions, edits, mutes, archives — when the task requires them.

## Policy & safety

- Fail closed on sends blocked by policy; say what the operator must change.
- send_policy=owner: dashboard and owner numbers may message anyone; other inbound chats are
  reply-only in their thread (no proxying to third parties).
- Never ask for API keys, tokens, passwords, or session databases.
- No bulk spam. No storing secrets in memory (see Memory section).

## WhatsApp style

- Be concise but **complete** — answer the actual question, offer a sensible next step when useful.
- Sound natural on WhatsApp; avoid corporate filler and lazy "I can't help with that"
  without trying tools first.
- Pairing QR: direct operators to /pair (after /login), not the chat bot.
"""

INSTRUCTIONS_TOOLS_MEM0 = (
    "- search_mem0_memories / add_mem0_memory / mem0_status — semantic long-term memory (Mem0).\n"
)

INSTRUCTIONS_TOOLS_COMPOSIO = """- Composio (Gmail, Google Calendar, GitHub, Slack, …) —
  COMPOSIO_* meta-tools only.
- **Hard boundary:** WhatsApp is never a Composio app/toolkit here. Do not call
  COMPOSIO_SEARCH_TOOLS for WhatsApp lookup/send/use cases. Do not call COMPOSIO_MANAGE_CONNECTIONS
  with `whatsapp`. All WhatsApp sending, lookup,
  groups, media, and readiness checks must use the native wabot tools.
- **Gmail & Calendar are connected** for this operator. For any email or calendar question,
  you MUST call COMPOSIO_SEARCH_TOOLS then COMPOSIO_MULTI_EXECUTE_TOOL in this turn before
  stating facts. Re-fetch every turn; never reuse stale inbox/calendar summaries from chat.
- For appointment booking, use Calendar tools to verify the owner's availability before offering
  times and again before creating the event. Use native wabot tools for the attendee's WhatsApp
  contact/outreach. The attendee's availability must come from their WhatsApp reply or another
  live source, not from a guess.
- **Never hallucinate** mail or events: no invented subjects, senders, times, attendees, or counts.
  If tools fail or return empty, say that plainly — do not guess.
- Read skill `composio-gmail-calendar` (read_local_skill) before non-trivial mail/calendar work.
- COMPOSIO_MANAGE_CONNECTIONS when Gmail/Calendar or another external non-WhatsApp app auth
  fails; paste the OAuth link in your reply. Never generate or share a Composio WhatsApp link.
"""

INSTRUCTIONS_INBOUND = """## Inbound auto-reply

- Your **final** plain-text reply is sent to the sender automatically
  (1:1 and groups when enabled).
- In groups, `chat` is the group JID; `sender` is the participant —
  reply via send_whatsapp_text(to=chat).
- Do not send_whatsapp_text to that same chat unless messaging a *different* recipient.
- If they sent media, download and understand it before answering when relevant.
- After messaging someone on the owner's behalf, use track_outbound_conversation
  (or rely on auto-track) so the owner gets a WhatsApp update when they reply.
"""

INSTRUCTIONS_MULTI_STEP = """## Multi-step tasks (plan + progress on WhatsApp)

When a request needs **several tools**, **multiple minutes**, or **3+ distinct actions**:

1. **Plan first** — Call `send_task_plan` with 3–8 short step titles before heavy work.
   Do not start scraping, bulk sends, or long research without posting the plan.
2. **After each step** — Call `report_task_step_complete` with step number, title, and
   one-line outcome before moving on.
3. **Long silent stretches** — If a step takes >60s with no other update, call
   `send_task_progress` (e.g. "Still fetching page 4/12…").
4. **Final answer** — Your closing plain-text reply should summarize results; do not
   repeat the whole plan unless asked.

Skip progress tools for quick one-shot questions (single lookup, yes/no, short reply).
"""


@dataclass
class AgentRunResult:
    run_id: str
    final_output: str
    session_id: str
    live_model: bool
    sent_destinations: frozenset[str] = frozenset()


def build_agent_instructions(settings: Settings, skill_summary: str) -> str:
    memory_block = (
        INSTRUCTIONS_MEMORY_MEM0
        if mem0_enabled(settings)
        else INSTRUCTIONS_MEMORY_SQLITE
    )
    tools_block = INSTRUCTIONS_TOOLS
    if mem0_enabled(settings):
        tools_block = tools_block.replace(
            "- lookup_whatsapp_contacts",
            f"{INSTRUCTIONS_TOOLS_MEM0}- lookup_whatsapp_contacts",
            1,
        )
    if composio_enabled(settings):
        tools_block = tools_block.replace(
            "- lookup_whatsapp_contacts",
            f"{INSTRUCTIONS_TOOLS_COMPOSIO}- lookup_whatsapp_contacts",
            1,
        )
    parts = [
        INSTRUCTIONS,
        memory_block,
        tools_block,
        INSTRUCTIONS_MULTI_STEP,
        INSTRUCTIONS_INBOUND,
        f"\nInstalled local skills:\n{skill_summary}\n",
    ]
    custom = load_instructions(settings)
    global_mem = load_global_memory(settings)
    if custom:
        parts.append(f"\n## Client instructions\n{custom}\n")
    if global_mem:
        parts.append(f"\n## Operator knowledge\n{global_mem}\n")
    return "".join(parts)


@dataclass
class PreparedTurn:
    run_id: str
    session_key: str
    memory_user_ids: list[str]
    person_memory_id: str
    run_config: RunConfig
    context: RuntimeContext
    augmented: str
    runner_input: str | list[Any]
    composio_tools: list[Any]


async def _prepare_agent_turn(
    prompt: str,
    *,
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    wabot: WabotClient | None = None,
    inbound: InboundMessage | None = None,
    session_id: str | None = None,
) -> PreparedTurn:
    run_id = str(uuid.uuid4())
    session_key = session_id or (
        inbound_chat_session_id(inbound) if inbound else "operator"
    )
    memory_user_ids = inbound_memory_user_ids(inbound) if inbound else ["operator"]
    person_memory_id = (
        inbound_person_memory_id(inbound) if inbound else memory_user_ids[0]
    )
    run_config = build_agent_run_config(settings, session_key, memory)
    context = RuntimeContext(
        settings=settings,
        memory=memory,
        wabot=wabot or WabotClient(settings.wabot_endpoint, settings.resolved_wabot_token),
        event_log=event_log,
        run_id=run_id,
        inbound=inbound,
    )
    event_log.write("agent_run_start", {"run_id": run_id, "session_id": session_key})

    augmented = _augment_prompt(prompt, inbound, settings)
    downloaded = None
    if (
        inbound is not None
        and inbound.has_media
        and settings.file_process_inbound
    ):
        downloaded = await download_inbound_media(context.wabot, inbound, settings)
    file_context = await build_inbound_file_context(
        inbound,
        settings=settings,
        wabot=context.wabot,
        downloaded=downloaded,
    )
    augmented += file_context
    transcript = voice_transcript_from_context(file_context)
    if transcript:
        augmented = (
            f"[Voice note transcription — reply to this text; ignore earlier "
            f"failed-transcription replies in the thread if they conflict: "
            f"\"{transcript}\"]\n\n"
            + augmented
        )
    if person_memory_id:
        facts = memory.recall_contact(person_memory_id)
        block = format_contact_facts(
            facts, max_chars=settings.knowledge_contact_max_chars
        )
        if block:
            augmented = f"Known facts about this contact:\n{block}\n\n{augmented}"
    if mem0_enabled(settings):
        augmented = await inject_mem0_context(
            settings, augmented, user_ids=memory_user_ids
        )
    composio_tools = load_composio_tools(
        settings, user_id=person_memory_id, memory=memory
    )
    augmented += build_composio_prompt_context(tools_loaded=bool(composio_tools))
    augmented = cap_turn_prompt(augmented, settings.prompt_max_chars)
    runner_input = await prepare_runner_input(
        augmented,
        settings=settings,
        inbound=inbound,
        wabot=context.wabot,
        downloaded=downloaded,
    )
    await maybe_send_task_started_ack(context, prompt)
    return PreparedTurn(
        run_id=run_id,
        session_key=session_key,
        memory_user_ids=memory_user_ids,
        person_memory_id=person_memory_id,
        run_config=run_config,
        context=context,
        augmented=augmented,
        runner_input=runner_input,
        composio_tools=composio_tools,
    )


def build_agent(
    settings: Settings,
    mcp_servers: list[Any] | None = None,
    *,
    extra_tools: list[Any] | None = None,
    memory: MemoryStore | None = None,
) -> Agent[RuntimeContext]:
    skill_summary = cached_render_skill_summary(settings.skills_dir)
    instructions = cached_build_agent_instructions(
        settings,
        memory=memory,
        build_fn=build_agent_instructions,
        build_kwargs={"settings": settings, "skill_summary": skill_summary},
    )
    tools = [*core_tools(), *(extra_tools or [])]
    return Agent[RuntimeContext](
        name="wabot-agent-whatsapp-operator",
        instructions=instructions,
        model=build_model(settings),
        model_settings=model_settings(settings),
        tools=tools,
        mcp_servers=mcp_servers or [],
    )


def _mcp_skip_names(settings: Settings) -> frozenset[str]:
    if composio_enabled(settings):
        return frozenset({"composio"})
    return frozenset()


_CODEX_EMPTY_OUTPUT_MAX_ATTEMPTS = 2

_CODEX_LIGHTWEIGHT_INSTRUCTIONS = (
    "You are a helpful WhatsApp assistant. Reply in plain text only. "
    "Be concise and useful. Do not call tools."
)


async def _run_codex_lightweight_reply(
    settings: Settings,
    runner_input: str | list[Any],
    context: RuntimeContext,
) -> str:
    """Codex often returns empty with the full tool graph; a tiny agent is more reliable."""
    agent = Agent[RuntimeContext](
        name="wabot-agent-light-reply",
        instructions=_CODEX_LIGHTWEIGHT_INSTRUCTIONS,
        model=build_model(settings),
        model_settings=model_settings(settings),
        tools=[],
    )
    light_config = RunConfig(tracing_disabled=True, workflow_name="wabot-agent-light")
    for attempt in range(3):
        try:
            result = await Runner.run(
                agent,
                runner_input,
                context=context,
                max_turns=2,
                run_config=light_config,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Codex lightweight fallback failed (attempt %s/3): %s",
                attempt + 1,
                exc,
            )
            continue
        text = strip_model_thinking(str(result.final_output or ""))
        if text.strip():
            return text
    return ""


def _codex_max_attempts(settings: Settings) -> int:
    """Number of codex run attempts (1 for non-codex providers)."""
    return _CODEX_EMPTY_OUTPUT_MAX_ATTEMPTS if settings.model_provider == "codex" else 1


def _should_retry_codex_session_error(
    exc: Exception, attempt: int, max_attempts: int, settings: Settings
) -> bool:
    """True when the codex retry loop should swallow ``exc`` and try again.

    Both ``run_agent`` and ``run_agent_streamed`` use the same predicate so a
    future change to "what counts as recoverable" only needs one edit.
    """
    return (
        attempt < max_attempts - 1
        and settings.model_provider == "codex"
        and is_recoverable_codex_session_error(exc)
    )


def _log_codex_empty_attempt(
    attempt: int, max_attempts: int, session_key: str, *, streamed: bool = False
) -> None:
    """One-liner used by both run paths to log a codex empty-output retry."""
    label = "Codex streamed run" if streamed else "Codex run"
    logger.warning(
        "%s returned empty output (attempt %s/%s, session=%s)",
        label,
        attempt + 1,
        max_attempts,
        session_key,
    )


async def _finalize_turn_state(
    *,
    settings: Settings,
    memory: MemoryStore,
    session_key: str,
    run_id: str,
    prompt: str,
    final_output: str,
    person_memory_id: str | None,
    inbound: InboundMessage | None,
) -> None:
    """Post-run bookkeeping shared by ``run_agent`` and ``run_agent_streamed``.

    Runs the cleanup + audit sequence in this fixed order:
      1. ``prune_session_storage`` — agent SDK session table.
      2. ``maybe_prune_codex_session_storage`` — codex per-session sqlite.
      3. ``maybe_prune_audit_tables`` — runs / tool_events / session_summaries.
      4. ``memory.record_run`` — persist the run row.
      5. Best-effort ``capture_turn_mem0`` — never blocks the turn on mem0 errors.

    Callers do their own ``event_log.write`` afterwards (the streamed and
    non-streamed paths emit different event shapes intentionally) and their
    own return / yield. This helper does not write to ``event_log``.
    """
    await prune_session_storage(settings, session_key, memory)
    maybe_prune_codex_session_storage(settings, session_key)
    maybe_prune_audit_tables(memory, settings)
    memory.record_run(run_id, inbound.sender if inbound else None, prompt, final_output)
    if mem0_enabled(settings):
        try:
            await capture_turn_mem0(
                settings,
                user_id=person_memory_id,
                user_text=prompt,
                assistant_text=final_output,
                run_id=run_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("mem0 capture failed: %s", exc)


async def run_agent(
    prompt: str,
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    wabot: WabotClient | None = None,
    inbound: InboundMessage | None = None,
    session_id: str | None = None,
) -> AgentRunResult:
    turn = await _prepare_agent_turn(
        prompt,
        settings=settings,
        memory=memory,
        event_log=event_log,
        wabot=wabot,
        inbound=inbound,
        session_id=session_id,
    )
    run_id = turn.run_id
    session_key = turn.session_key
    person_memory_id = turn.person_memory_id
    run_config = turn.run_config
    context = turn.context
    runner_input = turn.runner_input
    composio_tools = turn.composio_tools

    async def _execute_run() -> Any:
        async with connected_mcp_servers(
            settings.mcp_config, skip_names=_mcp_skip_names(settings)
        ) as mcp_servers:
            agent = build_agent(
                settings,
                mcp_servers=mcp_servers,
                extra_tools=composio_tools,
                memory=memory,
            )
            return await Runner.run(
                agent,
                runner_input,
                context=context,
                max_turns=settings.max_agent_turns,
                run_config=run_config,
                session=build_agent_session(settings, session_key),
            )

    result: Any | None = None
    final_output = ""
    partial_error: Exception | None = None
    max_attempts = _codex_max_attempts(settings)
    for attempt in range(max_attempts):
        try:
            result = await _execute_run()
        except Exception as exc:
            if _should_retry_codex_session_error(exc, attempt, max_attempts, settings):
                clear_agent_session(settings.db_path, session_key)
                continue
            if context.sent_destinations:
                partial_error = exc
                logger.warning(
                    "Agent run failed after sending WhatsApp output "
                    "(run=%s, session=%s): %s",
                    run_id,
                    session_key,
                    exc,
                )
                break
            raise
        final_output = strip_model_thinking(str(result.final_output))
        if final_output.strip():
            break
        if settings.model_provider == "codex":
            _log_codex_empty_attempt(attempt, max_attempts, session_key)
            clear_agent_session(settings.db_path, session_key)
            continue
        break
    assert result is not None or partial_error is not None

    if (
        not final_output.strip()
        and settings.model_provider == "codex"
        and partial_error is None
    ):
        fallback = await _run_codex_lightweight_reply(settings, runner_input, context)
        if fallback.strip():
            logger.info(
                "Codex lightweight fallback produced a reply (session=%s)",
                session_key,
            )
            final_output = fallback

    await _finalize_turn_state(
        settings=settings,
        memory=memory,
        session_key=session_key,
        run_id=run_id,
        prompt=prompt,
        final_output=final_output,
        person_memory_id=person_memory_id,
        inbound=inbound,
    )
    event_payload = {
        "run_id": run_id,
        "session_id": session_key,
        "live_model": settings.live_model_enabled,
        # Carry enough for the dashboard runs panel to render without a
        # follow-up /api/runs fetch. EventLog passes both through redact()
        # before broadcast, so the SSE wire payload stays redacted.
        "sender": inbound.sender if inbound else None,
        "user_input": prompt,
        "final_output": final_output,
    }
    if partial_error is not None:
        event_payload["error"] = str(partial_error)
        event_payload["sent_destinations"] = sorted(context.sent_destinations or ())
        event_log.write("agent_run_partial", event_payload)
    else:
        event_log.write("agent_run_complete", event_payload)
    return AgentRunResult(
        run_id=run_id,
        final_output=final_output,
        session_id=session_key,
        live_model=settings.live_model_enabled,
        sent_destinations=frozenset(context.sent_destinations or ()),
    )


async def run_agent_streamed(
    prompt: str,
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    wabot: WabotClient | None = None,
    inbound: InboundMessage | None = None,
    session_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run the agent and yield NDJSON-shaped events as they happen.

    Yields dicts of the following shapes:
      {"type": "delta", "text": "..."}
      {"type": "tool_call", "name": "...", "args_redacted": {...}, "call_id": "..."}
      {"type": "tool_result", "name": "...", "ok": true, "call_id": "..."}
      {"type": "final", "run_id": "...", "session_id": "...",
       "output": "...", "live_model": bool}
      {"type": "error", "message": "..."}

    Falls back to a single delta+final pair when the underlying model does not
    support streaming (e.g. OfflineModel) or when Runner.run_streamed is
    unavailable on the installed SDK. The wire shape is identical either way,
    so the client only needs one parser.
    """
    turn = await _prepare_agent_turn(
        prompt,
        settings=settings,
        memory=memory,
        event_log=event_log,
        wabot=wabot,
        inbound=inbound,
        session_id=session_id,
    )
    run_id = turn.run_id
    session_key = turn.session_key
    person_memory_id = turn.person_memory_id
    run_config = turn.run_config
    context = turn.context
    runner_input = turn.runner_input
    composio_tools = turn.composio_tools

    final_output = ""
    errored: Exception | None = None
    max_attempts = _codex_max_attempts(settings)

    for attempt in range(max_attempts):
        final_output = ""
        errored = None
        async with connected_mcp_servers(
            settings.mcp_config, skip_names=_mcp_skip_names(settings)
        ) as mcp_servers:
            agent = build_agent(
                settings,
                mcp_servers=mcp_servers,
                extra_tools=composio_tools,
                memory=memory,
            )
            use_streaming = (
                hasattr(Runner, "run_streamed") and settings.live_model_enabled
            )

            if use_streaming:
                try:
                    stream_result = Runner.run_streamed(
                        agent,
                        runner_input,
                        context=context,
                        max_turns=settings.max_agent_turns,
                        run_config=run_config,
                        session=build_agent_session(settings, session_key),
                    )
                    try:
                        state: dict[str, str] = {}
                        async for event in stream_result.stream_events():
                            for payload in _translate_stream_event(event, state):
                                yield payload
                    except Exception as exc:  # noqa: BLE001
                        errored = exc
                        try:
                            stream_result.cancel()
                        except Exception:  # noqa: BLE001
                            pass
                    else:
                        final_output = strip_model_thinking(
                            str(stream_result.final_output or "")
                        )
                except NotImplementedError:
                    use_streaming = False
                except Exception as exc:  # noqa: BLE001
                    errored = exc

            if not use_streaming and errored is None:
                try:
                    result = await Runner.run(
                        agent,
                        runner_input,
                        context=context,
                        max_turns=settings.max_agent_turns,
                        run_config=run_config,
                        session=build_agent_session(settings, session_key),
                    )
                    final_output = strip_model_thinking(str(result.final_output))
                    if final_output:
                        yield {"type": "delta", "text": final_output}
                except Exception as exc:  # noqa: BLE001
                    errored = exc

        maybe_prune_codex_session_storage(settings, session_key)

        if errored is not None:
            if _should_retry_codex_session_error(
                errored, attempt, max_attempts, settings
            ):
                clear_agent_session(settings.db_path, session_key)
                continue
            break

        if final_output.strip():
            break
        if settings.model_provider == "codex":
            _log_codex_empty_attempt(attempt, max_attempts, session_key, streamed=True)
            clear_agent_session(settings.db_path, session_key)
            if attempt + 1 >= max_attempts:
                fallback = await _run_codex_lightweight_reply(
                    settings, runner_input, context
                )
                if fallback.strip():
                    final_output = fallback
                    yield {"type": "delta", "text": final_output}
            continue
        break

    if errored is not None:
        message = redact(str(errored))
        event_log.write(
            "agent_run_failed",
            {"run_id": run_id, "session_id": session_key, "error": message},
        )
        yield {"type": "error", "message": message}
        return

    await _finalize_turn_state(
        settings=settings,
        memory=memory,
        session_key=session_key,
        run_id=run_id,
        prompt=prompt,
        final_output=final_output,
        person_memory_id=person_memory_id,
        inbound=inbound,
    )
    event_log.write(
        "agent_run_complete",
        {
            "run_id": run_id,
            "session_id": session_key,
            "live_model": settings.live_model_enabled,
            # Match the non-streaming run_agent payload so the dashboard SSE
            # handler can render the run card without a follow-up /api/runs
            # fetch on the streaming path too. EventLog.write redacts.
            "sender": inbound.sender if inbound else None,
            "user_input": prompt,
            "final_output": final_output,
        },
    )
    yield {
        "type": "final",
        "run_id": run_id,
        "session_id": session_key,
        "output": final_output,
        "live_model": settings.live_model_enabled,
    }


def _translate_stream_event(
    event: Any, state: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Convert one Agents SDK StreamEvent into zero or more NDJSON payloads.

    Tool-call args are passed through `redact()` before they go on the wire —
    the model can emit raw user input or sensitive arguments as part of
    function calls, and these should never reach the operator UI unredacted.

    `state` carries call_id -> tool_name across successive events in one run,
    so that tool_output events can attach the matching ui envelope (the
    Agents-SDK output item doesn't carry the tool name directly). Callers
    that don't care about ui envelopes can omit it.
    """
    if state is None:
        state = {}
    out: list[dict[str, Any]] = []
    etype = getattr(event, "type", None)

    if etype == "raw_response_event":
        data = getattr(event, "data", None)
        # Only forward output_text deltas — these are the model's visible
        # response tokens. Tool-call argument deltas, function metadata, etc.
        # are noise for the chat composer.
        data_type = getattr(data, "type", None)
        delta = getattr(data, "delta", None)
        if data_type == "response.output_text.delta" and isinstance(delta, str) and delta:
            out.append({"type": "delta", "text": delta})
        return out

    if etype == "run_item_stream_event":
        name = getattr(event, "name", None)
        item = getattr(event, "item", None)
        if name == "tool_called" and item is not None:
            tool_name = getattr(item, "tool_name", None) or "<unknown>"
            raw = getattr(item, "raw_item", None)
            args = _extract_tool_args(raw)
            payload: dict[str, Any] = {
                "type": "tool_call",
                "name": str(tool_name),
                "args_redacted": redact(args) if args is not None else None,
            }
            call_id = getattr(item, "call_id", None)
            if call_id:
                payload["call_id"] = str(call_id)
                state[str(call_id)] = str(tool_name)
            out.append(payload)
        elif name == "tool_output" and item is not None:
            call_id = getattr(item, "call_id", None)
            tool_name = state.get(str(call_id)) if call_id else None
            raw_output = _extract_tool_output(item)
            payload2: dict[str, Any] = {
                "type": "tool_result",
                "ok": _tool_output_ok(item),
            }
            if call_id:
                payload2["call_id"] = str(call_id)
            if tool_name:
                payload2["name"] = tool_name
            if isinstance(raw_output, dict):
                envelope = build_ui_envelope(tool_name or "", raw_output)
                if envelope is not None:
                    payload2["ui"] = envelope
                payload2["result"] = redact(raw_output)
            elif isinstance(raw_output, list):
                payload2["result"] = redact(raw_output)
            elif raw_output is not None:
                # Scalar outputs (typically strings from MCP or error payloads) must
                # also go through redact() — otherwise Bearer tokens, OpenRouter keys,
                # and phone numbers in plain-string tool results leak unredacted to
                # the browser stream. redact() is identity on numbers/bools.
                payload2["result"] = redact(raw_output)
            out.append(payload2)
        return out

    return out


def _extract_tool_output(item: Any) -> Any:
    """Pull the tool result payload off a ToolCallOutputItem.

    Different SDK versions expose it as `output`, `raw_item.output`, or a
    JSON-encoded string on either. We try cheap paths first, parse strings
    where possible, and return None if nothing usable surfaces.
    """
    for getter in (
        lambda i: getattr(i, "output", None),
        lambda i: (getattr(i, "raw_item", None) or {}).get("output")
        if isinstance(getattr(i, "raw_item", None), dict)
        else None,
    ):
        candidate = getter(item)
        if candidate is None:
            continue
        if isinstance(candidate, str):
            try:
                return json.loads(candidate)
            except (ValueError, TypeError):
                return candidate
        return candidate
    return None


def _extract_tool_args(raw_item: Any) -> Any:
    """Best-effort extraction of tool-call arguments from a raw item.

    The raw item shape varies across SDK versions and tool kinds; treat all
    failure modes as "no args" rather than crashing the stream.
    """
    if raw_item is None:
        return None
    if isinstance(raw_item, dict):
        candidate = raw_item.get("arguments")
    else:
        candidate = getattr(raw_item, "arguments", None)
    if candidate is None:
        return None
    if isinstance(candidate, str):
        try:
            return json.loads(candidate)
        except (ValueError, TypeError):
            return {"_raw": candidate}
    return candidate


def _tool_output_ok(item: Any) -> bool:
    """Best-effort check for tool-call failure.

    The Agents SDK signals tool failure on the ToolCallOutputItem in a couple
    of shapes — an `error` attribute, a `status != "completed"` field, or a
    dict-shaped raw item with one of those keys. Be defensive across SDK
    versions: only mark a tool failed when we see an explicit failure signal,
    otherwise default to success so we never erroneously red-flag a healthy
    tool result.
    """
    error = getattr(item, "error", None)
    if error:
        return False
    status = getattr(item, "status", None)
    if isinstance(status, str) and status.lower() in {"error", "failed", "failure"}:
        return False
    raw = getattr(item, "raw_item", None)
    if isinstance(raw, dict):
        if raw.get("error") or raw.get("is_error"):
            return False
        raw_status = raw.get("status")
        if isinstance(raw_status, str) and raw_status.lower() in {"error", "failed", "failure"}:
            return False
    return True


def _augment_prompt(
    prompt: str, inbound: InboundMessage | None, settings: Settings
) -> str:
    if inbound is None:
        return prompt
    memory_user = inbound_memory_contact_id(inbound)
    # System instructions already cover memory/tools/inbound policy — only attach
    # per-message metadata here to keep Codex requests smaller and more reliable.
    group_note = ""
    if inbound.is_group:
        group_note = (
            f"Group chat (memory contact={memory_user}; auto-reply posts to chat JID).\n"
        )
    multi_step_note = ""
    if looks_like_multi_step_task(inbound.text):
        multi_step_note = "Multi-step task — use send_task_plan / report_task_step_complete.\n"
    return (
        group_note
        + multi_step_note
        + "Inbound WhatsApp message:\n"
        f"- message_id: {inbound.id}\n"
        f"- sender: {inbound.sender}\n"
        f"- chat: {inbound.chat or inbound.sender}\n"
        f"- push_name: {inbound.push_name or ''}\n"
        f"- is_group: {inbound.is_group}\n"
        f"- text: {inbound.text}\n"
        f"- has_media: {inbound.has_media}\n"
        f"- media_kind: {inbound.media_kind or ''}\n"
        f"- media_filename: {inbound.media_filename or ''}\n"
    )
