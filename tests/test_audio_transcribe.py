from __future__ import annotations

from wabot_agent.audio_transcribe import resolve_whisper_model, resolve_whisper_options
from wabot_agent.config import Settings


def test_resolve_whisper_model_owner_vs_default() -> None:
    settings = Settings(
        whisper_model="tiny",
        whisper_model_owner="small",
        _env_file=None,
    )
    assert resolve_whisper_model(settings, is_owner=False) == "tiny"
    assert resolve_whisper_model(settings, is_owner=True) == "small"


def test_resolve_whisper_options_owner_beam_and_language() -> None:
    settings = Settings(
        whisper_model="tiny",
        whisper_model_owner="small",
        whisper_beam_size=3,
        whisper_beam_size_owner=5,
        whisper_language="en",
        whisper_initial_prompt="WhatsApp voice note",
        _env_file=None,
    )
    owner = resolve_whisper_options(settings, is_owner=True)
    assert owner.model_name == "small"
    assert owner.beam_size == 5
    assert owner.language == "en"
    assert owner.initial_prompt == "WhatsApp voice note"

    other = resolve_whisper_options(settings, is_owner=False)
    assert other.model_name == "tiny"
    assert other.beam_size == 3
