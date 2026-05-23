"""Pydantic v2 schemas for the agents and tools catalog API.

Phase 3a — kept in a dedicated file to avoid growing api/schemas.py further.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Agent inputs
# ---------------------------------------------------------------------------


class AgentCreate(BaseModel):
    slug: str
    display_name: str
    description: str | None = None
    instructions: str
    parent_slug: str | None = None
    handoff_filter: str | None = None


class AgentUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    instructions: str | None = None
    is_enabled: bool | None = None
    parent_slug: str | None = None
    handoff_filter: str | None = None


class AgentToolsUpdate(BaseModel):
    tool_ids: list[int]


class AgentSkillsUpdate(BaseModel):
    skill_ids: list[int]


class AgentTestRequest(BaseModel):
    prompt: str = Field(..., max_length=8192)


# ---------------------------------------------------------------------------
# Agent outputs
# ---------------------------------------------------------------------------


class AgentSummary(BaseModel):
    id: int
    slug: str
    display_name: str
    description: str | None
    is_builtin: bool
    is_enabled: bool
    parent_slug: str | None
    handoff_filter: str | None
    tool_count: int
    skill_count: int
    updated_at: str


class AgentDetail(AgentSummary):
    instructions: str
    tool_ids: list[int]
    skill_ids: list[int]


class AgentTestResponse(BaseModel):
    transcript: str
    tool_calls: list[dict]
    error: str | None


# ---------------------------------------------------------------------------
# Tool inputs/outputs
# ---------------------------------------------------------------------------


class ToolRow(BaseModel):
    id: int
    kind: str  # 'native' | 'mcp' | 'composio' | 'skill_action'
    source_ref: str
    name: str
    description: str | None
    is_enabled: bool
    is_assigned_to: list[str]  # slugs


class ToolsListResponse(BaseModel):
    native: list[ToolRow]
    mcp: list[ToolRow]
    composio: list[ToolRow]
    skill_action: list[ToolRow]


class ToolRefreshResponse(BaseModel):
    native_added: int
    composio_added: int
    mcp_added: int


class ToolToggleRequest(BaseModel):
    is_enabled: bool


__all__ = [
    "AgentCreate",
    "AgentDetail",
    "AgentSkillsUpdate",
    "AgentSummary",
    "AgentTestRequest",
    "AgentTestResponse",
    "AgentToolsUpdate",
    "AgentUpdate",
    "ToolRefreshResponse",
    "ToolRow",
    "ToolToggleRequest",
    "ToolsListResponse",
]
