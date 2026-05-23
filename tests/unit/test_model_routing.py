"""Tests for per-purpose model routing (Phase 2 of the simplification roadmap).

Covers:
1. Fallback — empty model_routing → global provider + model.
2. Direct hit — routing entry with explicit provider + model.
3. Empty-model fallback — entry with empty model → provider's default model.
4. Unknown purpose — parsing a routing dict with an invalid purpose key.
5. Unknown provider — parsing a routing dict with an invalid provider name.
6. API integration — PATCH /api/settings with model_routing, reflected in GET.
7. API rejects bad routing — unknown provider returns 400.
8. JSON round-trip — routing serialises/deserialises correctly via JSON.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wabot_agent.config import Settings  # noqa: F401 (used in type hints in helpers)
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
        OPENROUTER_MODEL="openai/gpt-5.5",
        OPENAI_API_KEY="sk-test-key",
        OPENAI_MODEL="gpt-4.1-mini",
        _env_file=None,
    )
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# 1. Fallback: empty routing uses global provider
# ---------------------------------------------------------------------------


def test_fallback_empty_routing_uses_global_provider(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    assert settings.model_routing == {}

    resolved = get_model_for(ModelPurpose.CHAT, settings)

    assert isinstance(resolved, ResolvedModel)
    assert resolved.used_fallback is True
    assert resolved.purpose is ModelPurpose.CHAT
    # Global provider is "openai" (the default)
    assert resolved.provider == "openai"
    assert resolved.model_id == settings.openai_model


def test_fallback_for_all_purposes(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    for purpose in ModelPurpose:
        resolved = get_model_for(purpose, settings)
        assert resolved.used_fallback is True
        assert resolved.provider == settings.model_provider


# ---------------------------------------------------------------------------
# 2. Direct hit: routing entry with explicit provider + model
# ---------------------------------------------------------------------------


def test_direct_hit_uses_routed_provider_and_model(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.model_routing = {
        ModelPurpose.CHAT: ModelChoice(provider="openrouter", model="anthropic/claude-sonnet-4-6")
    }

    resolved = get_model_for(ModelPurpose.CHAT, settings)

    assert resolved.used_fallback is False
    assert resolved.provider == "openrouter"
    assert resolved.model_id == "anthropic/claude-sonnet-4-6"
    assert resolved.api_key == settings.openrouter_api_key
    assert resolved.base_url is not None


def test_unrouted_purpose_still_falls_back(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.model_routing = {
        ModelPurpose.CHAT: ModelChoice(provider="openrouter", model="anthropic/claude-sonnet-4-6")
    }

    # SCRAPING has no entry — must fall back to global provider
    resolved = get_model_for(ModelPurpose.SCRAPING, settings)
    assert resolved.used_fallback is True
    assert resolved.provider == settings.model_provider


# ---------------------------------------------------------------------------
# 3. Empty-model fallback: entry with empty model uses provider's default
# ---------------------------------------------------------------------------


def test_empty_model_uses_provider_default(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.model_routing = {
        ModelPurpose.CHAT: ModelChoice(provider="openrouter", model="")
    }

    resolved = get_model_for(ModelPurpose.CHAT, settings)

    assert resolved.used_fallback is False
    assert resolved.provider == "openrouter"
    # Empty model → resolves to settings.openrouter_model
    assert resolved.model_id == settings.openrouter_model


def test_empty_model_for_openai_uses_openai_model(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.model_routing = {
        ModelPurpose.MEMORY_EXTRACTION: ModelChoice(provider="openai", model="")
    }

    resolved = get_model_for(ModelPurpose.MEMORY_EXTRACTION, settings)

    assert resolved.provider == "openai"
    assert resolved.model_id == settings.openai_model


# ---------------------------------------------------------------------------
# 4. Unknown purpose key raises ValidationError
# ---------------------------------------------------------------------------


def test_unknown_purpose_raises_validation_error() -> None:
    from pydantic import TypeAdapter, ValidationError

    ta = TypeAdapter(dict[ModelPurpose, ModelChoice])
    with pytest.raises(ValidationError):
        ta.validate_python({"frobnicate": {"provider": "openai", "model": "gpt-4.1"}})


# ---------------------------------------------------------------------------
# 5. Unknown provider raises ValidationError
# ---------------------------------------------------------------------------


def test_unknown_provider_raises_validation_error() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ModelChoice(provider="anthropic_direct", model="claude-opus-4")


def test_unknown_provider_in_dict_raises_validation_error() -> None:
    from pydantic import TypeAdapter, ValidationError

    ta = TypeAdapter(dict[ModelPurpose, ModelChoice])
    with pytest.raises(ValidationError):
        ta.validate_python({"chat": {"provider": "anthropic_direct", "model": "x"}})


# ---------------------------------------------------------------------------
# 6. API integration: PATCH accepted, reflected in GET
# ---------------------------------------------------------------------------


def test_api_patch_model_routing_accepted_and_reflected(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from wabot_agent.api import create_app

    settings = make_settings(tmp_path, WABOT_INBOUND_TOKEN="inbound-secret")
    client = TestClient(create_app(settings))

    routing_payload = {
        "model_routing": {
            "chat": {"provider": "openrouter", "model": "x"},
        }
    }

    resp = client.patch("/api/settings", json=routing_payload)
    assert resp.status_code == 200, resp.text

    view = resp.json()
    assert "model_routing" in view
    assert "chat" in view["model_routing"]
    assert view["model_routing"]["chat"]["provider"] == "openrouter"
    assert view["model_routing"]["chat"]["model"] == "x"

    # GET also reflects it
    get_resp = client.get("/api/settings")
    assert get_resp.status_code == 200
    get_view = get_resp.json()
    assert get_view["model_routing"]["chat"]["provider"] == "openrouter"


def test_api_patch_empty_model_routing_wipes_all_routing(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from wabot_agent.api import create_app

    settings = make_settings(tmp_path)
    # Pre-seed a routing entry
    settings.model_routing = {"chat": {"provider": "openrouter", "model": "x"}}
    client = TestClient(create_app(settings))

    # PATCH with empty dict wipes all routing
    resp = client.patch("/api/settings", json={"model_routing": {}})
    assert resp.status_code == 200
    assert resp.json()["model_routing"] == {}


# ---------------------------------------------------------------------------
# 7. API rejects routing with unknown provider
# ---------------------------------------------------------------------------


def test_api_patch_rejects_unknown_provider(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from wabot_agent.api import create_app

    settings = make_settings(tmp_path)
    client = TestClient(create_app(settings))

    resp = client.patch(
        "/api/settings",
        json={"model_routing": {"chat": {"provider": "made_up_provider", "model": "x"}}},
    )
    assert resp.status_code == 400
    assert "model_routing" in resp.text.lower() or "provider" in resp.text.lower()


def test_api_patch_rejects_non_dict_routing(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from wabot_agent.api import create_app

    settings = make_settings(tmp_path)
    client = TestClient(create_app(settings))

    # Sending a list instead of dict should fail
    resp = client.patch("/api/settings", json={"model_routing": ["not", "a", "dict"]})
    assert resp.status_code == 422  # Pydantic schema validation rejects list for dict


# ---------------------------------------------------------------------------
# 8. JSON round-trip
# ---------------------------------------------------------------------------


def test_model_routing_round_trips_via_json() -> None:
    import json

    from pydantic import TypeAdapter

    ta = TypeAdapter(dict[ModelPurpose, ModelChoice])

    original: dict[ModelPurpose, ModelChoice] = {
        ModelPurpose.CHAT: ModelChoice(provider="openrouter", model="claude-sonnet-4-6"),
        ModelPurpose.MEMORY_EXTRACTION: ModelChoice(provider="ollama", model=""),
    }

    # Serialise to JSON-compatible form (string keys, dict values)
    serialised = {k.value: v.model_dump() for k, v in original.items()}
    json_str = json.dumps(serialised)

    # Deserialise back
    loaded = json.loads(json_str)
    recovered = ta.validate_python(loaded)

    assert recovered[ModelPurpose.CHAT].provider == "openrouter"
    assert recovered[ModelPurpose.CHAT].model == "claude-sonnet-4-6"
    assert recovered[ModelPurpose.MEMORY_EXTRACTION].provider == "ollama"
    assert recovered[ModelPurpose.MEMORY_EXTRACTION].model == ""


# ---------------------------------------------------------------------------
# 9. String key routing (dict loaded from JSON has string keys)
# ---------------------------------------------------------------------------


def test_get_model_for_handles_string_keys_from_json(tmp_path: Path) -> None:
    """After loading from runtime_overrides.json, keys are plain strings."""
    settings = make_settings(tmp_path)
    # Simulate what apply_overrides does — sets a plain string-keyed dict
    settings.model_routing = {"chat": {"provider": "openrouter", "model": "test-model"}}

    resolved = get_model_for(ModelPurpose.CHAT, settings)

    assert resolved.used_fallback is False
    assert resolved.provider == "openrouter"
    assert resolved.model_id == "test-model"
