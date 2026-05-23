"""Codex login and credential management routes.

Carved out of api/__init__.py as part of MASTER ME-1 Part 4.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...auth import verify_human_factory
from ...codex_auth import disconnect_codex_credentials
from ...codex_device_login import (
    cancel_device_login,
    device_login_view,
    poll_device_login,
    start_device_login,
)
from ..deps import AppDeps


def register_codex_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    event_log = deps.event_log

    verify_human = verify_human_factory(settings)
    human_dependency = Depends(verify_human)

    @router.get("/api/codex/login", dependencies=[human_dependency])
    async def codex_login_status() -> dict[str, Any]:
        await poll_device_login(settings)
        return device_login_view(settings)

    @router.post("/api/codex/login/device", dependencies=[human_dependency])
    async def codex_login_device_start() -> dict[str, Any]:
        await start_device_login(settings)
        await poll_device_login(settings, wait_seconds=8)
        return device_login_view(settings)

    @router.post("/api/codex/login/device/cancel", dependencies=[human_dependency])
    async def codex_login_device_cancel() -> dict[str, Any]:
        await cancel_device_login()
        return device_login_view(settings)

    @router.post("/api/codex/login/disconnect", dependencies=[human_dependency])
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
