from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .redaction import redact

# Bounded buffers so the hub can never starve the agent on a slow client.
# Sized to cover ~5 minutes of typical activity (run.* + inbound.*); a longer
# disconnect means the client gives up replay and falls back to /api/runs.
RING_BUFFER_SIZE = 256
SUBSCRIBER_QUEUE_SIZE = 256


@dataclass(frozen=True)
class Event:
    id: int
    name: str
    payload: dict[str, Any]
    ts: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventHub:
    """In-process pub/sub over redacted events.

    EventLog.write() pushes here; the SSE endpoint subscribes. Subscribers
    receive a backlog of recent events (filtered past their Last-Event-ID)
    followed by the live stream. Per-subscriber queues drop their oldest
    event under backpressure — the agent's publish path must never block,
    a stale operator dashboard is acceptable.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counter = 0
        self._ring: deque[Event] = deque(maxlen=RING_BUFFER_SIZE)
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Capture the running event loop so sync publishers can dispatch safely."""
        self._loop = loop

    def publish(self, name: str, payload: dict[str, Any]) -> Event:
        with self._lock:
            self._counter += 1
            event = Event(
                id=self._counter,
                name=name,
                payload=redact(payload) if isinstance(payload, dict) else payload,
                ts=datetime.now(UTC).isoformat(),
            )
            self._ring.append(event)
            subs = list(self._subscribers)

        loop = self._loop
        if loop is not None and subs:
            loop.call_soon_threadsafe(self._dispatch, event, subs)
        return event

    def _dispatch(self, event: Event, subs: list[asyncio.Queue[Event]]) -> None:
        for q in subs:
            # Drop-oldest under backpressure: a slow client loses history,
            # but the publisher is never blocked.
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def open_subscription(
        self, last_event_id: int | None
    ) -> tuple[list[Event], asyncio.Queue[Event]]:
        """Register a new subscriber and return (backlog, live_queue).

        The caller must invoke `close_subscription(queue)` when done — usually
        from a `finally` block in the SSE generator.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        with self._lock:
            backlog = [
                e for e in self._ring if last_event_id is None or e.id > last_event_id
            ]
            self._subscribers.append(queue)
        return backlog, queue

    def close_subscription(self, queue: asyncio.Queue[Event]) -> None:
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)


class EventLog:
    """Append-only JSONL log of redacted events, with optional hub fan-out."""

    def __init__(self, path: Path, hub: EventHub | None = None):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.hub = hub

    def write(self, event_type: str, payload: dict[str, Any]) -> None:
        redacted = redact(payload)
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "type": event_type,
            "payload": redacted,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")
        if self.hub is not None:
            self.hub.publish(event_type, redacted)
