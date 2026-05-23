from __future__ import annotations

from typing import Any

from agents import RunContextWrapper, function_tool

from ..redaction import redact
from ..web_agent import web_agent_health
from ..web_search import search_web as duckduckgo_search
from ._common import RuntimeContext, _is_owner_session, _requester_jid


@function_tool
async def web_research_health(
    ctx: RunContextWrapper[RuntimeContext],
) -> dict[str, Any]:
    """Check whether the Firecrawl web-agent sidecar (Express /v1/run) is reachable."""
    payload = await web_agent_health(ctx.context.settings)
    ctx.context.memory.record_tool_event(ctx.context.run_id, "web_research_health", payload)
    return redact(payload)


@function_tool
async def search_web(
    ctx: RunContextWrapper[RuntimeContext],
    query: str,
    max_results: int = 8,
) -> dict[str, Any]:
    """Search the public web (DuckDuckGo). Use before fetch_url_to_media when you need a URL."""
    results, error = await duckduckgo_search(
        ctx.context.settings,
        query,
        max_results=max_results,
        images=False,
    )
    payload: dict[str, Any] = {
        "ok": error is None,
        "query": query,
        "results": [
            {"title": r.title, "url": r.url, "snippet": r.snippet, "kind": r.kind}
            for r in results
        ],
    }
    if error:
        payload["detail"] = error
    ctx.context.memory.record_tool_event(ctx.context.run_id, "search_web", payload)
    return redact(payload)


@function_tool
async def search_images(
    ctx: RunContextWrapper[RuntimeContext],
    query: str,
    max_results: int = 6,
) -> dict[str, Any]:
    """Search for image URLs on the web. Use for logos/photos, then fetch_url_to_media + send."""
    results, error = await duckduckgo_search(
        ctx.context.settings,
        query,
        max_results=max_results,
        images=True,
    )
    payload: dict[str, Any] = {
        "ok": error is None,
        "query": query,
        "results": [{"title": r.title, "url": r.url, "kind": "image"} for r in results],
    }
    if error:
        payload["detail"] = error
    ctx.context.memory.record_tool_event(ctx.context.run_id, "search_images", payload)
    return redact(payload)


@function_tool
async def start_web_research(
    ctx: RunContextWrapper[RuntimeContext],
    prompt: str,
    title: str | None = None,
    output_format: str = "csv",
    output_schema_json: str | None = None,
) -> dict[str, Any]:
    """Start a long-running Firecrawl web-agent research job (results sent on WhatsApp when done).

    Use for structured lead lists, multi-page scraping, and deep web research. Pass the full
    research brief in prompt (targets, exclusions, columns, output headers). output_format:
    csv | markdown | json. For json, pass output_schema_json as a JSON Schema string.
    """
    requester = _requester_jid(ctx)
    if requester is None:
        payload = {"created": False, "reason": "no_inbound_requester"}
        ctx.context.memory.record_tool_event(ctx.context.run_id, "start_web_research", payload)
        return payload

    if not ctx.context.settings.web_agent_enabled:
        payload = {"created": False, "reason": "web_agent_disabled"}
        ctx.context.memory.record_tool_event(ctx.context.run_id, "start_web_research", payload)
        return payload

    if ctx.context.settings.web_agent_owner_only and not _is_owner_session(
        ctx.context.settings, ctx.context.inbound
    ):
        payload = {"created": False, "reason": "owner_only"}
        ctx.context.memory.record_tool_event(ctx.context.run_id, "start_web_research", payload)
        return payload

    pending = ctx.context.memory.count_web_research_jobs(
        requester_jid=requester, status="pending"
    )
    running = ctx.context.memory.count_web_research_jobs(
        requester_jid=requester, status="running"
    )
    cap = ctx.context.settings.web_agent_max_pending_per_contact
    if pending + running >= cap:
        payload = {
            "created": False,
            "reason": "pending_limit",
            "pending": pending,
            "running": running,
            "limit": cap,
        }
        ctx.context.memory.record_tool_event(ctx.context.run_id, "start_web_research", payload)
        return payload

    fmt = output_format.strip().lower()
    if fmt not in {"csv", "markdown", "json"}:
        fmt = "markdown"

    payload = ctx.context.memory.create_web_research_job(
        requester_jid=requester,
        prompt=prompt.strip(),
        title=title.strip() if title else None,
        output_format=fmt,
        schema_json=output_schema_json,
    )
    payload["message"] = (
        "Research job queued. You will receive a WhatsApp summary and file when it completes."
    )
    ctx.context.memory.record_tool_event(ctx.context.run_id, "start_web_research", payload)
    ctx.context.event_log.write("web_research_queued", redact(payload))
    return redact(payload)


@function_tool
async def get_web_research_status(
    ctx: RunContextWrapper[RuntimeContext],
    job_id: str,
) -> dict[str, Any]:
    """Get status, preview, and result path for a web research job."""
    job = ctx.context.memory.get_web_research_job(job_id)
    requester = _requester_jid(ctx)
    if job is None:
        payload = {"found": False, "id": job_id}
    elif requester and job.get("requester_jid") != requester:
        payload = {"found": False, "id": job_id, "reason": "not_your_job"}
    else:
        payload = {"found": True, **job}
    ctx.context.memory.record_tool_event(
        ctx.context.run_id, "get_web_research_status", {"id": job_id, "found": job is not None}
    )
    return redact(payload)


@function_tool
async def list_web_research_jobs(
    ctx: RunContextWrapper[RuntimeContext],
    status: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """List web research jobs for the current requester."""
    requester = _requester_jid(ctx)
    rows = ctx.context.memory.list_web_research_jobs(
        requester_jid=requester,
        status=status,
        limit=limit,
    )
    payload = {"count": len(rows), "jobs": rows}
    ctx.context.memory.record_tool_event(ctx.context.run_id, "list_web_research_jobs", payload)
    return redact(payload)


@function_tool
async def cancel_web_research(
    ctx: RunContextWrapper[RuntimeContext],
    job_id: str,
) -> dict[str, Any]:
    """Cancel a pending web research job."""
    requester = _requester_jid(ctx)
    payload = ctx.context.memory.cancel_web_research_job(
        job_id, requester_jid=requester
    )
    ctx.context.memory.record_tool_event(ctx.context.run_id, "cancel_web_research", payload)
    return redact(payload)
