from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "knowledge" / "templates"
_INSTRUCTIONS_NAME = "instructions.md"
_MEMORY_NAME = "memory.md"

_cache: dict[str, tuple[float, str]] = {}


def _knowledge_dir(settings: Settings) -> Path:
    return Path(settings.knowledge_dir)


def _instructions_path(settings: Settings) -> Path:
    return _knowledge_dir(settings) / _INSTRUCTIONS_NAME


def _memory_path(settings: Settings) -> Path:
    return _knowledge_dir(settings) / _MEMORY_NAME


def _template_path(name: str) -> Path:
    return _TEMPLATES_DIR / name


def _invalidate_cache(path: Path) -> None:
    key = str(path.resolve())
    _cache.pop(key, None)


def _read_cached(path: Path) -> str:
    key = str(path.resolve())
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return ""
    cached = _cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    _cache[key] = (mtime, text)
    return text


def truncate_for_prompt(text: str, max_chars: int) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if len(stripped) <= max_chars:
        return stripped
    suffix = "… [truncated]"
    keep = max(0, max_chars - len(suffix))
    return stripped[:keep].rstrip() + suffix


def format_contact_facts(facts: dict[str, Any], max_chars: int) -> str:
    rows = facts.get("facts") if isinstance(facts, dict) else None
    if not rows:
        return ""
    lines: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key", "")).strip()
        value = str(row.get("value", "")).strip()
        if not key:
            continue
        lines.append(f"- {key}: {value}")
    if not lines:
        return ""
    return truncate_for_prompt("\n".join(lines), max_chars)


def ensure_knowledge_files(settings: Settings) -> None:
    dest = _knowledge_dir(settings)
    dest.mkdir(parents=True, exist_ok=True)
    for name in (_INSTRUCTIONS_NAME, _MEMORY_NAME):
        target = dest / name
        if target.exists():
            continue
        template = _template_path(name)
        if template.exists():
            shutil.copy2(template, target)
        else:
            target.write_text("", encoding="utf-8")


def read_instructions_raw(settings: Settings) -> str:
    ensure_knowledge_files(settings)
    path = _instructions_path(settings)
    if not path.exists():
        return ""
    return _read_cached(path)


def read_global_memory_raw(settings: Settings) -> str:
    ensure_knowledge_files(settings)
    path = _memory_path(settings)
    if not path.exists():
        return ""
    return _read_cached(path)


def load_instructions(settings: Settings) -> str:
    return truncate_for_prompt(
        read_instructions_raw(settings),
        settings.knowledge_instructions_max_chars,
    )


def load_global_memory(settings: Settings) -> str:
    return truncate_for_prompt(
        read_global_memory_raw(settings),
        settings.knowledge_memory_max_chars,
    )


def save_instructions(settings: Settings, content: str) -> dict[str, Any]:
    from .instructions_cache import invalidate_instructions_cache

    ensure_knowledge_files(settings)
    path = _instructions_path(settings)
    path.write_text(content, encoding="utf-8")
    _invalidate_cache(path)
    invalidate_instructions_cache()
    return _doc_meta(path, settings.knowledge_instructions_max_chars)


def save_global_memory(settings: Settings, content: str) -> dict[str, Any]:
    from .instructions_cache import invalidate_instructions_cache

    ensure_knowledge_files(settings)
    path = _memory_path(settings)
    path.write_text(content, encoding="utf-8")
    _invalidate_cache(path)
    invalidate_instructions_cache()
    return _doc_meta(path, settings.knowledge_memory_max_chars)


@dataclass(frozen=True)
class KnowledgeDocMeta:
    id: str
    path: str
    updated_at: str | None
    char_count: int
    truncated_preview: str


def _doc_meta(path: Path, preview_max: int) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        mtime = path.stat().st_mtime
        updated_at = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
    except OSError:
        text = ""
        updated_at = None
    preview = truncate_for_prompt(text, min(preview_max, 500))
    doc_id = path.name.removesuffix(".md")
    return {
        "id": doc_id,
        "path": str(path),
        "updated_at": updated_at,
        "char_count": len(text),
        "truncated_preview": preview,
    }


def list_knowledge_docs(settings: Settings) -> list[dict[str, Any]]:
    ensure_knowledge_files(settings)
    return [
        _doc_meta(_instructions_path(settings), settings.knowledge_instructions_max_chars),
        _doc_meta(_memory_path(settings), settings.knowledge_memory_max_chars),
    ]
