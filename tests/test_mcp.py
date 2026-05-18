from __future__ import annotations

import json
from pathlib import Path

import pytest

from wabot_agent.mcp import _resolve_env_mapping, _resolve_env_value, load_mcp_servers


def test_resolve_env_value(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _resolve_env_value("plain") == "plain"
    monkeypatch.setenv("COMPOSIO_API_KEY", "sk-test")
    assert _resolve_env_value("${COMPOSIO_API_KEY}") == "sk-test"
    assert _resolve_env_value("prefix-${COMPOSIO_API_KEY}-suffix") == "prefix-sk-test-suffix"


def test_resolve_env_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPOSIO_API_KEY", "key-123")
    out = _resolve_env_mapping({"x-consumer-api-key": "${COMPOSIO_API_KEY}"})
    assert out == {"x-consumer-api-key": "key-123"}


def test_composio_config_shape(tmp_path: Path) -> None:
    repo_config = Path(__file__).resolve().parents[1] / "configs" / "mcp.composio.json"
    raw = json.loads(repo_config.read_text(encoding="utf-8"))
    assert raw["servers"][0]["transport"] == "streamable_http"
    assert raw["servers"][0]["url"] == "https://connect.composio.dev/mcp"


def test_load_skips_disabled_servers(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "off",
                        "enabled": False,
                        "transport": "streamable_http",
                        "url": "https://example.com/mcp",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_mcp_servers(cfg) == []
