from __future__ import annotations

from typing import Any

import httpx

from .config import Settings
from .redaction import redact


class WebAgentError(RuntimeError):
    pass


async def web_agent_health(settings: Settings) -> dict[str, Any]:
    """Probe the Firecrawl web-agent Express service (GET /)."""
    if not settings.web_agent_enabled:
        return {"ok": False, "reason": "disabled"}
    url = settings.web_agent_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": "unreachable", "detail": redact(str(exc))}
    return {
        "ok": True,
        "status": data.get("status"),
        "model": data.get("model"),
        "routes": data.get("routes"),
    }


async def run_web_agent(
    settings: Settings,
    *,
    prompt: str,
    output_format: str = "markdown",
    schema: dict[str, Any] | None = None,
    max_steps: int | None = None,
) -> dict[str, Any]:
    """Run Firecrawl web-agent POST /v1/run (blocking until complete)."""
    if not settings.web_agent_enabled:
        raise WebAgentError("web agent is disabled (WABOT_AGENT_WEB_AGENT_ENABLED)")

    body: dict[str, Any] = {
        "prompt": prompt,
        "format": output_format if output_format in {"json", "markdown"} else "markdown",
        "stream": False,
    }
    if schema is not None:
        body["format"] = "json"
        body["schema"] = schema
    if max_steps is not None:
        body["maxSteps"] = max_steps

    url = f"{settings.web_agent_url.rstrip('/')}/v1/run"
    timeout = httpx.Timeout(settings.web_agent_timeout_sec)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body)
            if resp.status_code >= 400:
                raise WebAgentError(
                    f"web-agent HTTP {resp.status_code}: {redact(resp.text[:500])}"
                )
            return resp.json()
    except httpx.TimeoutException as exc:
        raise WebAgentError(
            f"web-agent timed out after {settings.web_agent_timeout_sec}s"
        ) from exc
    except httpx.HTTPError as exc:
        raise WebAgentError(redact(str(exc))) from exc
