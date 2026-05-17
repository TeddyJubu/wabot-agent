from __future__ import annotations

import ipaddress
import re
import socket
from html import unescape
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, unquote, urlparse

import httpx

from .config import Settings
from .media_download import _extension_for_mime
from .media_paths import filename_from_content_disposition, safe_media_segment

_PRIVATE_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


@dataclass(frozen=True)
class FetchUrlResult:
    ok: bool
    path: Path | None = None
    bytes: int = 0
    mime: str | None = None
    url: str | None = None
    detail: str | None = None


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return True
    return any(ip in net for net in _PRIVATE_NETWORKS)


def validate_public_http_url(url: str) -> tuple[str, str]:
    """Return (normalized_url, hostname) or raise ValueError."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed.")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname.")
    host = parsed.hostname.lower()
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise ValueError("Hostname is not allowed.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port in {22, 25, 3306, 5432, 6379, 11211}:
            raise ValueError("Port is not allowed.")
    except ValueError as exc:
        raise ValueError("Invalid URL.") from exc

    try:
        addr_infos = socket.getaddrinfo(host, parsed.port or 0, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname: {host}") from exc

    for info in addr_infos:
        ip_str = info[4][0]
        ip = ipaddress.ip_address(ip_str)
        if _ip_is_blocked(ip):
            raise ValueError("URL resolves to a private or reserved address.")

    return url.strip(), host


_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_IMAGE_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image["\']',
    re.IGNORECASE,
)


def extract_og_image_url(html: str, page_url: str) -> str | None:
    for pattern in (_OG_IMAGE_RE, _OG_IMAGE_RE_ALT):
        match = pattern.search(html)
        if match:
            raw = unescape(match.group(1).strip())
            return urljoin(page_url, raw)
    return None


def _filename_from_url(url: str, content_type: str | None) -> str:
    path = urlparse(url).path
    name = unquote(Path(path).name) if path else ""
    if name and "." in name:
        return safe_media_segment(name)
    ext = _extension_for_mime(content_type or "")
    return f"download{ext}"


async def fetch_url_to_media(
    settings: Settings,
    url: str,
    *,
    filename: str | None = None,
    subdir: str = "downloads",
    prefer_page_image: bool = False,
) -> FetchUrlResult:
    """Download a public http(s) URL into media_dir/subdir/."""
    if not settings.web_fetch_enabled:
        return FetchUrlResult(ok=False, detail="web fetch is disabled (WABOT_AGENT_WEB_FETCH_ENABLED)")

    try:
        normalized, _host = validate_public_http_url(url)
    except ValueError as exc:
        return FetchUrlResult(ok=False, detail=str(exc))

    headers = {
        "User-Agent": settings.web_fetch_user_agent,
        "Accept": "*/*",
    }
    max_bytes = settings.web_fetch_max_bytes
    timeout = float(settings.web_fetch_timeout_sec)

    content_type = ""
    content_disposition = ""
    chunks: list[bytes] = []
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers=headers,
        ) as client:
            async with client.stream("GET", normalized) as resp:
                if resp.status_code >= 400:
                    return FetchUrlResult(
                        ok=False,
                        detail=f"HTTP {resp.status_code} fetching URL",
                        url=normalized,
                    )
                content_type = (resp.headers.get("content-type") or "").split(";", 1)[
                    0
                ].strip()
                content_disposition = resp.headers.get("content-disposition", "")
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return FetchUrlResult(
                            ok=False,
                            detail=f"Download exceeds {max_bytes} bytes limit",
                            url=normalized,
                        )
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        return FetchUrlResult(ok=False, detail=f"Download failed: {exc}", url=normalized)

    body = b"".join(chunks)
    if not body:
        return FetchUrlResult(ok=False, detail="Empty response body", url=normalized)

    if prefer_page_image and content_type.startswith("text/html"):
        try:
            html = body.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            html = ""
        og_url = extract_og_image_url(html, normalized) if html else None
        if og_url:
            nested = await fetch_url_to_media(
                settings,
                og_url,
                filename=filename,
                subdir=subdir,
                prefer_page_image=False,
            )
            if nested.ok:
                return nested
            return FetchUrlResult(
                ok=False,
                detail=nested.detail or "og:image download failed",
                url=og_url,
            )

    suggested = filename or filename_from_content_disposition(content_disposition)
    if not suggested:
        suggested = _filename_from_url(normalized, content_type)

    dest_dir = settings.media_dir.resolve() / safe_media_segment(subdir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_media_segment(suggested)
    dest_path.write_bytes(body)

    return FetchUrlResult(
        ok=True,
        path=dest_path,
        bytes=len(body),
        mime=content_type or None,
        url=normalized,
    )
