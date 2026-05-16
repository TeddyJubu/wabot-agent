from __future__ import annotations

from pathlib import Path

from agents.tool import ToolContext

from wabot_agent.config import Settings
from wabot_agent.events import EventLog
from wabot_agent.memory import MemoryStore
from wabot_agent.tools import (
    RuntimeContext,
    download_whatsapp_profile_picture,
    get_whatsapp_user_info,
)
from wabot_agent.wabot import FakeWabotClient


async def test_get_user_info_when_ready(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(update={"send_policy": "allowlist", "allowed_recipients": set()})
    ctx = ToolContext(
        RuntimeContext(live, memory, fake_wabot, event_log, run_id="run-user-info"),
        tool_name="get_whatsapp_user_info",
        tool_call_id="call-user-info",
        tool_arguments="{}",
    )
    result = await get_whatsapp_user_info.on_invoke_tool(
        ctx, '{"jid":"15550001111@s.whatsapp.net"}'
    )
    assert result["ok"] is True
    assert result["user"]["status"] == "Available"
    assert result["user"]["verified_name"] == "Fake User"


async def test_download_profile_picture_saves_file(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    live = settings.model_copy(update={"send_policy": "allowlist", "allowed_recipients": set()})
    ctx = ToolContext(
        RuntimeContext(live, memory, fake_wabot, event_log, run_id="run-avatar"),
        tool_name="download_whatsapp_profile_picture",
        tool_call_id="call-avatar",
        tool_arguments="{}",
    )
    result = await download_whatsapp_profile_picture.on_invoke_tool(
        ctx, '{"jid":"15550001111@s.whatsapp.net"}'
    )
    assert result["ok"] is True
    assert result["picture_id"] == "fake-pic"
    avatars = settings.media_dir / "avatars"
    saved = list(avatars.glob("*.jpg"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"fake-avatar-bytes"
