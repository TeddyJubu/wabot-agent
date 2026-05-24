"""Pydantic response models for /api/metrics/* endpoints (Phase 6)."""
from __future__ import annotations

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


class IntegrationsHealth(BaseModel):
    ok: int
    error: int
    unknown: int


class OverviewResponse(BaseModel):
    messages_today: int
    messages_today_delta_pct: float | None
    runs_today: int
    runs_today_delta_pct: float | None
    avg_latency_ms_24h: float | None
    cost_usd_24h: float
    cost_usd_24h_delta_pct: float | None
    integrations_health: IntegrationsHealth
    queue_depth: int


# ---------------------------------------------------------------------------
# Runs series
# ---------------------------------------------------------------------------


class RunsBucket(BaseModel):
    timestamp: str
    count: int
    by_agent: dict[str, int]


class RunsSeriesResponse(BaseModel):
    window: str
    bucket: str
    series: list[RunsBucket]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class ToolUsageItem(BaseModel):
    tool_name: str
    invocations: int
    avg_latency_ms: float | None
    errors: int


class ToolsResponse(BaseModel):
    window: str
    items: list[ToolUsageItem]


# ---------------------------------------------------------------------------
# Costs
# ---------------------------------------------------------------------------


class CostByDay(BaseModel):
    date: str
    usd: float


class CostByProvider(BaseModel):
    provider: str
    usd: float
    model_breakdown: dict[str, float]


class CostsResponse(BaseModel):
    window: str
    total_usd: float
    by_day: list[CostByDay]
    by_provider: list[CostByProvider]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class WabotDaemonHealth(BaseModel):
    status: str
    message: str | None
    last_checked_at: str | None


class McpServerHealth(BaseModel):
    id: int
    name: str
    status: str
    message: str | None
    last_checked_at: str | None


class ComposioHealth(BaseModel):
    status: str
    connections_count: int
    last_error: str | None


class HealthResponse(BaseModel):
    wabot_daemon: WabotDaemonHealth
    mcp_servers: list[McpServerHealth]
    composio: ComposioHealth
