"""Pydantic v2 schemas for the skills admin API — Phase 4."""
from __future__ import annotations

from pydantic import BaseModel


class SkillRow(BaseModel):
    id: int
    slug: str
    display_name: str
    description: str | None
    source: str
    version: str | None
    install_path: str
    origin_url: str | None
    installed_at: str
    is_enabled: bool | int


class SkillInstallRegistryRequest(BaseModel):
    registry_id: str


class SkillScanResponse(BaseModel):
    added: int
    removed: int


class SkillRegistryEntry(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    version: str
    source_url: str
    tags: list[str]


__all__ = [
    "SkillInstallRegistryRequest",
    "SkillRegistryEntry",
    "SkillRow",
    "SkillScanResponse",
]
