from __future__ import annotations

import httpx
import pytest

from wabot_agent.config import Settings
from wabot_agent.inbound_media import build_inbound_file_context
from wabot_agent.memory import InboundMessage
from wabot_agent.wabot import FakeWabotClient


class DocFake(FakeWabotClient):
    async def download_media(self, chat: str, message_id: str) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/pdf",
                "X-Media-Kind": "document",
            },
            content=b"%PDF-1.4 fake",
        )


@pytest.mark.asyncio
async def test_build_inbound_file_context_includes_excerpt(tmp_path) -> None:
    settings = Settings(
        media_dir=tmp_path / "media",
        data_dir=tmp_path / "data",
        file_process_inbound=True,
        _env_file=None,
    )
    inbound = InboundMessage(
        id="m1",
        sender="+1",
        chat="1@s.whatsapp.net",
        text="see attached",
        has_media=True,
        media_kind="document",
        media_mime="application/pdf",
    )
    ctx = await build_inbound_file_context(
        inbound, settings=settings, wabot=DocFake()
    )
    assert "VPS file processing" in ctx
    assert "saved_path" in ctx
