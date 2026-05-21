from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Settings
from .events import EventHub, EventLog
from .memory import InboundMessage, MemoryStore
from .redaction import mask_phone, redact
from .tools import _is_send_allowed
from .wabot import WabotClient, WabotError
from .web_agent import WebAgentError, run_web_agent


def research_output_dir(settings: Settings) -> Path:
    path = settings.media_dir / "research"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _extract_result_text(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if isinstance(data, str) and data.strip():
        return data.strip()
    if isinstance(data, dict):
        return json.dumps(data, indent=2, ensure_ascii=False)
    text = payload.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return json.dumps(payload, indent=2, ensure_ascii=False)[:500_000]


def _pick_extension(output_format: str, content: str) -> str:
    fmt = output_format.lower()
    if fmt == "json":
        return ".json"
    looks_csv = "," in content and "\n" in content and content.lstrip().startswith("business")
    if fmt == "csv" or looks_csv:
        return ".csv"
    return ".md"


def _save_result(
    settings: Settings,
    *,
    job_id: str,
    title: str | None,
    output_format: str,
    content: str,
) -> Path:
    ext = _pick_extension(output_format, content)
    raw_title = title or "research"
    safe_title = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw_title)[:60]
    filename = f"{job_id[:8]}_{safe_title}{ext}"
    path = research_output_dir(settings) / filename
    path.write_text(content, encoding="utf-8")
    return path


def _preview_text(content: str, *, limit: int = 1200) -> str:
    text = content.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n… ({len(text)} chars total)"


def _step_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, list | tuple):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def execute_web_research_job(
    job: dict[str, Any],
    *,
    settings: Settings,
    memory: MemoryStore,
    wabot: WabotClient,
    event_log: EventLog,
    hub: EventHub,
) -> None:
    job_id = str(job["id"])
    requester = str(job.get("requester_jid") or "").strip()
    prompt = str(job.get("prompt") or "")
    output_format = str(job.get("output_format") or "markdown")
    title = job.get("title")
    schema_raw = job.get("schema_json")
    schema: dict[str, Any] | None = None
    if schema_raw:
        try:
            schema = json.loads(schema_raw)
        except json.JSONDecodeError:
            memory.complete_web_research_job(
                job_id, error="invalid_schema_json", result_path=None, preview=None
            )
            return

    event_log.write("web_research_started", {"id": job_id, "requester": mask_phone(requester)})
    hub.publish("web_research_started", {"id": job_id})

    try:
        payload = await run_web_agent(
            settings,
            prompt=prompt,
            output_format=output_format,
            schema=schema,
            max_steps=settings.web_agent_max_steps,
        )
    except WebAgentError as exc:
        memory.complete_web_research_job(
            job_id, error=redact(str(exc)), result_path=None, preview=None
        )
        event_log.write("web_research_failed", {"id": job_id, "error": redact(str(exc))})
        hub.publish("web_research_failed", {"id": job_id, "error": redact(str(exc))})
        await _notify_web_research_done(
            job_id=job_id,
            requester=requester,
            title=title,
            success=False,
            message=f"Research job failed: {exc}",
            result_path=None,
            settings=settings,
            wabot=wabot,
            event_log=event_log,
            hub=hub,
        )
        return

    content = _extract_result_text(payload)
    try:
        result_path = _save_result(
            settings,
            job_id=job_id,
            title=str(title) if title else None,
            output_format=output_format,
            content=content,
        )
    except OSError as exc:
        memory.complete_web_research_job(
            job_id, error=f"save_failed:{exc}", result_path=None, preview=None
        )
        await _notify_web_research_done(
            job_id=job_id,
            requester=requester,
            title=title,
            success=False,
            message=f"Could not save research output: {exc}",
            result_path=None,
            settings=settings,
            wabot=wabot,
            event_log=event_log,
            hub=hub,
        )
        return

    preview = _preview_text(content)
    memory.complete_web_research_job(
        job_id,
        error=None,
        result_path=str(result_path),
        preview=preview,
        duration_ms=payload.get("durationMs"),
        steps=_step_count(payload.get("steps")),
    )
    event_log.write(
        "web_research_completed",
        {
            "id": job_id,
            "path": str(result_path.relative_to(settings.media_dir)),
            "duration_ms": payload.get("durationMs"),
        },
    )
    hub.publish("web_research_completed", {"id": job_id, "path": str(result_path)})

    summary = (
        f"Research complete ({title or job_id[:8]}).\n"
        f"Steps: {_step_count(payload.get('steps')) or '?'}, "
        f"duration: {payload.get('durationMs', '?')}ms.\n\n"
        f"{preview}"
    )
    await _notify_web_research_done(
        job_id=job_id,
        requester=requester,
        title=title,
        success=True,
        message=summary,
        result_path=result_path,
        settings=settings,
        wabot=wabot,
        event_log=event_log,
        hub=hub,
    )


async def _notify_web_research_done(
    *,
    job_id: str,
    requester: str,
    title: str | None,
    success: bool,
    message: str,
    result_path: Path | None,
    settings: Settings,
    wabot: WabotClient,
    event_log: EventLog,
    hub: EventHub,
) -> None:
    if not requester or not settings.web_agent_notify_on_complete:
        return

    fake_inbound = InboundMessage(id="", sender=requester, text="", chat=requester)
    allowed, policy = _is_send_allowed(settings, requester, inbound=fake_inbound)
    if not allowed:
        event_log.write(
            "web_research_notify_skipped",
            {"id": job_id, "reason": policy},
        )
        return

    health = await wabot.health()
    if not health.ready:
        event_log.write(
            "web_research_notify_skipped",
            {"id": job_id, "reason": "wabot_not_ready"},
        )
        return

    try:
        await wabot.send_text(to=requester, text=message[:4000])
    except WabotError as exc:
        event_log.write(
            "web_research_notify_failed",
            {"id": job_id, "error": redact(str(exc))},
        )
        return

    if success and result_path is not None and result_path.exists():
        rel = result_path.relative_to(settings.media_dir.resolve())
        try:
            await wabot.send_media(
                to=requester,
                kind="document",
                path=str(result_path),
                caption=f"Research file: {title or job_id[:8]}",
                filename=result_path.name,
            )
        except WabotError as exc:
            event_log.write(
                "web_research_file_send_failed",
                {"id": job_id, "path": str(rel), "error": redact(str(exc))},
            )

    hub.publish(
        "web_research_notified",
        {"id": job_id, "to": mask_phone(requester), "success": success},
    )
