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


def vision_supported(settings: Settings) -> bool:
    """Whether the active model is expected to accept image inputs."""
    if not settings.live_model_enabled:
        return False
    model = active_model_id(settings).lower()
    if settings.model_provider == "openai":
        return any(token in model for token in ("gpt-4o", "gpt-4.1", "vision"))
    if settings.model_provider == "codex":
        return any(token in model for token in ("gpt-4o", "gpt-4.1", "vision"))
    if settings.model_provider == "openrouter":
        return any(
            token in model
            for token in (
                "vision",
                "vl",
                "gpt-4o",
                "gpt-4.1",
                "gpt-4-turbo",
                "claude-3",
                "claude-sonnet-4",
                "gemini",
                "llava",
                "pixtral",
                "qwen-vl",
                "qwen2-vl",
            )
        )
    return any(
        token in model
        for token in ("gemma4", "gemma3", "vl", "llava", "moondream", "bakllava", "vision")
    )


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
