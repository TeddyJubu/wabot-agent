from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import (
    APIRouter,
    FastAPI,
)
from fastapi.staticfiles import StaticFiles

from ..auto_reply import (
    deliver_auto_reply as deliver_auto_reply,  # noqa: F401 (re-export — patched by tests)
)
from ..auto_reply import (
    deliver_inbound_error_reply as deliver_inbound_error_reply,  # noqa: F401 (re-export)
)
from ..config import Settings, get_settings
from ..context_management import maybe_prune_audit_tables
from ..events import EventHub, EventLog
from ..knowledge_store import ensure_knowledge_files
from ..memory import MemoryStore
from ..settings_service import SettingsService
from ..wabot import WabotClient
from ..wabot_process import (
    WabotRestartError as WabotRestartError,  # noqa: F401 (re-export for routes/pairing.py late-import patch target)
)
from ..wabot_process import (
    restart_wabot_daemon as restart_wabot_daemon,  # noqa: F401 (re-export — patched by tests via api module)
)
from ..wabot_process import (
    rotate_wabot_store_files as rotate_wabot_store_files,  # noqa: F401 (re-export)
)
from ..wabot_process import (
    wait_for_fresh_pairing as wait_for_fresh_pairing,  # noqa: F401 (re-export)
)
from .dependencies import (
    _LOOPBACK_HOSTS,  # noqa: F401  (re-export — used by external callers and tests)
)
from .dependencies import (
    _require_loopback_url as _require_loopback_url,  # noqa: F401  (re-export)
)
from .dependencies import (
    _verify_inbound_auth as _verify_inbound_auth,  # noqa: F401 (re-export)
)
from .deps import AppDeps, PairingState, SchedulerState, SnapshotCache
from .routes.agents import register_agents_routes
from .routes.auth import register_auth_routes
from .routes.codex import register_codex_routes
from .routes.groups import register_groups_routes
from .routes.health import register_health_routes
from .routes.inbound import register_inbound_routes
from .routes.memory import register_memory_routes
from .routes.pages import register_pages_routes
from .routes.pairing import (
    _pairing_payload as _pairing_payload,  # noqa: F401 (re-export — used by SSE snapshot builder)
)
from .routes.pairing import (
    _pairing_unreachable_payload as _pairing_unreachable_payload,  # noqa: F401 (re-export)
)
from .routes.pairing import (
    _qr_svg as _qr_svg,  # noqa: F401 re-exported: wabot_agent.api._qr_svg used by tests
)
from .routes.pairing import (
    pairing_poll_loop,
    register_pairing_routes,
)
from .routes.settings import register_settings_routes
from .routes.stream import _sse_frame as _sse_frame  # noqa: F401 (re-export)
from .routes.stream import register_stream_routes
from .routes.tools_catalog import register_tools_catalog_routes
from .scheduler import scheduler_loop

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.requires_inbound_token() and not (settings.wabot_inbound_token or "").strip():
        raise RuntimeError(
            "WABOT_INBOUND_TOKEN must be set: inbound webhooks require auth "
            "(non-loopback WABOT_AGENT_HOST, non-local WABOT_AGENT_ENV, or "
            "WABOT_INBOUND_TOKEN_REQUIRED=true)"
        )
    settings.ensure_dirs()
    from ..runtime_overrides import apply_overrides, load_overrides

    overrides = load_overrides(settings.runtime_overrides_path)
    if overrides:
        # Validate atomically on a snapshot first — a stale override file with
        # one bad value (e.g. a Literal that no longer exists) shouldn't half-
        # mutate live settings before the exception fires.
        snapshot = settings.model_copy(deep=True)
        try:
            apply_overrides(snapshot, overrides)
        except Exception as exc:
            logger.error(
                "runtime overrides file failed validation, ignoring: %s", exc
            )
        else:
            apply_overrides(settings, overrides)
    memory = MemoryStore(settings.db_path, settings)
    hub = EventHub()
    event_log = EventLog(settings.log_path, hub=hub)
    wabot = WabotClient(settings.wabot_endpoint, settings.resolved_wabot_token)

    # SR-1: SettingsService is the single owner of settings mutations.
    settings_service = SettingsService(settings)

    # Subscriber: keep WabotClient in sync when wabot_endpoint / wabot_token change.
    def _on_settings_change(new_settings: Settings, changed: frozenset[str]) -> None:
        if "wabot_endpoint" in changed:
            wabot.endpoint = new_settings.wabot_endpoint.rstrip("/")
        if "wabot_token" in changed:
            wabot.token = new_settings.resolved_wabot_token

    settings_service.subscribe(_on_settings_change)

    # TODO(Phase-6): subscribe event_log SSE broadcast here so the dashboard
    # receives a settings_updated event from any settings change source.
    # e.g.: settings_service.subscribe(lambda s, changed:
    #     event_log.write("settings_updated", {"fields": sorted(changed)}))
    # Blocked until hub.publish() is safe to call from a sync subscriber.

    # Pairing poller state — last published payload + the asyncio task handle.
    pairing_state = PairingState()
    snapshot_cache = SnapshotCache()
    scheduler_state = SchedulerState()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Capture the running uvicorn loop so sync publishers (EventLog.write
        # called from inside tools, threads, etc.) can dispatch safely via
        # call_soon_threadsafe. Then drive pairing state through the hub so
        # the dashboard can rely on `pairing_changed` for live updates.
        hub.bind_loop(asyncio.get_running_loop())
        ensure_knowledge_files(settings)
        maybe_prune_audit_tables(memory, settings, force=True)
        pairing_state.task = asyncio.create_task(pairing_poll_loop(deps))
        scheduler_state.task = asyncio.create_task(scheduler_loop(deps))
        try:
            yield
        finally:
            pairing_task = pairing_state.task
            if pairing_task is not None:
                pairing_task.cancel()
                try:
                    await pairing_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            sched_task = scheduler_state.task
            if sched_task is not None:
                sched_task.cancel()
                try:
                    await sched_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            await wabot.aclose()

    deps = AppDeps(
        settings=settings,
        memory=memory,
        wabot=wabot,
        event_log=event_log,
        hub=hub,
        pairing_state=pairing_state,
        scheduler_state=scheduler_state,
        snapshot_cache=snapshot_cache,
        settings_service=settings_service,
    )

    app = FastAPI(title="wabot-agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.memory = memory
    app.state.event_log = event_log
    app.state.event_hub = hub
    app.state.wabot = wabot
    app.state.deps = deps

    # NOTE: api/__init__.py is one level deeper than the old api.py was,
    # so the walk to the project root needs parents[3] (api → wabot_agent → src → root).
    static_dir = Path(__file__).resolve().parents[3] / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # /health and /ready — extracted to api/routes/health.py (MASTER ME-1 Part 2).
    _health_router = APIRouter()
    register_health_routes(_health_router, deps)
    app.include_router(_health_router)

    # /, /pair, /knowledge, /favicon.ico — extracted to api/routes/pages.py (ME-1 Part 3).
    _pages_router = APIRouter()
    register_pages_routes(_pages_router, deps)
    app.include_router(_pages_router)

    # /login, /api/auth/login — extracted to api/routes/auth.py (ME-1 Part 3).
    _auth_router = APIRouter()
    register_auth_routes(_auth_router, deps)
    app.include_router(_auth_router)

    # /api/settings/* — extracted to api/routes/settings.py (ME-1 Part 4).
    _settings_router = APIRouter()
    register_settings_routes(_settings_router, deps)
    app.include_router(_settings_router)

    # /api/whatsapp/groups/* — extracted to api/routes/groups.py (ME-1 Part 4).
    _groups_router = APIRouter()
    register_groups_routes(_groups_router, deps)
    app.include_router(_groups_router)

    # /api/codex/* — extracted to api/routes/codex.py (ME-1 Part 4).
    _codex_router = APIRouter()
    register_codex_routes(_codex_router, deps)
    app.include_router(_codex_router)

    # /api/whatsapp/pairing/* — extracted to api/routes/pairing.py (ME-1 Part 5).
    _pairing_router = APIRouter()
    register_pairing_routes(_pairing_router, deps)
    app.include_router(_pairing_router)

    # /api/memory/* + /api/knowledge/* + /api/runs — extracted to routes/memory.py (ME-1 Part 6).
    _memory_router = APIRouter()
    register_memory_routes(_memory_router, deps)
    app.include_router(_memory_router)

    # /whatsapp/inbound + /whatsapp/receipt + /whatsapp/presence
    # + /whatsapp/history-sync + /whatsapp/history — ME-1 Part 7b.
    _inbound_router = APIRouter()
    register_inbound_routes(_inbound_router, deps)
    app.include_router(_inbound_router)

    # /api/stream — SSE endpoint + initial snapshot builder — ME-1 Part 7c.
    _stream_router = APIRouter()
    register_stream_routes(_stream_router, deps)
    app.include_router(_stream_router)

    # /api/agents/* — Phase 3a agents CRUD + test endpoint.
    _agents_router = APIRouter()
    register_agents_routes(_agents_router, deps)
    app.include_router(_agents_router)

    # /api/tools/* — Phase 3a tools catalog.
    _tools_catalog_router = APIRouter()
    register_tools_catalog_routes(_tools_catalog_router, deps)
    app.include_router(_tools_catalog_router)

    return app


# URL guards now live in api/dependencies.py; re-exported above.


# LLM connectivity probes + the GET /api/settings view builder now live in
# api/llm_tests.py and are re-exported via the import block above.


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, reload=False)
