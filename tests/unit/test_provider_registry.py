"""Provider registry shape guard. Phase 1 of the simplification roadmap.

These tests verify:
1. PROVIDER_NAMES matches the Settings.model_provider Literal exactly.
2. All five expected providers are present in the registry.
3. SECRET_FIELDS in runtime_overrides covers all provider secret fields.
4. MUTABLE_FIELDS in runtime_overrides covers all provider model fields.
5. The registry's all_secret_fields() matches runtime_overrides.SECRET_FIELDS
   (minus the non-provider wabot_token).
"""

from __future__ import annotations

from wabot_agent.providers import (
    PROVIDER_NAMES,
    all_provider_mutable_fields,
    all_secret_fields,
    assert_registry_matches_settings,
    get_registry,
)


def test_registry_provider_names_match_settings_literal() -> None:
    """If a provider is added to the registry, the Settings Literal must include it
    (and vice versa). assert_registry_matches_settings raises on drift."""
    assert_registry_matches_settings()  # raises AssertionError on drift


def test_registry_has_all_five_providers() -> None:
    assert set(get_registry().keys()) == {
        "openai",
        "openrouter",
        "codex",
        "ollama",
        "ollama_cloud",
    }


def test_provider_names_tuple_matches_registry_keys() -> None:
    """PROVIDER_NAMES (eager, no-import-cycle constant) must equal registry keys."""
    assert set(PROVIDER_NAMES) == set(get_registry().keys())


def test_secret_fields_includes_known_provider_keys() -> None:
    """all_secret_fields() must include the known provider API-key fields."""
    expected = {"openai_api_key", "openrouter_api_key", "codex_access_token", "ollama_api_key"}
    assert expected <= set(all_secret_fields()), (
        f"Missing from all_secret_fields(): {expected - set(all_secret_fields())}"
    )


def test_mutable_fields_covers_all_provider_model_fields() -> None:
    """Every provider's model_field must appear in all_provider_mutable_fields()."""
    mf = set(all_provider_mutable_fields())
    for spec in get_registry().values():
        assert spec.model_field in mf, (
            f"{spec.name}.model_field '{spec.model_field}' "
            "missing from all_provider_mutable_fields()"
        )


def test_runtime_overrides_secret_fields_covers_registry() -> None:
    """runtime_overrides.SECRET_FIELDS must include every provider secret field."""
    from wabot_agent.runtime_overrides import SECRET_FIELDS

    provider_secrets = set(all_secret_fields())
    missing = provider_secrets - SECRET_FIELDS
    assert not missing, (
        f"SECRET_FIELDS in runtime_overrides.py is missing provider secrets: {missing!r}. "
        "Add them to SECRET_FIELDS or update the registry."
    )


def test_runtime_overrides_mutable_fields_covers_registry() -> None:
    """runtime_overrides.MUTABLE_FIELDS must include every provider mutable field."""
    from wabot_agent.runtime_overrides import MUTABLE_FIELDS

    provider_fields = set(all_provider_mutable_fields())
    missing = provider_fields - MUTABLE_FIELDS
    assert not missing, (
        f"MUTABLE_FIELDS in runtime_overrides.py is missing provider fields: {missing!r}. "
        "Add them to MUTABLE_FIELDS or update the registry."
    )


def test_each_provider_spec_fields_are_valid_settings_attributes() -> None:
    """Every field name referenced in the registry must exist as a Settings attribute."""
    from wabot_agent.config import Settings

    settings_fields = set(Settings.model_fields.keys())
    for spec in get_registry().values():
        for fname in (spec.secret_field, spec.base_url_field, spec.model_field):
            if fname is not None:
                assert fname in settings_fields, (
                    f"Provider '{spec.name}' references field '{fname}' "
                    "which does not exist on Settings."
                )
