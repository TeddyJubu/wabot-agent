"""Health and readiness routes.

First module migrated under MASTER ME-1 Part 2 — proves the
register_routes(router, deps) seam works without app.state munging.
Subsequent route modules (pages, auth, chat, inbound, ...) follow the
same shape.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...auth import verify_human_factory
from ...llm_provider import active_model_id
from ...redaction import redact
from ..deps import AppDeps


def register_health_routes(router: APIRouter, deps: AppDeps) -> None:
    verify_human = verify_human_factory(deps.settings)
    human_dependency = Depends(verify_human)

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "service": "wabot-agent", "env": deps.settings.env}

    @router.get("/ready", dependencies=[human_dependency])
    async def ready() -> dict[str, Any]:
        wabot_health = await deps.wabot.health()
        return redact(
            {
                "ok": True,
                "live_model": deps.settings.live_model_enabled,
                "model_provider": deps.settings.model_provider,
                "model": (
                    active_model_id(deps.settings)
                    if deps.settings.live_model_enabled
                    else "offline"
                ),
                "send_policy": deps.settings.send_policy,
                "memory": deps.memory.stats(),
                "wabot": {
                    "reachable": wabot_health.reachable,
                    "logged_in": wabot_health.logged_in,
                    "connected": wabot_health.connected,
                    "ready": wabot_health.ready,
                    "detail": wabot_health.detail,
                },
            }
        )
