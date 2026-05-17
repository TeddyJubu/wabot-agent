from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .config import Settings

logger = logging.getLogger(__name__)

_RESULT_LINK_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    kind: str = "page"


def _normalize_ddg_href(href: str) -> str | None:
    href = unescape(href.strip())
    if href.startswith("//"):
        href = f"https:{href}"
    if "duckduckgo.com/l/?" in href or "duckduckgo.com/l?" in href:
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        targets = params.get("uddg") or params.get("u")
        if targets:
            return unquote(targets[0])
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return None


def parse_duckduckgo_html(html: str, *, max_results: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen: set[str] = set()
    for match in _RESULT_LINK_RE.finditer(html):
        url = _normalize_ddg_href(match.group(1))
        if not url or url in seen:
            continue
        if "duckduckgo.com" in urlparse(url).netloc:
            continue
        title = _TAG_RE.sub("", match.group(2))
        title = unescape(title).strip()
        if not title:
            continue
        seen.add(url)
        results.append(SearchResult(title=title, url=url))
        if len(results) >= max_results:
            break
    return results


def _search_via_ddgs(
    query: str,
    *,
    max_results: int,
    images: bool,
) -> list[SearchResult]:
    from ddgs import DDGS

    results: list[SearchResult] = []
    with DDGS() as ddgs:
        if images:
            rows = ddgs.images(query, max_results=max_results)
            for row in rows:
                url = (row.get("image") or row.get("url") or "").strip()
                if not url.startswith("http"):
                    continue
                title = (row.get("title") or row.get("source") or "image").strip()
                results.append(SearchResult(title=title, url=url, kind="image"))
        else:
            rows = ddgs.text(query, max_results=max_results)
            for row in rows:
                url = (row.get("href") or row.get("url") or "").strip()
                if not url.startswith("http"):
                    continue
                title = (row.get("title") or url).strip()
                body = (row.get("body") or "").strip()
                results.append(SearchResult(title=title, url=url, snippet=body, kind="page"))
    return results[:max_results]


async def _search_via_html(
    settings: Settings,
    query: str,
    *,
    max_results: int,
) -> list[SearchResult]:
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=float(settings.web_fetch_timeout_sec),
        headers={"User-Agent": settings.web_fetch_user_agent},
    ) as client:
        resp = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
        )
    if resp.status_code >= 400:
        return []
    return parse_duckduckgo_html(resp.text, max_results=max_results)


async def search_web(
    settings: Settings,
    query: str,
    *,
    max_results: int | None = None,
    images: bool = False,
) -> tuple[list[SearchResult], str | None]:
    """Search the public web via duckduckgo-search (falls back to HTML scrape)."""
    if not settings.web_search_enabled:
        return [], "web search is disabled (WABOT_AGENT_WEB_SEARCH_ENABLED)"

    q = query.strip()
    if not q:
        return [], "empty search query"

    limit = max_results if max_results is not None else settings.web_search_max_results
    limit = max(1, min(limit, 15))

    try:
        results = _search_via_ddgs(q, max_results=limit, images=images)
        if results:
            return results, None
    except Exception as exc:  # noqa: BLE001
        logger.warning("ddgs search failed, trying HTML fallback: %s", exc)

    if images:
        return [], (
            "image search unavailable (install duckduckgo-search or try a direct image URL)"
        )

    try:
        results = await _search_via_html(settings, q, max_results=limit)
    except httpx.HTTPError as exc:
        return [], f"search request failed: {exc}"

    if not results:
        return [], "no results (try a direct URL with fetch_url_to_media)"
    return results, None
