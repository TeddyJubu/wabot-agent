from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    Request,
)
from fastapi.responses import (
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from ..agent import run_agent
from ..auth import (
    verify_human_factory,
)
from ..auto_reply import (
    deliver_auto_reply,
    deliver_inbound_error_reply,
    inbound_session_id,
)
from ..config import Settings, get_settings
from ..context_management import maybe_prune_audit_tables
from ..events import EventHub, EventLog
from ..knowledge_store import ensure_knowledge_files
from ..llm_provider import active_model_id
from ..memory import InboundMessage, MemoryStore
from ..recipients import is_owner_inbound
from ..redaction import redact
from ..runtime_overrides import (
    apply_overrides,
    load_overrides,
)
from ..settings_service import SettingsService
from ..tools import _is_send_allowed
from ..typing_indicator import inbound_typing_indicator
from ..wabot import WabotClient, WabotError
from ..wabot_process import (
    WabotRestartError as WabotRestartError,  # noqa: F401 (re-export for routes/pairing.py late-import patch target)
)
from ..wabot_process import (
    restart_wabot_daemon as restart_wabot_daemon,  # noqa: F401 (re-export — patched by tests via api module)
)
from ..wabot_process import (
    rotate_wabot_store_files as rotate_wabot_store_files,  # noqa: F401 (re-export)
)
from ..wabot_process import (
    wait_for_fresh_pairing as wait_for_fresh_pairing,  # noqa: F401 (re-export)
)
from .dependencies import (
    _LOOPBACK_HOSTS,  # noqa: F401  (re-export — used by external callers and tests)
    _verify_inbound_auth,
)
from .dependencies import (
    _require_loopback_url as _require_loopback_url,  # noqa: F401  (re-export)
)
from .deps import AppDeps, PairingState, SchedulerState, SnapshotCache
from .routes.auth import register_auth_routes
from .routes.codex import register_codex_routes
from .routes.groups import register_groups_routes
from .routes.health import register_health_routes
from .routes.memory import register_memory_routes
from .routes.pages import register_pages_routes
from .routes.pairing import (
    _pairing_payload,  # re-exported for the SSE initial-snapshot call site
    pairing_poll_loop,
    register_pairing_routes,
)
from .routes.pairing import (
    _pairing_unreachable_payload as _pairing_unreachable_payload,  # noqa: F401 (re-export)
)
from .routes.pairing import (
    _qr_svg as _qr_svg,  # noqa: F401 re-exported: wabot_agent.api._qr_svg used by tests
)
from .routes.settings import register_settings_routes
from .schemas import (
    HistoryBatchPayload,
    HistorySyncSummaryPayload,
    InboundPayload,
    PresencePayload,
    ReceiptPayload,
)

logger = logging.getLogger(__name__)


def _reminder_target_jid(reminder: dict[str, Any]) -> str:
    return str(reminder.get("target_jid") or reminder.get("requester_jid") or "").strip()


async def _fire_reminder(
    reminder: dict[str, Any],
    *,
    settings: Settings,
    memory: MemoryStore,
    wabot: WabotClient,
    hub: EventHub,
    event_log: EventLog,
) -> None:
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


async def _notify_outbound_expired(
    task: dict[str, Any],
    *,
    settings: Settings,
    wabot: WabotClient,
    event_log: EventLog,
    hub: EventHub,
) -> None:
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


async def _handle_outbound_reply(
    inbound: InboundMessage,
    *,
    settings: Settings,
    memory: MemoryStore,
    wabot: WabotClient,
    event_log: EventLog,
    hub: EventHub,
) -> dict[str, Any] | None:
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.requires_inbound_token() and not (settings.wabot_inbound_token or "").strip():
        raise RuntimeError(
            "WABOT_INBOUND_TOKEN must be set: inbound webhooks require auth "
            "(non-loopback WABOT_AGENT_HOST, non-local WABOT_AGENT_ENV, or "
            "WABOT_INBOUND_TOKEN_REQUIRED=true)"
        )
    settings.ensure_dirs()
    overrides = load_overrides(settings.runtime_overrides_path)
    if overrides:
        # Validate atomically on a snapshot first — a stale override file with
        # one bad value (e.g. a Literal that no longer exists) shouldn't half-
        # mutate live settings before the exception fires.
        snapshot = settings.model_copy(deep=True)
        try:
            apply_overrides(snapshot, overrides)
        except Exception as exc:
            logger.error(
                "runtime overrides file failed validation, ignoring: %s", exc
            )
        else:
            apply_overrides(settings, overrides)
    memory = MemoryStore(settings.db_path)
    hub = EventHub()
    event_log = EventLog(settings.log_path, hub=hub)
    wabot = WabotClient(settings.wabot_endpoint, settings.resolved_wabot_token)

    # SR-1: SettingsService is the single owner of settings mutations.
    settings_service = SettingsService(settings)

    # Subscriber: keep WabotClient in sync when wabot_endpoint / wabot_token change.
    def _on_settings_change(new_settings: Settings, changed: frozenset[str]) -> None:
        if "wabot_endpoint" in changed:
            wabot.endpoint = new_settings.wabot_endpoint.rstrip("/")
        if "wabot_token" in changed:
            wabot.token = new_settings.resolved_wabot_token

    settings_service.subscribe(_on_settings_change)

    # TODO(Phase-6): subscribe event_log SSE broadcast here so the dashboard
    # receives a settings_updated event from any settings change source.
    # e.g.: settings_service.subscribe(lambda s, changed:
    #     event_log.write("settings_updated", {"fields": sorted(changed)}))
    # Blocked until hub.publish() is safe to call from a sync subscriber.

    # Pairing poller state — last published payload + the asyncio task handle.
    pairing_state = PairingState()
    snapshot_cache = SnapshotCache()
    _SNAPSHOT_TTL_SEC = 2.0
    scheduler_state = SchedulerState()
    inbound_locks: dict[str, asyncio.Lock] = {}
    inbound_locks_guard = asyncio.Lock()

    async def _inbound_session_lock(session_key: str) -> asyncio.Lock:
        async with inbound_locks_guard:
            lock = inbound_locks.get(session_key)
            if lock is None:
                lock = asyncio.Lock()
                inbound_locks[session_key] = lock
            return lock

    async def _run_web_research_job(job: dict[str, Any]) -> None:
        from ..web_research import execute_web_research_job

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

    async def _maybe_start_web_research() -> None:
        from datetime import UTC, datetime, timedelta

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
            asyncio.create_task(_run_web_research_job(job))

    async def _scheduler_loop() -> None:
        from ..memory import now_iso

        interval = max(5.0, float(settings.reminder_poll_interval_sec))
        while True:
            try:
                if settings.reminders_enabled:
                    due = memory.claim_due_reminders(now=now_iso(), limit=20)
                    for reminder in due:
                        await _fire_reminder(
                            reminder,
                            settings=settings,
                            memory=memory,
                            wabot=wabot,
                            hub=hub,
                            event_log=event_log,
                        )
                expired = memory.expire_outbound_tasks(now=now_iso())
                for task in expired:
                    await _notify_outbound_expired(
                        task,
                        settings=settings,
                        wabot=wabot,
                        event_log=event_log,
                        hub=hub,
                    )
                await _maybe_start_web_research()
            except Exception as exc:  # noqa: BLE001
                event_log.write("scheduler_loop_error", {"error": redact(str(exc))})
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Capture the running uvicorn loop so sync publishers (EventLog.write
        # called from inside tools, threads, etc.) can dispatch safely via
        # call_soon_threadsafe. Then drive pairing state through the hub so
        # the dashboard can rely on `pairing_changed` for live updates.
        hub.bind_loop(asyncio.get_running_loop())
        ensure_knowledge_files(settings)
        maybe_prune_audit_tables(memory, settings, force=True)
        pairing_state.task = asyncio.create_task(pairing_poll_loop(deps))
        scheduler_state.task = asyncio.create_task(_scheduler_loop())
        try:
            yield
        finally:
            pairing_task = pairing_state.task
            if pairing_task is not None:
                pairing_task.cancel()
                try:
                    await pairing_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            sched_task = scheduler_state.task
            if sched_task is not None:
                sched_task.cancel()
                try:
                    await sched_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            await wabot.aclose()

    deps = AppDeps(
        settings=settings,
        memory=memory,
        wabot=wabot,
        event_log=event_log,
        hub=hub,
        pairing_state=pairing_state,
        scheduler_state=scheduler_state,
        snapshot_cache=snapshot_cache,
        settings_service=settings_service,
    )

    app = FastAPI(title="wabot-agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.memory = memory
    app.state.event_log = event_log
    app.state.event_hub = hub
    app.state.wabot = wabot
    app.state.deps = deps

    # NOTE: api/__init__.py is one level deeper than the old api.py was,
    # so the walk to the project root needs parents[3] (api → wabot_agent → src → root).
    static_dir = Path(__file__).resolve().parents[3] / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    verify_human = verify_human_factory(settings)
    human_dependency = Depends(verify_human)

    async def _verify_inbound_auth_dep(
        authorization: str | None = Header(default=None),
    ) -> None:
        """FastAPI dependency wrapper for ``_verify_inbound_auth``.

        Centralising this on every ``/whatsapp/*`` route means the WABOT_INBOUND_TOKEN
        check happens consistently before any handler body runs (CLAUDE.md / MASTER §3).
        """
        _verify_inbound_auth(settings, authorization)

    inbound_auth_dependency = Depends(_verify_inbound_auth_dep)

    # /health and /ready — extracted to api/routes/health.py (MASTER ME-1 Part 2).
    _health_router = APIRouter()
    register_health_routes(_health_router, deps)
    app.include_router(_health_router)

    # /, /pair, /knowledge, /favicon.ico — extracted to api/routes/pages.py (ME-1 Part 3).
    _pages_router = APIRouter()
    register_pages_routes(_pages_router, deps)
    app.include_router(_pages_router)

    # /login, /api/auth/login — extracted to api/routes/auth.py (ME-1 Part 3).
    _auth_router = APIRouter()
    register_auth_routes(_auth_router, deps)
    app.include_router(_auth_router)

    # /api/settings/* — extracted to api/routes/settings.py (ME-1 Part 4).
    _settings_router = APIRouter()
    register_settings_routes(_settings_router, deps)
    app.include_router(_settings_router)

    # /api/whatsapp/groups/* — extracted to api/routes/groups.py (ME-1 Part 4).
    _groups_router = APIRouter()
    register_groups_routes(_groups_router, deps)
    app.include_router(_groups_router)

    # /api/codex/* — extracted to api/routes/codex.py (ME-1 Part 4).
    _codex_router = APIRouter()
    register_codex_routes(_codex_router, deps)
    app.include_router(_codex_router)

    # /api/whatsapp/pairing/* — extracted to api/routes/pairing.py (ME-1 Part 5).
    _pairing_router = APIRouter()
    register_pairing_routes(_pairing_router, deps)
    app.include_router(_pairing_router)

    # /api/memory/* + /api/knowledge/* + /api/runs — extracted to routes/memory.py (ME-1 Part 6).
    _memory_router = APIRouter()
    register_memory_routes(_memory_router, deps)
    app.include_router(_memory_router)

    async def _process_whatsapp_inbound(
        inbound: InboundMessage,
        request: Request,
    ) -> dict[str, Any]:
        # SAFETY: claim the dedup id BEFORE persisting the message body so a
        # replayed webhook with the same message_id but a mutated text cannot
        # overwrite the stored body via record_inbound's INSERT ... ON CONFLICT
        # DO UPDATE path. See MASTER-architecture-debt-testing.md (Part I §3).
        if not is_owner_inbound(settings, inbound):
            await _handle_outbound_reply(
                inbound,
                settings=settings,
                memory=memory,
                wabot=wabot,
                event_log=event_log,
                hub=hub,
            )
        if not (inbound.text or "").strip() and not inbound.has_media:
            if not memory.claim_message(inbound.id, inbound.sender):
                return {"accepted": True, "duplicate": True, "message_id": inbound.id}
            memory.record_inbound(inbound)
            memory.complete_message(inbound.id, "skipped-empty")
            return {
                "accepted": True,
                "skipped": True,
                "reason": "empty_text_no_media",
                "message_id": inbound.id,
            }
        if not memory.claim_message(inbound.id, inbound.sender):
            return {"accepted": True, "duplicate": True, "message_id": inbound.id}
        memory.record_inbound(inbound)
        event_log.write(
            "inbound_message",
            {"message_id": inbound.id, "sender": inbound.sender, "path": str(request.url.path)},
        )
        try:
            async with inbound_typing_indicator(wabot, inbound, settings):
                result = await run_agent(
                    inbound.text,
                    settings=settings,
                    memory=memory,
                    event_log=event_log,
                    wabot=wabot,
                    inbound=inbound,
                    session_id=inbound_session_id(inbound),
                )
        except Exception as exc:
            memory.fail_message(inbound.id, str(exc))
            event_log.write(
                "inbound_message_failed",
                {"message_id": inbound.id, "sender": inbound.sender, "error": str(exc)},
            )
            error_reply = await deliver_inbound_error_reply(
                settings=settings,
                wabot=wabot,
                inbound=inbound,
                error=str(exc),
            )
            if error_reply.get("sent"):
                event_log.write(
                    "auto_reply_sent",
                    {
                        "message_id": inbound.id,
                        "sender": inbound.sender,
                        "to": error_reply.get("to"),
                        "policy": error_reply.get("policy"),
                        "reason": "agent_error_fallback",
                    },
                )
            hub.publish(
                "inbound_agent_failed",
                {
                    "message_id": inbound.id,
                    "sender": inbound.sender,
                    "error": redact(str(exc)),
                },
            )
            # Message is already in inbound_messages; do not fail the webhook or
            # wabot will treat delivery as unsuccessful and the inbox stays empty.
            return {
                "accepted": True,
                "duplicate": False,
                "message_id": inbound.id,
                "auto_reply": error_reply,
                "agent_error": redact(str(exc)),
            }
        memory.complete_message(inbound.id, result.run_id)
        auto = await deliver_auto_reply(
            settings=settings,
            wabot=wabot,
            inbound=inbound,
            result=result,
        )
        if auto.get("sent"):
            event_log.write(
                "auto_reply_sent",
                {
                    "message_id": inbound.id,
                    "sender": inbound.sender,
                    "to": auto.get("to"),
                    "policy": auto.get("policy"),
                },
            )
        return {
            "accepted": True,
            "duplicate": False,
            "message_id": inbound.id,
            "run_id": result.run_id,
            "output": result.final_output,
            "auto_reply": auto,
        }

    @app.post("/whatsapp/inbound", dependencies=[inbound_auth_dependency])
    async def whatsapp_inbound(
        payload: InboundPayload,
        request: Request,
    ) -> dict[str, Any]:
        inbound = payload.to_inbound_message()
        session_key = inbound_session_id(inbound)
        lock = await _inbound_session_lock(session_key)
        if lock.locked():
            event_log.write(
                "inbound_message_queued",
                {"message_id": inbound.id, "sender": inbound.sender, "session_id": session_key},
            )
        async with lock:
            return await _process_whatsapp_inbound(inbound, request)

    @app.post("/whatsapp/receipt", dependencies=[inbound_auth_dependency])
    async def whatsapp_receipt(payload: ReceiptPayload) -> dict[str, Any]:
        body = payload.model_dump()
        hub.publish("whatsapp_receipt", body)
        event_log.write(
            "whatsapp_receipt",
            {
                "chat": payload.chat,
                "receipt_type": payload.receipt_type,
                "message_ids": payload.message_ids,
            },
        )
        return {"accepted": True}

    @app.post("/whatsapp/presence", dependencies=[inbound_auth_dependency])
    async def whatsapp_presence(payload: PresencePayload) -> dict[str, Any]:
        body = payload.model_dump()
        hub.publish("whatsapp_presence", body)
        event_log.write(
            "whatsapp_presence",
            {"chat": payload.chat, "sender": payload.sender, "state": payload.state},
        )
        return {"accepted": True}

    @app.post("/whatsapp/history-sync", dependencies=[inbound_auth_dependency])
    async def whatsapp_history_sync(
        payload: HistorySyncSummaryPayload,
    ) -> dict[str, Any]:
        body = payload.model_dump()
        hub.publish("whatsapp_history_sync", body)
        event_log.write(
            "whatsapp_history_sync",
            {
                "sync_type": payload.sync_type,
                "conversation_count": payload.conversation_count,
                "message_count": payload.message_count,
                "chunk_order": payload.chunk_order,
                "progress": payload.progress,
            },
        )
        return {"accepted": True}

    @app.post("/whatsapp/history", dependencies=[inbound_auth_dependency])
    async def whatsapp_history(payload: HistoryBatchPayload) -> dict[str, Any]:
        """Backfill inbound_messages from wabot history sync (no agent auto-reply)."""
        inbounds = [msg.to_inbound_message() for msg in payload.messages]
        result = memory.bulk_record_inbound(inbounds)
        hub.publish(
            "whatsapp_history_batch",
            {
                "sync_type": payload.sync_type,
                "stored": result["stored"],
                "chunk_order": payload.chunk_order,
                "progress": payload.progress,
            },
        )
        event_log.write(
            "whatsapp_history_batch",
            {
                "sync_type": payload.sync_type,
                "stored": result["stored"],
                "chunk_order": payload.chunk_order,
                "progress": payload.progress,
            },
        )
        return {"accepted": True, **result}

    async def _build_initial_snapshot() -> dict[str, Any]:
        """Initial payload pushed when an SSE client connects.

        Bundles /ready + /api/runs + pairing into one event so the dashboard
        renders completely without follow-up REST calls. Subsequent state
        changes arrive as deltas on the same stream.
        """
        now = time.monotonic()
        cached = snapshot_cache.payload
        if (
            cached is not None
            and now - float(snapshot_cache.at) < _SNAPSHOT_TTL_SEC
        ):
            return cached
        wabot_health = await wabot.health()
        # Prefer the poller's cached pairing snapshot (already redacted on
        # publish); on cold start before the first tick fires, fall through
        # to a fresh probe so the client doesn't paint a blank pairing card.
        pairing = pairing_state.last
        if pairing is None:
            pairing = _pairing_payload(await wabot.pairing_qr())
        snapshot = redact(
            {
                "ok": True,
                "live_model": settings.live_model_enabled,
                "model_provider": settings.model_provider,
                "model": active_model_id(settings) if settings.live_model_enabled else "offline",
                "send_policy": settings.send_policy,
                "memory": memory.stats(),
                "wabot": {
                    "reachable": wabot_health.reachable,
                    "logged_in": wabot_health.logged_in,
                    "connected": wabot_health.connected,
                    "ready": wabot_health.ready,
                    "detail": wabot_health.detail,
                },
                "pairing": pairing,
                "runs": memory.recent_runs(limit=8),
            }
        )
        snapshot_cache.at = now
        snapshot_cache.payload = snapshot
        return snapshot

    @app.get("/api/stream", dependencies=[human_dependency])
    async def event_stream(
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        """Server-sent events for live dashboard updates.

        On connect: an initial `ready_snapshot` event with /ready + recent runs.
        Live: every event published via EventLog (agent_run_*, inbound_message,
        settings_updated) is forwarded with monotonic Last-Event-ID for replay.
        Heartbeat comments every 15s keep proxies from idling the connection.
        """
        try:
            lid: int | None = int(last_event_id) if last_event_id else None
        except ValueError:
            lid = None

        async def generator() -> Any:
            # 1) Initial snapshot — fast first paint, no separate REST round-trips.
            snapshot = await _build_initial_snapshot()
            yield _sse_frame(event_id=None, name="ready_snapshot", data=snapshot)

            # 2) Backlog (anything we already broadcast past Last-Event-ID) + live.
            backlog, queue = hub.open_subscription(lid)
            try:
                for event in backlog:
                    yield _sse_frame(event.id, event.name, event.payload)
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except TimeoutError:
                        # Named heartbeat — the client uses it to keep the
                        # staleness pill green during quiet periods. Doubles
                        # as a proxy-keepalive (line traffic every 15s).
                        yield _sse_frame(event_id=None, name="heartbeat", data={})
                        continue
                    yield _sse_frame(event.id, event.name, event.payload)
            finally:
                hub.close_subscription(queue)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                # Defeat nginx proxy buffering if anything ever sits in front.
                "X-Accel-Buffering": "no",
            },
        )

    return app


# URL guards now live in api/dependencies.py; re-exported above.


# LLM connectivity probes + the GET /api/settings view builder now live in
# api/llm_tests.py and are re-exported via the import block above.


def _sse_frame(event_id: int | None, name: str, data: Any) -> str:
    """Format a single SSE frame. Data is JSON-encoded; multi-line bodies are
    split across multiple `data:` lines per the SSE spec, though our redacted
    payloads almost never contain newlines."""
    parts: list[str] = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {name}")
    body = json.dumps(data, ensure_ascii=False)
    for line in body.split("\n"):
        parts.append(f"data: {line}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


# _wabot_call and _verify_inbound_auth now live in api/dependencies.py.


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, reload=False)
