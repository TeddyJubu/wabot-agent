from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from agents.mcp import MCPServerManager, MCPServerStdio, MCPServerStreamableHttp


def load_mcp_servers(config_path: Path | None) -> list[Any]:
    if not config_path or not config_path.exists():
        return []
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    servers: list[Any] = []
    for entry in raw.get("servers", []):
        if not entry.get("enabled", False):
            continue
        transport = entry.get("transport", "stdio")
        name = entry.get("name")
        if transport == "stdio":
            params: dict[str, Any] = {
                "command": entry["command"],
                "args": entry.get("args", []),
            }
            if entry.get("cwd"):
                params["cwd"] = entry["cwd"]
            if entry.get("env"):
                params["env"] = entry["env"]
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
                params["headers"] = entry["headers"]
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
async def connected_mcp_servers(config_path: Path | None) -> AsyncIterator[list[Any]]:
    servers = load_mcp_servers(config_path)
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
