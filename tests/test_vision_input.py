from __future__ import annotations

import pytest

from wabot_agent.config import Settings
from wabot_agent.llm_provider import vision_supported
from wabot_agent.memory import InboundMessage
from wabot_agent.vision_input import inbound_is_image, prepare_runner_input
from wabot_agent.wabot import FakeWabotClient


@pytest.mark.asyncio
async def test_prepare_runner_input_attaches_image_for_gemma4() -> None:
    settings = Settings(
        model_provider="ollama_cloud",
        ollama_model="gemma4:31b-cloud",
        ollama_api_key="test",
        offline_mode=False,
        vision_attach_images=True,
        _env_file=None,
    )
    assert vision_supported(settings)
    inbound = InboundMessage(
        id="msg-1",
        sender="+8801521207499",
        chat="8801521207499@s.whatsapp.net",
        text="what is in this photo?",
        has_media=True,
        media_kind="image",
        media_mime="image/png",
    )
    wabot = FakeWabotClient()
    result = await prepare_runner_input(
        "augmented prompt",
        settings=settings,
        inbound=inbound,
        wabot=wabot,
    )
    assert isinstance(result, list)
    assert result[0]["role"] == "user"
    content = result[0]["content"]
    assert any(p.get("type") == "input_image" for p in content)
    assert any(p.get("type") == "input_text" for p in content)


@pytest.mark.asyncio
async def test_prepare_runner_input_text_only_without_media() -> None:
    settings = Settings(
        model_provider="ollama_cloud",
        ollama_model="gemma4:31b-cloud",
        ollama_api_key="test",
        offline_mode=False,
        _env_file=None,
    )
    inbound = InboundMessage(
        id="msg-2",
        sender="+1",
        chat="+1",
        text="hello",
        has_media=False,
    )
    result = await prepare_runner_input(
        "text only",
        settings=settings,
        inbound=inbound,
        wabot=FakeWabotClient(),
    )
    assert result == "text only"


def test_inbound_is_image() -> None:
    assert inbound_is_image(
        InboundMessage(id="1", sender="a", chat="a", text="", has_media=True, media_kind="image")
    )
    assert not inbound_is_image(
        InboundMessage(
            id="2", sender="a", chat="a", text="", has_media=True, media_kind="document"
        )
    )
