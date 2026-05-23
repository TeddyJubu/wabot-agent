"""Pydantic schemas for /api/composio routes (Phase 5)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ComposioStatus(BaseModel):
    enabled: bool
    api_key_present: bool
    user_id: str | None
    last_error: str | None


class ComposioApiKeyRequest(BaseModel):
    api_key: str = Field(
        min_length=8,
        max_length=200,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class ComposioApp(BaseModel):
    slug: str
    name: str
    description: str | None
    logo_url: str | None
    categories: list[str]
    auth_schemes: list[str]


class ComposioConnection(BaseModel):
    id: int
    app_slug: str
    display_name: str
    status: str
    user_id: str | None
    last_checked_at: str | None
    metadata: dict[str, Any] | None


class ComposioConnectionCreateRequest(BaseModel):
    app_slug: str
    user_id: str | None = None


class ComposioConnectionCreateResponse(ComposioConnection):
    redirect_url: str
