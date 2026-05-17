from __future__ import annotations

from wabot_agent.config import Settings
from wabot_agent.recipients import is_owner_sender


def test_is_owner_sender_matches_numbers() -> None:
    settings = Settings(
        owner_numbers={"+8801521207499", "6580286424"},
        _env_file=None,
    )
    assert is_owner_sender(settings, "+8801521207499")
    assert is_owner_sender(settings, "6580286424@s.whatsapp.net")
    assert not is_owner_sender(settings, "+15550001111")
