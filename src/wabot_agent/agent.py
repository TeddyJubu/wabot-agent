from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from agents import Agent, Runner
from agents.tracing import set_tracing_disabled

from .composio_tools import composio_enabled, load_composio_tools
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
from .mcp import connected_mcp_servers
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
from .skills import render_skill_summary
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
- web_research_health / start_web_research / get_web_research_status / list_web_research_jobs /
  cancel_web_research — Firecrawl web-agent deep scraping (owner-only). Queue long research jobs;
  results are delivered on WhatsApp as text + CSV/document when complete. Read skills/web-research
  for lead-gen briefs.
- Groups, reactions, edits, mutes, archives — when the task requires them.

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

INSTRUCTIONS_TOOLS_COMPOSIO = (
    "- Composio (Gmail, GitHub, Slack, Notion, etc.) — use COMPOSIO_* tools for external apps.\n"
    "- Call COMPOSIO_MANAGE_CONNECTIONS when auth is required; send the OAuth link in your "
    "reply so the user can approve in a browser.\n"
    "- Then use COMPOSIO_SEARCH_TOOLS / COMPOSIO_MULTI_EXECUTE_TOOL as needed.\n"
)

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
    return (
        f"{INSTRUCTIONS}{memory_block}{tools_block}{INSTRUCTIONS_MULTI_STEP}"
        f"{INSTRUCTIONS_INBOUND}\n\n"
        f"Installed local skills:\n{skill_summary}\n"
    )


def build_agent(
    settings: Settings,
    mcp_servers: list[Any] | None = None,
    *,
    extra_tools: list[Any] | None = None,
) -> Agent[RuntimeContext]:
    skill_summary = render_skill_summary(settings.skills_dir)
    instructions = build_agent_instructions(settings, skill_summary)
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


async def run_agent(
    prompt: str,
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    wabot: WabotClient | None = None,
    inbound: InboundMessage | None = None,
    session_id: str | None = None,
) -> AgentRunResult:
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
    file_context = await build_inbound_file_context(
        inbound, settings=settings, wabot=context.wabot
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
    if mem0_enabled(settings):
        augmented = await inject_mem0_context(
            settings, augmented, user_ids=memory_user_ids
        )
    augmented = cap_turn_prompt(augmented, settings.prompt_max_chars)
    runner_input = await prepare_runner_input(
        augmented,
        settings=settings,
        inbound=inbound,
        wabot=context.wabot,
    )

    await maybe_send_task_started_ack(context, prompt)

    composio_tools = load_composio_tools(
        settings, user_id=person_memory_id, memory=memory
    )

    async def _execute_run() -> Any:
        async with connected_mcp_servers(
            settings.mcp_config, skip_names=_mcp_skip_names(settings)
        ) as mcp_servers:
            agent = build_agent(
                settings, mcp_servers=mcp_servers, extra_tools=composio_tools
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
    for attempt in range(2):
        try:
            result = await _execute_run()
            break
        except Exception as exc:
            if (
                attempt == 0
                and settings.model_provider == "codex"
                and is_recoverable_codex_session_error(exc)
            ):
                clear_agent_session(settings.db_path, session_key)
                continue
            raise
    assert result is not None

    await prune_session_storage(settings, session_key, memory)
    maybe_prune_codex_session_storage(settings, session_key)
    maybe_prune_audit_tables(memory, settings)

    final_output = strip_model_thinking(str(result.final_output))
    if settings.model_provider == "codex" and not final_output.strip():
        if clear_agent_session(settings.db_path, session_key) > 0:
            result = await _execute_run()
            final_output = strip_model_thinking(str(result.final_output))
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
    event_log.write(
        "agent_run_complete",
        {
            "run_id": run_id,
            "session_id": session_key,
            "live_model": settings.live_model_enabled,
            # Carry enough for the dashboard runs panel to render without a
            # follow-up /api/runs fetch. EventLog passes both through redact()
            # before broadcast, so the SSE wire payload stays redacted.
            "sender": inbound.sender if inbound else None,
            "user_input": prompt,
            "final_output": final_output,
        },
    )
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
    file_context = await build_inbound_file_context(
        inbound, settings=settings, wabot=context.wabot
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
    if mem0_enabled(settings):
        augmented = await inject_mem0_context(
            settings, augmented, user_ids=memory_user_ids
        )
    augmented = cap_turn_prompt(augmented, settings.prompt_max_chars)
    runner_input = await prepare_runner_input(
        augmented,
        settings=settings,
        inbound=inbound,
        wabot=context.wabot,
    )

    await maybe_send_task_started_ack(context, prompt)

    composio_tools = load_composio_tools(
        settings, user_id=person_memory_id, memory=memory
    )

    final_output = ""
    errored: Exception | None = None
    streamed_events: list[dict[str, Any]] = []

    for attempt in range(2):
        final_output = ""
        errored = None
        streamed_events = []
        async with connected_mcp_servers(
            settings.mcp_config, skip_names=_mcp_skip_names(settings)
        ) as mcp_servers:
            agent = build_agent(
                settings, mcp_servers=mcp_servers, extra_tools=composio_tools
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
                                streamed_events.append(payload)
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
                        streamed_events.append({"type": "delta", "text": final_output})
                except Exception as exc:  # noqa: BLE001
                    errored = exc

        maybe_prune_codex_session_storage(settings, session_key)

        if errored is not None:
            if (
                attempt == 0
                and settings.model_provider == "codex"
                and is_recoverable_codex_session_error(errored)
            ):
                clear_agent_session(settings.db_path, session_key)
                continue
            break

        if settings.model_provider == "codex" and not final_output.strip():
            if clear_agent_session(settings.db_path, session_key) > 0:
                continue
        break

    for payload in streamed_events:
        yield payload

    if errored is not None:
        message = redact(str(errored))
        event_log.write(
            "agent_run_failed",
            {"run_id": run_id, "session_id": session_key, "error": message},
        )
        yield {"type": "error", "message": message}
        return

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
    mem0_ids = inbound_memory_user_ids(inbound)
    mem0_on = mem0_enabled(settings)
    if mem0_on:
        recall_step = (
            f"2) Recall memory for sender={memory_user} (includes facts from other chats "
            f"with this person): call search_mem0_memories (query the topic; optional "
            f"user_id one of {mem0_ids}) and recall_contact_memory (contact={memory_user}).\n"
        )
        persist_step = (
            f"7) If they shared anything important (preferences, names, deadlines, passcodes, "
            f"standing requests, or said remember/don't forget), call add_mem0_memory "
            f"(user_id={memory_user}) and/or remember_contact_fact (contact={memory_user}) "
            "BEFORE your final reply.\n"
        )
    else:
        recall_step = (
            f"2) Recall memory: call recall_contact_memory (contact={memory_user}) when "
            "prior context may matter.\n"
        )
        persist_step = (
            f"7) If they shared anything important, call remember_contact_fact "
            f"(contact={memory_user}) BEFORE your final reply.\n"
        )
    steps = (
        "Before you answer this inbound WhatsApp message:\n"
        "1) Decide what they need.\n"
        + recall_step
        + "3) If you need thread context, call get_last_whatsapp_inbound_message or "
        "list_whatsapp_inbound_messages.\n"
        "4) For requests to find/download/send files from the internet, use search_images or "
        "search_web, then fetch_url_to_media, then send_whatsapp_file to the sender. "
        "5) Inbound attachments are downloaded and processed on the VPS automatically; "
        "voice notes include voice_transcript / [transcript] — reply using that text directly "
        "(do not claim you cannot hear audio when a transcript is present). PDFs include "
        "extracted or OCR text in the VPS file processing block — summarize that content; do not "
        "claim you cannot read a PDF when an excerpt is present. Photos also attach for vision. "
        "Use process_whatsapp_attachment only if processing failed or you need a refresh.\n"
        "6) If WhatsApp status is unclear, call wabot_health.\n"
        + persist_step
        + "8) Then write your final reply (plain text only — it is sent automatically).\n\n"
    )
    group_note = ""
    if inbound.is_group:
        group_note = (
            "Group chat: reply to the group using send_whatsapp_text(to=chat, ...) when you need "
            "an extra message; auto-reply posts to chat. Long-term memory is keyed to sender "
            f"({memory_user}), not only this group — recall works across their other chats. "
            "Add the group JID to WABOT_AGENT_ALLOWED_RECIPIENTS when send_policy=allowlist.\n"
        )
    multi_step_note = ""
    if looks_like_multi_step_task(inbound.text):
        multi_step_note = (
            "Multi-step task detected: call send_task_plan with your steps BEFORE "
            "heavy work, then report_task_step_complete after each step. Use "
            "send_task_progress if a step runs silently for more than a minute.\n\n"
        )
    return (
        steps
        + multi_step_note
        + group_note
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
