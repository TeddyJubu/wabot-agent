from __future__ import annotations

import base64

from agents.items import TResponseInputItem

from .config import Settings
from .llm_provider import active_model_id, vision_supported
from .media_download import MediaDownloadResult, download_inbound_media
from .memory import InboundMessage
from .wabot import WabotClient

MAX_VISION_BYTES = 5 * 1024 * 1024


def inbound_is_image(inbound: InboundMessage) -> bool:
    if not inbound.has_media:
        return False
    kind = (inbound.media_kind or "").lower()
    if kind == "image" or kind.startswith("image"):
        return True
    mime = (inbound.media_mime or "").lower()
    return mime.startswith("image/")


async def fetch_inbound_image_data_url(
    wabot: WabotClient,
    inbound: InboundMessage,
    settings: Settings,
    *,
    downloaded: MediaDownloadResult | None = None,
) -> str | None:
    """Download inbound image bytes and return a data: URL for the vision API."""
    if downloaded is None:
        downloaded = await download_inbound_media(wabot, inbound, settings)
    if not downloaded.ok or downloaded.path is None:
        return None
    if downloaded.bytes > MAX_VISION_BYTES:
        return None
    mime = (downloaded.mime or inbound.media_mime or "image/jpeg").split(";", 1)[0].strip()
    if not mime.startswith("image/"):
        return None
    encoded = base64.standard_b64encode(downloaded.path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def prepare_runner_input(
    augmented_text: str,
    *,
    settings: Settings,
    inbound: InboundMessage | None,
    wabot: WabotClient,
    downloaded: MediaDownloadResult | None = None,
) -> str | list[TResponseInputItem]:
    """Text prompt, or multimodal input when an inbound image can be attached."""
    if inbound is None or not settings.vision_attach_images or not vision_supported(settings):
        return augmented_text
    if not inbound_is_image(inbound):
        return augmented_text

    data_url = await fetch_inbound_image_data_url(
        wabot, inbound, settings, downloaded=downloaded
    )
    if not data_url:
        return (
            augmented_text
            + "\n\n(An image was attached but could not be loaded for vision — it may have "
            "expired from wabot cache. Ask the user to resend if needed.)"
        )

    model = active_model_id(settings)
    note = (
        f"\n\n[The user's image is attached below for model {model}. Describe what you see "
        "and answer their message. Do not say you cannot see images.]"
    )
    return [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": augmented_text + note},
                {"type": "input_image", "image_url": data_url, "detail": "auto"},
            ],
        }
    ]
