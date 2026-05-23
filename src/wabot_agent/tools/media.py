from __future__ import annotations

from typing import Any

from agents import RunContextWrapper, function_tool

from ..file_processing import process_file_at_path
from ..media_download import download_media_message
from ..media_paths import workspace_path_allowed
from ..redaction import redact
from ..web_fetch import fetch_url_to_media as download_url_to_media
from ._common import RuntimeContext, _is_owner_session, _wabot_ready_or_block


@function_tool
async def download_whatsapp_media(
    ctx: RunContextWrapper[RuntimeContext],
    chat: str,
    message_id: str,
    filename: str | None = None,
) -> dict[str, Any]:
    """Download inbound WhatsApp media to WABOT_AGENT_MEDIA_DIR (recent messages only)."""
    downloaded = await download_media_message(
        ctx.context.wabot,
        chat,
        message_id,
        ctx.context.settings,
        filename=filename,
    )
    if not downloaded.ok or downloaded.path is None:
        payload = {"ok": False, "detail": downloaded.detail}
    else:
        payload = {
            "ok": True,
            "path": str(downloaded.path),
            "bytes": downloaded.bytes,
            "media_kind": downloaded.media_kind,
            "mime": downloaded.mime,
            "chat": chat,
            "message_id": message_id,
        }
    ctx.context.memory.record_tool_event(ctx.context.run_id, "download_whatsapp_media", payload)
    if payload.get("ok"):
        redacted = redact({k: v for k, v in payload.items() if k != "path"})
        redacted["path"] = payload["path"]
        return redacted
    return redact(payload)


@function_tool
async def download_whatsapp_profile_picture(
    ctx: RunContextWrapper[RuntimeContext],
    jid: str,
    preview: bool = False,
    filename: str | None = None,
) -> dict[str, Any]:
    """Download a contact or group profile picture to WABOT_AGENT_MEDIA_DIR/avatars/."""
    blocked = await _wabot_ready_or_block(ctx, "download_whatsapp_profile_picture")
    if blocked is not None:
        return blocked
    try:
        resp = await ctx.context.wabot.get_user_picture(jid, preview=preview)
    except Exception as exc:
        payload = {"ok": False, "detail": str(exc)}
        ctx.context.memory.record_tool_event(
            ctx.context.run_id, "download_whatsapp_profile_picture", payload
        )
        return payload

    if resp.status_code == 404:
        payload = {"ok": False, "detail": "no profile picture"}
    elif resp.status_code >= 400:
        payload = {"ok": False, "detail": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    elif "application/json" in (resp.headers.get("content-type") or ""):
        payload = {"ok": True, "unchanged": True, "result": resp.json()}
    else:
        avatars = ctx.context.settings.media_dir / "avatars"
        avatars.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in jid)[:120]
        ext = ".jpg"
        if "png" in (resp.headers.get("content-type") or ""):
            ext = ".png"
        out_name = filename or f"{safe}{ext}"
        out_path = avatars / out_name
        out_path.write_bytes(resp.content)
        payload = {
            "ok": True,
            "path": str(out_path),
            "picture_id": resp.headers.get("X-Picture-ID"),
            "preview": preview,
        }
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "download_whatsapp_profile_picture", payload
    )
    return redact(payload)


@function_tool
async def process_vps_file(
    ctx: RunContextWrapper[RuntimeContext], path: str
) -> dict[str, Any]:
    """Read and summarize a file on the VPS (under media/ or data/)."""
    allowed, safe_path, reason = workspace_path_allowed(ctx.context.settings, path)
    if not allowed or safe_path is None:
        payload = {"ok": False, "detail": reason}
    else:
        payload = process_file_at_path(
            safe_path,
            excerpt_limit=ctx.context.settings.file_excerpt_limit,
            max_bytes=ctx.context.settings.file_max_process_bytes,
            settings=ctx.context.settings,
            is_owner=_is_owner_session(ctx.context.settings, ctx.context.inbound),
        )
    ctx.context.memory.record_tool_event(ctx.context.run_id, "process_vps_file", payload)
    return redact(payload)


@function_tool
async def process_whatsapp_attachment(
    ctx: RunContextWrapper[RuntimeContext],
    chat: str,
    message_id: str,
    filename: str | None = None,
) -> dict[str, Any]:
    """Download a WhatsApp attachment and extract text/metadata on the VPS."""
    downloaded = await download_media_message(
        ctx.context.wabot,
        chat,
        message_id,
        ctx.context.settings,
        filename=filename,
    )
    if not downloaded.ok or downloaded.path is None:
        payload = {"ok": False, "detail": downloaded.detail}
    else:
        payload = process_file_at_path(
            downloaded.path,
            mime=downloaded.mime,
            excerpt_limit=ctx.context.settings.file_excerpt_limit,
            max_bytes=ctx.context.settings.file_max_process_bytes,
            settings=ctx.context.settings,
            is_owner=_is_owner_session(ctx.context.settings, ctx.context.inbound),
        )
        payload["download_path"] = str(downloaded.path)
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "process_whatsapp_attachment", payload
    )
    return redact(payload)


@function_tool
async def fetch_url_to_media(
    ctx: RunContextWrapper[RuntimeContext],
    url: str,
    filename: str | None = None,
    prefer_page_image: bool = False,
) -> dict[str, Any]:
    """Download a public http(s) URL into the VPS media directory; then send_whatsapp_file(path).

    Set prefer_page_image=True for homepages (uses og:image when the URL returns HTML).
    """
    fetched = await download_url_to_media(
        ctx.context.settings,
        url,
        filename=filename,
        prefer_page_image=prefer_page_image,
    )
    if not fetched.ok or fetched.path is None:
        payload = {"ok": False, "detail": fetched.detail, "url": fetched.url}
    else:
        payload = {
            "ok": True,
            "path": str(fetched.path),
            "bytes": fetched.bytes,
            "mime": fetched.mime,
            "url": fetched.url,
            "send_hint": "Call send_whatsapp_file or send_whatsapp_image with this path.",
        }
    ctx.context.memory.record_tool_event(ctx.context.run_id, "fetch_url_to_media", payload)
    if payload.get("ok"):
        redacted = redact({k: v for k, v in payload.items() if k != "path"})
        redacted["path"] = payload["path"]
        return redacted
    return redact(payload)
