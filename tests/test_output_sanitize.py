from wabot_agent.output_sanitize import strip_model_thinking


def test_strip_model_thinking_removes_blocks() -> None:
    raw = "Hello <thinking>internal</thinking> world"
    cleaned = strip_model_thinking(raw)
    assert cleaned == "Hello  world"
    assert "internal" not in cleaned
