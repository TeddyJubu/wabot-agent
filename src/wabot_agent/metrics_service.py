"""metrics_service — query functions for Phase 6 dashboard metrics.

One function per /api/metrics/* endpoint.  All take a MemoryStore (and
optionally Settings) and return plain dicts matching the locked API contract.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .memory import MemoryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------

_WINDOW_TO_INTERVAL: dict[str, str] = {
    "1h":  "-1 hours",
    "24h": "-24 hours",
    "7d":  "-7 days",
    "30d": "-30 days",
}

_DEFAULT_BUCKET: dict[str, str] = {
    "1h":  "minute",
    "24h": "hour",
    "7d":  "day",
    "30d": "day",
}

_BUCKET_STRFTIME: dict[str, str] = {
    "minute": "%Y-%m-%dT%H:%M:00Z",
    "hour":   "%Y-%m-%dT%H:00:00Z",
    "day":    "%Y-%m-%dT00:00:00Z",
}

# Snapshot of valid strftime formats — used by get_runs_series for the
# defence-in-depth check against accidental SQL injection via the
# f-string interpolation. See review BLOCKER 2.
_ALLOWED_BUCKET_FMTS = frozenset(_BUCKET_STRFTIME.values())


def _window_interval(window: str) -> str:
    return _WINDOW_TO_INTERVAL.get(window, "-24 hours")


def _bucket_fmt(bucket: str) -> str:
    return _BUCKET_STRFTIME.get(bucket, _BUCKET_STRFTIME["hour"])


def _safe_pct(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


# ---------------------------------------------------------------------------
# get_overview
# ---------------------------------------------------------------------------


def get_overview(store: MemoryStore, settings: Any) -> dict:  # noqa: ANN401
    with store.connect() as conn:
        # messages today / yesterday
        msg_today = conn.execute(
            "SELECT COUNT(*) FROM inbound_messages WHERE date(received_at) = date('now')"
        ).fetchone()[0] or 0
        msg_yesterday = conn.execute(
            "SELECT COUNT(*) FROM inbound_messages WHERE date(received_at) = date('now','-1 day')"
        ).fetchone()[0] or 0

        # runs today / yesterday
        runs_today = conn.execute(
            "SELECT COUNT(*) FROM runs WHERE date(created_at) = date('now')"
        ).fetchone()[0] or 0
        runs_yesterday = conn.execute(
            "SELECT COUNT(*) FROM runs WHERE date(created_at) = date('now','-1 day')"
        ).fetchone()[0] or 0

        # avg latency last 24h
        row = conn.execute(
            "SELECT AVG(latency_ms) FROM runs WHERE created_at >= datetime('now','-24 hours')"
        ).fetchone()
        avg_latency = row[0] if row and row[0] is not None else None

        # cost last 24h / yesterday 24h
        cost_row = conn.execute(
            "SELECT SUM(cost_usd) FROM runs WHERE created_at >= datetime('now','-24 hours')"
        ).fetchone()
        cost_24h = float(cost_row[0] or 0.0)

        cost_prev_row = conn.execute(
            "SELECT SUM(cost_usd) FROM runs "
            "WHERE created_at >= datetime('now','-48 hours') "
            "  AND created_at <  datetime('now','-24 hours')"
        ).fetchone()
        cost_prev = float(cost_prev_row[0] or 0.0)

        # integration health: combine mcp_servers + composio_connections
        ok_mcp = conn.execute(
            "SELECT COUNT(*) FROM mcp_servers WHERE health_status = 'ok'"
        ).fetchone()[0] or 0
        error_mcp = conn.execute(
            "SELECT COUNT(*) FROM mcp_servers WHERE health_status = 'error'"
        ).fetchone()[0] or 0
        unknown_mcp = conn.execute(
            "SELECT COUNT(*) FROM mcp_servers "
            "WHERE health_status IS NULL OR health_status = 'unknown'"
        ).fetchone()[0] or 0

        ok_comp = conn.execute(
            "SELECT COUNT(*) FROM composio_connections WHERE status IN ('ok','connected')"
        ).fetchone()[0] or 0
        error_comp = conn.execute(
            "SELECT COUNT(*) FROM composio_connections WHERE status = 'error'"
        ).fetchone()[0] or 0
        unknown_comp = conn.execute(
            "SELECT COUNT(*) FROM composio_connections "
            "WHERE status NOT IN ('ok','connected','error')"
        ).fetchone()[0] or 0

        # queue depth
        queue_depth = conn.execute(
            "SELECT COUNT(*) FROM outbound_tasks WHERE status = 'pending'"
        ).fetchone()[0] or 0

    return {
        "messages_today": msg_today,
        "messages_today_delta_pct": _safe_pct(msg_today, msg_yesterday),
        "runs_today": runs_today,
        "runs_today_delta_pct": _safe_pct(runs_today, runs_yesterday),
        "avg_latency_ms_24h": float(avg_latency) if avg_latency is not None else None,
        "cost_usd_24h": cost_24h,
        "cost_usd_24h_delta_pct": _safe_pct(cost_24h, cost_prev),
        "integrations_health": {
            "ok": ok_mcp + ok_comp,
            "error": error_mcp + error_comp,
            "unknown": unknown_mcp + unknown_comp,
        },
        "queue_depth": queue_depth,
    }


# ---------------------------------------------------------------------------
# get_runs_series
# ---------------------------------------------------------------------------


def get_runs_series(store: MemoryStore, *, window: str, bucket: str) -> dict:
    interval = _window_interval(window)
    fmt = _bucket_fmt(bucket)

    # Phase 6 review BLOCKER 2: defence-in-depth. The route layer
    # whitelists `bucket`, and `_bucket_fmt` only returns values from the
    # _BUCKET_STRFTIME dict, but the f-string interpolation on the next
    # line is one whitelist deletion away from a SQL-injection vector.
    # Assert the resolved format is from the known set before
    # constructing the query.
    if fmt not in _ALLOWED_BUCKET_FMTS:
        raise ValueError(f"unsafe bucket format: {fmt!r}")

    with store.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                strftime('{fmt}', created_at)  AS ts,
                subagent_slug,
                COUNT(*)                        AS cnt
            FROM runs
            WHERE created_at >= datetime('now', ?)
            GROUP BY ts, subagent_slug
            ORDER BY ts
            """,
            (interval,),
        ).fetchall()

    # Aggregate into series buckets
    bucket_map: dict[str, dict[str, int]] = {}
    for row in rows:
        ts = row[0] or ""
        slug = row[1] or "orchestrator"
        cnt = row[2] or 0
        if ts not in bucket_map:
            bucket_map[ts] = {}
        bucket_map[ts][slug] = bucket_map[ts].get(slug, 0) + cnt

    series = []
    for ts in sorted(bucket_map):
        by_agent = bucket_map[ts]
        series.append({
            "timestamp": ts,
            "count": sum(by_agent.values()),
            "by_agent": by_agent,
        })

    return {"window": window, "bucket": bucket, "series": series}


# ---------------------------------------------------------------------------
# get_top_tools
# ---------------------------------------------------------------------------


def get_top_tools(store: MemoryStore, *, window: str, limit: int) -> dict:
    interval = _window_interval(window)

    with store.connect() as conn:
        # tool_events has: id, run_id, name, payload, created_at
        # We parse the payload JSON for success/error detection — fallback to name
        rows = conn.execute(
            """
            SELECT
                name,
                COUNT(*) AS invocations,
                SUM(CASE WHEN payload LIKE '%"error"%' THEN 1 ELSE 0 END) AS errors
            FROM tool_events
            WHERE created_at >= datetime('now', ?)
            GROUP BY name
            ORDER BY invocations DESC
            LIMIT ?
            """,
            (interval, limit),
        ).fetchall()

    items = []
    for row in rows:
        items.append({
            "tool_name": row[0] or "",
            "invocations": row[1] or 0,
            "avg_latency_ms": None,   # tool_events doesn't store latency per call
            "errors": row[2] or 0,
        })

    return {"window": window, "items": items}


# ---------------------------------------------------------------------------
# get_costs
# ---------------------------------------------------------------------------


def get_costs(store: MemoryStore, *, window: str) -> dict:
    interval = _window_interval(window)

    with store.connect() as conn:
        # Total
        total_row = conn.execute(
            "SELECT SUM(cost_usd) FROM runs WHERE created_at >= datetime('now', ?)",
            (interval,),
        ).fetchone()
        total_usd = float(total_row[0] or 0.0)

        # By day
        day_rows = conn.execute(
            """
            SELECT date(created_at) AS d, SUM(cost_usd) AS usd
            FROM runs
            WHERE created_at >= datetime('now', ?)
            GROUP BY d
            ORDER BY d
            """,
            (interval,),
        ).fetchall()

        # By provider + model breakdown
        provider_rows = conn.execute(
            """
            SELECT provider, model, SUM(cost_usd) AS usd
            FROM runs
            WHERE created_at >= datetime('now', ?)
              AND provider IS NOT NULL
            GROUP BY provider, model
            ORDER BY provider, usd DESC
            """,
            (interval,),
        ).fetchall()

    by_day = [{"date": row[0] or "", "usd": float(row[1] or 0.0)} for row in day_rows]

    # Collapse to per-provider with model_breakdown dict
    provider_map: dict[str, dict] = {}
    for row in provider_rows:
        prov = row[0] or "unknown"
        mod = row[1] or "unknown"
        usd = float(row[2] or 0.0)
        if prov not in provider_map:
            provider_map[prov] = {"provider": prov, "usd": 0.0, "model_breakdown": {}}
        provider_map[prov]["usd"] += usd
        provider_map[prov]["model_breakdown"][mod] = (
            provider_map[prov]["model_breakdown"].get(mod, 0.0) + usd
        )

    by_provider = list(provider_map.values())

    return {"window": window, "total_usd": total_usd, "by_day": by_day, "by_provider": by_provider}


# ---------------------------------------------------------------------------
# get_health
# ---------------------------------------------------------------------------


def get_health(store: MemoryStore, settings: Any) -> dict:  # noqa: ANN401
    with store.connect() as conn:
        mcp_rows = conn.execute(
            "SELECT id, name, health_status, health_message, last_checked_at "
            "FROM mcp_servers ORDER BY id"
        ).fetchall()

        comp_rows = conn.execute(
            "SELECT status, last_checked_at, metadata FROM composio_connections"
        ).fetchall()

    mcp_servers = []
    for row in mcp_rows:
        mcp_servers.append({
            "id": row[0],
            "name": row[1] or "",
            "status": row[2] or "unknown",
            "message": row[3] or None,
            "last_checked_at": row[4] or None,
        })

    # Composio aggregate
    comp_total = len(comp_rows)
    comp_last_error: str | None = None
    comp_status = "ok" if comp_total > 0 else "unknown"
    for row in comp_rows:
        if row[0] not in ("ok", "connected"):
            comp_status = row[0] or "unknown"
            # Try to get last_error from metadata JSON
            if row[2]:
                try:
                    import json
                    meta = json.loads(row[2])
                    comp_last_error = meta.get("last_error")
                except Exception:  # noqa: BLE001
                    pass

    composio = {
        "status": comp_status,
        "connections_count": comp_total,
        "last_error": comp_last_error,
    }

    # wabot daemon health — check if there's a cached health status anywhere
    # Fall back to "unknown" since we don't have an in-process cache here
    wabot_health: dict[str, Any] = {
        "status": "unknown",
        "message": None,
        "last_checked_at": None,
    }
    # Try to get from the most recent tool_events entry for wabot_health tool
    try:
        with store.connect() as conn:
            row = conn.execute(
                "SELECT payload, created_at FROM tool_events "
                "WHERE name = 'wabot_health' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row:
                import json
                payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                if isinstance(payload, dict):
                    result_data = payload.get("result") or payload.get("output") or {}
                    if isinstance(result_data, dict):
                        linked = result_data.get("linked")
                        if linked is True:
                            wabot_health["status"] = "ok"
                        elif linked is False:
                            wabot_health["status"] = "error"
                        wabot_health["last_checked_at"] = row[1]
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_health: wabot_health lookup failed: %s", exc)

    return {
        "wabot_daemon": wabot_health,
        "mcp_servers": mcp_servers,
        "composio": composio,
    }
