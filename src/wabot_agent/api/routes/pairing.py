"""WhatsApp pairing — operator routes + async pairing-state poll loop.

Carved out of api/__init__.py as part of MASTER ME-1 Part 5. The pairing
flow has two halves:

- HTTP routes (operator initiated): GET pairing state, GET pairing.svg
  (QR rendered), POST pairing/restart, POST pairing/disconnect.
- Background loop: pairing_poll_loop polls wabot.pairing_qr() and
  publishes state changes to the SSE hub so the dashboard's pairing slide-
  over reacts to QR rotations and connect/disconnect events without the
  operator refreshing.

The loop is owned by create_app's lifespan (it stores the asyncio.Task
on deps.pairing_state.task and cancels it on shutdown). The function
itself lives here so all pairing logic is colocated.

Public surface:
- register_pairing_routes(router, deps) — attaches 4 HTTP routes.
- pairing_poll_loop(deps) — async coroutine, expected to be wrapped in
  asyncio.create_task(...) by the lifespan.
- _pairing_payload(p) and _pairing_unreachable_payload(...) — helpers
  used by both the routes and by other code (e.g., /api/stream's initial
  snapshot at api/__init__.py:925). Re-export them so external callers
  can keep importing.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from qrcode.image.svg import SvgFillImage

from ...auth import verify_human_factory
from ...redaction import redact
from ...wabot_process import WabotRestartError
from ..deps import AppDeps

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure data-shape helpers — used by routes, the poll loop, and the SSE
# initial-snapshot builder in api/__init__.py.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# QR rendering — lives here alongside the pairing routes that serve it.
# api/__init__.py re-exports _qr_svg for backward-compat (test_api.py).
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Async background poll loop — owned by lifespan, runs for the lifetime of
# the server process. Calling code wraps this in asyncio.create_task().
# ---------------------------------------------------------------------------


async def pairing_poll_loop(deps: AppDeps) -> None:
    """Probe wabot pairing state and publish pairing_changed on diff.

    Polls every 5s on loopback — cheap. We only publish when the snapshot
    actually changes, so a stable linked session generates zero events
    beyond the initial state push at startup.
    """
    pairing_state = deps.pairing_state
    wabot = deps.wabot
    hub = deps.hub

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


# ---------------------------------------------------------------------------
# HTTP routes — 4 operator-facing endpoints.
# ---------------------------------------------------------------------------


def register_pairing_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    wabot = deps.wabot
    pairing_state = deps.pairing_state
    hub = deps.hub
    event_log = deps.event_log

    verify_human = verify_human_factory(settings)
    human_dependency = Depends(verify_human)

    @router.get("/api/whatsapp/pairing", dependencies=[human_dependency])
    async def whatsapp_pairing() -> dict[str, Any]:
        # _pairing_payload defines the canonical shape; both the SSE
        # `pairing_changed` event and this REST endpoint emit it.
        return redact(_pairing_payload(await wabot.pairing_qr()))

    @router.get(
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

    @router.post("/api/whatsapp/pairing/restart", dependencies=[human_dependency])
    async def whatsapp_pairing_restart() -> dict[str, Any]:
        # Late import so monkeypatch.setattr(api, "restart_wabot_daemon", ...)
        # in tests reaches the same name these handlers resolve at call time.
        import wabot_agent.api as _api  # noqa: PLC0415
        try:
            await _api.restart_wabot_daemon(settings)
        except WabotRestartError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        pairing = await _api.wait_for_fresh_pairing(wabot.pairing_qr)
        payload = redact(_pairing_payload(pairing))
        pairing_state.last = payload
        hub.publish("pairing_changed", payload)
        return payload

    @router.post("/api/whatsapp/pairing/disconnect", dependencies=[human_dependency])
    async def whatsapp_pairing_disconnect() -> dict[str, Any]:
        # Late import so monkeypatch.setattr(api, "restart_wabot_daemon", ...)
        # in tests reaches the same name these handlers resolve at call time.
        import wabot_agent.api as _api  # noqa: PLC0415
        try:
            backups = _api.rotate_wabot_store_files(settings)
            await _api.restart_wabot_daemon(settings)
        except (OSError, WabotRestartError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        pairing = await _api.wait_for_fresh_pairing(wabot.pairing_qr)
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
