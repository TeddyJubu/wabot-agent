"""Provider registry — single source of truth for model-provider wiring.

Phase 1 of the simplification roadmap (docs/design/simplification-roadmap.md).
The registry lists every model provider and the settings fields, URL safety
rule, and test endpoint each one needs. Other modules (config, runtime
overrides, llm_provider, api routes) consume the registry instead of
duplicating the per-provider boilerplate inline.

Design notes:
- ProviderSpec is frozen so the registry can't be mutated at runtime.
- Callable references (url_validator, test_endpoint_handler) are stored as
  callables, not strings, to keep static analysis honest. They're imported
  lazily inside ``_build_registry`` so the only import edge is
  providers -> api helpers, not the other way around.
- Adding a new provider is one entry here + one TSX section in the SPA.
  Phase 2 (per-purpose model selection) iterates this registry directly.

Caveats on the ollama providers
--------------------------------
Both ``ollama`` and ``ollama_cloud`` share the same Settings field for the
model name (``ollama_model``) and the same API-key field (``ollama_api_key``).
``ollama`` treats the key as optional (local daemon); ``ollama_cloud``
requires it.  ``all_provider_mutable_fields`` deduplicates shared fields so
they appear only once in the derived sets.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class ProviderSpec:
    name: str  # API identifier ("openai")
    display_name: str  # Human label ("OpenAI")
    secret_field: str | None  # Settings field for the API key; None for local providers
    base_url_field: str | None  # Settings field for base URL; None when not configurable
    model_field: str  # Settings field for the model name
    url_safety_validator: Callable[[str, str], None] | None  # _require_safe_*_url or None
    test_endpoint_path: str | None  # "/api/settings/test/openai" or None
    test_endpoint_handler: Callable[..., Awaitable[dict[str, Any]]] | None  # or None
    test_request_model: type[BaseModel] | None  # OpenAITestRequest etc.; None if N/A
    notes: str = field(default="")


def _build_registry() -> dict[str, ProviderSpec]:
    """Lazy-build the registry to avoid import cycles.

    Imports the per-provider helpers from ``api.dependencies``,
    ``api.llm_tests``, and ``api.schemas`` at call time.  Module load of
    ``providers.py`` itself does not pull in those modules — so ``config.py``,
    which is loaded before ``api/``, can still safely import from
    ``providers.py`` for name lists.
    """
    # Local imports to dodge circular-import cycles.
    from .api.dependencies import (
        _require_safe_ollama_cloud_url,
        _require_safe_ollama_local_url,
        _require_safe_openai_url,
        _require_safe_openrouter_url,
    )
    from .api.llm_tests import _test_openai_endpoint, _test_openrouter_endpoint
    from .api.schemas import OpenAITestRequest, OpenRouterTestRequest

    return {
        "openai": ProviderSpec(
            name="openai",
            display_name="OpenAI",
            secret_field="openai_api_key",
            base_url_field="openai_base_url",
            model_field="openai_model",
            url_safety_validator=_require_safe_openai_url,
            test_endpoint_path="/api/settings/test/openai",
            test_endpoint_handler=_test_openai_endpoint,
            test_request_model=OpenAITestRequest,
        ),
        "openrouter": ProviderSpec(
            name="openrouter",
            display_name="OpenRouter",
            secret_field="openrouter_api_key",
            base_url_field="openrouter_base_url",
            model_field="openrouter_model",
            url_safety_validator=_require_safe_openrouter_url,
            test_endpoint_path="/api/settings/test/openrouter",
            test_endpoint_handler=_test_openrouter_endpoint,
            test_request_model=OpenRouterTestRequest,
        ),
        "codex": ProviderSpec(
            name="codex",
            display_name="OpenAI Codex (device-flow login)",
            secret_field="codex_access_token",
            base_url_field=None,
            model_field="codex_model",
            url_safety_validator=None,
            test_endpoint_path=None,
            test_endpoint_handler=None,
            test_request_model=None,
            notes="Codex uses device-flow auth; no URL safety rule or remote test endpoint.",
        ),
        "ollama": ProviderSpec(
            name="ollama",
            display_name="Ollama (local)",
            secret_field=None,
            base_url_field="ollama_base_url",
            model_field="ollama_model",
            url_safety_validator=_require_safe_ollama_local_url,
            test_endpoint_path=None,
            test_endpoint_handler=None,
            test_request_model=None,
            # Local-only; loopback URL required.
            # Shares ollama_model + ollama_api_key with ollama_cloud.
            notes="Local-only; loopback URL required.",
        ),
        "ollama_cloud": ProviderSpec(
            name="ollama_cloud",
            display_name="Ollama Cloud",
            secret_field="ollama_api_key",
            base_url_field="ollama_cloud_base_url",
            model_field="ollama_model",
            url_safety_validator=_require_safe_ollama_cloud_url,
            test_endpoint_path=None,
            test_endpoint_handler=None,
            test_request_model=None,
            notes="Shares ollama_model + ollama_api_key with ollama (local).",
        ),
    }


# Eager helpers use the static name tuple — no callable imports needed.
# ``config.py`` (loaded before api/) can import these safely.
PROVIDER_NAMES: tuple[str, ...] = ("openai", "openrouter", "codex", "ollama", "ollama_cloud")

_registry: dict[str, ProviderSpec] | None = None


def get_registry() -> dict[str, ProviderSpec]:
    """Cached accessor. Builds once on first call; returns the cached dict thereafter."""
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_provider(name: str) -> ProviderSpec:
    """Look up a provider by name. Raises KeyError if unknown."""
    return get_registry()[name]


def all_secret_fields() -> tuple[str, ...]:
    """Field names that hold provider API keys / tokens (de-duplicated, stable order).

    Used alongside ``runtime_overrides.SECRET_FIELDS`` — the test suite verifies
    the two sets stay in sync.
    """
    seen: set[str] = set()
    result: list[str] = []
    for spec in get_registry().values():
        if spec.secret_field and spec.secret_field not in seen:
            seen.add(spec.secret_field)
            result.append(spec.secret_field)
    return tuple(result)


def assert_registry_matches_settings() -> None:
    """Assert that PROVIDER_NAMES matches the Settings.model_provider Literal.

    Called from the test suite (tests/unit/test_provider_registry.py) and can
    also be called from application startup to detect configuration drift early.
    Importing providers.py itself is safe at any point; this function is the
    only spot that pulls in config.Settings.
    """
    from typing import get_args

    from .config import Settings

    literal_values = set(get_args(Settings.model_fields["model_provider"].annotation))
    registry_names = set(PROVIDER_NAMES)
    if literal_values != registry_names:
        drift = literal_values.symmetric_difference(registry_names)
        raise AssertionError(
            "Drift between providers.PROVIDER_NAMES and "
            f"Settings.model_provider Literal: symmetric difference = {sorted(drift)!r}"
        )


def all_provider_mutable_fields() -> tuple[str, ...]:
    """Provider-related settings fields that can be patched at runtime (de-duplicated).

    Used alongside ``runtime_overrides.MUTABLE_FIELDS`` — the test suite verifies
    the two sets stay in sync.
    Fields shared by multiple providers (e.g. ``ollama_model`` for both ollama
    variants) appear only once.
    """
    seen: set[str] = set()
    fields: list[str] = []
    for spec in get_registry().values():
        for fname in (spec.secret_field, spec.base_url_field, spec.model_field):
            if fname and fname not in seen:
                seen.add(fname)
                fields.append(fname)
    return tuple(fields)
