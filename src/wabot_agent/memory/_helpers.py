"""Shared helpers for the memory package (kept here to avoid circular imports)."""
from __future__ import annotations

from datetime import UTC, datetime


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
