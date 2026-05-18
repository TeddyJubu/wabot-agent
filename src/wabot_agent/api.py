from __future__ import annotations

import asyncio
import hashlib
import io
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import qrcode
import uvicorn
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from qrcode.image.svg import SvgFillImage

from .agent import run_agent, run_agent_streamed
from .auth import (
    AuthIdentity,
    maybe_mint_operator_cookie,
    mint_operator_session_cookie,
    password_grants_dashboard_access,
    render_login_page,
    resolve_human_factory,
    verify_human_factory,
)
from .auto_reply import (
    deliver_auto_reply,
    deliver_inbound_error_reply,
    inbound_session_id,
)
from .recipients import is_owner_inbound
from .tools import _is_send_allowed
from .wabot import WabotError
from .config import Settings, get_settings
from .context_management import maybe_prune_audit_tables
from .events import EventHub, EventLog
from .llm_provider import active_model_id, llm_provider_label
from .memory import InboundMessage, MemoryStore
from .redaction import redact
from .runtime_overrides import (
    MUTABLE_FIELDS,
    SECRET_FIELDS,
    apply_overrides,
    load_overrides,
    mask_secret,
    save_overrides,
)
from .typing_indicator import inbound_typing_indicator
from .wabot import WabotClient
from .wabot_process import WabotRestartError, restart_wabot_daemon, wait_for_fresh_pairing


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    run_id: str
    session_id: str
    output: str
    live_model: bool


class InboundPayload(BaseModel):
    id: str
    timestamp: str | None = None
    from_: str = Field(alias="from")
    chat: str | None = None
    is_group: bool = False
    push_name: str | None = None
    text: str = ""
    media_kind: str | None = None
    media_mime: str | None = None
    media_filename: str | None = None
    has_media: bool = False


class ReceiptPayload(BaseModel):
    type: str = "receipt"
    chat: str
    message_ids: list[str] = Field(default_factory=list)
    receipt_type: str
    timestamp: str | None = None
    sender: str | None = None
    message_sender: str | None = None


class PresencePayload(BaseModel):
    type: str = "chat_presence"
    chat: str
    sender: str
    state: str
    media: str | None = None


class HistorySyncSummaryPayload(BaseModel):
    type: str = "history_sync"
    sync_type: str
    conversation_count: int = 0
    message_count: int = 0
    chunk_order: int | None = None
    progress: int | None = None


class HistoryBatchPayload(BaseModel):
    type: str = "history_batch"
    sync_type: str
    messages: list[InboundPayload] = Field(default_factory=list)
    message_count: int = 0
    chunk_order: int | None = None
    progress: int | None = None


class SettingsPatch(BaseModel):
    """Partial update to runtime-mutable settings.

    Any field omitted is unchanged. To clear a secret, pass an empty string.
    `confirm_allow_all` must be true to set send_policy='allow_all'.
    """

    model_provider: str | None = None
    openrouter_api_key: str | None = None
    openrouter_base_url: str | None = None
    openrouter_model: str | None = None
    ollama_model: str | None = None
    ollama_base_url: str | None = None
    ollama_api_key: str | None = None
    ollama_cloud_base_url: str | None = None
    wabot_endpoint: str | None = None
    wabot_token: str | None = None
    send_policy: str | None = None
    allowed_recipients: list[str] | None = None
    owner_numbers: list[str] | None = None
    auto_reply_enabled: bool | None = None
    max_agent_turns: int | None = None
    confirm_allow_all: bool = False


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
        memory.mark_reminder_fired(reminder_id, error="wabot_not_ready")
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
        return
    health = await wabot.health()
    if not health.ready:
        return
    summary = (
        f"No reply from {target} within the tracking window (task {task.get('id', '')})."
    )
    try:
        await wabot.send_text(to=owner, text=summary)
    except WabotError:
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
        return task

    health = await wabot.health()
    if not health.ready:
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
            print(
                f"[runtime_overrides] overrides file failed validation, ignoring: {exc}",
                flush=True,
            )
        else:
            apply_overrides(settings, overrides)
    memory = MemoryStore(settings.db_path)
    hub = EventHub()
    event_log = EventLog(settings.log_path, hub=hub)
    wabot = WabotClient(settings.wabot_endpoint, settings.resolved_wabot_token)

    # Pairing poller state — last published payload + the asyncio task handle.
    pairing_state: dict[str, Any] = {"last": None, "task": None}
    scheduler_state: dict[str, Any] = {"task": None}

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
            except Exception:  # noqa: BLE001 — never let a transient HTTP error kill the loop
                payload = None
            if payload is not None and payload != pairing_state["last"]:
                pairing_state["last"] = payload
                hub.publish("pairing_changed", payload)
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                return

    async def _run_web_research_job(job: dict[str, Any]) -> None:
        from .web_research import execute_web_research_job

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
        from .memory import now_iso

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
        maybe_prune_audit_tables(memory, settings, force=True)
        pairing_state["task"] = asyncio.create_task(_pairing_poll_loop())
        scheduler_state["task"] = asyncio.create_task(_scheduler_loop())
        try:
            yield
        finally:
            pairing_task = pairing_state.get("task")
            if pairing_task is not None:
                pairing_task.cancel()
                try:
                    await pairing_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            sched_task = scheduler_state.get("task")
            if sched_task is not None:
                sched_task.cancel()
                try:
                    await sched_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    app = FastAPI(title="wabot-agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.memory = memory
    app.state.event_log = event_log
    app.state.event_hub = hub
    app.state.wabot = wabot

    static_dir = Path(__file__).resolve().parents[2] / "static"
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

    def _safe_next_path(next_path: str) -> str:
        if next_path.startswith("/") and not next_path.startswith("//"):
            return next_path
        return "/"

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

    def _dashboard_file(static_dir: Path) -> FileResponse:
        index = static_dir / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="Dashboard not built.")
        return FileResponse(index)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "service": "wabot-agent", "env": settings.env}

    @app.get("/ready", dependencies=[human_dependency])
    async def ready() -> dict[str, Any]:
        wabot_health = await wabot.health()
        return redact(
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
            }
        )

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
        pairing_state["last"] = payload
        hub.publish("pairing_changed", payload)
        return payload

    @app.post("/api/chat", response_model=ChatResponse, dependencies=[human_dependency])
    async def chat(payload: ChatRequest) -> ChatResponse:
        result = await run_agent(
            payload.message,
            settings=settings,
            memory=memory,
            event_log=event_log,
            wabot=wabot,
            session_id=payload.session_id,
        )
        return ChatResponse(
            run_id=result.run_id,
            session_id=result.session_id,
            output=result.final_output,
            live_model=result.live_model,
        )

    @app.post(
        "/api/chat/stream",
        dependencies=[human_dependency],
        response_model=None,
    )
    async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
        """Run the agent and stream NDJSON events to the client.

        One JSON object per line. Event types:
          - delta:      incremental model token (text)
          - tool_call:  tool invocation (name + redacted args)
          - tool_result: tool completion marker
          - final:      run summary (run_id, output, live_model)
          - error:      terminal failure (message)
        The stream ends after `final` or `error`.

        The existing `POST /api/chat` JSON endpoint is preserved for callers
        that don't want a stream (external scripts, the inbound webhook path).
        """

        async def event_generator() -> Any:
            iterator = run_agent_streamed(
                payload.message,
                settings=settings,
                memory=memory,
                event_log=event_log,
                wabot=wabot,
                session_id=payload.session_id,
            ).__aiter__()
            try:
                while True:
                    # Cancel the agent if the client has gone away — otherwise
                    # we'd keep burning OpenRouter tokens for nobody.
                    if await request.is_disconnected():
                        raise asyncio.CancelledError()
                    try:
                        event = await iterator.__anext__()
                    except StopAsyncIteration:
                        return
                    yield json.dumps(event, ensure_ascii=False) + "\n"
            except asyncio.CancelledError:
                try:
                    await iterator.aclose()
                except Exception:  # noqa: BLE001
                    pass
                event_log.write("chat_stream_cancelled", {"session_id": payload.session_id})
                raise

        return StreamingResponse(
            event_generator(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/whatsapp/inbound")
    async def whatsapp_inbound(
        payload: InboundPayload,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _verify_inbound_auth(settings, authorization)
        inbound = InboundMessage(
            id=payload.id,
            sender=payload.from_,
            chat=payload.chat,
            text=payload.text,
            timestamp=payload.timestamp,
            push_name=payload.push_name,
            is_group=payload.is_group,
            media_kind=payload.media_kind,
            media_mime=payload.media_mime,
            media_filename=payload.media_filename,
            has_media=payload.has_media,
        )
        memory.record_inbound(inbound)
        if not is_owner_inbound(settings, inbound):
            await _handle_outbound_reply(
                inbound,
                settings=settings,
                memory=memory,
                wabot=wabot,
                event_log=event_log,
                hub=hub,
            )
        if not memory.claim_message(inbound.id, inbound.sender):
            return {"accepted": True, "duplicate": True, "message_id": inbound.id}
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

    @app.post("/whatsapp/receipt")
    async def whatsapp_receipt(
        payload: ReceiptPayload,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _verify_inbound_auth(settings, authorization)
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

    @app.post("/whatsapp/presence")
    async def whatsapp_presence(
        payload: PresencePayload,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _verify_inbound_auth(settings, authorization)
        body = payload.model_dump()
        hub.publish("whatsapp_presence", body)
        event_log.write(
            "whatsapp_presence",
            {"chat": payload.chat, "sender": payload.sender, "state": payload.state},
        )
        return {"accepted": True}

    @app.post("/whatsapp/history-sync")
    async def whatsapp_history_sync(
        payload: HistorySyncSummaryPayload,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _verify_inbound_auth(settings, authorization)
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

    @app.post("/whatsapp/history")
    async def whatsapp_history(
        payload: HistoryBatchPayload,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Backfill inbound_messages from wabot history sync (no agent auto-reply)."""
        _verify_inbound_auth(settings, authorization)
        inbounds = [
            InboundMessage(
                id=msg.id,
                sender=msg.from_,
                chat=msg.chat,
                text=msg.text,
                timestamp=msg.timestamp,
                push_name=msg.push_name,
                is_group=msg.is_group,
                media_kind=msg.media_kind,
                media_mime=msg.media_mime,
                media_filename=msg.media_filename,
                has_media=msg.has_media,
            )
            for msg in payload.messages
        ]
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

    @app.get("/api/memory/{contact}", dependencies=[human_dependency])
    async def contact_memory(contact: str) -> dict[str, Any]:
        return redact(memory.recall_contact(contact))

    @app.get("/api/runs", dependencies=[human_dependency])
    async def recent_runs(limit: int = Query(default=20, ge=0, le=100)) -> list[dict[str, Any]]:
        return memory.recent_runs(limit=limit)

    async def _build_initial_snapshot() -> dict[str, Any]:
        """Initial payload pushed when an SSE client connects.

        Bundles /ready + /api/runs + pairing into one event so the dashboard
        renders completely without follow-up REST calls. Subsequent state
        changes arrive as deltas on the same stream.
        """
        wabot_health = await wabot.health()
        # Prefer the poller's cached pairing snapshot (already redacted on
        # publish); on cold start before the first tick fires, fall through
        # to a fresh probe so the client doesn't paint a blank pairing card.
        pairing = pairing_state.get("last")
        if pairing is None:
            pairing = _pairing_payload(await wabot.pairing_qr())
        return redact(
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

        # openrouter_base_url must be HTTPS or loopback HTTP. AND if the base URL
        # changes, require a new API key in the same patch — otherwise the next
        # /api/settings/test/openrouter (or /api/chat) would send the existing
        # stored key to the new endpoint, defeating the no-round-trip property.
        if "openrouter_base_url" in proposed:
            _require_safe_openrouter_url("openrouter_base_url", proposed["openrouter_base_url"])
            if (
                proposed["openrouter_base_url"] != settings.openrouter_base_url
                and "openrouter_api_key" not in proposed
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Changing openrouter_base_url requires openrouter_api_key in the "
                        "same PATCH so the existing stored key is not sent to a new endpoint."
                    ),
                )

        if "ollama_base_url" in proposed:
            _require_safe_ollama_local_url("ollama_base_url", proposed["ollama_base_url"])

        if "ollama_cloud_base_url" in proposed:
            _require_safe_ollama_cloud_url(
                "ollama_cloud_base_url", proposed["ollama_cloud_base_url"]
            )
            if (
                proposed["ollama_cloud_base_url"] != settings.ollama_cloud_base_url
                and "ollama_api_key" not in proposed
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Changing ollama_cloud_base_url requires ollama_api_key in the "
                        "same PATCH so the existing stored key is not sent to a new endpoint."
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

    @app.post("/api/settings/test/openrouter", dependencies=[human_dependency])
    async def test_openrouter() -> dict[str, Any]:
        return await _test_llm_endpoint(settings)

    @app.post("/api/settings/test/llm", dependencies=[human_dependency])
    async def test_llm() -> dict[str, Any]:
        return await _test_llm_endpoint(settings)

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

    return app


_LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})


def _require_loopback_url(field: str, url: str) -> None:
    """Reject URLs whose host is not loopback. Defends the wabot bearer token
    from being redirected to an arbitrary host by an operator-token holder."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().strip("[]")
    if host not in _LOOPBACK_HOSTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field} must point at loopback (localhost, 127.0.0.1, or ::1); "
                f"got '{host or url}'."
            ),
        )


def _require_safe_ollama_local_url(field: str, url: str) -> None:
    """Ollama local must be loopback — the daemon holds cloud credentials."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail=f"{field} must use http or https; got scheme '{parsed.scheme}'.",
        )
    host = (parsed.hostname or "").lower().strip("[]")
    if host not in _LOOPBACK_HOSTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field} must point at the local Ollama daemon on loopback; "
                f"got '{host or url}'."
            ),
        )


def _require_safe_ollama_cloud_url(field: str, url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(
            status_code=400,
            detail=f"{field} must use https; got scheme '{parsed.scheme}'.",
        )
    host = (parsed.hostname or "").lower().strip("[]")
    if host not in ("ollama.com", "www.ollama.com"):
        raise HTTPException(
            status_code=400,
            detail=f"{field} must target ollama.com; got '{host or url}'.",
        )


def _require_safe_openrouter_url(field: str, url: str) -> None:
    """Allow https://anywhere or http://loopback. Plain HTTP to a remote host
    would leak the API key in cleartext."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail=f"{field} must use http or https; got scheme '{parsed.scheme}'.",
        )
    host = (parsed.hostname or "").lower().strip("[]")
    if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field} over plain HTTP is only allowed for loopback hosts; "
                f"use https for '{host or url}'."
            ),
        )


async def _test_llm_endpoint(settings: Settings) -> dict[str, Any]:
    import httpx

    from .llm_provider import resolved_llm_api_key, resolved_llm_base_url

    label = llm_provider_label(settings)
    if not settings.live_model_enabled:
        if settings.model_provider == "openrouter":
            return {"ok": False, "detail": "OPENROUTER_API_KEY is not configured."}
        if settings.model_provider == "ollama_cloud":
            return {"ok": False, "detail": "OLLAMA_API_KEY is not configured."}
        return {"ok": False, "detail": "Offline mode is enabled."}

    url = resolved_llm_base_url(settings) + "/models"
    headers: dict[str, str] = {}
    api_key = resolved_llm_api_key(settings)
    if settings.model_provider != "ollama" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": f"{label} connection failed: {exc}"}
    model = active_model_id(settings)
    if resp.status_code == 200:
        return {"ok": True, "detail": f"{label} reachable. Active model: {model}"}
    return {
        "ok": False,
        "detail": f"{label} returned HTTP {resp.status_code}: {resp.text[:200]}",
    }


def _settings_view(settings: Settings) -> dict[str, Any]:
    """Build the GET /api/settings response: secrets masked, source-of-truth annotated."""
    return {
        "env_source": ".env (immutable) + data/runtime_overrides.json (operator-mutable)",
        "send_policy": settings.send_policy,
        "send_policy_choices": ["dry_run", "allowlist", "allow_all", "owner"],
        "allowed_recipients": sorted(settings.allowed_recipients),
        "owner_numbers": sorted(settings.owner_numbers),
        "auto_reply_enabled": settings.auto_reply_enabled,
        "max_agent_turns": settings.max_agent_turns,
        "llm": {
            "provider": settings.model_provider,
            "provider_choices": ["openrouter", "ollama", "ollama_cloud"],
            "model": active_model_id(settings),
            "label": llm_provider_label(settings),
            "live": settings.live_model_enabled,
        },
        "openrouter": {
            "api_key": mask_secret(settings.openrouter_api_key),
            "base_url": settings.openrouter_base_url,
            "model": settings.openrouter_model,
            "live": settings.model_provider == "openrouter" and settings.live_model_enabled,
        },
        "ollama": {
            "api_key": mask_secret(settings.ollama_api_key),
            "model": settings.ollama_model,
            "base_url": settings.ollama_base_url,
            "cloud_base_url": settings.ollama_cloud_base_url,
            "live": settings.model_provider.startswith("ollama") and settings.live_model_enabled,
        },
        "wabot": {
            "endpoint": settings.wabot_endpoint,
            "token": mask_secret(settings.resolved_wabot_token),
            "token_file": str(settings.wabot_token_file) if settings.wabot_token_file else None,
        },
    }


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


def _verify_inbound_auth(settings: Settings, authorization: str | None) -> None:
    if not settings.wabot_inbound_token:
        return
    expected = f"Bearer {settings.wabot_inbound_token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, reload=False)
