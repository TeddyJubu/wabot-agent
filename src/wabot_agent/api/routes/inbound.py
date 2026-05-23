"""WhatsApp inbound webhooks — the canonical entry point for every message.

Carved out of api/__init__.py as part of MASTER ME-1 Part 7. The wabot
daemon POSTs to /whatsapp/inbound (and receipt/presence/history-sync/history)
over loopback with the WABOT_INBOUND_TOKEN bearer. This module owns the
auth check (via the inbound_auth_dependency fixture from api.dependencies),
the idempotency claim (via memory.claim_message), and the full agent-run
+ auto-reply pipeline.

The send-policy chokepoint (_is_send_allowed) is NOT here — it lives in
tools/_common.py and is invoked from within auto_reply.deliver_auto_reply.
This module's job is to receive, validate, dedupe, and dispatch.

NOTE on monkeypatching: tests patch ``wabot_agent.api.deliver_auto_reply``
(the original location). To keep that patch working after the extract, we
import ``deliver_auto_reply`` and ``deliver_inbound_error_reply`` via a
late module-level lookup of ``wabot_agent.auto_reply`` inside the handler
body — that way the patch on any attribute of ``wabot_agent.auto_reply``
still intercepts the call. The re-export in ``api/__init__.py`` means
``wabot_agent.api.deliver_auto_reply`` and
``wabot_agent.auto_reply.deliver_auto_reply`` are the same object; the
test's ``monkeypatch.setattr("wabot_agent.api.deliver_auto_reply", fake)``
replaces the name in the ``wabot_agent.api`` namespace, so we look it up
there at call time.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Header, Request

from ...agent import run_agent
from ...auto_reply import inbound_session_id
from ...recipients import is_owner_inbound
from ...redaction import redact
from ...typing_indicator import inbound_typing_indicator
from ..dependencies import _verify_inbound_auth
from ..scheduler import handle_outbound_reply
from ..schemas import (
    HistoryBatchPayload,
    HistorySyncSummaryPayload,
    InboundPayload,
    PresencePayload,
    ReceiptPayload,
)

if TYPE_CHECKING:
    from ..deps import AppDeps

logger = logging.getLogger(__name__)


async def _process_whatsapp_inbound(
    inbound: Any,
    request: Request,
    *,
    deps: AppDeps,
) -> dict[str, Any]:
    """Canonical inbound pipeline: dedup → agent → auto-reply.

    Uses late module lookups for ``deliver_auto_reply`` /
    ``deliver_inbound_error_reply`` so that test monkeypatches on
    ``wabot_agent.api.deliver_auto_reply`` are correctly intercepted.
    """
    # Late-import so monkeypatches on wabot_agent.api.deliver_auto_reply work.
    _api_mod = importlib.import_module("wabot_agent.api")
    _auto_reply_mod = importlib.import_module("wabot_agent.auto_reply")
    deliver_auto_reply = getattr(_api_mod, "deliver_auto_reply", _auto_reply_mod.deliver_auto_reply)
    deliver_inbound_error_reply = getattr(
        _api_mod,
        "deliver_inbound_error_reply",
        _auto_reply_mod.deliver_inbound_error_reply,
    )

    settings = deps.settings
    memory = deps.memory
    wabot = deps.wabot
    event_log = deps.event_log
    hub = deps.hub

    # SAFETY: claim the dedup id BEFORE persisting the message body so a
    # replayed webhook with the same message_id but a mutated text cannot
    # overwrite the stored body via record_inbound's INSERT ... ON CONFLICT
    # DO UPDATE path. See MASTER-architecture-debt-testing.md (Part I §3).
    if not is_owner_inbound(settings, inbound):
        await handle_outbound_reply(inbound, deps=deps)
    if not (inbound.text or "").strip() and not inbound.has_media:
        if not memory.claim_message(inbound.id, inbound.sender):
            return {"accepted": True, "duplicate": True, "message_id": inbound.id}
        memory.record_inbound(inbound)
        memory.complete_message(inbound.id, "skipped-empty")
        return {
            "accepted": True,
            "skipped": True,
            "reason": "empty_text_no_media",
            "message_id": inbound.id,
        }
    if not memory.claim_message(inbound.id, inbound.sender):
        return {"accepted": True, "duplicate": True, "message_id": inbound.id}
    memory.record_inbound(inbound)
    event_log.write(
        "inbound_message",
        {"message_id": inbound.id, "sender": inbound.sender, "path": str(request.url.path)},
    )
    try:
        async with inbound_typing_indicator(wabot, inbound, settings):
            result = await run_agent(
                inbound.text,
                settings=settings,
                memory=memory,
                event_log=event_log,
                wabot=wabot,
                inbound=inbound,
                session_id=inbound_session_id(inbound),
            )
    except Exception as exc:
        memory.fail_message(inbound.id, str(exc))
        event_log.write(
            "inbound_message_failed",
            {"message_id": inbound.id, "sender": inbound.sender, "error": str(exc)},
        )
        error_reply = await deliver_inbound_error_reply(
            settings=settings,
            wabot=wabot,
            inbound=inbound,
            error=str(exc),
        )
        if error_reply.get("sent"):
            event_log.write(
                "auto_reply_sent",
                {
                    "message_id": inbound.id,
                    "sender": inbound.sender,
                    "to": error_reply.get("to"),
                    "policy": error_reply.get("policy"),
                    "reason": "agent_error_fallback",
                },
            )
        hub.publish(
            "inbound_agent_failed",
            {
                "message_id": inbound.id,
                "sender": inbound.sender,
                "error": redact(str(exc)),
            },
        )
        # Message is already in inbound_messages; do not fail the webhook or
        # wabot will treat delivery as unsuccessful and the inbox stays empty.
        return {
            "accepted": True,
            "duplicate": False,
            "message_id": inbound.id,
            "auto_reply": error_reply,
            "agent_error": redact(str(exc)),
        }
    memory.complete_message(inbound.id, result.run_id)
    auto = await deliver_auto_reply(
        settings=settings,
        wabot=wabot,
        inbound=inbound,
        result=result,
    )
    if auto.get("sent"):
        event_log.write(
            "auto_reply_sent",
            {
                "message_id": inbound.id,
                "sender": inbound.sender,
                "to": auto.get("to"),
                "policy": auto.get("policy"),
            },
        )
    return {
        "accepted": True,
        "duplicate": False,
        "message_id": inbound.id,
        "run_id": result.run_id,
        "output": result.final_output,
        "auto_reply": auto,
    }


def register_inbound_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    memory = deps.memory
    hub = deps.hub
    event_log = deps.event_log

    # Reconstruct inbound auth dependency — same pattern as human_dependency in other modules.
    async def _verify_inbound_auth_dep(
        authorization: str | None = Header(default=None),
    ) -> None:
        """FastAPI dependency wrapper for ``_verify_inbound_auth``.

        Centralising this on every ``/whatsapp/*`` route means the WABOT_INBOUND_TOKEN
        check happens consistently before any handler body runs (CLAUDE.md / MASTER §3).
        """
        _verify_inbound_auth(settings, authorization)

    inbound_auth_dependency = Depends(_verify_inbound_auth_dep)

    # Per-session serialisation locks — one lock per inbound session_id so concurrent
    # webhooks for the same chat queue behind each other without blocking unrelated chats.
    inbound_locks: dict[str, asyncio.Lock] = {}
    inbound_locks_guard = asyncio.Lock()

    async def _inbound_session_lock(session_key: str) -> asyncio.Lock:
        async with inbound_locks_guard:
            lock = inbound_locks.get(session_key)
            if lock is None:
                lock = asyncio.Lock()
                inbound_locks[session_key] = lock
            return lock

    @router.post("/whatsapp/inbound", dependencies=[inbound_auth_dependency])
    async def whatsapp_inbound(
        payload: InboundPayload,
        request: Request,
    ) -> dict[str, Any]:
        inbound = payload.to_inbound_message()
        session_key = inbound_session_id(inbound)
        lock = await _inbound_session_lock(session_key)
        if lock.locked():
            event_log.write(
                "inbound_message_queued",
                {"message_id": inbound.id, "sender": inbound.sender, "session_id": session_key},
            )
        async with lock:
            return await _process_whatsapp_inbound(inbound, request, deps=deps)

    @router.post("/whatsapp/receipt", dependencies=[inbound_auth_dependency])
    async def whatsapp_receipt(payload: ReceiptPayload) -> dict[str, Any]:
        body = payload.model_dump()
        hub.publish("whatsapp_receipt", body)
        event_log.write(
            "whatsapp_receipt",
            {
                "chat": payload.chat,
                "receipt_type": payload.receipt_type,
                "message_ids": payload.message_ids,
            },
        )
        return {"accepted": True}

    @router.post("/whatsapp/presence", dependencies=[inbound_auth_dependency])
    async def whatsapp_presence(payload: PresencePayload) -> dict[str, Any]:
        body = payload.model_dump()
        hub.publish("whatsapp_presence", body)
        event_log.write(
            "whatsapp_presence",
            {"chat": payload.chat, "sender": payload.sender, "state": payload.state},
        )
        return {"accepted": True}

    @router.post("/whatsapp/history-sync", dependencies=[inbound_auth_dependency])
    async def whatsapp_history_sync(
        payload: HistorySyncSummaryPayload,
    ) -> dict[str, Any]:
        body = payload.model_dump()
        hub.publish("whatsapp_history_sync", body)
        event_log.write(
            "whatsapp_history_sync",
            {
                "sync_type": payload.sync_type,
                "conversation_count": payload.conversation_count,
                "message_count": payload.message_count,
                "chunk_order": payload.chunk_order,
                "progress": payload.progress,
            },
        )
        return {"accepted": True}

    @router.post("/whatsapp/history", dependencies=[inbound_auth_dependency])
    async def whatsapp_history(payload: HistoryBatchPayload) -> dict[str, Any]:
        """Backfill inbound_messages from wabot history sync (no agent auto-reply)."""
        inbounds = [msg.to_inbound_message() for msg in payload.messages]
        result = memory.bulk_record_inbound(inbounds)
        hub.publish(
            "whatsapp_history_batch",
            {
                "sync_type": payload.sync_type,
                "stored": result["stored"],
                "chunk_order": payload.chunk_order,
                "progress": payload.progress,
            },
        )
        event_log.write(
            "whatsapp_history_batch",
            {
                "sync_type": payload.sync_type,
                "stored": result["stored"],
                "chunk_order": payload.chunk_order,
                "progress": payload.progress,
            },
        )
        return {"accepted": True, **result}
