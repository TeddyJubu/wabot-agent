"""Tests for Phase-2 routing wiring — verifying that consumer call sites honour
per-purpose model routing rather than always falling back to the global provider.

These tests do NOT run live agents or make real API calls.  They verify the
model resolution layer that each consumer calls before building a client.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wabot_agent.config import Settings
from wabot_agent.llm_provider import active_model_for_purpose
from wabot_agent.model_routing import ModelChoice, ModelPurpose, ResolvedModel, get_model_for

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="dry_run",
        OPENROUTER_API_KEY="router-key-test",
        OPENROUTER_MODEL="openai/gpt-4.1-mini",
        OPENAI_API_KEY="sk-test-key",
        OPENAI_MODEL="gpt-4.1-mini",
        _env_file=None,
    )
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# 1. Chat wiring honours routing
# ---------------------------------------------------------------------------


def test_chat_wiring_uses_routed_provider_and_model(tmp_path: Path) -> None:
    """active_model_for_purpose(CHAT, settings) returns the routed provider + model."""
    settings = make_settings(tmp_path)
    settings.model_routing = {
        ModelPurpose.CHAT: ModelChoice(
            provider="openrouter", model="anthropic/claude-sonnet-4-6"
        )
    }

    resolved = active_model_for_purpose(ModelPurpose.CHAT, settings)

    assert isinstance(resolved, ResolvedModel)
    assert resolved.used_fallback is False
    assert resolved.provider == "openrouter"
    assert resolved.model_id == "anthropic/claude-sonnet-4-6"


def test_chat_wiring_string_key_routing(tmp_path: Path) -> None:
    """String keys (as stored in runtime_overrides.json) also work for CHAT."""
    settings = make_settings(tmp_path)
    settings.model_routing = {
        "chat": {"provider": "openrouter", "model": "anthropic/claude-sonnet-4-6"}
    }

    resolved = active_model_for_purpose(ModelPurpose.CHAT, settings)

    assert resolved.provider == "openrouter"
    assert resolved.model_id == "anthropic/claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# 2. Mem0 wiring honours routing
# ---------------------------------------------------------------------------


def test_mem0_wiring_uses_routed_provider(tmp_path: Path) -> None:
    """_mem0_openai_llm returns the routed api_key, base_url, and model."""
    from wabot_agent.mem0_store import _mem0_openai_llm

    settings = make_settings(tmp_path)
    settings.model_routing = {
        ModelPurpose.MEMORY_EXTRACTION: ModelChoice(
            provider="openrouter", model="openai/gpt-4o-mini"
        )
    }

    api_key, base_url, model = _mem0_openai_llm(settings)

    assert api_key == settings.openrouter_api_key
    assert "openrouter" in base_url.lower()
    assert model == "openai/gpt-4o-mini"


def test_mem0_wiring_uses_routed_openai_provider(tmp_path: Path) -> None:
    """Routing MEMORY_EXTRACTION to openai gives openai api_key and base_url."""
    from wabot_agent.mem0_store import _mem0_openai_llm

    settings = make_settings(tmp_path)
    settings.model_routing = {
        ModelPurpose.MEMORY_EXTRACTION: ModelChoice(
            provider="openai", model="gpt-4o-mini"
        )
    }

    api_key, base_url, model = _mem0_openai_llm(settings)

    assert api_key == settings.openai_api_key
    assert model == "gpt-4o-mini"


def test_mem0_routing_string_key(tmp_path: Path) -> None:
    """String key 'memory_extraction' in routing dict is accepted."""
    from wabot_agent.mem0_store import _mem0_openai_llm

    settings = make_settings(tmp_path)
    settings.model_routing = {
        "memory_extraction": {"provider": "openai", "model": "gpt-4o-mini"}
    }

    api_key, base_url, model = _mem0_openai_llm(settings)
    assert model == "gpt-4o-mini"


def test_mem0_routing_codex_raises(tmp_path: Path) -> None:
    """Routing MEMORY_EXTRACTION to 'codex' raises Mem0UnavailableError."""
    from wabot_agent.mem0_store import Mem0UnavailableError, _mem0_openai_llm

    settings = make_settings(tmp_path)
    settings.model_routing = {
        ModelPurpose.MEMORY_EXTRACTION: ModelChoice(provider="codex", model="")
    }

    with pytest.raises(Mem0UnavailableError, match="codex"):
        _mem0_openai_llm(settings)


# ---------------------------------------------------------------------------
# 3. Existing behaviour preserved with empty routing
# ---------------------------------------------------------------------------


def test_no_routing_chat_resolves_to_global_provider(tmp_path: Path) -> None:
    """With empty model_routing, CHAT resolves to the global provider (openai)."""
    settings = make_settings(tmp_path)
    assert settings.model_routing == {}

    resolved = active_model_for_purpose(ModelPurpose.CHAT, settings)

    assert resolved.used_fallback is True
    assert resolved.provider == "openai"
    assert resolved.model_id == settings.openai_model


def test_no_routing_mem0_openai_llm_unchanged(tmp_path: Path) -> None:
    """With empty model_routing, _mem0_openai_llm returns the legacy path result."""
    from wabot_agent.mem0_store import _mem0_openai_llm

    settings = make_settings(tmp_path)
    assert settings.model_routing == {}

    api_key, base_url, model = _mem0_openai_llm(settings)

    # Global provider is openai; expect openai credentials
    assert api_key == settings.openai_api_key
    assert model == settings.openai_model


def test_no_routing_all_purposes_fallback(tmp_path: Path) -> None:
    """All purposes fall back to global provider when routing is empty."""
    settings = make_settings(tmp_path)
    for purpose in ModelPurpose:
        resolved = active_model_for_purpose(purpose, settings)
        assert resolved.used_fallback is True
        assert resolved.provider == settings.model_provider


# ---------------------------------------------------------------------------
# 4. Web research scraping path honours routing
# ---------------------------------------------------------------------------


def test_scraping_routing_resolves_model(tmp_path: Path) -> None:
    """get_model_for(SCRAPING) returns the routed model."""
    settings = make_settings(tmp_path)
    settings.model_routing = {
        ModelPurpose.SCRAPING: ModelChoice(
            provider="openrouter", model="openai/gpt-4.1"
        )
    }

    resolved = get_model_for(ModelPurpose.SCRAPING, settings)

    assert resolved.used_fallback is False
    assert resolved.provider == "openrouter"
    assert resolved.model_id == "openai/gpt-4.1"


def test_scraping_model_via_resolve_scraping_model(tmp_path: Path) -> None:
    """resolve_scraping_model() returns the routed model_id for SCRAPING."""
    from wabot_agent.web_fetch import resolve_scraping_model

    settings = make_settings(tmp_path)
    settings.model_routing = {
        ModelPurpose.SCRAPING: ModelChoice(
            provider="openrouter", model="openai/gpt-4.1"
        )
    }

    assert resolve_scraping_model(settings) == "openai/gpt-4.1"


def test_scraping_model_falls_back_to_global(tmp_path: Path) -> None:
    """With no SCRAPING entry, resolve_scraping_model returns the global default."""
    from wabot_agent.web_fetch import resolve_scraping_model

    settings = make_settings(tmp_path)

    model_id = resolve_scraping_model(settings)
    assert model_id == settings.openai_model


def test_background_research_routing_resolves_model(tmp_path: Path) -> None:
    """get_model_for(BACKGROUND_RESEARCH) returns the routed model."""
    settings = make_settings(tmp_path)
    settings.model_routing = {
        ModelPurpose.BACKGROUND_RESEARCH: ModelChoice(
            provider="openrouter", model="openai/o3-mini"
        )
    }

    resolved = get_model_for(ModelPurpose.BACKGROUND_RESEARCH, settings)

    assert resolved.used_fallback is False
    assert resolved.model_id == "openai/o3-mini"


# ---------------------------------------------------------------------------
# 5. Vision routing
# ---------------------------------------------------------------------------


def test_vision_routing_resolves_model(tmp_path: Path) -> None:
    """get_model_for(VISION) returns the routed vision model."""
    settings = make_settings(tmp_path)
    settings.model_routing = {
        ModelPurpose.VISION: ModelChoice(
            provider="openrouter", model="openai/gpt-4o"
        )
    }

    resolved = get_model_for(ModelPurpose.VISION, settings)

    assert resolved.used_fallback is False
    assert resolved.provider == "openrouter"
    assert resolved.model_id == "openai/gpt-4o"


def test_vision_active_model_for_purpose(tmp_path: Path) -> None:
    """active_model_for_purpose(VISION) delegates to get_model_for correctly."""
    settings = make_settings(tmp_path)
    settings.model_routing = {
        "vision": {"provider": "openai", "model": "gpt-4o"}
    }

    resolved = active_model_for_purpose(ModelPurpose.VISION, settings)

    assert resolved.provider == "openai"
    assert resolved.model_id == "gpt-4o"
