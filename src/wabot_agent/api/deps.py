"""AppDeps — the dependency container passed to register_*_routes().

Carved out of api/__init__.py:create_app() as part of MASTER ME-1 Part 2.
Each route module gets one of these instead of capturing create_app's
closure. Frozen so route handlers can't mutate the wiring; the state
sub-dataclasses are mutable on purpose (pairing_state.last gets
overwritten on every poll, snapshot_cache.payload on every refresh).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PairingState:
    last: dict[str, Any] | None = None
    task: Any = None  # asyncio.Task | None — Any to avoid the import here


@dataclass
class SchedulerState:
    task: Any = None  # asyncio.Task | None


@dataclass
class SnapshotCache:
    at: float = 0.0
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class AppDeps:
    settings: Any            # Settings — Any to avoid import cycles
    memory: Any              # MemoryStore
    wabot: Any               # WabotClient
    event_log: Any           # EventLog
    hub: Any                 # EventHub
    pairing_state: PairingState
    scheduler_state: SchedulerState
    snapshot_cache: SnapshotCache
