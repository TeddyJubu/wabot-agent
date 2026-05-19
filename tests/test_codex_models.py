from __future__ import annotations

from wabot_agent.codex_models import codex_model_choices_for_settings


def test_codex_model_choices_includes_current_custom_model() -> None:
    choices = codex_model_choices_for_settings("my-custom-model")
    assert choices[0] == "my-custom-model"
    assert "gpt-5.5" in choices
