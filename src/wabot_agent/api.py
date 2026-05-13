from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import run_agent
from .config import Settings, get_settings
from .events import EventLog
from .memory import InboundMessage, MemoryStore
from .redaction import redact
from .wabot import WabotClient


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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    memory = MemoryStore(settings.db_path)
    event_log = EventLog(settings.log_path)
    wabot = WabotClient(settings.wabot_endpoint, settings.wabot_token)

    app = FastAPI(title="wabot-agent", version="0.1.0")
    app.state.settings = settings
    app.state.memory = memory
    app.state.event_log = event_log
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

    async def verify_operator(
        x_operator_token: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
        operator_session: str | None = Cookie(default=None, alias="wabot_agent_operator_token"),
    ) -> None:
        _verify_operator_auth(settings, x_operator_token, authorization, operator_session)

    operator_dependency = Depends(verify_operator)

    @app.get("/")
    async def dashboard(
        token: str | None = Query(default=None),
        operator_session: str | None = Cookie(default=None, alias="wabot_agent_operator_token"),
    ) -> FileResponse:
        if settings.operator_token:
            if token:
                _verify_operator_auth(settings, token, None, None)
                file_response = _dashboard_file(static_dir)
                file_response.set_cookie(
                    "wabot_agent_operator_token",
                    token,
                    httponly=True,
                    secure=False,
                    samesite="strict",
                )
                return file_response
            _verify_operator_auth(settings, None, None, operator_session)
        file_response = _dashboard_file(static_dir)
        file_response.headers["Cache-Control"] = "no-store"
        return file_response

    def _dashboard_file(static_dir: Path) -> FileResponse:
        index = static_dir / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="Dashboard not built.")
        return FileResponse(index)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "service": "wabot-agent", "env": settings.env}

    @app.get("/ready", dependencies=[operator_dependency])
    async def ready() -> dict[str, Any]:
        wabot_health = await wabot.health()
        return redact(
            {
                "ok": True,
                "live_model": settings.live_model_enabled,
                "model": settings.openrouter_model if settings.live_model_enabled else "offline",
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

    @app.post("/api/chat", response_model=ChatResponse, dependencies=[operator_dependency])
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
        )
        if not memory.claim_message(inbound.id, inbound.sender):
            return {"accepted": True, "duplicate": True, "message_id": inbound.id}
        event_log.write(
            "inbound_message",
            {"message_id": inbound.id, "sender": inbound.sender, "path": str(request.url.path)},
        )
        try:
            result = await run_agent(
                inbound.text,
                settings=settings,
                memory=memory,
                event_log=event_log,
                wabot=wabot,
                inbound=inbound,
                session_id=inbound.sender,
            )
        except Exception as exc:
            memory.fail_message(inbound.id, str(exc))
            event_log.write(
                "inbound_message_failed",
                {"message_id": inbound.id, "sender": inbound.sender, "error": str(exc)},
            )
            raise
        memory.complete_message(inbound.id, result.run_id)
        return {
            "accepted": True,
            "duplicate": False,
            "message_id": inbound.id,
            "run_id": result.run_id,
            "output": result.final_output,
        }

    @app.get("/api/memory/{contact}", dependencies=[operator_dependency])
    async def contact_memory(contact: str) -> dict[str, Any]:
        return redact(memory.recall_contact(contact))

    @app.get("/api/runs", dependencies=[operator_dependency])
    async def recent_runs(limit: int = Query(default=20, ge=0, le=100)) -> list[dict[str, Any]]:
        return memory.recent_runs(limit=limit)

    return app


def _verify_inbound_auth(settings: Settings, authorization: str | None) -> None:
    if not settings.wabot_inbound_token:
        return
    expected = f"Bearer {settings.wabot_inbound_token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


def _verify_operator_auth(
    settings: Settings,
    x_operator_token: str | None,
    authorization: str | None,
    operator_session: str | None,
) -> None:
    if not settings.operator_token:
        return
    candidates = [x_operator_token, operator_session]
    if authorization and authorization.lower().startswith("bearer "):
        candidates.append(authorization.split(" ", 1)[1])
    if any(
        candidate and secrets.compare_digest(candidate, settings.operator_token)
        for candidate in candidates
    ):
        return
    raise HTTPException(status_code=401, detail="operator auth required")


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, reload=False)
