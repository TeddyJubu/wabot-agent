from __future__ import annotations

import pytest

from wabot_agent.config import Settings
from wabot_agent.web_fetch import validate_public_http_url


def test_validate_public_http_url_rejects_localhost() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        validate_public_http_url("http://localhost/file.png")


def test_validate_public_http_url_accepts_https() -> None:
    url, host = validate_public_http_url("https://example.com/logo.png")
    assert host == "example.com"
    assert url.startswith("https://")
