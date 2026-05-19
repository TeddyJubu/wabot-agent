from __future__ import annotations

from wabot_agent.codex_device_login import parse_device_auth_output

SAMPLE = """
Welcome to Codex
Follow these steps to sign in with ChatGPT using device code authorization:

1. Open this link in your browser and sign in to your account
   https://auth.openai.com/codex/device

2. Enter this one-time code (expires in 15 minutes)
   AY53-ERUBQ

Device codes are a common phishing target.
"""


def test_parse_device_auth_output() -> None:
    parsed = parse_device_auth_output(SAMPLE)
    assert parsed == ("https://auth.openai.com/codex/device", "AY53-ERUBQ")
