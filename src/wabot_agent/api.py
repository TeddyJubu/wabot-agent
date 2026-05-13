from __future__ import annotations

import io
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import qrcode
import uvicorn
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from qrcode.image.svg import SvgPathImage

from .agent import run_agent
from .config import Settings, get_settings
from .events import EventLog
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


class SettingsPatch(BaseModel):
    """Partial update to runtime-mutable settings.

    Any field omitted is unchanged. To clear a secret, pass an empty string.
    `confirm_allow_all` must be true to set send_policy='allow_all'.
    """

    openrouter_api_key: str | None = None
    openrouter_base_url: str | None = None
    openrouter_model: str | None = None
    wabot_endpoint: str | None = None
    wabot_token: str | None = None
    send_policy: str | None = None
    allowed_recipients: list[str] | None = None
    max_agent_turns: int | None = None
    confirm_allow_all: bool = False


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
    event_log = EventLog(settings.log_path)
    wabot = WabotClient(settings.wabot_endpoint, settings.resolved_wabot_token)

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

    @app.get("/api/whatsapp/pairing", dependencies=[operator_dependency])
    async def whatsapp_pairing() -> dict[str, Any]:
        pairing = await wabot.pairing_qr()
        return redact(
            {
                "supported": pairing.supported,
                "reachable": pairing.reachable,
                "logged_in": pairing.logged_in,
                "connected": pairing.connected,
                "qr_available": pairing.qr_available,
                "event": pairing.event,
                "updated_at": pairing.updated_at,
                "expires_at": pairing.expires_at,
                "detail": pairing.detail,
            }
        )

    @app.get(
        "/api/whatsapp/pairing.svg",
        dependencies=[operator_dependency],
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

    @app.get("/api/settings", dependencies=[operator_dependency])
    async def read_settings() -> dict[str, Any]:
        return _settings_view(settings)

    @app.patch("/api/settings", dependencies=[operator_dependency])
    async def update_settings(patch: SettingsPatch) -> dict[str, Any]:
        # Build the override dict from non-None fields only.
        proposed: dict[str, Any] = {}
        raw = patch.model_dump(exclude={"confirm_allow_all"}, exclude_none=True)
        for key, value in raw.items():
            if key not in MUTABLE_FIELDS:
                continue
            if key == "allowed_recipients":
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

    @app.post("/api/settings/test/openrouter", dependencies=[operator_dependency])
    async def test_openrouter() -> dict[str, Any]:
        if not settings.openrouter_api_key:
            return {"ok": False, "detail": "OPENROUTER_API_KEY is not configured."}
        import httpx

        url = settings.openrouter_base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            return {"ok": False, "detail": f"Connection failed: {exc}"}
        if resp.status_code == 200:
            return {
                "ok": True,
                "detail": f"OpenRouter reachable. Active model: {settings.openrouter_model}",
            }
        return {
            "ok": False,
            "detail": f"OpenRouter returned HTTP {resp.status_code}: {resp.text[:200]}",
        }

    @app.post("/api/settings/test/wabot", dependencies=[operator_dependency])
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


def _settings_view(settings: Settings) -> dict[str, Any]:
    """Build the GET /api/settings response: secrets masked, source-of-truth annotated."""
    return {
        "env_source": ".env (immutable) + data/runtime_overrides.json (operator-mutable)",
        "send_policy": settings.send_policy,
        "send_policy_choices": ["dry_run", "allowlist", "allow_all"],
        "allowed_recipients": sorted(settings.allowed_recipients),
        "max_agent_turns": settings.max_agent_turns,
        "openrouter": {
            "api_key": mask_secret(settings.openrouter_api_key),
            "base_url": settings.openrouter_base_url,
            "model": settings.openrouter_model,
            "live": settings.live_model_enabled,
        },
        "wabot": {
            "endpoint": settings.wabot_endpoint,
            "token": mask_secret(settings.resolved_wabot_token),
            "token_file": str(settings.wabot_token_file) if settings.wabot_token_file else None,
        },
    }


def _qr_svg(payload: str) -> bytes:
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    out = io.BytesIO()
    image.save(out)
    return out.getvalue()


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
