"""Metrics API routes — Phase 6.

5 read-only endpoints under /api/metrics, all requiring operator-token auth.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ...auth import verify_human_factory
from ...metrics_service import (
    get_costs,
    get_health,
    get_overview,
    get_runs_series,
    get_top_tools,
)
from ..deps import AppDeps
from ..metrics_schemas import (
    CostsResponse,
    HealthResponse,
    OverviewResponse,
    RunsSeriesResponse,
    ToolsResponse,
)

_VALID_WINDOWS = {"1h", "24h", "7d", "30d"}
_DEFAULT_BUCKET: dict[str, str] = {
    "1h": "minute",
    "24h": "hour",
    "7d": "day",
    "30d": "day",
}


def register_metrics_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    memory = deps.memory
    human_dependency = Depends(verify_human_factory(settings))

    # ------------------------------------------------------------------
    # GET /api/metrics/overview
    # ------------------------------------------------------------------

    @router.get(
        "/api/metrics/overview",
        response_model=OverviewResponse,
        dependencies=[human_dependency],
        tags=["metrics"],
    )
    async def metrics_overview_route() -> dict:
        return get_overview(memory, settings)

    # ------------------------------------------------------------------
    # GET /api/metrics/runs
    # ------------------------------------------------------------------

    @router.get(
        "/api/metrics/runs",
        response_model=RunsSeriesResponse,
        dependencies=[human_dependency],
        tags=["metrics"],
    )
    async def metrics_runs_route(
        window: str = Query(default="24h"),
        bucket: str = Query(default=""),
    ) -> dict:
        if window not in _VALID_WINDOWS:
            window = "24h"
        if bucket not in {"minute", "hour", "day", ""}:
            bucket = ""
        if not bucket:
            bucket = _DEFAULT_BUCKET.get(window, "hour")
        return get_runs_series(memory, window=window, bucket=bucket)

    # ------------------------------------------------------------------
    # GET /api/metrics/tools
    # ------------------------------------------------------------------

    @router.get(
        "/api/metrics/tools",
        response_model=ToolsResponse,
        dependencies=[human_dependency],
        tags=["metrics"],
    )
    async def metrics_tools_route(
        window: str = Query(default="24h"),
        limit: int = Query(default=10, ge=1, le=100),
    ) -> dict:
        if window not in _VALID_WINDOWS:
            window = "24h"
        return get_top_tools(memory, window=window, limit=limit)

    # ------------------------------------------------------------------
    # GET /api/metrics/costs
    # ------------------------------------------------------------------

    @router.get(
        "/api/metrics/costs",
        response_model=CostsResponse,
        dependencies=[human_dependency],
        tags=["metrics"],
    )
    async def metrics_costs_route(
        window: str = Query(default="24h"),
    ) -> dict:
        if window not in _VALID_WINDOWS:
            window = "24h"
        return get_costs(memory, window=window)

    # ------------------------------------------------------------------
    # GET /api/metrics/health
    # ------------------------------------------------------------------

    @router.get(
        "/api/metrics/health",
        response_model=HealthResponse,
        dependencies=[human_dependency],
        tags=["metrics"],
    )
    async def metrics_health_route() -> dict:
        return get_health(memory, settings)
