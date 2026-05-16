from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents import Agent, RunConfig, Runner, SQLiteSession
from agents.tracing import set_tracing_disabled

from .config import Settings
from .events import EventLog
from .mcp import connected_mcp_servers
from .memory import InboundMessage, MemoryStore
from .models import build_model, model_settings
from .redaction import redact
from .skills import render_skill_summary
from .tools import RuntimeContext, core_tools
from .ui_envelopes import build_ui_envelope
from .wabot import WabotClient

set_tracing_disabled(True)


INSTRUCTIONS = """You are wabot-agent, a careful WhatsApp operations agent running on a VPS.

Your main job is to help an operator automate WhatsApp workflows through wabot.
You can check wabot health, read recent inbound WhatsApp messages via
list_whatsapp_inbound_messages / get_last_whatsapp_inbound_message, download inbound
media with download_whatsapp_media, send text/image/document/audio/video when policy
allows, remember non-secret contact facts, recall memory, and use configured MCP servers.

The OpenRouter model name may include "omni" (multimodal); that does not grant
extra WhatsApp permissions by itself. Capabilities come from wabot/whatsmeow tools.

Use inbox tools for recent observed messages. Use lookup_whatsapp_contacts,
list_whatsapp_groups, get_whatsapp_group, create/join/invite group tools,
mark_whatsapp_read, send_whatsapp_typing, react/edit/revoke message tools when relevant.
Use mute_whatsapp_chat, archive_whatsapp_chat, and pin_whatsapp_chat for chat list state.
Receipt and typing events from contacts arrive via wabot webhooks and surface on /api/stream
as whatsapp_receipt and whatsapp_presence when WABOT_RECEIPT_URL / WABOT_PRESENCE_URL are set.
mark_read applies server-side read receipts when you have message IDs from inbox or receipts.

Operating rules:
- Fail closed. If a send is not clearly allowed by tool policy, explain what is blocked.
- Never ask the user to paste API keys, WhatsApp tokens, session databases, cookies, or passwords.
- Never store secrets or raw credentials in memory.
- Use wabot_health before assuming WhatsApp is linked and connected.
- Keep messages short, useful, and suitable for WhatsApp unless the operator asks otherwise.
- For inbound WhatsApp messages, answer as an assistant to the sender and use memory only for
  that sender unless the operator explicitly asks for a cross-contact action.
- Respect rate limits and avoid bulk/spam behavior.
- If an MCP tool or skill could change files, run shell commands, or affect external systems,
  treat it as privileged and prefer a brief plan unless policy explicitly allows it.
- Media paths for send/download must stay under WABOT_AGENT_MEDIA_DIR. Use download_whatsapp_media
  for recent inbound media (chat + message_id from inbox/webhook).
- When send_policy allows sending, call send_whatsapp_* tools directly — do not ask the operator
  to type "approved" first.
- Reply in plain English only. Never paste raw tool JSON, function names, or markers like
  [tool_name] in your messages; the dashboard shows structured cards for tool results.
"""


@dataclass
class AgentRunResult:
    run_id: str
    final_output: str
    session_id: str
    live_model: bool


def build_agent(settings: Settings, mcp_servers: list[Any] | None = None) -> Agent[RuntimeContext]:
    skill_summary = render_skill_summary(settings.skills_dir)
    instructions = f"{INSTRUCTIONS}\n\nInstalled local skills:\n{skill_summary}\n"
    return Agent[RuntimeContext](
        name="wabot-agent-whatsapp-operator",
        instructions=instructions,
        model=build_model(settings),
        model_settings=model_settings(settings),
        tools=core_tools(),
        mcp_servers=mcp_servers or [],
    )


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
    session_key = session_id or (inbound.sender if inbound else "operator")
    sqlite_session = SQLiteSession(
        session_id=session_key,
        db_path=Path(settings.db_path),
    )
    context = RuntimeContext(
        settings=settings,
        memory=memory,
        wabot=wabot or WabotClient(settings.wabot_endpoint, settings.resolved_wabot_token),
        event_log=event_log,
        run_id=run_id,
        inbound=inbound,
    )
    event_log.write("agent_run_start", {"run_id": run_id, "session_id": session_key})

    async with connected_mcp_servers(settings.mcp_config) as mcp_servers:
        agent = build_agent(settings, mcp_servers=mcp_servers)
        result = await Runner.run(
            agent,
            _augment_prompt(prompt, inbound),
            context=context,
            max_turns=settings.max_agent_turns,
            run_config=RunConfig(tracing_disabled=True, workflow_name="wabot-agent"),
            session=sqlite_session,
        )

    final_output = str(result.final_output)
    memory.record_run(run_id, inbound.sender if inbound else None, prompt, final_output)
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
    session_key = session_id or (inbound.sender if inbound else "operator")
    sqlite_session = SQLiteSession(
        session_id=session_key,
        db_path=Path(settings.db_path),
    )
    context = RuntimeContext(
        settings=settings,
        memory=memory,
        wabot=wabot or WabotClient(settings.wabot_endpoint, settings.resolved_wabot_token),
        event_log=event_log,
        run_id=run_id,
        inbound=inbound,
    )
    event_log.write("agent_run_start", {"run_id": run_id, "session_id": session_key})

    augmented = _augment_prompt(prompt, inbound)
    final_output = ""
    errored: Exception | None = None

    async with connected_mcp_servers(settings.mcp_config) as mcp_servers:
        agent = build_agent(settings, mcp_servers=mcp_servers)
        run_config = RunConfig(tracing_disabled=True, workflow_name="wabot-agent")

        # Try the real streaming path. OfflineModel raises NotImplementedError
        # from stream_response — when that happens, or the SDK lacks streaming,
        # fall back to a single delta/final pair so the wire contract holds.
        # Gate on live_model_enabled (not just offline_mode) since the offline
        # echo model is also used when there's no OPENROUTER_API_KEY.
        use_streaming = hasattr(Runner, "run_streamed") and settings.live_model_enabled

        if use_streaming:
            try:
                stream_result = Runner.run_streamed(
                    agent,
                    augmented,
                    context=context,
                    max_turns=settings.max_agent_turns,
                    run_config=run_config,
                    session=sqlite_session,
                )
                try:
                    state: dict[str, str] = {}
                    async for event in stream_result.stream_events():
                        for payload in _translate_stream_event(event, state):
                            yield payload
                except Exception as exc:  # noqa: BLE001 — surface but cleanup
                    errored = exc
                    try:
                        stream_result.cancel()
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    final_output = str(stream_result.final_output or "")
            except NotImplementedError:
                # Model doesn't implement stream_response — fall through to the
                # non-streamed Runner.run() path below.
                use_streaming = False
            except Exception as exc:  # noqa: BLE001
                errored = exc

        if not use_streaming and errored is None:
            # Single-event fallback path (offline echo model, SDK without
            # streaming, etc.). Identical wire contract: one synthetic delta
            # carrying the entire final output, then the final marker.
            try:
                result = await Runner.run(
                    agent,
                    augmented,
                    context=context,
                    max_turns=settings.max_agent_turns,
                    run_config=run_config,
                    session=sqlite_session,
                )
                final_output = str(result.final_output)
                if final_output:
                    yield {"type": "delta", "text": final_output}
            except Exception as exc:  # noqa: BLE001
                errored = exc

    if errored is not None:
        message = redact(str(errored))
        event_log.write(
            "agent_run_failed",
            {"run_id": run_id, "session_id": session_key, "error": message},
        )
        yield {"type": "error", "message": message}
        return

    memory.record_run(run_id, inbound.sender if inbound else None, prompt, final_output)
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


def _augment_prompt(prompt: str, inbound: InboundMessage | None) -> str:
    if inbound is None:
        return prompt
    return (
        "Inbound WhatsApp message:\n"
        f"- message_id: {inbound.id}\n"
        f"- sender: {inbound.sender}\n"
        f"- chat: {inbound.chat or inbound.sender}\n"
        f"- push_name: {inbound.push_name or ''}\n"
        f"- is_group: {inbound.is_group}\n"
        f"- text: {inbound.text}\n"
        f"- has_media: {inbound.has_media}\n"
        f"- media_kind: {inbound.media_kind or ''}\n"
        f"- media_filename: {inbound.media_filename or ''}\n\n"
        "Handle this message according to policy. For media, use download_whatsapp_media "
        "with chat + message_id before replying with file contents."
    )
