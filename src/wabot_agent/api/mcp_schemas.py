"""Pydantic v2 schemas for the MCP admin API — Phase 4."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class McpServerRow(BaseModel):
    id: int
    name: str
    transport: str
    config_json: str
    is_enabled: bool | int
    health_status: str | None
    health_message: str | None
    last_checked_at: str | None


class McpServerCreate(BaseModel):
    name: str
    transport: Literal["stdio", "http"]
    config_json: dict


class McpServerUpdate(BaseModel):
    name: str | None = None
    transport: Literal["stdio", "http"] | None = None
    config_json: dict | None = None
    is_enabled: bool | None = None


class McpServerCheckResponse(BaseModel):
    health_status: str | None
    health_message: str | None
    last_checked_at: str | None
    tool_count: int


class McpRegistryEntry(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    source: str  # 'curated' | 'composio'
    tags: list[str]
    transport_hint: str


class McpInstallRegistryRequest(BaseModel):
    registry_id: str


__all__ = [
    "McpInstallRegistryRequest",
    "McpRegistryEntry",
    "McpServerCheckResponse",
    "McpServerCreate",
    "McpServerRow",
    "McpServerUpdate",
]
