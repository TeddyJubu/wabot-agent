"""composio_service — business logic for the /api/composio routes (Phase 5).

All functions that need Composio SDK calls go through thin adapters
(_list_apps_upstream, _initiate_connection_upstream, etc.) so tests can
monkeypatch just those without touching the SDK.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import Settings
    from .memory import MemoryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simple time-based in-process cache for apps list (5-minute TTL)
# ---------------------------------------------------------------------------
_APPS_CACHE_TTL_SEC = 300.0
_apps_cache: dict[str, Any] = {}  # {"data": list, "cached_at": float}


def _invalidate_apps_cache() -> None:
    _apps_cache.clear()


# ---------------------------------------------------------------------------
# Thin upstream adapters — monkeypatch these in tests
# ---------------------------------------------------------------------------


def _list_apps_upstream(settings: Settings) -> list[dict]:
    """Call Composio SDK to list available apps/toolkits."""
    from .composio_tools import _ensure_composio_api_key, _get_composio_client

    _ensure_composio_api_key(settings)
    client = _get_composio_client()
    # Composio SDK: client.toolkits.list() or client.apps.list()
    raw_apps: list[Any] = []
    try:
        raw_apps = list(client.toolkits.list())
    except AttributeError:
        try:
            raw_apps = list(client.apps.list())
        except Exception as exc:
            raise RuntimeError(f"Cannot list Composio apps: {exc}") from exc

    result = []
    for app in raw_apps:
        slug = str(getattr(app, "slug", None) or getattr(app, "name", "") or "")
        name = str(getattr(app, "display_name", None) or getattr(app, "name", slug) or slug)
        description = getattr(app, "description", None)
        logo_url = getattr(app, "logo", None) or getattr(app, "logo_url", None)
        categories = list(getattr(app, "categories", None) or [])
        auth_schemes_raw = getattr(app, "auth_schemes", None) or []
        auth_schemes = [str(a) for a in auth_schemes_raw]
        result.append(
            {
                "slug": slug.lower(),
                "name": name,
                "description": str(description) if description else None,
                "logo_url": str(logo_url) if logo_url else None,
                "categories": [str(c) for c in categories],
                "auth_schemes": auth_schemes,
            }
        )
    return result


def _initiate_connection_upstream(
    settings: Settings, app_slug: str, user_id: str | None
) -> dict:
    """Initiate a Composio OAuth/API-key connection and return redirect_url."""
    from .composio_tools import _ensure_composio_api_key, _get_composio_client

    _ensure_composio_api_key(settings)
    client = _get_composio_client()
    effective_user = user_id or (settings.composio_user_id or "default")

    try:
        conn = client.connected_accounts.initiate(
            app_name=app_slug.upper(),
            entity_id=effective_user,
        )
        redirect_url = str(
            getattr(conn, "redirect_url", None)
            or getattr(conn, "redirectUrl", None)
            or getattr(conn, "url", None)
            or ""
        )
        connection_id = str(getattr(conn, "id", None) or getattr(conn, "connectionId", "") or "")
    except Exception as exc:
        raise RuntimeError(f"Failed to initiate Composio connection: {exc}") from exc

    return {"redirect_url": redirect_url, "connection_id": connection_id}


def _get_connection_status_upstream(
    settings: Settings, app_slug: str, user_id: str | None
) -> dict | None:
    """Query Composio for current connection status. Returns None on not-found."""
    from .composio_tools import _ensure_composio_api_key, _get_composio_client

    _ensure_composio_api_key(settings)
    client = _get_composio_client()
    effective_user = user_id or (settings.composio_user_id or "default")

    try:
        connections = client.connected_accounts.list(entity_id=effective_user)
        for conn in connections:
            slug = str(getattr(conn, "appName", None) or getattr(conn, "app_name", "") or "")
            if slug.lower() == app_slug.lower():
                raw_status = str(
                    getattr(conn, "status", None) or getattr(conn, "connectionStatus", "unknown")
                ).lower()
                # Normalize to contract statuses
                status = _normalize_status(raw_status)
                meta = getattr(conn, "meta", None) or getattr(conn, "metadata", None)
                return {
                    "status": status,
                    "metadata": meta if isinstance(meta, dict) else None,
                }
    except Exception as exc:
        logger.warning("composio_service: status query failed for %s: %s", app_slug, exc)
    return None


def _disconnect_upstream(settings: Settings, app_slug: str, user_id: str | None) -> None:
    """Disconnect a Composio connection. Ignores not-found errors."""
    from .composio_tools import _ensure_composio_api_key, _get_composio_client

    _ensure_composio_api_key(settings)
    client = _get_composio_client()
    effective_user = user_id or (settings.composio_user_id or "default")

    try:
        connections = client.connected_accounts.list(entity_id=effective_user)
        for conn in connections:
            slug = str(getattr(conn, "appName", None) or getattr(conn, "app_name", "") or "")
            if slug.lower() == app_slug.lower():
                conn_id = str(getattr(conn, "id", None) or "")
                if conn_id:
                    client.connected_accounts.delete(conn_id)
                return
    except Exception as exc:
        logger.warning("composio_service: disconnect failed for %s: %s", app_slug, exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_status(raw: str) -> str:
    raw = raw.lower()
    if raw in {"connected", "active", "ok"}:
        return "connected"
    if raw in {"pending", "initiated", "authorizing"}:
        return "pending"
    if raw in {"error", "failed", "invalid"}:
        return "error"
    if raw in {"disconnected", "removed", "deleted", "inactive"}:
        return "disconnected"
    return "pending"


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _row_to_dict(row: Any) -> dict:
    d = dict(row)
    meta = d.get("metadata")
    if isinstance(meta, str):
        try:
            d["metadata"] = json.loads(meta)
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = None
    last = d.get("last_checked_at")
    d["last_checked_at"] = last if last else None
    return d


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_status(settings: Settings) -> dict:
    """Return the /api/composio/status payload."""
    api_key_present = bool(settings.composio_api_key)
    user_id = settings.composio_user_id or None
    last_error: str | None = None
    enabled = False

    if not api_key_present:
        return {
            "enabled": False,
            "api_key_present": False,
            "user_id": user_id,
            "last_error": None,
        }

    try:
        from .composio_tools import _ensure_composio_api_key, _get_composio_client

        _ensure_composio_api_key(settings)
        _get_composio_client()
        enabled = True
    except ImportError as exc:
        last_error = f"composio package not installed: {exc}"
    except Exception as exc:
        last_error = str(exc)

    return {
        "enabled": enabled,
        "api_key_present": api_key_present,
        "user_id": user_id,
        "last_error": last_error,
    }


def set_api_key(settings: Settings, api_key: str) -> dict:
    """Persist API key to runtime_secrets, reload settings, re-init client."""
    from .composio_tools import reset_composio_client_for_tests
    from .secrets_service import maybe_write_env_file, write_runtime_secret

    # Write to runtime_secrets.json
    write_runtime_secret(settings, "COMPOSIO_API_KEY", api_key)

    # Optionally write to .env
    maybe_write_env_file(settings, "COMPOSIO_API_KEY", api_key)

    # Reload in-memory settings
    settings.reload_from_runtime_secrets()

    # Also patch os.environ so SDK calls pick it up immediately
    os.environ["COMPOSIO_API_KEY"] = api_key

    # Reset the module-level composio client so it re-initialises with the new key
    reset_composio_client_for_tests()

    # Invalidate the apps cache so the next GET /apps reflects the new account
    _invalidate_apps_cache()

    return get_status(settings)


def list_apps(settings: Settings) -> list[dict]:
    """Return list of available Composio apps. Cached 5 min in process."""
    now = time.monotonic()
    cached = _apps_cache.get("data")
    cached_at = _apps_cache.get("cached_at", 0.0)
    if cached is not None and (now - cached_at) < _APPS_CACHE_TTL_SEC:
        return cached  # type: ignore[return-value]

    apps = _list_apps_upstream(settings)
    _apps_cache["data"] = apps
    _apps_cache["cached_at"] = now
    return apps


def list_connections(store: MemoryStore) -> list[dict]:
    """Return all composio_connections rows."""
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT id, app_slug, display_name, status, user_id, last_checked_at, metadata "
            "FROM composio_connections ORDER BY id"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def create_connection(
    store: MemoryStore,
    settings: Settings,
    app_slug: str,
    user_id: str | None,
) -> dict:
    """Initiate upstream OAuth flow, insert pending row. Returns contract shape."""
    # 409 check: already connected
    with store.connect() as conn:
        existing = conn.execute(
            "SELECT id, status FROM composio_connections WHERE app_slug=? AND user_id IS ?",
            (app_slug, user_id),
        ).fetchone()
    if existing and existing["status"] == "connected":
        raise ValueError("already_connected")

    # Call upstream
    upstream = _initiate_connection_upstream(settings, app_slug, user_id)
    redirect_url = upstream.get("redirect_url", "")
    display_name = app_slug.title()

    if existing:
        # Update the existing pending/error row
        with store.connect() as conn:
            conn.execute(
                "UPDATE composio_connections SET status='pending', last_checked_at=? WHERE id=?",
                (_now_iso(), existing["id"]),
            )
            conn.commit()
        row_id = existing["id"]
    else:
        with store.connect() as conn:
            cur = conn.execute(
                "INSERT INTO composio_connections"
                " (app_slug, display_name, status, user_id, last_checked_at)"
                " VALUES (?, ?, 'pending', ?, ?)",
                (app_slug, display_name, user_id, _now_iso()),
            )
            conn.commit()
            row_id = cur.lastrowid

    return {
        "id": row_id,
        "app_slug": app_slug,
        "display_name": display_name,
        "status": "pending",
        "redirect_url": redirect_url,
        "user_id": user_id,
        "last_checked_at": _now_iso(),
        "metadata": None,
    }


def refresh_connection(store: MemoryStore, settings: Settings, conn_id: int) -> dict | None:
    """Re-query upstream status and update the row. Returns updated row or None."""
    with store.connect() as conn:
        row = conn.execute(
            "SELECT id, app_slug, display_name, status, user_id, last_checked_at, metadata "
            "FROM composio_connections WHERE id=?",
            (conn_id,),
        ).fetchone()
    if row is None:
        return None

    row_dict = _row_to_dict(row)
    upstream = _get_connection_status_upstream(
        settings, row_dict["app_slug"], row_dict["user_id"]
    )

    now = _now_iso()
    if upstream:
        new_status = upstream["status"]
        meta = upstream.get("metadata")
        meta_json = json.dumps(meta) if meta else None
        with store.connect() as conn:
            conn.execute(
                "UPDATE composio_connections"
                " SET status=?, last_checked_at=?, metadata=? WHERE id=?",
                (new_status, now, meta_json, conn_id),
            )
            conn.commit()
        row_dict["status"] = new_status
        row_dict["last_checked_at"] = now
        row_dict["metadata"] = meta
    else:
        with store.connect() as conn:
            conn.execute(
                "UPDATE composio_connections SET last_checked_at=? WHERE id=?",
                (now, conn_id),
            )
            conn.commit()
        row_dict["last_checked_at"] = now

    return row_dict


def delete_connection(store: MemoryStore, settings: Settings, conn_id: int) -> bool:
    """Disconnect upstream and delete the DB row. Returns False if not found."""
    with store.connect() as conn:
        row = conn.execute(
            "SELECT id, app_slug, user_id FROM composio_connections WHERE id=?",
            (conn_id,),
        ).fetchone()
    if row is None:
        return False

    # Best-effort upstream disconnect
    try:
        _disconnect_upstream(settings, row["app_slug"], row["user_id"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("composio_service: upstream disconnect failed (continuing): %s", exc)

    with store.connect() as conn:
        conn.execute("DELETE FROM composio_connections WHERE id=?", (conn_id,))
        conn.commit()

    return True
