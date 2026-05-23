"""Tools catalog API — Phase 3a.

3 endpoints under /api/tools.  All require the operator token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...auth import verify_human_factory
from ...tools_service import list_tools, refresh_catalog, toggle_tool
from ..agent_schemas import ToolRefreshResponse, ToolsListResponse, ToolToggleRequest
from ..deps import AppDeps


def register_tools_catalog_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    memory = deps.memory
    human_dependency = Depends(verify_human_factory(settings))

    # -----------------------------------------------------------------------
    # GET /api/tools — list all tools grouped by kind
    # -----------------------------------------------------------------------

    @router.get(
        "/api/tools",
        response_model=ToolsListResponse,
        dependencies=[human_dependency],
        tags=["tools"],
    )
    async def list_tools_route() -> dict:
        return list_tools(memory)

    # -----------------------------------------------------------------------
    # POST /api/tools/refresh — re-seed the catalog
    # -----------------------------------------------------------------------

    @router.post(
        "/api/tools/refresh",
        response_model=ToolRefreshResponse,
        dependencies=[human_dependency],
        tags=["tools"],
    )
    async def refresh_catalog_route() -> dict:
        return refresh_catalog(memory, settings)

    # -----------------------------------------------------------------------
    # PATCH /api/tools/{id} — toggle is_enabled
    # -----------------------------------------------------------------------

    @router.patch(
        "/api/tools/{tool_id}",
        dependencies=[human_dependency],
        tags=["tools"],
    )
    async def toggle_tool_route(tool_id: int, body: ToolToggleRequest) -> dict:
        result = toggle_tool(memory, tool_id, body.is_enabled)
        if result is None:
            raise HTTPException(status_code=404, detail=f"tool id={tool_id} not found")
        return result
