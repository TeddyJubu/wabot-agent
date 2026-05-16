from __future__ import annotations

from wabot_agent.config import Settings
from wabot_agent.models import _omit_tool_choice, model_settings


def test_nemotron_omits_tool_choice() -> None:
    settings = Settings(
        OPENROUTER_API_KEY="test-key",
        OPENROUTER_MODEL="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        WABOT_AGENT_OFFLINE_MODE=False,
    )
    assert _omit_tool_choice(settings.openrouter_model)
    assert model_settings(settings).tool_choice is None


def test_default_model_sets_tool_choice_auto() -> None:
    settings = Settings(
        OPENROUTER_API_KEY="test-key",
        OPENROUTER_MODEL="openai/gpt-4o-mini",
        WABOT_AGENT_OFFLINE_MODE=False,
    )
    assert not _omit_tool_choice(settings.openrouter_model)
    assert model_settings(settings).tool_choice == "auto"
