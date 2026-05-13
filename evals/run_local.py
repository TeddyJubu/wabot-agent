from __future__ import annotations

import asyncio
import json
from pathlib import Path

from vignesh_agent.agent import run_agent
from vignesh_agent.config import Settings
from vignesh_agent.events import EventLog
from vignesh_agent.memory import MemoryStore
from vignesh_agent.wabot import FakeWabotClient

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "cases.jsonl"
RESULTS = ROOT / "evals" / "results" / "latest.jsonl"


async def main() -> int:
    tmp = ROOT / "data" / "eval-offline.db"
    settings = Settings(
        VIGNESH_OFFLINE_MODE=True,
        VIGNESH_DB_PATH=tmp,
        VIGNESH_LOG_PATH=ROOT / "data" / "eval-events.jsonl",
        VIGNESH_MCP_CONFIG=None,
        VIGNESH_SEND_POLICY="dry_run",
        OPENROUTER_API_KEY=None,
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
            result = await run_agent(
                case["input"],
                settings=settings,
                memory=memory,
                event_log=event_log,
                wabot=fake_wabot,
                session_id=f"eval-{case['name']}",
            )
            passed = (not result.live_model) and not fake_wabot.sent
            failures += 0 if passed else 1
            out.write(
                json.dumps(
                    {
                        "name": case["name"],
                        "passed": passed,
                        "run_id": result.run_id,
                        "output": result.final_output,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
