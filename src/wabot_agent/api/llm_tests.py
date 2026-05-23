"""LLM connectivity probes + the GET /api/settings view builder.

Carved out of ``api/__init__.py`` as part of MASTER ME-1. MASTER called this
module ``api/views.py``; I renamed it ``api/llm_tests.py`` because its content
is dominated by LLM connectivity probes and the settings view that surfaces
their state to the dashboard. None of these functions capture state from
``create_app``'s closure — they all take an explicit ``Settings``.

What lives here:

* ``_test_llm_endpoint(settings)`` — generic active-provider connectivity probe.
  Branches on ``settings.model_provider`` for codex (uses ``responses.create``
  with streaming) vs the OpenAI-compatible providers (GET ``/models``).
* ``_test_openrouter_endpoint(settings, payload)`` — dashboard "Test"
  button for OpenRouter. Takes a partial ``OpenRouterTestRequest`` snapshot so
  the operator can probe new credentials *without* persisting them; runs a
  chat-completions roundtrip that asks for "ok".
* ``_settings_view(settings)`` — builds the GET ``/api/settings`` response.
  Secrets are masked via ``mask_secret``; choice lists / provider labels are
  fixed source-of-truth lists.

Adding a new LLM provider: extend ``_test_llm_endpoint``'s branching and add
a corresponding section to ``_settings_view``. MASTER notes this is currently
the *only* growing pain in the provider seam (the rest of the LLM dispatch is
already clean via ``models.build_model`` + ``llm_provider.active_model_id``).
"""

from __future__ import annotations

import shutil
from typing import Any

from ..codex_auth import codex_request_headers, load_codex_credentials
from ..codex_models import (
    CODEX_REASONING_EFFORT_CHOICES,
    CODEX_REASONING_LABELS,
    codex_model_choices_for_settings,
)
from ..config import Settings
from ..llm_provider import (
    active_model_id,
    llm_default_headers,
    llm_provider_label,
    resolved_llm_api_key,
    resolved_llm_base_url,
)
from ..runtime_overrides import mask_secret
from .dependencies import _require_safe_openai_url, _require_safe_openrouter_url
from .schemas import OpenAITestRequest, OpenRouterTestRequest


async def _test_llm_endpoint(settings: Settings) -> dict[str, Any]:
    import httpx
    from openai import AsyncOpenAI
    from openai.types.responses import ResponseCompletedEvent

    label = llm_provider_label(settings)
    if not settings.live_model_enabled:
        if settings.model_provider == "openai":
            return {"ok": False, "detail": "OPENAI_API_KEY is not configured."}
        if settings.model_provider == "codex":
            return {
                "ok": False,
                "detail": (
                    "Codex / ChatGPT credentials are not configured. "
                    "Run `codex login` or set CODEX_ACCESS_TOKEN."
                ),
            }
        if settings.model_provider == "openrouter":
            return {"ok": False, "detail": "OPENROUTER_API_KEY is not configured."}
        if settings.model_provider == "ollama_cloud":
            return {"ok": False, "detail": "OLLAMA_API_KEY is not configured."}
        return {"ok": False, "detail": "Offline mode is enabled."}

    model = active_model_id(settings)
    if settings.model_provider == "codex":
        credentials = load_codex_credentials(settings)
        if credentials is None:
            return {"ok": False, "detail": "Codex credentials are missing."}
        client = AsyncOpenAI(
            api_key=credentials.access_token,
            base_url=resolved_llm_base_url(settings),
            default_headers=codex_request_headers(credentials),
        )
        try:
            stream = await client.responses.create(
                model=model,
                instructions="You are a connectivity probe.",
                input=[{"role": "user", "content": "Reply with exactly: ok"}],
                store=False,
                stream=True,
            )
            async for event in stream:
                if isinstance(event, ResponseCompletedEvent):
                    return {
                        "ok": True,
                        "detail": f"{label} reachable. Active model: {model}",
                    }
        except Exception as exc:
            return {"ok": False, "detail": f"{label} connection failed: {exc}"}
        return {"ok": False, "detail": f"{label} probe ended without a completed response."}

    url = resolved_llm_base_url(settings) + "/models"
    headers: dict[str, str] = {}
    api_key = resolved_llm_api_key(settings)
    if settings.model_provider != "ollama" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": f"{label} connection failed: {exc}"}
    if resp.status_code == 200:
        return {"ok": True, "detail": f"{label} reachable. Active model: {model}"}
    return {
        "ok": False,
        "detail": f"{label} returned HTTP {resp.status_code}: {resp.text[:200]}",
    }


async def _test_openai_endpoint(
    settings: Settings, payload: OpenAITestRequest
) -> dict[str, Any]:
    from openai import AsyncOpenAI

    snapshot = settings.model_copy(deep=True)
    snapshot.model_provider = "openai"
    snapshot.offline_mode = False

    if payload.base_url is not None:
        base_url = payload.base_url.strip()
        if base_url:
            _require_safe_openai_url("openai_base_url", base_url)
            snapshot.openai_base_url = base_url
    if payload.model is not None:
        model = payload.model.strip()
        if model:
            snapshot.openai_model = model
    if payload.api_key is not None:
        api_key = payload.api_key.strip()
        if api_key:
            snapshot.openai_api_key = api_key

    if not snapshot.openai_api_key:
        return {"ok": False, "detail": "OPENAI_API_KEY is not configured."}

    model = active_model_id(snapshot)
    client = AsyncOpenAI(
        api_key=snapshot.openai_api_key,
        base_url=snapshot.openai_base_url.rstrip("/"),
    )
    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            max_tokens=8,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"OpenAI connection failed: {exc}"}

    text = (completion.choices[0].message.content or "").strip() if completion.choices else ""
    if text.lower().strip(".") == "ok":
        return {
            "ok": True,
            "detail": f"OpenAI chat completions reachable. Active model: {model}",
        }
    return {
        "ok": True,
        "detail": f"OpenAI reachable. Active model: {model}; probe replied: {text[:80]}",
    }


async def _test_openrouter_endpoint(
    settings: Settings, payload: OpenRouterTestRequest
) -> dict[str, Any]:
    from openai import AsyncOpenAI

    snapshot = settings.model_copy(deep=True)
    snapshot.model_provider = "openrouter"
    snapshot.offline_mode = False

    if payload.base_url is not None:
        base_url = payload.base_url.strip()
        if base_url:
            _require_safe_openrouter_url("openrouter_base_url", base_url)
            snapshot.openrouter_base_url = base_url
    if payload.model is not None:
        model = payload.model.strip()
        if model:
            snapshot.openrouter_model = model
    if payload.api_key is not None:
        api_key = payload.api_key.strip()
        if api_key:
            snapshot.openrouter_api_key = api_key

    if not snapshot.openrouter_api_key:
        return {"ok": False, "detail": "OPENROUTER_API_KEY is not configured."}

    model = active_model_id(snapshot)
    client = AsyncOpenAI(
        api_key=snapshot.openrouter_api_key,
        base_url=snapshot.openrouter_base_url.rstrip("/"),
        default_headers=llm_default_headers(snapshot),
    )
    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            max_tokens=8,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"OpenRouter connection failed: {exc}"}

    text = (completion.choices[0].message.content or "").strip() if completion.choices else ""
    if text.lower().strip(".") == "ok":
        return {
            "ok": True,
            "detail": f"OpenRouter chat completions reachable. Active model: {model}",
        }
    return {
        "ok": True,
        "detail": f"OpenRouter reachable. Active model: {model}; probe replied: {text[:80]}",
    }


def _settings_view(settings: Settings) -> dict[str, Any]:
    """Build the GET /api/settings response: secrets masked, source-of-truth annotated."""
    return {
        "env_source": ".env (immutable) + data/runtime_overrides.json (operator-mutable)",
        "send_policy": settings.send_policy,
        "send_policy_choices": ["dry_run", "allowlist", "allow_all", "owner"],
        "allowed_recipients": sorted(settings.allowed_recipients),
        "owner_numbers": sorted(settings.owner_numbers),
        "auto_reply_enabled": settings.auto_reply_enabled,
        "max_agent_turns": settings.max_agent_turns,
        "llm": {
            "provider": settings.model_provider,
            "provider_choices": ["openai", "codex", "openrouter", "ollama", "ollama_cloud"],
            "model": active_model_id(settings),
            "label": llm_provider_label(settings),
            "live": settings.live_model_enabled,
        },
        "openai": {
            "api_key": mask_secret(settings.openai_api_key),
            "base_url": settings.openai_base_url,
            "model": settings.openai_model,
            "live": settings.model_provider == "openai" and settings.live_model_enabled,
        },
        "codex": {
            "access_token": mask_secret(settings.codex_access_token),
            "account_id": settings.codex_account_id,
            "auth_path": str(settings.codex_auth_path),
            "base_url": settings.codex_base_url,
            "model": settings.codex_model,
            "model_choices": codex_model_choices_for_settings(settings.codex_model),
            "reasoning_effort": settings.codex_reasoning_effort,
            "reasoning_effort_choices": list(CODEX_REASONING_EFFORT_CHOICES),
            "reasoning_effort_labels": CODEX_REASONING_LABELS,
            "live": settings.model_provider == "codex" and settings.live_model_enabled,
            "logged_in": load_codex_credentials(settings) is not None,
            "cli_available": shutil.which("codex") is not None,
        },
        "openrouter": {
            "api_key": mask_secret(settings.openrouter_api_key),
            "base_url": settings.openrouter_base_url,
            "model": settings.openrouter_model,
            "live": settings.model_provider == "openrouter" and settings.live_model_enabled,
        },
        "ollama": {
            "api_key": mask_secret(settings.ollama_api_key),
            "model": settings.ollama_model,
            "base_url": settings.ollama_base_url,
            "cloud_base_url": settings.ollama_cloud_base_url,
            "live": settings.model_provider.startswith("ollama") and settings.live_model_enabled,
        },
        "wabot": {
            "endpoint": settings.wabot_endpoint,
            "token": mask_secret(settings.resolved_wabot_token),
            "token_file": str(settings.wabot_token_file) if settings.wabot_token_file else None,
        },
    }


__all__ = [
    "_settings_view",
    "_test_llm_endpoint",
    "_test_openai_endpoint",
    "_test_openrouter_endpoint",
]
