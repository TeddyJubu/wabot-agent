from __future__ import annotations

from pathlib import Path

import pytest

from wabot_agent.config import Settings
from wabot_agent.memory import InboundMessage
from wabot_agent.typing_indicator import inbound_typing_indicator
from wabot_agent.wabot import FakeWabotClient, WabotHealth


def _settings(tmp_path: Path, **kwargs: object) -> Settings:
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        OPENROUTER_MODEL="openai/gpt-5.2",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
        _env_file=None,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_typing_indicator_sends_composing_and_paused(tmp_path: Path) -> None:
    wabot = FakeWabotClient()
    settings = _settings(tmp_path, WABOT_AGENT_TYPING_INDICATOR=True)
    inbound = InboundMessage(
        id="m1",
        sender="+15550001111",
        text="hello",
        chat="+15550001111",
    )

    async with inbound_typing_indicator(wabot, inbound, settings):
        assert any(c["state"] == "composing" for c in wabot.typing_calls)

    assert wabot.typing_calls[-1]["state"] == "paused"
    assert wabot.typing_calls[-1]["to"] == "+15550001111"


@pytest.mark.asyncio
async def test_typing_indicator_skips_groups(tmp_path: Path) -> None:
    wabot = FakeWabotClient()
    settings = _settings(tmp_path)
    inbound = InboundMessage(
        id="m2",
        sender="+15550001111",
        text="hello",
        chat="120363@g.us",
        is_group=True,
    )

    async with inbound_typing_indicator(wabot, inbound, settings):
        pass

    assert wabot.typing_calls == []


@pytest.mark.asyncio
async def test_typing_indicator_disabled(tmp_path: Path) -> None:
    wabot = FakeWabotClient()
    settings = _settings(tmp_path, WABOT_AGENT_TYPING_INDICATOR=False)
    inbound = InboundMessage(
        id="m3",
        sender="+15550001111",
        text="hello",
        chat="+15550001111",
    )

    async with inbound_typing_indicator(wabot, inbound, settings):
        pass

    assert wabot.typing_calls == []


@pytest.mark.asyncio
async def test_typing_indicator_skips_when_wabot_not_ready(tmp_path: Path) -> None:
    wabot = FakeWabotClient()

    async def not_ready() -> WabotHealth:
        return WabotHealth(
            reachable=True, logged_in=False, connected=False, detail="not logged in"
        )

    wabot.health = not_ready  # type: ignore[method-assign]
    settings = _settings(tmp_path)
    inbound = InboundMessage(
        id="m4",
        sender="+15550001111",
        text="hello",
        chat="+15550001111",
    )

    async with inbound_typing_indicator(wabot, inbound, settings):
        pass

    assert wabot.typing_calls == []
