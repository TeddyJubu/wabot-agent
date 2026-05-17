from __future__ import annotations

from wabot_agent.audio_transcribe import resolve_whisper_model
from wabot_agent.config import Settings


def test_resolve_whisper_model_owner_vs_default() -> None:
    settings = Settings(
        whisper_model="tiny",
        whisper_model_owner="base",
        _env_file=None,
    )
    assert resolve_whisper_model(settings, is_owner=False) == "tiny"
    assert resolve_whisper_model(settings, is_owner=True) == "base"
