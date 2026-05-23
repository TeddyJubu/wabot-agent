"""SSE stream endpoint and the initial-snapshot builder.

Carved out of api/__init__.py as part of MASTER ME-1 Part 7. The
dashboard's status hub connects to /api/stream and receives:

1. An initial snapshot frame summarizing current state (settings view,
   wabot health, pairing state, scheduler state, recent runs, etc.).
2. A live event stream from deps.hub.subscribe(...) — settings_updated,
   reminder_fired, outbound_task_completed, pairing changes, etc.

The initial snapshot helpers (or inline composition) move with the route.
The snapshot_cache (deps.snapshot_cache) has a 2-second TTL — reads the
cached payload if fresh; rebuilds and writes it when stale.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Header
from fastapi.requests import Request
from fastapi.responses import StreamingResponse

from ...auth import verify_human_factory
from ...llm_provider import active_model_id
from ...redaction import redact
from ..routes.pairing import _pairing_payload

if TYPE_CHECKING:
    from ..deps import AppDeps

logger = logging.getLogger(__name__)

_SNAPSHOT_TTL_SEC = 2.0


def _sse_frame(event_id: int | None, name: str, data: Any) -> str:
    """Format a single SSE frame. Data is JSON-encoded; multi-line bodies are
    split across multiple `data:` lines per the SSE spec, though our redacted
    payloads almost never contain newlines."""
    parts: list[str] = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {name}")
    body = json.dumps(data, ensure_ascii=False)
    for line in body.split("\n"):
        parts.append(f"data: {line}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


async def _build_initial_snapshot(deps: AppDeps) -> dict[str, Any]:
    """Initial payload pushed when an SSE client connects.

    Bundles /ready + /api/runs + pairing into one event so the dashboard
    renders completely without follow-up REST calls. Subsequent state
    changes arrive as deltas on the same stream.
    """
    settings = deps.settings
    memory = deps.memory
    wabot = deps.wabot
    pairing_state = deps.pairing_state
    snapshot_cache = deps.snapshot_cache

    now = time.monotonic()
    cached = snapshot_cache.payload
    if (
        cached is not None
        and now - float(snapshot_cache.at) < _SNAPSHOT_TTL_SEC
    ):
        return cached
    wabot_health = await wabot.health()
    # Prefer the poller's cached pairing snapshot (already redacted on
    # publish); on cold start before the first tick fires, fall through
    # to a fresh probe so the client doesn't paint a blank pairing card.
    pairing = pairing_state.last
    if pairing is None:
        pairing = _pairing_payload(await wabot.pairing_qr())
    snapshot = redact(
        {
            "ok": True,
            "live_model": settings.live_model_enabled,
            "model_provider": settings.model_provider,
            "model": active_model_id(settings) if settings.live_model_enabled else "offline",
            "send_policy": settings.send_policy,
            "memory": memory.stats(),
            "wabot": {
                "reachable": wabot_health.reachable,
                "logged_in": wabot_health.logged_in,
                "connected": wabot_health.connected,
                "ready": wabot_health.ready,
                "detail": wabot_health.detail,
            },
            "pairing": pairing,
            "runs": memory.recent_runs(limit=8),
        }
    )
    snapshot_cache.at = now
    snapshot_cache.payload = snapshot
    return snapshot


def register_stream_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    hub = deps.hub

    verify_human = verify_human_factory(settings)
    human_dependency = Depends(verify_human)

    @router.get("/api/stream", dependencies=[human_dependency])
    async def event_stream(
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        """Server-sent events for live dashboard updates.

        On connect: an initial `ready_snapshot` event with /ready + recent runs.
        Live: every event published via EventLog (agent_run_*, inbound_message,
        settings_updated) is forwarded with monotonic Last-Event-ID for replay.
        Heartbeat comments every 15s keep proxies from idling the connection.
        """
        try:
            lid: int | None = int(last_event_id) if last_event_id else None
        except ValueError:
            lid = None

        async def generator() -> Any:
            # 1) Initial snapshot — fast first paint, no separate REST round-trips.
            snapshot = await _build_initial_snapshot(deps)
            yield _sse_frame(event_id=None, name="ready_snapshot", data=snapshot)

            # 2) Backlog (anything we already broadcast past Last-Event-ID) + live.
            backlog, queue = hub.open_subscription(lid)
            try:
                for event in backlog:
                    yield _sse_frame(event.id, event.name, event.payload)
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except TimeoutError:
                        # Named heartbeat — the client uses it to keep the
                        # staleness pill green during quiet periods. Doubles
                        # as a proxy-keepalive (line traffic every 15s).
                        yield _sse_frame(event_id=None, name="heartbeat", data={})
                        continue
                    yield _sse_frame(event.id, event.name, event.payload)
            finally:
                hub.close_subscription(queue)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                # Defeat nginx proxy buffering if anything ever sits in front.
                "X-Accel-Buffering": "no",
            },
        )
