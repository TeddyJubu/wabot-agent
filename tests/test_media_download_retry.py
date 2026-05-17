from __future__ import annotations

import httpx
import pytest

from wabot_agent.config import Settings
from wabot_agent.media_download import download_inbound_media
from wabot_agent.memory import InboundMessage
from wabot_agent.wabot import FakeWabotClient


class FlakyMediaFake(FakeWabotClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def download_media(self, chat: str, message_id: str) -> httpx.Response:
        self.calls += 1
        if self.calls < 3:
            return httpx.Response(404)
        return httpx.Response(
            200,
            headers={"Content-Type": "audio/ogg", "X-Media-Kind": "audio"},
            content=b"OggS",
        )


@pytest.mark.asyncio
async def test_download_inbound_media_retries_on_404(tmp_path) -> None:
    settings = Settings(
        media_dir=tmp_path / "media",
        data_dir=tmp_path / "data",
        media_download_attempts=4,
        media_download_retry_seconds=0,
        _env_file=None,
    )
    inbound = InboundMessage(
        id="m-audio",
        sender="user@lid",
        chat="user@lid",
        text="[audio]",
        has_media=True,
        media_kind="audio",
    )
    fake = FlakyMediaFake()
    result = await download_inbound_media(fake, inbound, settings)
    assert result.ok is True
    assert result.path is not None
    assert result.path.read_bytes() == b"OggS"
    assert fake.calls == 3


@pytest.mark.asyncio
async def test_download_inbound_media_gives_up_after_attempts(tmp_path) -> None:
    settings = Settings(
        media_dir=tmp_path / "media",
        data_dir=tmp_path / "data",
        media_download_attempts=2,
        media_download_retry_seconds=0,
        _env_file=None,
    )
    inbound = InboundMessage(
        id="m-miss",
        sender="user@lid",
        chat="user@lid",
        text="[audio]",
        has_media=True,
    )
    fake = FlakyMediaFake()
    result = await download_inbound_media(fake, inbound, settings)
    assert result.ok is False
    assert "cache" in (result.detail or "").lower()
    assert fake.calls == 2
