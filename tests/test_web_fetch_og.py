from __future__ import annotations

from wabot_agent.web_fetch import extract_og_image_url


def test_extract_og_image_url() -> None:
    html = '<meta property="og:image" content="/logo.png">'
    assert extract_og_image_url(html, "https://example.com/page") == "https://example.com/logo.png"
