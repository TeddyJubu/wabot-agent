from __future__ import annotations

from pathlib import Path

import httpx
from agents.tool import ToolContext

from wabot_agent.config import Settings
from wabot_agent.events import EventLog
from wabot_agent.memory import MemoryStore
from wabot_agent.tools import (
    RuntimeContext,
    download_whatsapp_media,
    send_whatsapp_document,
)
from wabot_agent.wabot import FakeWabotClient


class DownloadFake(FakeWabotClient):
    async def download_media(self, chat: str, message_id: str) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/pdf",
                "X-Media-Kind": "document",
                "Content-Disposition": 'attachment; filename="note.pdf"',
            },
            content=b"%PDF-1.4",
        )


async def test_download_whatsapp_media_writes_under_media_dir(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    tmp_path: Path,
) -> None:
    media_settings = settings.model_copy(update={"media_dir": tmp_path / "media"})
    client = DownloadFake()
    ctx = ToolContext(
        RuntimeContext(media_settings, memory, client, event_log, run_id="run-media-dl"),
        tool_name="download_whatsapp_media",
        tool_call_id="call-dl",
        tool_arguments="{}",
    )

    result = await download_whatsapp_media.on_invoke_tool(
        ctx,
        '{"chat":"+15550001111@s.whatsapp.net","message_id":"abc-123"}',
    )

    assert result["ok"] is True
    saved = Path(result["path"])
    assert saved.is_file()
    assert saved.read_bytes() == b"%PDF-1.4"
    assert "inbound" in saved.parts


async def test_send_whatsapp_document_allowlisted(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    tmp_path: Path,
) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    doc = media_dir / "brief.pdf"
    doc.write_bytes(b"%PDF")

    live_settings = settings.model_copy(
        update={
            "send_policy": "allowlist",
            "allowed_recipients": {"+15550001111"},
            "media_dir": media_dir,
        }
    )
    fake = FakeWabotClient()
    ctx = ToolContext(
        RuntimeContext(live_settings, memory, fake, event_log, run_id="run-doc"),
        tool_name="send_whatsapp_document",
        tool_call_id="call-doc",
        tool_arguments="{}",
    )

    result = await send_whatsapp_document.on_invoke_tool(
        ctx,
        f'{{"to":"+15550001111","path":"{doc}"}}',
    )

    assert result["sent"] is True
    assert fake.sent[-1]["type"] == "document"


async def test_send_whatsapp_document_rejects_outside_media_dir(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
) -> None:
    live_settings = settings.model_copy(
        update={"send_policy": "allowlist", "allowed_recipients": {"+15550001111"}}
    )
    ctx = ToolContext(
        RuntimeContext(live_settings, memory, FakeWabotClient(), event_log, run_id="run-doc2"),
        tool_name="send_whatsapp_document",
        tool_call_id="call-doc2",
        tool_arguments="{}",
    )

    result = await send_whatsapp_document.on_invoke_tool(
        ctx,
        '{"to":"+15550001111","path":"/tmp/outside.pdf"}',
    )

    assert result["sent"] is False
    assert result["reason"] == "media_path_not_allowed"
