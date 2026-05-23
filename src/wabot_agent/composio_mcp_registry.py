"""Composio MCP registry adapter.

Fetches MCP server entries from Composio's app registry endpoint.

This module is intentionally thin so tests can monkeypatch
``fetch_composio_mcp_index`` without touching network or import machinery.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# The URL can be monkeypatched by tests or overridden via the caller.
COMPOSIO_MCP_INDEX_URL = "https://mcp.composio.dev/v1/apps"


def fetch_composio_mcp_index(
    api_key: str,
    *,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Return a list of MCP server entries from Composio's registry.

    Pluggable: tests monkeypatch this function to return a fake list.

    Each returned dict has at minimum the keys:
        id, slug, name, description, transport_hint, tags

    On any failure returns [] and logs a warning so the caller's registry
    search degrades gracefully rather than raising.
    """
    try:
        response = httpx.get(
            COMPOSIO_MCP_INDEX_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        response.raise_for_status()
        data: Any = response.json()
        if isinstance(data, list):
            return data
        # Some APIs wrap in {"apps": [...]}
        if isinstance(data, dict):
            for key in ("apps", "servers", "items", "data", "results"):
                if isinstance(data.get(key), list):
                    return data[key]
        logger.warning("composio_mcp_registry: unexpected response shape")
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("composio_mcp_registry: fetch failed: %s", exc)
        return []
