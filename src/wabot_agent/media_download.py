from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import Settings
from .media_paths import filename_from_content_disposition, safe_media_segment
from .memory import InboundMessage
from .wabot import WabotClient, WabotError


@dataclass(frozen=True)
class MediaDownloadResult:
    ok: bool
    path: Path | None = None
    bytes: int = 0
    media_kind: str | None = None
    mime: str | None = None
    detail: str | None = None


def _extension_for_mime(mime: str) -> str:
    lowered = mime.lower()
    if "png" in lowered:
        return ".png"
    if "gif" in lowered:
        return ".gif"
    if "webp" in lowered:
        return ".webp"
    if "pdf" in lowered:
        return ".pdf"
    if "video/" in lowered:
        return ".mp4"
    if "audio/" in lowered:
        return ".ogg"
    if "image/" in lowered:
        return ".jpg"
    return ".bin"


async def download_media_message(
    wabot: WabotClient,
    chat: str,
    message_id: str,
    settings: Settings,
    *,
    filename: str | None = None,
    media_kind: str | None = None,
    media_mime: str | None = None,
) -> MediaDownloadResult:
    inbound = InboundMessage(
        id=message_id,
        sender=chat,
        chat=chat,
        text="",
        media_kind=media_kind,
        media_mime=media_mime,
        has_media=True,
    )
    return await download_inbound_media(wabot, inbound, settings, filename=filename)


async def download_inbound_media(
    wabot: WabotClient,
    inbound: InboundMessage,
    settings: Settings,
    *,
    filename: str | None = None,
) -> MediaDownloadResult:
    """Download a recent inbound attachment from wabot into media_dir/inbound/."""
    chat = (inbound.chat or inbound.sender).strip()
    if not chat:
        return MediaDownloadResult(ok=False, detail="missing chat")
    try:
        resp = await wabot.download_media(chat=chat, message_id=inbound.id)
    except WabotError as exc:
        return MediaDownloadResult(ok=False, detail=str(exc))

    if resp.status_code == 404:
        return MediaDownloadResult(
            ok=False,
            detail=(
                "Media not in wabot cache. Only recent inbound media can be downloaded; "
                "ensure the message was received while wabot was running."
            ),
        )
    if resp.status_code >= 400:
        return MediaDownloadResult(
            ok=False,
            detail=f"wabot returned HTTP {resp.status_code}: {resp.text[:200]}",
        )

    media_kind = resp.headers.get("X-Media-Kind", inbound.media_kind or "media")
    mime = (resp.headers.get("Content-Type") or inbound.media_mime or "").split(";", 1)[
        0
    ].strip()
    suggested = filename or inbound.media_filename or filename_from_content_disposition(
        resp.headers.get("Content-Disposition", "")
    )
    if not suggested:
        suggested = f"{safe_media_segment(inbound.id)}{_extension_for_mime(mime)}"

    dest_dir = settings.media_dir.resolve() / "inbound" / safe_media_segment(chat)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_media_segment(suggested)
    dest_path.write_bytes(resp.content)

    return MediaDownloadResult(
        ok=True,
        path=dest_path,
        bytes=len(resp.content),
        media_kind=media_kind,
        mime=mime or None,
    )
