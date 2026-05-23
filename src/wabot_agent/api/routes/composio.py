"""Composio API routes — Phase 5.

7 endpoints under /api/composio, all requiring operator-token auth.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from ...auth import verify_human_factory
from ...composio_service import (
    create_connection,
    delete_connection,
    get_status,
    list_apps,
    list_connections,
    refresh_connection,
    set_api_key,
)
from ..composio_schemas import (
    ComposioApiKeyRequest,
    ComposioApp,
    ComposioConnection,
    ComposioConnectionCreateRequest,
    ComposioConnectionCreateResponse,
    ComposioStatus,
)
from ..deps import AppDeps


def register_composio_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    memory = deps.memory
    human_dependency = Depends(verify_human_factory(settings))

    # ------------------------------------------------------------------
    # GET /api/composio/status
    # ------------------------------------------------------------------

    @router.get(
        "/api/composio/status",
        response_model=ComposioStatus,
        dependencies=[human_dependency],
        tags=["composio"],
    )
    async def composio_status_route() -> dict:
        return get_status(settings)

    # ------------------------------------------------------------------
    # POST /api/composio/api-key
    # ------------------------------------------------------------------

    @router.post(
        "/api/composio/api-key",
        response_model=ComposioStatus,
        dependencies=[human_dependency],
        tags=["composio"],
    )
    async def composio_set_api_key_route(body: ComposioApiKeyRequest) -> dict:
        try:
            import composio  # noqa: F401
        except ImportError as exc:
            raise HTTPException(
                status_code=503, detail=f"composio package not installed: {exc}"
            ) from exc
        return set_api_key(settings, body.api_key)

    # ------------------------------------------------------------------
    # GET /api/composio/apps
    # ------------------------------------------------------------------

    @router.get(
        "/api/composio/apps",
        response_model=list[ComposioApp],
        dependencies=[human_dependency],
        tags=["composio"],
    )
    async def composio_list_apps_route() -> list[dict]:
        if not settings.composio_api_key:
            raise HTTPException(status_code=503, detail="Composio not enabled: no API key set")
        try:
            return list_apps(settings)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Upstream Composio call failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # GET /api/composio/connections
    # ------------------------------------------------------------------

    @router.get(
        "/api/composio/connections",
        response_model=list[ComposioConnection],
        dependencies=[human_dependency],
        tags=["composio"],
    )
    async def composio_list_connections_route() -> list[dict]:
        return list_connections(memory)

    # ------------------------------------------------------------------
    # POST /api/composio/connections
    # ------------------------------------------------------------------

    @router.post(
        "/api/composio/connections",
        response_model=ComposioConnectionCreateResponse,
        status_code=201,
        dependencies=[human_dependency],
        tags=["composio"],
    )
    async def composio_create_connection_route(
        body: ComposioConnectionCreateRequest,
    ) -> dict:
        if not settings.composio_api_key:
            raise HTTPException(status_code=503, detail="Composio not enabled: no API key set")
        try:
            return create_connection(memory, settings, body.app_slug, body.user_id)
        except ValueError as exc:
            if "already_connected" in str(exc):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Connection for {body.app_slug!r} already exists"
                        " with status 'connected'"
                    ),
                ) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Upstream Composio call failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # POST /api/composio/connections/{id}/refresh
    # ------------------------------------------------------------------

    @router.post(
        "/api/composio/connections/{conn_id}/refresh",
        response_model=ComposioConnection,
        dependencies=[human_dependency],
        tags=["composio"],
    )
    async def composio_refresh_connection_route(conn_id: int) -> dict:
        result = refresh_connection(memory, settings, conn_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Connection {conn_id} not found")
        return result

    # ------------------------------------------------------------------
    # DELETE /api/composio/connections/{id}
    # ------------------------------------------------------------------

    @router.delete(
        "/api/composio/connections/{conn_id}",
        status_code=204,
        dependencies=[human_dependency],
        tags=["composio"],
    )
    async def composio_delete_connection_route(conn_id: int) -> Response:
        found = delete_connection(memory, settings, conn_id)
        if not found:
            raise HTTPException(status_code=404, detail=f"Connection {conn_id} not found")
        return Response(status_code=204)
