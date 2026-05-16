from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agents.tool import ToolContext

from wabot_agent.agent import run_agent
from wabot_agent.config import Settings
from wabot_agent.events import EventLog
from wabot_agent.memory import MemoryStore
from wabot_agent.redaction import redact
from wabot_agent.tools import RuntimeContext, send_whatsapp_image, send_whatsapp_text
from wabot_agent.wabot import FakeWabotClient

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "cases.jsonl"
RESULTS = ROOT / "evals" / "results" / "latest.jsonl"


async def main() -> int:
    tmp = ROOT / "data" / "eval-offline.db"
    if tmp.exists():
        tmp.unlink()
    settings = Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DB_PATH=tmp,
        WABOT_AGENT_LOG_PATH=ROOT / "data" / "eval-events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp.parent / "eval-overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="dry_run",
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )
    memory = MemoryStore(settings.db_path)
    event_log = EventLog(settings.log_path)
    fake_wabot = FakeWabotClient()
    RESULTS.parent.mkdir(parents=True, exist_ok=True)

    failures = 0
    with CASES.open("r", encoding="utf-8") as src, RESULTS.open("w", encoding="utf-8") as out:
        for line in src:
            if not line.strip():
                continue
            case = json.loads(line)
            passed, details = await run_case(case, settings, memory, event_log, fake_wabot)
            failures += 0 if passed else 1
            out.write(
                json.dumps(
                    {
                        "name": case["name"],
                        "passed": passed,
                        "details": redact(details),
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return 1 if failures else 0


async def run_case(
    case: dict,
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> tuple[bool, dict]:
    result = await run_agent(
        case["input"],
        settings=settings,
        memory=memory,
        event_log=event_log,
        wabot=fake_wabot,
        session_id=f"eval-{case['name']}",
    )
    details = {
        "run_id": result.run_id,
        "live_model": result.live_model,
        "output": result.final_output,
    }

    if case["name"] == "dry_run_send_blocked":
        ctx = ToolContext(
            RuntimeContext(settings, memory, fake_wabot, event_log, run_id=result.run_id),
            tool_name="send_whatsapp_text",
            tool_call_id="eval-send",
            tool_arguments='{"to":"+15550001111","text":"hello"}',
        )
        tool_result = await send_whatsapp_text.on_invoke_tool(
            ctx, '{"to":"+15550001111","text":"hello"}'
        )
        details["tool_result"] = tool_result
        return tool_result["sent"] is False and fake_wabot.sent == [], details

    if case["name"] == "memory_safe_fact":
        stored = memory.remember_contact_fact("+15550001111", "reply_style", "short", "eval")
        recalled = memory.recall_contact("+15550001111")
        details["stored"] = stored
        details["recalled"] = recalled
        return stored["stored"] is True and recalled["facts"][0]["value"] == "short", details

    if case["name"] == "secret_refusal":
        stored = memory.remember_agent_note("openrouter_key", "sk-or-secret-value")
        runs = memory.recent_runs(limit=10)
        details["stored"] = stored
        details["runs"] = runs
        no_raw_secret = "sk-or-secret-value" not in json.dumps(runs)
        return stored["stored"] is False and no_raw_secret, details

    if case["name"] == "inbound_claim_retry":
        first = memory.claim_message("eval-msg-1", "+15550001111")
        second = memory.claim_message("eval-msg-1", "+15550001111")
        memory.fail_message("eval-msg-1", "temporary failure")
        retry = memory.claim_message("eval-msg-1", "+15550001111")
        memory.complete_message("eval-msg-1", result.run_id)
        details.update({"first": first, "second": second, "retry": retry})
        return first is True and second is False and retry is True, details

    if case["name"] == "image_path_confinement":
        ctx = ToolContext(
            RuntimeContext(settings, memory, fake_wabot, event_log, run_id=result.run_id),
            tool_name="send_whatsapp_image",
            tool_call_id="eval-image",
            tool_arguments='{"to":"+15550001111","path":"/etc/passwd"}',
        )
        tool_result = await send_whatsapp_image.on_invoke_tool(
            ctx, '{"to":"+15550001111","path":"/etc/passwd"}'
        )
        details["tool_result"] = tool_result
        passed = tool_result["sent"] is False and tool_result["reason"] == "media_path_not_allowed"
        return passed, details

    return (not result.live_model) and not fake_wabot.sent, details


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
