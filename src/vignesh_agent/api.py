from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
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

    app = FastAPI(title="Vignesh WhatsApp Agent", version="0.1.0")
    app.state.settings = settings
    app.state.memory = memory
    app.state.event_log = event_log
    app.state.wabot = wabot

    static_dir = Path(__file__).resolve().parents[2] / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def dashboard() -> FileResponse:
        index = static_dir / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="Dashboard not built.")
        return FileResponse(index)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "service": "vignesh-agent", "env": settings.env}

    @app.get("/ready")
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

    @app.post("/api/chat", response_model=ChatResponse)
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
        if memory.is_processed(inbound.id):
            return {"accepted": True, "duplicate": True, "message_id": inbound.id}
        memory.mark_processed(inbound.id, inbound.sender)
        event_log.write(
            "inbound_message",
            {"message_id": inbound.id, "sender": inbound.sender, "path": str(request.url.path)},
        )
        result = await run_agent(
            inbound.text,
            settings=settings,
            memory=memory,
            event_log=event_log,
            wabot=wabot,
            inbound=inbound,
            session_id=inbound.sender,
        )
        return {
            "accepted": True,
            "duplicate": False,
            "message_id": inbound.id,
            "run_id": result.run_id,
            "output": result.final_output,
        }

    @app.get("/api/memory/{contact}")
    async def contact_memory(contact: str) -> dict[str, Any]:
        return redact(memory.recall_contact(contact))

    @app.get("/api/runs")
    async def recent_runs(limit: int = 20) -> list[dict[str, Any]]:
        return memory.recent_runs(limit=min(limit, 100))

    return app


def _verify_inbound_auth(settings: Settings, authorization: str | None) -> None:
    if not settings.wabot_inbound_token:
        return
    expected = f"Bearer {settings.wabot_inbound_token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


def get_app() -> FastAPI:
    return create_app()


app = get_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run("vignesh_agent.api:app", host=settings.host, port=settings.port, reload=False)

