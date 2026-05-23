from __future__ import annotations

from wabot_agent.config import Settings
from wabot_agent.llm_provider import omit_tool_choice
from wabot_agent.models import model_settings


def test_trinity_free_keeps_tool_choice() -> None:
    settings = Settings(
        WABOT_AGENT_MODEL_PROVIDER="openrouter",
        OPENROUTER_API_KEY="test-key",
        OPENROUTER_MODEL="arcee-ai/trinity-large-thinking:free",
        WABOT_AGENT_OFFLINE_MODE=False,
    )
    assert not omit_tool_choice(settings)
    assert model_settings(settings).tool_choice == "auto"


def test_default_model_sets_tool_choice_auto() -> None:
    settings = Settings(
        WABOT_AGENT_MODEL_PROVIDER="openrouter",
        OPENROUTER_API_KEY="test-key",
        OPENROUTER_MODEL="openai/gpt-4o-mini",
        WABOT_AGENT_OFFLINE_MODE=False,
    )
    assert not omit_tool_choice(settings)
    assert model_settings(settings).tool_choice == "auto"


def test_ollama_always_uses_tool_choice() -> None:
    settings = Settings(
        WABOT_AGENT_MODEL_PROVIDER="ollama",
        OLLAMA_MODEL="minimax-m2.7:cloud",
        WABOT_AGENT_OFFLINE_MODE=False,
    )
    assert not omit_tool_choice(settings)
    assert model_settings(settings).tool_choice == "auto"
