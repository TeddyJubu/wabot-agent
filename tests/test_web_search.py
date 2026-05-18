from __future__ import annotations

from wabot_agent.web_search import parse_duckduckgo_html

SAMPLE_HTML = """
<a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fopenclaw.ai%2F&amp;rut=1">OpenClaw</a>
<a class="result__a" href="https://example.com/logo.png">Logo PNG</a>
"""


def test_parse_duckduckgo_html_extracts_urls() -> None:
    results = parse_duckduckgo_html(SAMPLE_HTML, max_results=5)
    urls = {r.url for r in results}
    assert "https://openclaw.ai/" in urls
    assert "https://example.com/logo.png" in urls
