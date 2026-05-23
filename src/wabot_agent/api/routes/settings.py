"""Settings routes — GET/PATCH /api/settings and the LLM/wabot test endpoints.

Carved out of api/__init__.py as part of MASTER ME-1 Part 4.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, Response

from ...auth import verify_human_factory
from ...providers import get_registry
from ...runtime_overrides import MUTABLE_FIELDS
from ..deps import AppDeps
from ..llm_tests import _settings_view, _test_llm_endpoint
from ..schemas import OpenAITestRequest, OpenRouterTestRequest, SettingsPatch


def register_settings_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    event_log = deps.event_log
    wabot = deps.wabot
    settings_service = deps.settings_service

    verify_human = verify_human_factory(settings)
    human_dependency = Depends(verify_human)

    @router.get("/api/settings", dependencies=[human_dependency])
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

    @router.patch("/api/settings", dependencies=[human_dependency])
    async def update_settings(patch: SettingsPatch) -> dict[str, Any]:
        # SR-1: all validation, persistence, and subscriber notification is
        # now owned by SettingsService.patch(). The route handler is ~5 lines.
        settings_service.patch(patch)
        event_log.write(
            "settings_updated",
            {"fields": sorted(
                k for k in patch.model_dump(exclude={"confirm_allow_all"}, exclude_none=True)
                if k in MUTABLE_FIELDS
            )},
        )
        return _settings_view(settings)

    # Test endpoints for providers that declare test_endpoint_path in the registry.
    # FastAPI requires static type annotations for request bodies, so these handlers
    # are kept as explicit named functions rather than dynamically generated routes.
    # The handlers look up the spec from the registry to delegate to the right
    # test_endpoint_handler — adding a new provider with a test endpoint requires
    # a registry entry + a new handler here + a TSX section in the SPA.

    @router.post("/api/settings/test/openai", dependencies=[human_dependency])
    async def test_openai(payload: OpenAITestRequest | None = None) -> dict[str, Any]:
        spec = get_registry()["openai"]
        assert spec.test_endpoint_handler is not None
        return await spec.test_endpoint_handler(settings, payload or OpenAITestRequest())

    @router.post("/api/settings/test/openrouter", dependencies=[human_dependency])
    async def test_openrouter(payload: OpenRouterTestRequest | None = None) -> dict[str, Any]:
        spec = get_registry()["openrouter"]
        assert spec.test_endpoint_handler is not None
        return await spec.test_endpoint_handler(settings, payload or OpenRouterTestRequest())

    @router.post("/api/settings/test/llm", dependencies=[human_dependency])
    async def test_llm() -> dict[str, Any]:
        return await _test_llm_endpoint(settings)

    @router.post("/api/settings/test/wabot", dependencies=[human_dependency])
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
