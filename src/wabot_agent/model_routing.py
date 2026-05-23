"""Per-purpose model routing — Phase 2 of the simplification roadmap.

Each "purpose" (chat reply, web scraping, memory extraction, vision, etc.)
can be routed to a different provider + model.  If a purpose has no entry in
``Settings.model_routing``, it falls back to the global ``model_provider``
setting — identical to pre-Phase-2 behaviour.

Public surface:
    ModelPurpose      — str Enum of the seven purposes.
    ModelChoice       — Pydantic model: {provider, model}.
    ResolvedModel     — frozen dataclass returned by get_model_for().
    get_model_for()   — main entry-point for consumer call sites.

Design notes:
- ModelPurpose extends str so it round-trips cleanly as a JSON/dict key.
- ModelChoice.model = "" means "use the provider's default model field on
  Settings" — a useful shorthand when the operator only wants to switch
  provider, not model.
- ResolvedModel contains everything a consumer needs; no second Settings
  lookup required downstream.
- Consumers that don't care about per-purpose routing continue to work
  unchanged because get_model_for() returns the global default when the
  purpose is absent from Settings.model_routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, field_validator

from .providers import PROVIDER_NAMES


class ModelPurpose(StrEnum):
    """The seven recognised routing purposes.

    Visible by default in the settings UI:
        CHAT, SCRAPING, MEMORY_EXTRACTION, VISION

    Advanced (shown behind "Show advanced" toggle):
        TOOL_REASONING, TRANSCRIPTION, BACKGROUND_RESEARCH
    """

    CHAT = "chat"
    SCRAPING = "scraping"
    MEMORY_EXTRACTION = "memory_extraction"
    VISION = "vision"
    TOOL_REASONING = "tool_reasoning"
    TRANSCRIPTION = "transcription"
    BACKGROUND_RESEARCH = "background_research"


class ModelChoice(BaseModel):
    """One row in the routing table: use this provider + model for this purpose.

    ``model`` is optional (defaults to ``""``).  An empty model means
    "use the provider's default model field on Settings"
    (i.e. ``settings.<provider>_model``).
    """

    provider: str
    model: str = ""

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        if value not in PROVIDER_NAMES:
            raise ValueError(
                f"Unknown provider {value!r}. "
                f"Valid providers: {sorted(PROVIDER_NAMES)}"
            )
        return value


@dataclass(frozen=True)
class ResolvedModel:
    """Everything a consumer needs to construct an API client for a purpose.

    No further Settings lookups required after receiving a ResolvedModel.

    Attributes:
        purpose:        The purpose that was resolved.
        provider:       Name of the chosen provider (e.g. "openai").
        model_id:       The verbatim model string to send to the API.
        api_key:        The provider API key (None for local providers like ollama).
        base_url:       The provider base URL, or None for codex (which builds its
                        own URL internally).
        used_fallback:  True iff the purpose had no routing entry and the global
                        default was used.
    """

    purpose: ModelPurpose
    provider: str
    model_id: str
    api_key: str | None
    base_url: str | None
    used_fallback: bool


def _resolve_from_provider(
    purpose: ModelPurpose,
    provider_name: str,
    model_override: str,
    settings: Any,
    *,
    used_fallback: bool,
) -> ResolvedModel:
    """Build a ResolvedModel from a provider name + optional model override."""
    from .llm_provider import active_model_id  # local import to avoid cycles

    # Determine the model string.
    if model_override:
        model_id = model_override
    else:
        # Use the provider's default model field from Settings.
        if provider_name == "openai":
            model_id = settings.openai_model
        elif provider_name == "codex":
            model_id = settings.codex_model
        elif provider_name == "openrouter":
            model_id = settings.openrouter_model
        elif provider_name in ("ollama", "ollama_cloud"):
            # Ollama cloud strips the ":cloud" suffix — reuse active_model_id
            # logic by temporarily checking the provider.
            if provider_name == "ollama_cloud":
                m = settings.ollama_model
                for suffix in (":cloud", "-cloud"):
                    if m.endswith(suffix):
                        m = m[: -len(suffix)]
                model_id = m
            else:
                model_id = settings.ollama_model
        else:
            # Fallback: use global active_model_id (shouldn't normally hit).
            model_id = active_model_id(settings)

    # Determine the API key.
    if provider_name == "openai":
        api_key = settings.openai_api_key
    elif provider_name == "codex":
        from .codex_auth import load_codex_credentials

        creds = load_codex_credentials(settings)
        api_key = creds.access_token if creds else None
    elif provider_name == "openrouter":
        api_key = settings.openrouter_api_key
    elif provider_name in ("ollama", "ollama_cloud"):
        api_key = settings.ollama_api_key  # None for local ollama (no key needed)
    else:
        api_key = None

    # Determine the base URL.
    if provider_name == "openai":
        base_url: str | None = settings.openai_base_url.rstrip("/")
    elif provider_name == "codex":
        # Codex constructs its own URL + headers; callers that use ResolvedModel
        # for Codex should use settings.codex_base_url directly.
        base_url = settings.codex_base_url.rstrip("/")
    elif provider_name == "openrouter":
        base_url = settings.openrouter_base_url.rstrip("/")
    elif provider_name == "ollama_cloud":
        base_url = settings.ollama_cloud_base_url.rstrip("/")
    elif provider_name == "ollama":
        base_url = settings.ollama_base_url.rstrip("/")
    else:
        base_url = None

    return ResolvedModel(
        purpose=purpose,
        provider=provider_name,
        model_id=model_id,
        api_key=api_key,
        base_url=base_url,
        used_fallback=used_fallback,
    )


def _coerce_choice(value: Any) -> ModelChoice:
    """Coerce a raw dict or ModelChoice instance to a ModelChoice.

    The routing dict stored on Settings may contain either:
    - ``ModelChoice`` instances (when set via the in-memory API),
    - plain dicts like ``{"provider": "openai", "model": ""}`` (when loaded
      from the JSON override file and applied via ``setattr``).
    Both forms are supported here.
    """
    if isinstance(value, ModelChoice):
        return value
    if isinstance(value, dict):
        return ModelChoice.model_validate(value)
    raise TypeError(f"Cannot coerce {type(value)!r} to ModelChoice")


def get_model_for(purpose: ModelPurpose, settings: Any) -> ResolvedModel:
    """Resolve which provider + model to use for a given purpose.

    Lookup order
    ------------
    1. If ``settings.model_routing`` has an entry for *purpose* → use it.
       If that entry's ``model`` is empty, fall through to the provider's
       default model field on Settings.
    2. Otherwise (no entry) → use ``settings.model_provider`` (the global
       default), identical to pre-Phase-2 behaviour.

    Returns a ``ResolvedModel`` containing everything a consumer needs
    (provider name, model id, api_key, base_url, fallback flag).
    No second Settings lookups needed downstream.

    The routing dict on settings may use either ``ModelPurpose`` enum values
    or their string equivalents as keys — both are checked so callers do not
    need to worry about which form was stored.
    """
    raw_routing: dict = getattr(settings, "model_routing", {}) or {}

    # Look up by enum value or string key.
    choice_raw: Any = raw_routing.get(purpose) or raw_routing.get(purpose.value)

    if choice_raw is not None:
        choice = _coerce_choice(choice_raw)
        return _resolve_from_provider(
            purpose,
            provider_name=choice.provider,
            model_override=choice.model,
            settings=settings,
            used_fallback=False,
        )

    # No entry for this purpose — fall back to global default.
    return _resolve_from_provider(
        purpose,
        provider_name=settings.model_provider,
        model_override="",
        settings=settings,
        used_fallback=True,
    )
