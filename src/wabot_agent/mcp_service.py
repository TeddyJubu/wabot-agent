"""mcp_service — CRUD + health-check logic for the mcp_servers table.

Phase 4 service layer.  All functions take a MemoryStore as their first
argument, mirroring agents_service.py / skills_service.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import UTC
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import Settings
    from .memory import MemoryStore

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_VALID_TRANSPORTS = {"stdio", "http"}

# Simple in-process Composio cache: (timestamp, entries)
_composio_cache: tuple[float, list[dict]] | None = None
_COMPOSIO_CACHE_TTL = 300.0  # 5 minutes

# ---------------------------------------------------------------------------
# Secret masking
# ---------------------------------------------------------------------------

_SECRET_KEY_PATTERNS = (
    "token", "key", "secret", "password", "auth", "bearer", "credential", "api_key"
)


def _mask_recursive(obj: Any) -> None:
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            if any(p in k.lower() for p in _SECRET_KEY_PATTERNS):
                if isinstance(obj[k], str) and obj[k]:
                    obj[k] = "•" * 8 + "(masked)"
                elif isinstance(obj[k], dict):
                    for sk in obj[k]:
                        if isinstance(obj[k][sk], str) and obj[k][sk]:
                            obj[k][sk] = "•" * 8 + "(masked)"
            elif isinstance(obj[k], (dict, list)):
                _mask_recursive(obj[k])
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                _mask_recursive(item)


def _mask_config_json(config_json_str: str) -> str:
    """Mask values for keys that look secret in env/headers dicts. Returns JSON string."""
    try:
        data = json.loads(config_json_str)
    except (ValueError, TypeError):
        return config_json_str
    _mask_recursive(data)
    return json.dumps(data)


def _mask_row(row: dict) -> dict:
    """Return a copy of the row with config_json secrets masked."""
    if "config_json" in row and isinstance(row["config_json"], str):
        row = dict(row)
        row["config_json"] = _mask_config_json(row["config_json"])
    return row


def _row_to_dict(row: Any) -> dict:
    try:
        return dict(row)
    except (TypeError, ValueError):
        raise


def _registry_path():
    from pathlib import Path
    return Path(__file__).resolve().parents[2] / "data" / "mcp_registry.json"


# ---------------------------------------------------------------------------
# list_servers
# ---------------------------------------------------------------------------


def list_servers(store: MemoryStore) -> list[dict]:
    with store.connect() as conn:
        rows = conn.execute("select * from mcp_servers order by id").fetchall()
        return [_mask_row(_row_to_dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# create_server
# ---------------------------------------------------------------------------


def create_server(store: MemoryStore, payload: dict) -> dict:
    """Insert a new MCP server row.

    Validates:
      - name matches ^[a-z][a-z0-9_-]{1,63}$
      - transport in {'stdio', 'http'}
      - config_json is valid JSON (accepts dict or str)
      - stdio requires 'command' key; http requires 'url' key
    """
    name: str = payload.get("name", "")
    transport: str = payload.get("transport", "")
    config_json_raw = payload.get("config_json", {})

    if not _NAME_RE.match(name):
        raise ValueError(
            f"name {name!r} is invalid; must match ^[a-z][a-z0-9_-]{{1,63}}$"
        )
    if transport not in _VALID_TRANSPORTS:
        raise ValueError(
            f"transport {transport!r} must be one of {sorted(_VALID_TRANSPORTS)}"
        )

    # Normalise config_json to a dict for validation, then serialise.
    if isinstance(config_json_raw, str):
        try:
            config_dict = json.loads(config_json_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"config_json is not valid JSON: {exc}") from exc
    elif isinstance(config_json_raw, dict):
        config_dict = config_json_raw
    else:
        raise ValueError("config_json must be a JSON object (dict or string)")

    if transport == "stdio" and "command" not in config_dict:
        raise ValueError("config_json for stdio transport must include 'command'")
    if transport == "http" and "url" not in config_dict:
        raise ValueError("config_json for http transport must include 'url'")

    config_json_str = json.dumps(config_dict)

    with store.connect() as conn:
        existing = conn.execute(
            "select id from mcp_servers where name = ?", (name,)
        ).fetchone()
        if existing is not None:
            raise ValueError(f"MCP server name {name!r} already exists")

        conn.execute(
            """
            insert into mcp_servers (name, transport, config_json, is_enabled, health_status)
            values (?, ?, ?, 1, 'unknown')
            """,
            (name, transport, config_json_str),
        )
        conn.commit()
        row = conn.execute(
            "select * from mcp_servers where name = ?", (name,)
        ).fetchone()
        return _mask_row(_row_to_dict(row))


# ---------------------------------------------------------------------------
# update_server
# ---------------------------------------------------------------------------


def update_server(
    store: MemoryStore,
    server_id: int,
    patch: dict,
) -> dict | None:
    with store.connect() as conn:
        row = conn.execute(
            "select * from mcp_servers where id = ?", (server_id,)
        ).fetchone()
        if row is None:
            return None

        current = _mask_row(_row_to_dict(row))
        updates: dict[str, Any] = {}

        if "name" in patch:
            name = patch["name"]
            if not _NAME_RE.match(name):
                raise ValueError(f"name {name!r} is invalid")
            updates["name"] = name

        if "transport" in patch:
            transport = patch["transport"]
            if transport not in _VALID_TRANSPORTS:
                raise ValueError(f"transport {transport!r} is invalid")
            updates["transport"] = transport

        if "config_json" in patch:
            raw = patch["config_json"]
            if isinstance(raw, dict):
                updates["config_json"] = json.dumps(raw)
            elif isinstance(raw, str):
                try:
                    json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"config_json is not valid JSON: {exc}") from exc
                updates["config_json"] = raw
            else:
                raise ValueError("config_json must be a JSON object (dict or string)")

        if "is_enabled" in patch:
            updates["is_enabled"] = 1 if patch["is_enabled"] else 0

        if not updates:
            return current

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [server_id]
        conn.execute(
            f"update mcp_servers set {set_clause} where id = ?",  # noqa: S608
            values,
        )
        conn.commit()
        row = conn.execute(
            "select * from mcp_servers where id = ?", (server_id,)
        ).fetchone()
        return _mask_row(_row_to_dict(row))


# ---------------------------------------------------------------------------
# delete_server
# ---------------------------------------------------------------------------


def delete_server(store: MemoryStore, server_id: int) -> bool:
    with store.connect() as conn:
        row = conn.execute(
            "select id from mcp_servers where id = ?", (server_id,)
        ).fetchone()
        if row is None:
            return False
        conn.execute("delete from mcp_servers where id = ?", (server_id,))
        conn.commit()
        return True


# ---------------------------------------------------------------------------
# check_server
# ---------------------------------------------------------------------------


async def check_server(
    store: MemoryStore,
    settings: Settings,
    server_id: int,
) -> dict:
    """Open the MCP server, list tools, and update the health columns.

    Wrapped in a 10-second asyncio.wait_for to avoid hanging on bad configs.
    """
    with store.connect() as conn:
        row = conn.execute(
            "select * from mcp_servers where id = ?", (server_id,)
        ).fetchone()
        if row is None:
            return {}

    server_row = _row_to_dict(row)
    name = server_row["name"]
    transport = server_row["transport"]

    try:
        config_dict = json.loads(server_row["config_json"])
    except json.JSONDecodeError:
        config_dict = {}

    # Build the one-shot config for connected_mcp_servers.
    # We create a temporary JSON file pointing only at this server.

    # Translate DB transport values to the mcp.py format.
    # Our DB uses 'http'; mcp.py uses 'streamable_http'.
    if transport == "http":
        mcp_transport = "streamable_http"
    else:
        mcp_transport = transport

    now_iso = _now_iso()
    health_status = "unknown"
    health_message = ""
    tool_count = 0

    try:
        async def _probe() -> list[str]:
            from agents.mcp import MCPServerManager, MCPServerStdio, MCPServerStreamableHttp

            if mcp_transport == "stdio":
                params: dict[str, Any] = {
                    "command": config_dict.get("command", ""),
                    "args": config_dict.get("args", []),
                }
                if config_dict.get("env"):
                    params["env"] = config_dict["env"]
                server = MCPServerStdio(
                    params=params,
                    name=name,
                    cache_tools_list=False,
                    require_approval="never",
                )
            else:
                params = {"url": config_dict.get("url", "")}
                if config_dict.get("headers"):
                    params["headers"] = config_dict["headers"]
                server = MCPServerStreamableHttp(
                    params=params,
                    name=name,
                    cache_tools_list=False,
                    require_approval="never",
                )

            manager = MCPServerManager(
                [server],
                strict=False,
                drop_failed_servers=False,
                connect_in_parallel=False,
            )
            async with manager:
                active = manager.active_servers
                if not active:
                    raise RuntimeError("server failed to connect")
                tools = await active[0].list_tools()
                return [t.name for t in tools]

        tool_names = await asyncio.wait_for(_probe(), timeout=10.0)
        tool_count = len(tool_names)
        health_status = "ok"
        health_message = f"{tool_count} tools"

    except TimeoutError:
        health_status = "error"
        health_message = "health check timed out after 10 seconds"
    except Exception as exc:  # noqa: BLE001
        health_status = "error"
        health_message = str(exc)[:500]

    with store.connect() as conn:
        conn.execute(
            """
            update mcp_servers
               set health_status   = ?,
                   health_message  = ?,
                   last_checked_at = ?
             where id = ?
            """,
            (health_status, health_message, now_iso, server_id),
        )
        conn.commit()
        row = conn.execute(
            "select * from mcp_servers where id = ?", (server_id,)
        ).fetchone()

    result = _mask_row(_row_to_dict(row))
    result["tool_count"] = tool_count
    return result


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# registry_search
# ---------------------------------------------------------------------------


def registry_search(
    query: str,
    *,
    include_composio: bool = True,
) -> list[dict]:
    """Return MCP server entries from the curated registry + optionally Composio.

    Each entry is tagged with 'source': 'curated' | 'composio'.
    Results are de-duplicated by id.
    """
    # 1) Local curated entries.
    registry_file = _registry_path()
    try:
        raw_entries: list[dict] = json.loads(
            registry_file.read_text(encoding="utf-8")
        )
    except Exception as exc:
        logger.warning("mcp_service: could not load registry: %s", exc)
        raw_entries = []

    for entry in raw_entries:
        entry.setdefault("source", "curated")

    # 2) Composio adapter.
    composio_entries: list[dict] = []
    if include_composio:
        composio_api_key = os.environ.get("COMPOSIO_API_KEY", "")
        if composio_api_key:
            composio_entries = _fetch_composio_cached(composio_api_key)

    # Merge + de-duplicate by id.
    seen_ids: set[str] = set()
    results: list[dict] = []
    for entry in raw_entries + composio_entries:
        eid = entry.get("id", "")
        if eid in seen_ids:
            continue
        seen_ids.add(eid)
        results.append(entry)

    # Filter by query.
    if not query:
        return results

    q = query.lower()
    filtered = []
    for entry in results:
        haystack = " ".join([
            entry.get("name", ""),
            entry.get("description", ""),
            " ".join(entry.get("tags", [])),
        ]).lower()
        if q in haystack:
            filtered.append(entry)
    return filtered


def _fetch_composio_cached(api_key: str) -> list[dict]:
    global _composio_cache
    now = time.monotonic()
    if _composio_cache is not None:
        ts, entries = _composio_cache
        if now - ts < _COMPOSIO_CACHE_TTL:
            return entries

    from .composio_mcp_registry import fetch_composio_mcp_index

    raw = fetch_composio_mcp_index(api_key)
    entries = []
    for item in raw:
        entry = {
            "id": item.get("id", item.get("slug", "")),
            "slug": item.get("slug", ""),
            "name": item.get("name", item.get("slug", "")),
            "description": item.get("description", ""),
            "source": "composio",
            "tags": item.get("tags", []),
            "transport_hint": item.get("transport_hint", "http"),
        }
        entries.append(entry)

    _composio_cache = (now, entries)
    return entries


# ---------------------------------------------------------------------------
# install_from_registry
# ---------------------------------------------------------------------------


def install_from_registry(store: MemoryStore, registry_id: str) -> dict:
    """Look up registry_id in the merged list and insert a mcp_servers row."""
    entries = registry_search("", include_composio=False)
    # Also include composio if key set
    composio_api_key = os.environ.get("COMPOSIO_API_KEY", "")
    if composio_api_key:
        composio_entries = _fetch_composio_cached(composio_api_key)
        seen = {e["id"] for e in entries}
        for e in composio_entries:
            if e["id"] not in seen:
                entries.append(e)

    entry = next((e for e in entries if e["id"] == registry_id), None)
    if entry is None:
        raise ValueError(f"MCP registry entry {registry_id!r} not found")

    slug = entry.get("slug") or entry.get("name", registry_id).lower().replace(" ", "-")
    transport_hint = entry.get("transport_hint", "stdio")
    # Map to our DB values.
    if transport_hint in ("streamable_http", "http"):
        transport = "http"
    else:
        transport = "stdio"

    # Build a minimal config_json.
    if transport == "http":
        config = {"url": entry.get("source_url", "")}
    else:
        config = {"command": slug, "args": []}

    payload = {
        "name": slug,
        "transport": transport,
        "config_json": config,
    }
    return create_server(store, payload)
