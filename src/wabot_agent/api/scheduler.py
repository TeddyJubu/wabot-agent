"""Scheduler track — reminder firing, outbound tracking, web-research jobs.

Carved out of api/__init__.py as part of MASTER ME-1 Part 7. The scheduler
track is the async-background-task half of api/__init__.py — none of these
functions is a route handler. The lifespan in api/__init__.py constructs
the asyncio.Task by calling scheduler_loop(deps) and stashes the task on
deps.scheduler_state.task; on shutdown the task is cancelled.

Public surface:
- fire_reminder(reminder, *, deps)
- notify_outbound_expired(task, *, deps)
- handle_outbound_reply(inbound, *, deps) -> dict | None
- maybe_start_web_research(deps) -> None
- run_web_research_job(job, *, deps) -> None
- scheduler_loop(deps) -> None  [the main loop; called once from lifespan]

Helpers are deps-injected via the AppDeps container. Drop the underscore
prefix on the public surface so they read as a proper API.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from ..memory import InboundMessage
from ..redaction import redact
from ..tools import _is_send_allowed
from ..wabot import WabotError

if TYPE_CHECKING:
    from .deps import AppDeps

logger = logging.getLogger(__name__)


def _reminder_target_jid(reminder: dict[str, Any]) -> str:
    return str(reminder.get("target_jid") or reminder.get("requester_jid") or "").strip()


async def fire_reminder(
    reminder: dict[str, Any],
    *,
    deps: AppDeps,
) -> None:
    settings = deps.settings
    memory = deps.memory
    wabot = deps.wabot
    hub = deps.hub
    event_log = deps.event_log

    reminder_id = str(reminder["id"])
    target = _reminder_target_jid(reminder)
    requester = str(reminder.get("requester_jid") or "")
    fake_inbound = (
        InboundMessage(id="", sender=requester, text="", chat=requester)
        if requester
        else None
    )
    allowed, policy = _is_send_allowed(settings, target, inbound=fake_inbound)
    if not allowed:
        memory.mark_reminder_fired(reminder_id, error=f"send_blocked:{policy}")
        event_log.write(
            "reminder_failed",
            {"id": reminder_id, "reason": policy, "to": target},
        )
        hub.publish("reminder_failed", {"id": reminder_id, "reason": policy})
        return

    health = await wabot.health()
    if not health.ready:
        memory.release_reminder_claim(reminder_id)
        payload = {"id": reminder_id, "reason": "wabot_not_ready", "to": target}
        event_log.write("reminder_deferred", payload)
        hub.publish("reminder_deferred", payload)
        return

    try:
        result = await wabot.send_text(to=target, text=str(reminder.get("message") or ""))
    except WabotError as exc:
        memory.mark_reminder_fired(reminder_id, error=str(exc))
        hub.publish("reminder_failed", {"id": reminder_id, "error": redact(str(exc))})
        return

    memory.mark_reminder_fired(reminder_id)
    payload = {"id": reminder_id, "to": target, "policy": policy, "result": redact(result)}
    event_log.write("reminder_fired", payload)
    hub.publish("reminder_fired", payload)


async def notify_outbound_expired(
    task: dict[str, Any],
    *,
    deps: AppDeps,
) -> None:
    settings = deps.settings
    wabot = deps.wabot
    event_log = deps.event_log
    hub = deps.hub

    if not task.get("notify_owner"):
        return
    owner = str(task.get("owner_jid") or "")
    target = str(task.get("target_jid") or "")
    if not owner:
        return
    allowed, policy = _is_send_allowed(
        settings,
        owner,
        inbound=InboundMessage(id="", sender=owner, text="", chat=owner),
    )
    if not allowed:
        event_log.write(
            "outbound_expire_notify_skipped",
            {"id": task.get("id"), "reason": policy},
        )
        return
    health = await wabot.health()
    if not health.ready:
        event_log.write(
            "outbound_expire_notify_skipped",
            {"id": task.get("id"), "reason": "wabot_not_ready"},
        )
        return
    summary = (
        f"No reply from {target} within the tracking window (task {task.get('id', '')})."
    )
    try:
        await wabot.send_text(to=owner, text=summary)
    except WabotError as exc:
        event_log.write(
            "outbound_expire_notify_failed",
            {"id": task.get("id"), "error": redact(str(exc))},
        )
        return
    event_log.write("outbound_task_expired", {"id": task.get("id"), "owner": owner})
    hub.publish("outbound_task_expired", {"id": task.get("id"), "target_jid": target})


async def handle_outbound_reply(
    inbound: InboundMessage,
    *,
    deps: AppDeps,
) -> dict[str, Any] | None:
    settings = deps.settings
    memory = deps.memory
    wabot = deps.wabot
    event_log = deps.event_log
    hub = deps.hub

    task = memory.find_pending_outbound_task(
        sender=inbound.sender,
        chat=inbound.chat,
        is_group=inbound.is_group,
    )
    if task is None:
        return None

    task_id = str(task["id"])
    memory.complete_outbound_task(
        task_id,
        reply_text=inbound.text,
        reply_message_id=inbound.id,
    )
    owner = str(task.get("owner_jid") or "")
    target = str(task.get("target_jid") or "")
    if not task.get("notify_owner") or not owner:
        hub.publish(
            "outbound_task_completed",
            {"id": task_id, "target_jid": target, "notify_owner": False},
        )
        return task

    allowed, policy = _is_send_allowed(
        settings,
        owner,
        inbound=InboundMessage(id="", sender=owner, text="", chat=owner),
    )
    if not allowed:
        event_log.write(
            "outbound_notify_skipped",
            {"task_id": task_id, "reason": policy},
        )
        return task

    health = await wabot.health()
    if not health.ready:
        event_log.write(
            "outbound_notify_skipped",
            {"task_id": task_id, "reason": "wabot_not_ready"},
        )
        return task

    excerpt = (inbound.text or "")[:500]
    summary = f'Update re: {target} — they replied: "{excerpt}" (task {task_id})'
    try:
        await wabot.send_text(to=owner, text=summary)
    except WabotError as exc:
        event_log.write(
            "outbound_notify_failed",
            {"task_id": task_id, "error": redact(str(exc))},
        )
        return task

    event_log.write(
        "outbound_task_completed",
        {"id": task_id, "owner": owner, "policy": policy},
    )
    hub.publish(
        "outbound_task_completed",
        {"id": task_id, "target_jid": target, "reply_message_id": inbound.id},
    )
    return task


async def run_web_research_job(job: dict[str, Any], *, deps: AppDeps) -> None:
    from ..web_research import execute_web_research_job

    settings = deps.settings
    memory = deps.memory
    wabot = deps.wabot
    event_log = deps.event_log
    hub = deps.hub

    try:
        await execute_web_research_job(
            job,
            settings=settings,
            memory=memory,
            wabot=wabot,
            event_log=event_log,
            hub=hub,
        )
    except Exception as exc:  # noqa: BLE001
        job_id = str(job.get("id") or "")
        memory.complete_web_research_job(
            job_id,
            error=redact(str(exc)),
            result_path=None,
            preview=None,
        )
        event_log.write(
            "web_research_failed",
            {"id": job_id, "error": redact(str(exc))},
        )


async def maybe_start_web_research(deps: AppDeps) -> None:
    from datetime import UTC, datetime, timedelta

    settings = deps.settings
    memory = deps.memory
    event_log = deps.event_log

    if not settings.web_agent_enabled:
        return
    stale_before = (
        datetime.now(UTC) - timedelta(seconds=settings.web_agent_timeout_sec + 60)
    ).isoformat()
    for job_id in memory.fail_stale_web_research_jobs(stale_before=stale_before):
        event_log.write("web_research_stale", {"id": job_id})
    running = memory.count_web_research_jobs(status="running")
    if running >= max(1, settings.web_agent_max_concurrent):
        return
    job = memory.claim_pending_web_research_job()
    if job is not None:
        asyncio.create_task(run_web_research_job(job, deps=deps))


async def scheduler_loop(deps: AppDeps) -> None:
    from ..memory import now_iso

    settings = deps.settings
    memory = deps.memory
    event_log = deps.event_log

    interval = max(5.0, float(settings.reminder_poll_interval_sec))
    while True:
        try:
            if settings.reminders_enabled:
                due = memory.claim_due_reminders(now=now_iso(), limit=20)
                for reminder in due:
                    await fire_reminder(reminder, deps=deps)
            expired = memory.expire_outbound_tasks(now=now_iso())
            for task in expired:
                await notify_outbound_expired(task, deps=deps)
            await maybe_start_web_research(deps)
        except Exception as exc:  # noqa: BLE001
            event_log.write("scheduler_loop_error", {"error": redact(str(exc))})
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return
