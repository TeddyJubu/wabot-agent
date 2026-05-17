from __future__ import annotations

from typing import Any, Literal

from .config import Settings

ModelProvider = Literal["openrouter", "ollama", "ollama_cloud"]


def active_model_id(settings: Settings) -> str:
    if settings.model_provider == "openrouter":
        return settings.openrouter_model
    return settings.ollama_model


def resolved_llm_base_url(settings: Settings) -> str:
    if settings.model_provider == "openrouter":
        return settings.openrouter_base_url.rstrip("/")
    if settings.model_provider == "ollama_cloud":
        return settings.ollama_cloud_base_url.rstrip("/")
    return settings.ollama_base_url.rstrip("/")


def resolved_llm_api_key(settings: Settings) -> str:
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
        "X-Title": settings.openrouter_app_title,
    }


def llm_provider_label(settings: Settings) -> str:
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
    model = active_model_id(settings).lower()
    if "thinking" in model or "trinity" in model or (
        settings.model_provider != "openrouter" and "minimax" in model
    ):
        from openai.types.shared.reasoning import Reasoning

        return Reasoning(effort="high")
    return None
