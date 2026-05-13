from __future__ import annotations

import uuid
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
from .skills import render_skill_summary
from .tools import RuntimeContext, core_tools
from .wabot import WabotClient

set_tracing_disabled(True)


INSTRUCTIONS = """You are wabot-agent, a careful WhatsApp operations agent running on a VPS.

Your main job is to help an operator automate WhatsApp workflows through wabot.
You can check wabot health, send text/image messages when policy allows, remember
non-secret contact facts, recall memory, and use configured MCP servers.

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
        wabot=wabot or WabotClient(settings.wabot_endpoint, settings.wabot_token),
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
        },
    )
    return AgentRunResult(
        run_id=run_id,
        final_output=final_output,
        session_id=session_key,
        live_model=settings.live_model_enabled,
    )


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
        f"- text: {inbound.text}\n\n"
        "Handle this message according to policy. If you reply, use the wabot send tool."
    )
