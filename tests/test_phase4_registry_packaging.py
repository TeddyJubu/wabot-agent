"""Regression guard: curated registry JSONs ship inside the package.

These files used to live under data/, but the VPS deploy script
(scripts/deploy-to-vignesh.sh) rsyncs with `--exclude 'data/'` because
data/ holds runtime state (sqlite, mem0, caches). Anything kept there
silently fails to ship.

The fix was to move them under src/wabot_agent/registries/ which rsync
includes naturally. These tests guard against a future move back.
"""
from __future__ import annotations

import json
from pathlib import Path

import wabot_agent
from wabot_agent.mcp_service import _registry_path as mcp_registry_path
from wabot_agent.mcp_service import registry_search as mcp_registry_search
from wabot_agent.skills_service import _registry_path as skills_registry_path
from wabot_agent.skills_service import registry_search as skills_registry_search


def test_skills_registry_file_exists_inside_package() -> None:
    path = skills_registry_path()
    package_root = Path(wabot_agent.__file__).resolve().parent
    assert path.is_file(), f"skills_registry.json missing at {path}"
    # Must be inside the package (so package data ships with the wheel /
    # survives rsync); explicitly NOT under data/ where the deploy
    # excludes it.
    assert package_root in path.parents, (
        f"skills_registry.json must live under {package_root} "
        f"to survive VPS deploy, but resolved to {path}"
    )
    assert "data" not in path.parts, (
        f"skills_registry.json must not be under data/ (rsync excludes it); got {path}"
    )


def test_mcp_registry_file_exists_inside_package() -> None:
    path = mcp_registry_path()
    package_root = Path(wabot_agent.__file__).resolve().parent
    assert path.is_file(), f"mcp_registry.json missing at {path}"
    assert package_root in path.parents, (
        f"mcp_registry.json must live under {package_root} "
        f"to survive VPS deploy, but resolved to {path}"
    )
    assert "data" not in path.parts, (
        f"mcp_registry.json must not be under data/ (rsync excludes it); got {path}"
    )


def test_skills_registry_is_parseable_and_non_empty() -> None:
    path = skills_registry_path()
    data = json.loads(path.read_text())
    assert isinstance(data, list)
    assert len(data) >= 1, "skills_registry.json should ship with at least one curated entry"


def test_mcp_registry_is_parseable_and_non_empty() -> None:
    path = mcp_registry_path()
    data = json.loads(path.read_text())
    assert isinstance(data, list)
    assert len(data) >= 1, "mcp_registry.json should ship with at least one curated entry"


def test_skills_registry_search_returns_results_without_query() -> None:
    """If this fails, registry_search() can't find the file and the UI
    will show an empty browser modal in production."""
    results = skills_registry_search("")
    assert len(results) >= 1


def test_mcp_registry_search_returns_results_without_query() -> None:
    """Mirror guard for the MCP curated registry."""
    # include_composio=False so we don't fire a network call during tests.
    results = mcp_registry_search("", include_composio=False)
    assert len(results) >= 1
