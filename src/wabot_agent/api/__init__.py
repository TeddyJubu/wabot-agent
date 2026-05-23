from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import qrcode
import uvicorn
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from qrcode.image.svg import SvgFillImage

from ..agent import run_agent
from ..auth import (
    AuthIdentity,
    maybe_mint_operator_cookie,
    mint_operator_session_cookie,
    password_grants_dashboard_access,
    render_login_page,
    resolve_human_factory,
    verify_human_factory,
)
from ..auto_reply import (
    deliver_auto_reply,
    deliver_inbound_error_reply,
    inbound_session_id,
)
from ..codex_auth import disconnect_codex_credentials
from ..codex_device_login import (
    cancel_device_login,
    device_login_view,
    poll_device_login,
    start_device_login,
)
from ..config import Settings, get_settings
from ..context_management import maybe_prune_audit_tables
from ..events import EventHub, EventLog
from ..knowledge_store import (
    ensure_knowledge_files,
    list_knowledge_docs,
    read_global_memory_raw,
    read_instructions_raw,
    save_global_memory,
    save_instructions,
)
from ..llm_provider import active_model_id
from ..memory import InboundMessage, MemoryStore
from ..providers import get_registry
from ..recipients import is_owner_inbound
from ..redaction import redact
from ..runtime_overrides import (
    MUTABLE_FIELDS,
    SECRET_FIELDS,
    apply_overrides,
    load_overrides,
    save_overrides,
)
from ..tools import _is_send_allowed
from ..typing_indicator import inbound_typing_indicator
from ..wabot import WabotClient, WabotError
from ..wabot_process import (
    WabotRestartError,
    restart_wabot_daemon,
    rotate_wabot_store_files,
    wait_for_fresh_pairing,
)
from .dependencies import (
    _LOOPBACK_HOSTS,  # noqa: F401  (re-export — used by external callers and tests)
    _require_loopback_url,
    _safe_next_path,
    _verify_inbound_auth,
    _wabot_call,
)
from .deps import AppDeps, PairingState, SchedulerState, SnapshotCache
from .llm_tests import (
    _settings_view,
    _test_llm_endpoint,
)
from .routes.health import register_health_routes
from .schemas import (
    GroupCreateRequest,
    GroupInviteRequest,
    GroupJoinRequest,
    GroupParticipantsRequest,
    GroupUpdateRequest,
    HistoryBatchPayload,
    HistorySyncSummaryPayload,
    InboundPayload,
    KnowledgeContentBody,
    MemoryFactBody,
    OpenAITestRequest,
    OpenRouterTestRequest,
    PresencePayload,
    ReceiptPayload,
    SettingsPatch,
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

    def _pairing_payload(p: Any) -> dict[str, Any]:
        # Same shape as GET /api/whatsapp/pairing — keep them in sync so the
        # client can paint from either source.
        detail = p.detail
        if not p.qr_available and p.event == "timeout" and not detail:
            detail = (
                "The last QR expired before it was scanned. Tap New QR, then scan "
                "within about a minute while this page stays open."
            )
        return {
            "supported": p.supported,
            "reachable": p.reachable,
            "logged_in": p.logged_in,
            "connected": p.connected,
            "qr_available": p.qr_available,
            "event": p.event,
            "updated_at": p.updated_at,
            "expires_at": p.expires_at,
            "detail": detail,
        }

    def _pairing_unreachable_payload(
        last: dict[str, Any] | None, *, detail: str
    ) -> dict[str, Any]:
        payload = dict(last) if last else {
            "supported": True,
            "reachable": False,
            "logged_in": None,
            "connected": None,
            "qr_available": False,
            "event": None,
            "updated_at": None,
            "expires_at": None,
            "detail": detail,
        }
        payload["reachable"] = False
        payload["detail"] = detail
        return payload

    async def _pairing_poll_loop() -> None:
        """Probe wabot pairing state and publish pairing_changed on diff.

        Polls every 5s on loopback — cheap. We only publish when the snapshot
        actually changes, so a stable linked session generates zero events
        beyond the initial state push at startup.
        """
        while True:
            try:
                pairing = await wabot.pairing_qr()
                payload = _pairing_payload(pairing)
            except Exception as exc:  # noqa: BLE001 — never kill the loop
                logger.warning("pairing poll failed: %s", redact(str(exc)))
                payload = _pairing_unreachable_payload(
                    pairing_state.last,
                    detail="Could not reach wabot for pairing status.",
                )
            if payload != pairing_state.last:
                pairing_state.last = payload
                hub.publish("pairing_changed", payload)
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                return

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
        pairing_state.task = asyncio.create_task(_pairing_poll_loop())
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

    @app.get("/favicon.ico", include_in_schema=False, response_model=None)
    async def favicon() -> Response:
        favicon_path = static_dir / "favicon.svg"
        if favicon_path.exists():
            return FileResponse(favicon_path, media_type="image/svg+xml")
        return Response(status_code=204)

    verify_human = verify_human_factory(settings)
    resolve_human = resolve_human_factory(settings)
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

    @app.get("/login", include_in_schema=False, response_model=None)
    async def login_page(
        request: Request,
        identity: AuthIdentity | None = Depends(resolve_human),  # noqa: B008
        next_path: str = Query("/", alias="next"),
        err: str | None = Query(None),
    ) -> Response:
        if identity is not None:
            return RedirectResponse(url=_safe_next_path(next_path), status_code=302)
        error_html = f'<p class="err">{err}</p>' if err else ""
        return HTMLResponse(render_login_page(error_html=error_html, next_path=next_path))

    @app.post("/api/auth/login", include_in_schema=False, response_model=None)
    async def login_submit(
        request: Request,
        password: str = Form(...),
        next_path: str = Form("/", alias="next"),
    ) -> Response:
        if not settings.operator_token:
            raise HTTPException(status_code=503, detail="operator token not configured")
        safe_next = _safe_next_path(next_path)
        if not password_grants_dashboard_access(settings, password):
            return HTMLResponse(
                render_login_page(
                    error_html='<p class="err">Wrong password.</p>',
                    next_path=safe_next,
                ),
                status_code=401,
            )
        response = RedirectResponse(url=safe_next, status_code=303)
        mint_operator_session_cookie(response, request, settings)
        return response

    @app.get("/")
    async def dashboard(
        request: Request,
        identity: AuthIdentity | None = Depends(resolve_human),  # noqa: B008
    ) -> Response:
        if identity is None:
            return RedirectResponse(url="/login?next=/", status_code=302)
        file_response = _dashboard_file(static_dir)
        file_response.headers["Cache-Control"] = "no-store"
        maybe_mint_operator_cookie(file_response, request, settings)
        return file_response

    @app.get("/pair")
    async def pair_page(
        request: Request,
        identity: AuthIdentity | None = Depends(resolve_human),  # noqa: B008
    ) -> Response:
        """Mobile-first WhatsApp pairing page.

        Serves the same React bundle as ``/`` — ``web/src/main.tsx`` picks
        ``<PairView />`` when ``window.location.pathname === '/pair'``.
        """
        if identity is None:
            return RedirectResponse(url="/login?next=/pair", status_code=302)
        file_response = _dashboard_file(static_dir)
        file_response.headers["Cache-Control"] = "no-store"
        maybe_mint_operator_cookie(file_response, request, settings)
        return file_response

    @app.get("/knowledge")
    async def knowledge_page(
        request: Request,
        identity: AuthIdentity | None = Depends(resolve_human),  # noqa: B008
    ) -> Response:
        """Knowledge management dashboard (BlockNote editors + contact facts)."""
        if identity is None:
            return RedirectResponse(url="/login?next=/knowledge", status_code=302)
        file_response = _dashboard_file(static_dir)
        file_response.headers["Cache-Control"] = "no-store"
        maybe_mint_operator_cookie(file_response, request, settings)
        return file_response

    def _dashboard_file(static_dir: Path) -> FileResponse:
        index = static_dir / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="Dashboard not built.")
        return FileResponse(index)

    # /health and /ready — extracted to api/routes/health.py (MASTER ME-1 Part 2).
    _health_router = APIRouter()
    register_health_routes(_health_router, deps)
    app.include_router(_health_router)

    @app.get("/api/whatsapp/pairing", dependencies=[human_dependency])
    async def whatsapp_pairing() -> dict[str, Any]:
        # _pairing_payload defines the canonical shape; both the SSE
        # `pairing_changed` event and this REST endpoint emit it.
        return redact(_pairing_payload(await wabot.pairing_qr()))

    @app.get(
        "/api/whatsapp/pairing.svg",
        dependencies=[human_dependency],
        include_in_schema=False,
        response_model=None,
    )
    async def whatsapp_pairing_svg() -> Response:
        pairing = await wabot.pairing_qr()
        if not pairing.qr:
            raise HTTPException(
                status_code=404, detail=pairing.detail or "Pairing QR is unavailable."
            )
        return Response(
            content=_qr_svg(pairing.qr),
            media_type="image/svg+xml",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/whatsapp/pairing/restart", dependencies=[human_dependency])
    async def whatsapp_pairing_restart() -> dict[str, Any]:
        try:
            await restart_wabot_daemon(settings)
        except WabotRestartError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        pairing = await wait_for_fresh_pairing(wabot.pairing_qr)
        payload = redact(_pairing_payload(pairing))
        pairing_state.last = payload
        hub.publish("pairing_changed", payload)
        return payload

    @app.post("/api/whatsapp/pairing/disconnect", dependencies=[human_dependency])
    async def whatsapp_pairing_disconnect() -> dict[str, Any]:
        try:
            backups = rotate_wabot_store_files(settings)
            await restart_wabot_daemon(settings)
        except (OSError, WabotRestartError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        pairing = await wait_for_fresh_pairing(wabot.pairing_qr)
        payload = redact(_pairing_payload(pairing))
        payload.update(
            {
                "disconnected": True,
                "store_backups": [path.name for path in backups],
            }
        )
        pairing_state.last = payload
        hub.publish("pairing_changed", payload)
        event_log.write(
            "whatsapp_disconnected",
            {"store_backups": [path.name for path in backups]},
        )
        return payload

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

    @app.get("/api/memory/agent-notes", dependencies=[human_dependency])
    async def list_agent_notes() -> dict[str, Any]:
        # Top-level keys must not contain SECRET_KEYS substrings (e.g. "notes" → "key").
        return {"items": memory.agent_notes()}

    @app.put("/api/memory/agent-notes", dependencies=[human_dependency])
    async def upsert_agent_note(body: MemoryFactBody) -> dict[str, Any]:
        from ..instructions_cache import invalidate_instructions_cache

        result = memory.remember_agent_note(body.key, body.value)
        invalidate_instructions_cache()
        return redact(result)

    @app.delete("/api/memory/agent-notes/{key}", dependencies=[human_dependency])
    async def delete_agent_note_route(key: str) -> dict[str, Any]:
        from ..instructions_cache import invalidate_instructions_cache

        result = memory.delete_agent_note(key)
        invalidate_instructions_cache()
        return redact(result)

    @app.get("/api/memory/{contact}", dependencies=[human_dependency])
    async def contact_memory(contact: str) -> dict[str, Any]:
        return redact(memory.recall_contact(contact))

    @app.get("/api/knowledge", dependencies=[human_dependency])
    async def knowledge_index() -> dict[str, Any]:
        return {
            "docs": list_knowledge_docs(settings),
            "budgets": {
                "instructions": settings.knowledge_instructions_max_chars,
                "memory": settings.knowledge_memory_max_chars,
                "contact": settings.knowledge_contact_max_chars,
            },
        }

    @app.get("/api/knowledge/instructions", dependencies=[human_dependency])
    async def knowledge_instructions_get() -> dict[str, Any]:
        docs = list_knowledge_docs(settings)
        meta = docs[0] if docs else {}
        return {"content": read_instructions_raw(settings), **meta}

    @app.put("/api/knowledge/instructions", dependencies=[human_dependency])
    async def knowledge_instructions_put(body: KnowledgeContentBody) -> dict[str, Any]:
        meta = save_instructions(settings, body.content)
        return {"ok": True, **meta}

    @app.get("/api/knowledge/memory", dependencies=[human_dependency])
    async def knowledge_memory_get() -> dict[str, Any]:
        docs = list_knowledge_docs(settings)
        meta = docs[1] if len(docs) > 1 else {}
        return {"content": read_global_memory_raw(settings), **meta}

    @app.put("/api/knowledge/memory", dependencies=[human_dependency])
    async def knowledge_memory_put(body: KnowledgeContentBody) -> dict[str, Any]:
        meta = save_global_memory(settings, body.content)
        return {"ok": True, **meta}

    @app.get("/api/knowledge/contacts", dependencies=[human_dependency])
    async def knowledge_contacts() -> dict[str, Any]:
        return {"contacts": memory.list_contacts_with_facts()}

    @app.put("/api/memory/{contact}/facts", dependencies=[human_dependency])
    async def upsert_contact_fact(contact: str, body: MemoryFactBody) -> dict[str, Any]:
        result = memory.remember_contact_fact(
            contact, body.key, body.value, source="dashboard"
        )
        return redact(result)

    @app.delete("/api/memory/{contact}/facts/{key}", dependencies=[human_dependency])
    async def delete_contact_fact_route(contact: str, key: str) -> dict[str, Any]:
        return redact(memory.delete_contact_fact(contact, key))

    @app.get("/api/runs", dependencies=[human_dependency])
    async def recent_runs(limit: int = Query(default=20, ge=0, le=100)) -> list[dict[str, Any]]:
        return memory.recent_runs(limit=limit)

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

    @app.get("/api/settings", dependencies=[human_dependency])
    async def read_settings(
        if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    ) -> Response:
        # The settings view is small but the dashboard re-fetches it on every
        # save, refresh, and (soon) SSE settings.changed event. A weak ETag
        # over the redacted view turns the common case into a 304 with no body.
        view = _settings_view(settings)
        body = json.dumps(view, sort_keys=True, ensure_ascii=False).encode("utf-8")
        etag = f'W/"{hashlib.blake2s(body, digest_size=12).hexdigest()}"'
        if if_none_match == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return JSONResponse(view, headers={"ETag": etag, "Cache-Control": "no-cache"})

    @app.patch("/api/settings", dependencies=[human_dependency])
    async def update_settings(patch: SettingsPatch) -> dict[str, Any]:
        # Build the override dict from non-None fields only.
        proposed: dict[str, Any] = {}
        raw = patch.model_dump(exclude={"confirm_allow_all"}, exclude_none=True)
        for key, value in raw.items():
            if key not in MUTABLE_FIELDS:
                continue
            if key in {"allowed_recipients", "owner_numbers"}:
                cleaned = sorted(
                    {str(item).strip() for item in (value or []) if str(item).strip()}
                )
                proposed[key] = cleaned
                continue
            if key in SECRET_FIELDS and isinstance(value, str) and value == "":
                proposed[key] = None
                continue
            proposed[key] = value

        # Validate model_routing if present. Uses Pydantic TypeAdapter to parse
        # the whole dict in one shot — catches unknown purpose keys and invalid
        # ModelChoice values with a single call.
        if "model_routing" in proposed:
            routing_raw = proposed["model_routing"]
            if not isinstance(routing_raw, dict):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        'model_routing must be a dict (e.g. {"chat": '
                        '{"provider": "openai", "model": ""}})'
                    ),
                )
            try:
                from pydantic import TypeAdapter

                from ..model_routing import ModelChoice, ModelPurpose

                _ta = TypeAdapter(dict[ModelPurpose, ModelChoice])
                validated_routing = _ta.validate_python(routing_raw)
            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid model_routing: {exc}",
                ) from exc
            # Store as serialisable plain dicts for JSON persistence.
            proposed["model_routing"] = {
                purpose.value: choice.model_dump()
                for purpose, choice in validated_routing.items()
            }

        if proposed.get("send_policy") == "allow_all" and not patch.confirm_allow_all:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Setting send_policy=allow_all removes the recipient guard. "
                    "Pass confirm_allow_all=true to acknowledge."
                ),
            )

        # wabot must stay on loopback (README safety rule). A non-loopback endpoint
        # would let an operator redirect the bearer token to an arbitrary host.
        if "wabot_endpoint" in proposed:
            _require_loopback_url("wabot_endpoint", proposed["wabot_endpoint"])

        # Validate base URLs and enforce the key-in-same-PATCH rule for each
        # provider with a URL safety validator in the registry.  The rule is:
        # if base_url_field is present in proposed AND the URL differs from the
        # stored value AND the provider has a secret, require the secret in the
        # same PATCH — otherwise the stored key would be sent to the new endpoint.
        #
        # Codex is handled separately below because its URL validator raises
        # ValueError (not HTTPException) and it uses a non-registry codex_base_url
        # with a different token field (codex_access_token) already in MUTABLE_FIELDS.
        for _spec in get_registry().values():
            if _spec.base_url_field is None or _spec.url_safety_validator is None:
                continue
            if _spec.base_url_field not in proposed:
                continue
            _new_url = proposed[_spec.base_url_field]
            _spec.url_safety_validator(_spec.base_url_field, _new_url)
            # If the URL is changing AND the provider has a secret field, require
            # the secret to accompany the change.
            if _spec.secret_field is not None:
                _stored_url = getattr(settings, _spec.base_url_field, None)
                if _new_url != _stored_url and _spec.secret_field not in proposed:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Changing {_spec.base_url_field} requires {_spec.secret_field} in the "
                            "same PATCH so the existing stored key is not sent to a new endpoint."
                        ),
                    )

        # Codex base URL uses a different (ValueError-raising) validator and a
        # separate base_url field outside the standard ProviderSpec.base_url_field
        # contract (codex_base_url lives in MUTABLE_FIELDS but not in the spec).
        if "codex_base_url" in proposed:
            try:
                from ..codex_auth import require_safe_codex_url

                require_safe_codex_url(proposed["codex_base_url"])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if (
                proposed["codex_base_url"] != settings.codex_base_url
                and "codex_access_token" not in proposed
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Changing codex_base_url requires codex_access_token in the "
                        "same PATCH so the existing stored token is not sent to a new endpoint."
                    ),
                )

        # Build the full set we'll persist (existing disk overrides + this patch),
        # then validate the WHOLE thing on a snapshot — not just the delta. This
        # catches the edge case where a stale/manually-edited overrides file
        # contains a value that would fail validation when reapplied at restart.
        merged = load_overrides(settings.runtime_overrides_path)
        merged.update(proposed)

        snapshot = settings.model_copy(deep=True)
        try:
            apply_overrides(snapshot, merged)
        except Exception as exc:  # pydantic ValidationError or other
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Persist to disk first. If this raises, live settings stay unchanged.
        # Disk is the authoritative source on next restart, so failing here means
        # we MUST NOT mutate live state — the next reload would otherwise diverge.
        save_overrides(settings.runtime_overrides_path, merged)

        # Now commit to live settings. The same validators just succeeded on the
        # snapshot, so this is reliable (and we'd rather crash here than leave
        # disk and memory desynced — the operator can restart to recover).
        apply_overrides(settings, proposed)
        wabot.endpoint = settings.wabot_endpoint.rstrip("/")
        wabot.token = settings.resolved_wabot_token

        event_log.write(
            "settings_updated",
            {"fields": sorted(proposed.keys())},
        )
        return _settings_view(settings)

    # Test endpoints for providers that declare test_endpoint_path in the registry.
    # FastAPI requires static type annotations for request bodies, so these handlers
    # are kept as explicit named functions rather than dynamically generated routes.
    # The handlers look up the spec from the registry to delegate to the right
    # test_endpoint_handler — adding a new provider with a test endpoint requires
    # a registry entry + a new handler here + a TSX section in the SPA.

    @app.post("/api/settings/test/openai", dependencies=[human_dependency])
    async def test_openai(payload: OpenAITestRequest | None = None) -> dict[str, Any]:
        spec = get_registry()["openai"]
        assert spec.test_endpoint_handler is not None
        return await spec.test_endpoint_handler(settings, payload or OpenAITestRequest())

    @app.post("/api/settings/test/openrouter", dependencies=[human_dependency])
    async def test_openrouter(payload: OpenRouterTestRequest | None = None) -> dict[str, Any]:
        spec = get_registry()["openrouter"]
        assert spec.test_endpoint_handler is not None
        return await spec.test_endpoint_handler(settings, payload or OpenRouterTestRequest())

    @app.post("/api/settings/test/llm", dependencies=[human_dependency])
    async def test_llm() -> dict[str, Any]:
        return await _test_llm_endpoint(settings)

    @app.get("/api/codex/login", dependencies=[human_dependency])
    async def codex_login_status() -> dict[str, Any]:
        await poll_device_login(settings)
        return device_login_view(settings)

    @app.post("/api/codex/login/device", dependencies=[human_dependency])
    async def codex_login_device_start() -> dict[str, Any]:
        await start_device_login(settings)
        await poll_device_login(settings, wait_seconds=8)
        return device_login_view(settings)

    @app.post("/api/codex/login/device/cancel", dependencies=[human_dependency])
    async def codex_login_device_cancel() -> dict[str, Any]:
        await cancel_device_login()
        return device_login_view(settings)

    @app.post("/api/codex/login/disconnect", dependencies=[human_dependency])
    async def codex_login_disconnect() -> dict[str, Any]:
        await cancel_device_login()
        try:
            result = disconnect_codex_credentials(settings)
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not remove Codex credentials: {exc}",
            ) from exc

        view = device_login_view(settings)
        event_log.write(
            "codex_disconnected",
            {
                "auth_file_removed": result["auth_file_removed"],
                "token_override_masked": result["token_override_masked"],
            },
        )
        return {**view, "disconnected": True, **result}

    @app.post("/api/settings/test/wabot", dependencies=[human_dependency])
    async def test_wabot() -> dict[str, Any]:
        health = await wabot.health()
        return {
            "ok": health.ready,
            "reachable": health.reachable,
            "logged_in": health.logged_in,
            "connected": health.connected,
            "detail": health.detail or (
                "wabot daemon is reachable and WhatsApp is linked."
                if health.ready
                else "wabot reachable but session not ready."
            ),
        }

    @app.get("/api/whatsapp/groups", dependencies=[human_dependency])
    async def list_whatsapp_groups_api() -> dict[str, Any]:
        return await _wabot_call(wabot.list_groups())

    @app.post("/api/whatsapp/groups", dependencies=[human_dependency])
    async def create_whatsapp_group_api(body: GroupCreateRequest) -> dict[str, Any]:
        return await _wabot_call(wabot.create_group(body.name, body.participants))

    @app.get("/api/whatsapp/groups/{group_jid}", dependencies=[human_dependency])
    async def get_whatsapp_group_api(group_jid: str) -> dict[str, Any]:
        return await _wabot_call(wabot.get_group(group_jid))

    @app.patch("/api/whatsapp/groups/{group_jid}", dependencies=[human_dependency])
    async def update_whatsapp_group_api(
        group_jid: str, body: GroupUpdateRequest
    ) -> dict[str, Any]:
        if (
            body.name is None
            and body.topic is None
            and body.announce is None
            and body.locked is None
        ):
            raise HTTPException(
                status_code=400,
                detail="provide at least one of name, topic, announce, locked",
            )
        return await _wabot_call(
            wabot.update_group(
                group_jid,
                name=body.name,
                topic=body.topic,
                announce=body.announce,
                locked=body.locked,
            )
        )

    @app.post(
        "/api/whatsapp/groups/{group_jid}/participants",
        dependencies=[human_dependency],
    )
    async def update_whatsapp_group_participants_api(
        group_jid: str, body: GroupParticipantsRequest
    ) -> dict[str, Any]:
        return await _wabot_call(
            wabot.update_group_participants(
                group_jid, body.participants, action=body.action
            )
        )

    @app.post("/api/whatsapp/groups/{group_jid}/leave", dependencies=[human_dependency])
    async def leave_whatsapp_group_api(group_jid: str) -> dict[str, Any]:
        return await _wabot_call(wabot.leave_group(group_jid))

    @app.post(
        "/api/whatsapp/groups/{group_jid}/picture",
        dependencies=[human_dependency],
    )
    async def set_whatsapp_group_picture_api(
        group_jid: str,
        file: Annotated[UploadFile, File()],
    ) -> dict[str, Any]:
        suffix = Path(file.filename or "group.jpg").suffix or ".jpg"
        tmp = settings.media_dir / f"group-picture-upload-{secrets.token_hex(8)}{suffix}"
        try:
            data = await file.read()
            if not data:
                raise HTTPException(status_code=400, detail="empty file")
            tmp.write_bytes(data)
            return await _wabot_call(wabot.set_group_picture(group_jid, str(tmp)))
        finally:
            tmp.unlink(missing_ok=True)

    @app.delete(
        "/api/whatsapp/groups/{group_jid}/picture",
        dependencies=[human_dependency],
    )
    async def remove_whatsapp_group_picture_api(group_jid: str) -> dict[str, Any]:
        return await _wabot_call(wabot.remove_group_picture(group_jid))

    @app.post(
        "/api/whatsapp/groups/{group_jid}/invite",
        dependencies=[human_dependency],
    )
    async def get_whatsapp_group_invite_api(
        group_jid: str, body: GroupInviteRequest
    ) -> dict[str, Any]:
        return await _wabot_call(wabot.get_group_invite(group_jid, reset=body.reset))

    @app.post("/api/whatsapp/groups/join", dependencies=[human_dependency])
    async def join_whatsapp_group_api(body: GroupJoinRequest) -> dict[str, Any]:
        return await _wabot_call(wabot.join_group(body.invite_link))

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


def _qr_svg(payload: str) -> bytes:
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    # SvgFillImage embeds a white backdrop; SvgPathImage is transparent and
    # disappears on the dashboard's dark pairing panel.
    image = qr.make_image(
        image_factory=SvgFillImage,
        fill_color="black",
        back_color="white",
    )
    out = io.BytesIO()
    image.save(out)
    return out.getvalue()


# _wabot_call and _verify_inbound_auth now live in api/dependencies.py.


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, reload=False)
