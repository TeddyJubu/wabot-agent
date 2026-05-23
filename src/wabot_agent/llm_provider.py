from __future__ import annotations

from typing import Any, Literal

from .config import Settings

ModelProvider = Literal["openai", "codex", "openrouter", "ollama", "ollama_cloud"]


def active_model_id(settings: Settings) -> str:
    if settings.model_provider == "openai":
        return settings.openai_model
    if settings.model_provider == "codex":
        return settings.codex_model
    if settings.model_provider == "openrouter":
        return settings.openrouter_model
    model = settings.ollama_model
    # Local daemon uses ":cloud" / "-cloud" tags; Ollama Cloud API uses bare ids (e.g. gemma4:31b).
    if settings.model_provider == "ollama_cloud":
        for suffix in (":cloud", "-cloud"):
            if model.endswith(suffix):
                return model[: -len(suffix)]
    return model


def resolved_llm_base_url(settings: Settings) -> str:
    if settings.model_provider == "openai":
        return settings.openai_base_url.rstrip("/")
    if settings.model_provider == "codex":
        return settings.codex_base_url.rstrip("/")
    if settings.model_provider == "openrouter":
        return settings.openrouter_base_url.rstrip("/")
    if settings.model_provider == "ollama_cloud":
        return settings.ollama_cloud_base_url.rstrip("/")
    return settings.ollama_base_url.rstrip("/")


def resolved_llm_api_key(settings: Settings) -> str:
    if settings.model_provider == "openai":
        return settings.openai_api_key or ""
    if settings.model_provider == "codex":
        from .codex_auth import load_codex_credentials

        creds = load_codex_credentials(settings)
        return creds.access_token if creds else ""
    if settings.model_provider == "openrouter":
        return settings.openrouter_api_key or ""
    if settings.model_provider == "ollama_cloud":
        return settings.ollama_api_key or ""
    return settings.ollama_api_key or "ollama"


def llm_default_headers(settings: Settings) -> dict[str, str]:
    if settings.model_provider != "openrouter":
        return {}
    return {
        "HTTP-Referer": settings.openrouter_site_url,
        "X-OpenRouter-Title": settings.openrouter_app_title,
    }


def _model_is_vision_capable(provider: str, model_id: str) -> bool:
    """Return True when *model_id* on *provider* is known to accept image inputs.

    Central token list used by both ``vision_supported`` (global path) and
    ``vision_supported_for_purpose`` (routed path).  Includes validated
    May-2026 model names alongside the legacy ones.
    """
    model = model_id.lower()
    if provider in ("openai", "codex"):
        return any(
            token in model
            for token in (
                "gpt-4o",
                "gpt-4.1",
                "vision",
                # May-2026 additions (use precise substrings to avoid matching
                # unrelated gpt-5.x codex-only models like gpt-5.3-codex-spark)
                "gpt-5.5",
                "o3",
                "o4",
            )
        )
    if provider == "openrouter":
        return any(
            token in model
            for token in (
                "vision",
                "vl",
                "gpt-4o",
                "gpt-4.1",
                "gpt-4-turbo",
                "gpt-5.5",
                "claude-3",
                "claude-sonnet-4",
                "claude-opus-4",
                "claude-haiku-4",
                "gemini",
                "llava",
                "pixtral",
                "qwen-vl",
                "qwen2-vl",
                # May-2026 additions
                "claude-opus-4-7",
                "claude-sonnet-4-6",
                "claude-haiku-4-5",
            )
        )
    # ollama / ollama_cloud
    return any(
        token in model
        for token in ("gemma4", "gemma3", "vl", "llava", "moondream", "bakllava", "vision")
    )


def vision_supported(settings: Settings) -> bool:
    """Whether the active (global) model is expected to accept image inputs.

    This is the no-purpose fallback — it checks the *global* provider and model.
    Use ``vision_supported_for_purpose(purpose, settings)`` when a per-purpose
    vision route may be active (Finding 3 fix).
    """
    if not settings.live_model_enabled:
        return False
    return _model_is_vision_capable(settings.model_provider, active_model_id(settings))


def vision_supported_for_purpose(purpose: Any, settings: Settings) -> bool:
    """Whether the *routed* model for *purpose* is expected to accept image inputs.

    Finding 3 fix: consults the routed provider + model rather than the global
    provider, so a vision route pointing at a vision-capable model is honoured
    even when the global provider/model is not vision-capable.

    Falls back to the global path when the purpose has no routing entry
    (``used_fallback=True``), preserving backward compat.
    """
    resolved = active_model_for_purpose(purpose, settings)
    # Liveness: routed provider must have credentials (or be local).
    if settings.offline_mode:
        return False
    if resolved.provider == "openai" and not settings.openai_api_key:
        return False
    if resolved.provider == "codex":
        from .codex_auth import load_codex_credentials

        if load_codex_credentials(settings) is None:
            return False
    if resolved.provider == "openrouter" and not settings.openrouter_api_key:
        return False
    if resolved.provider == "ollama_cloud" and not settings.ollama_api_key:
        return False
    return _model_is_vision_capable(resolved.provider, resolved.model_id)


def llm_provider_label(settings: Settings) -> str:
    if settings.model_provider == "openai":
        return "OpenAI API"
    if settings.model_provider == "codex":
        return "ChatGPT / Codex subscription"
    if settings.model_provider == "openrouter":
        return "OpenRouter"
    if settings.model_provider == "ollama_cloud":
        return "Ollama Cloud"
    return "Ollama (local)"


def omit_tool_choice(settings: Settings) -> bool:
    """OpenRouter free endpoints may reject tool_choice; Ollama generally supports tools."""
    if settings.model_provider != "openrouter":
        return False
    lowered = settings.openrouter_model.lower()
    if "trinity" in lowered or "thinking" in lowered:
        return False
    return "nemotron" in lowered or ":free" in lowered


def max_tokens_for_model(settings: Settings) -> int:
    model = active_model_id(settings).lower()
    if settings.model_provider != "openrouter":
        if "minimax" in model or "thinking" in model:
            return 4096
        return 2500
    if "thinking" in model or "trinity" in model or "o1" in model or "o3" in model:
        return 4096
    return 2500


def reasoning_for_model(settings: Settings) -> Any | None:
    if settings.model_provider == "codex":
        return _codex_reasoning(settings)

    model = active_model_id(settings).lower()
    if "thinking" in model or "trinity" in model or "minimax" in model:
        from openai.types.shared.reasoning import Reasoning

        return Reasoning(effort="high")
    return None


def _codex_reasoning(settings: Settings) -> Any | None:
    """Codex subscription uses store=false; reasoning items cannot be replayed."""
    # Dashboard + WhatsApp use CodexSubscriptionModel which also strips reasoning
    # from streamed responses. Keep effort unset until store=true is supported.
    _ = settings.codex_reasoning_effort
    return None


def active_model_for_purpose(purpose: Any, settings: Settings) -> Any:
    """Resolve provider + model for *purpose*, delegating to get_model_for().

    This is the stable export point for per-purpose model resolution.  Other
    modules should import from here rather than importing model_routing directly,
    to keep the coupling surface small.

    With an empty model_routing (today's default) this behaves identically to
    calling ``active_model_id(settings)`` — the global provider fallback is used.
    """
    from .model_routing import get_model_for  # local import to avoid cycles

    return get_model_for(purpose, settings)
