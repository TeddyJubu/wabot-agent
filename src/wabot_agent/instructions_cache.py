from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .memory import MemoryStore
from .skills import render_skill_summary

_skill_summary_cache: dict[tuple[Any, ...], str] = {}
_instructions_cache: dict[tuple[Any, ...], str] = {}


def invalidate_instructions_cache() -> None:
    _skill_summary_cache.clear()
    _instructions_cache.clear()


def _skills_mtime_max(skills_dir: Path) -> float:
    if not skills_dir.is_dir():
        return 0.0
    latest = 0.0
    for skill_md in skills_dir.glob("*/SKILL.md"):
        try:
            latest = max(latest, skill_md.stat().st_mtime)
        except OSError:
            continue
    return latest


def _knowledge_mtime_max(settings: Settings) -> float:
    try:
        from .knowledge_store import _instructions_path, _memory_path
    except ImportError:
        return 0.0
    latest = 0.0
    for path_fn in (_instructions_path, _memory_path):
        path = path_fn(settings)
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return latest


def _agent_notes_version(memory: MemoryStore | None) -> str:
    if memory is None:
        return ""
    return memory.agent_notes_max_updated_at()


def cached_render_skill_summary(skills_dir: Path) -> str:
    key = ("skills", str(skills_dir.resolve()), _skills_mtime_max(skills_dir))
    cached = _skill_summary_cache.get(key)
    if cached is not None:
        return cached
    summary = render_skill_summary(skills_dir)
    _skill_summary_cache[key] = summary
    return summary


def cached_build_agent_instructions(
    settings: Settings,
    *,
    memory: MemoryStore | None,
    build_fn: Callable[..., str],
    build_kwargs: dict[str, Any],
) -> str:
    mem0_flag = bool(getattr(settings, "mem0_enabled", False))
    composio_flag = bool(getattr(settings, "composio_enabled", False))
    key = (
        "instructions",
        mem0_flag,
        composio_flag,
        _skills_mtime_max(settings.skills_dir),
        _knowledge_mtime_max(settings),
        _agent_notes_version(memory),
    )
    cached = _instructions_cache.get(key)
    if cached is not None:
        return cached
    instructions = build_fn(**build_kwargs)
    _instructions_cache[key] = instructions
    return instructions
