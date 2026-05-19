from __future__ import annotations

from wabot_agent.codex_device_login import _failure_detail, parse_device_auth_output

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


def test_failure_detail_is_short_not_raw_cli_banner() -> None:
    raw = SAMPLE + "\nSuccessfully logged in\n"
    detail = _failure_detail(raw, 1)
    assert "Welcome to Codex" not in detail
    assert len(detail) < 200
