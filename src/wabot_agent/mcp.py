from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from agents.mcp import MCPServerManager, MCPServerStdio, MCPServerStreamableHttp

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _resolve_env_value(value: str) -> str:
    """Expand ${VAR} placeholders from the process environment."""

    def repl(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return _ENV_REF.sub(repl, value)


def _resolve_env_mapping(mapping: dict[str, Any] | None) -> dict[str, str] | None:
    if not mapping:
        return None
    resolved: dict[str, str] = {}
    for key, raw in mapping.items():
        if not isinstance(raw, str):
            raise ValueError(
                f"MCP header/env values must be strings, got {type(raw).__name__} for {key!r}"
            )
        resolved[key] = _resolve_env_value(raw)
    return resolved


def load_mcp_servers(
    config_path: Path | None,
    *,
    skip_names: frozenset[str] | None = None,
) -> list[Any]:
    if not config_path or not config_path.exists():
        return []
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    servers: list[Any] = []
    skipped = skip_names or frozenset()
    for entry in raw.get("servers", []):
        if not entry.get("enabled", False):
            continue
        transport = entry.get("transport", "stdio")
        name = entry.get("name")
        if name in skipped:
            continue
        if transport == "stdio":
            params: dict[str, Any] = {
                "command": entry["command"],
                "args": entry.get("args", []),
            }
            if entry.get("cwd"):
                params["cwd"] = entry["cwd"]
            if entry.get("env"):
                params["env"] = _resolve_env_mapping(entry["env"])
            servers.append(
                MCPServerStdio(
                    params=params,
                    name=name,
                    cache_tools_list=True,
                    require_approval=entry.get("require_approval", "always"),
                )
            )
        elif transport == "streamable_http":
            params = {"url": entry["url"]}
            if entry.get("headers"):
                params["headers"] = _resolve_env_mapping(entry["headers"])
            servers.append(
                MCPServerStreamableHttp(
                    params=params,
                    name=name,
                    cache_tools_list=True,
                    require_approval=entry.get("require_approval", "always"),
                )
            )
        else:
            raise ValueError(f"Unsupported MCP transport: {transport}")
    return servers


@asynccontextmanager
async def connected_mcp_servers(
    config_path: Path | None,
    *,
    skip_names: frozenset[str] | None = None,
) -> AsyncIterator[list[Any]]:
    servers = load_mcp_servers(config_path, skip_names=skip_names)
    if not servers:
        yield []
        return
    manager = MCPServerManager(
        servers,
        strict=False,
        drop_failed_servers=True,
        connect_in_parallel=True,
    )
    async with manager:
        yield manager.active_servers
