from __future__ import annotations

import re

from .config import Settings
from .file_processing import process_file_at_path
from .media_download import download_inbound_media
from .memory import InboundMessage
from .recipients import is_owner_inbound
from .vision_input import inbound_is_image
from .wabot import WabotClient

_VOICE_TRANSCRIPT_RE = re.compile(
    r"^- voice_transcript:\s*(.+)$", re.MULTILINE
)


def voice_transcript_from_context(context: str) -> str | None:
    match = _VOICE_TRANSCRIPT_RE.search(context)
    if not match:
        return None
    text = match.group(1).strip()
    return text or None


async def build_inbound_file_context(
    inbound: InboundMessage | None,
    *,
    settings: Settings,
    wabot: WabotClient,
) -> str:
    """Download and process inbound attachments on the VPS; return prompt context."""
    if inbound is None or not inbound.has_media or not settings.file_process_inbound:
        return ""
    if inbound.is_group and not settings.group_process_media:
        return ""

    downloaded = await download_inbound_media(wabot, inbound, settings)
    if not downloaded.ok or downloaded.path is None:
        return (
            "\n\n[Inbound attachment could not be downloaded from wabot cache. "
            f"{downloaded.detail or 'unknown error'}]"
        )

    is_owner = is_owner_inbound(settings, inbound)
    processed = process_file_at_path(
        downloaded.path,
        mime=downloaded.mime,
        excerpt_limit=settings.file_excerpt_limit,
        max_bytes=settings.file_max_process_bytes,
        settings=settings,
        is_owner=is_owner,
    )
    lines = [
        "\n\n[VPS file processing — inbound attachment]",
        f"- saved_path: {processed.get('path', downloaded.path)}",
        f"- kind: {processed.get('kind', downloaded.media_kind)}",
        f"- bytes: {processed.get('bytes', downloaded.bytes)}",
        f"- mime: {processed.get('mime') or downloaded.mime or ''}",
    ]
    if is_owner:
        lines.append(
            f"- whisper: {settings.whisper_model_owner} (owner); "
            f"others use {settings.whisper_model}"
        )
    if processed.get("summary"):
        lines.append(f"- summary: {processed['summary']}")
    for warning in processed.get("warnings") or []:
        lines.append(f"- warning: {warning}")
    if processed.get("excerpt"):
        lines.append("- excerpt:\n" + str(processed["excerpt"]))
    excerpt_text = str(processed.get("excerpt") or "")
    if "[transcript]:" in excerpt_text:
        for line in excerpt_text.splitlines():
            if line.startswith("[transcript]:"):
                lines.append(f"- voice_transcript: {line.removeprefix('[transcript]:').strip()}")
                break
    if not processed.get("ok"):
        lines.append(f"- processing_error: {processed.get('detail', 'failed')}")
    elif inbound.media_kind == "audio" and "[transcript]:" not in excerpt_text:
        lines.append(
            "- processing_error: audio downloaded but speech-to-text produced no transcript "
            "(check whisper warnings above)."
        )
    if inbound_is_image(inbound):
        lines.append(
            "- note: image pixels are also attached for vision when the model supports it."
        )
    lines.append(
        "- tools: process_vps_file(path), send_whatsapp_file(to, path) for follow-up actions."
    )
    return "\n".join(lines)
