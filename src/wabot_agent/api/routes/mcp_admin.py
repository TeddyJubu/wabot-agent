"""MCP admin endpoints — Phase 4.

All endpoints require the operator token.
Prefix: /api/mcp
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ...auth import verify_human_factory
from ...mcp_service import (
    check_server,
    create_server,
    delete_server,
    install_from_registry,
    list_servers,
    registry_search,
    update_server,
)
from ..deps import AppDeps
from ..mcp_schemas import (
    McpInstallRegistryRequest,
    McpRegistryEntry,
    McpServerCheckResponse,
    McpServerCreate,
    McpServerRow,
    McpServerUpdate,
)


def register_mcp_admin_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    memory = deps.memory
    human_dependency = Depends(verify_human_factory(settings))

    # -----------------------------------------------------------------------
    # GET /api/mcp/servers
    # -----------------------------------------------------------------------

    @router.get(
        "/api/mcp/servers",
        response_model=list[McpServerRow],
        dependencies=[human_dependency],
        tags=["mcp"],
    )
    async def list_mcp_servers_route() -> list[dict]:
        return list_servers(memory)

    # -----------------------------------------------------------------------
    # POST /api/mcp/servers
    # -----------------------------------------------------------------------

    @router.post(
        "/api/mcp/servers",
        response_model=McpServerRow,
        status_code=201,
        dependencies=[human_dependency],
        tags=["mcp"],
    )
    async def create_mcp_server_route(body: McpServerCreate) -> dict:
        try:
            return create_server(memory, body.model_dump())
        except ValueError as exc:
            msg = str(exc)
            if "already exists" in msg:
                raise HTTPException(status_code=409, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc

    # -----------------------------------------------------------------------
    # PATCH /api/mcp/servers/{id}
    # -----------------------------------------------------------------------

    @router.patch(
        "/api/mcp/servers/{server_id}",
        response_model=McpServerRow,
        dependencies=[human_dependency],
        tags=["mcp"],
    )
    async def update_mcp_server_route(server_id: int, body: McpServerUpdate) -> dict:
        try:
            result = update_server(
                memory, server_id, body.model_dump(exclude_unset=True)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(
                status_code=404, detail=f"MCP server id={server_id} not found"
            )
        return result

    # -----------------------------------------------------------------------
    # DELETE /api/mcp/servers/{id}
    # -----------------------------------------------------------------------

    @router.delete(
        "/api/mcp/servers/{server_id}",
        status_code=204,
        dependencies=[human_dependency],
        tags=["mcp"],
    )
    async def delete_mcp_server_route(server_id: int) -> Response:
        result = delete_server(memory, server_id)
        if not result:
            raise HTTPException(
                status_code=404, detail=f"MCP server id={server_id} not found"
            )
        return Response(status_code=204)

    # -----------------------------------------------------------------------
    # POST /api/mcp/servers/{id}/check
    # -----------------------------------------------------------------------

    @router.post(
        "/api/mcp/servers/{server_id}/check",
        response_model=McpServerCheckResponse,
        dependencies=[human_dependency],
        tags=["mcp"],
    )
    async def check_mcp_server_route(server_id: int) -> dict:
        result = await check_server(memory, settings, server_id)
        if not result:
            raise HTTPException(
                status_code=404, detail=f"MCP server id={server_id} not found"
            )
        return {
            "health_status": result.get("health_status"),
            "health_message": result.get("health_message"),
            "last_checked_at": result.get("last_checked_at"),
            "tool_count": result.get("tool_count", 0),
        }

    # -----------------------------------------------------------------------
    # GET /api/mcp/registry/search
    # -----------------------------------------------------------------------

    @router.get(
        "/api/mcp/registry/search",
        response_model=list[McpRegistryEntry],
        dependencies=[human_dependency],
        tags=["mcp"],
    )
    async def search_mcp_registry_route(
        q: str = Query(default="", description="Search query"),
    ) -> list[dict]:
        results = registry_search(q)
        # Ensure required fields are present with defaults.
        normalised = []
        for entry in results:
            normalised.append({
                "id": entry.get("id", ""),
                "slug": entry.get("slug", ""),
                "name": entry.get("name", ""),
                "description": entry.get("description", ""),
                "source": entry.get("source", "curated"),
                "tags": entry.get("tags", []),
                "transport_hint": entry.get("transport_hint", "stdio"),
            })
        return normalised

    # -----------------------------------------------------------------------
    # POST /api/mcp/registry/install
    # -----------------------------------------------------------------------

    @router.post(
        "/api/mcp/registry/install",
        response_model=McpServerRow,
        status_code=201,
        dependencies=[human_dependency],
        tags=["mcp"],
    )
    async def install_mcp_registry_route(body: McpInstallRegistryRequest) -> dict:
        try:
            return install_from_registry(memory, body.registry_id)
        except ValueError as exc:
            msg = str(exc)
            if "already exists" in msg:
                raise HTTPException(status_code=409, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
