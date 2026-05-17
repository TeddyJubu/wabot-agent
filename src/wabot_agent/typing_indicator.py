from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from .auto_reply import inbound_reply_destination
from .config import Settings
from .memory import InboundMessage
from .wabot import WabotClient, WabotError

logger = logging.getLogger(__name__)


async def _send_typing(wabot: WabotClient, chat: str, state: str) -> None:
    try:
        await wabot.send_typing(chat, state=state)
    except WabotError as exc:
        logger.debug("typing indicator %s for %s failed: %s", state, chat, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("typing indicator %s for %s failed: %s", state, chat, exc)


async def _refresh_typing(
    wabot: WabotClient,
    chat: str,
    *,
    interval_sec: float,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        await _send_typing(wabot, chat, "composing")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_sec)
        except TimeoutError:
            continue


@contextlib.asynccontextmanager
async def inbound_typing_indicator(
    wabot: WabotClient,
    inbound: InboundMessage,
    settings: Settings,
) -> AsyncIterator[None]:
    """Show WhatsApp 'typing…' while the agent processes an inbound message."""
    if not settings.typing_indicator_enabled or inbound.is_group:
        yield
        return

    chat = inbound_reply_destination(inbound)
    if not chat:
        yield
        return

    health = await wabot.health()
    if not health.ready:
        yield
        return

    stop = asyncio.Event()
    refresh_task = asyncio.create_task(
        _refresh_typing(
            wabot,
            chat,
            interval_sec=max(2.0, float(settings.typing_refresh_seconds)),
            stop=stop,
        )
    )
    await _send_typing(wabot, chat, "composing")
    try:
        yield
    finally:
        stop.set()
        refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await refresh_task
        await _send_typing(wabot, chat, "paused")
