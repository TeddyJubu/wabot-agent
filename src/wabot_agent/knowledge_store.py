from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "knowledge" / "templates"
_INSTRUCTIONS_NAME = "instructions.md"
_LEGACY_MEMORY_NAME = "memory.md"
_LEGACY_MEMORY_MIGRATED_NAME = "memory.md.migrated"
_MIGRATION_MARKER = "<!-- merged from memory.md -->"

_cache: dict[str, tuple[float, str]] = {}
_write_locks: dict[Path, asyncio.Lock] = {}
# Sync-safe lock for the legacy-memory migration. The migration is called
# from sync code paths (``read_instructions_raw`` / ``list_knowledge_docs``)
# so the asyncio per-path write lock does not apply. Without this guard
# two concurrent first-reads could both pass the marker check and append
# the merged block twice before either write lands. The marker check
# inside the critical section makes the operation idempotent across all
# in-process callers.
_migration_lock = threading.Lock()


def _knowledge_dir(settings: Settings) -> Path:
    return Path(settings.knowledge_dir)


def _instructions_path(settings: Settings) -> Path:
    return _knowledge_dir(settings) / _INSTRUCTIONS_NAME


def _legacy_memory_path(settings: Settings) -> Path:
    return _knowledge_dir(settings) / _LEGACY_MEMORY_NAME


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


def get_write_lock(path: Path) -> asyncio.Lock:
    """Return a per-path asyncio.Lock, creating it on first use.

    Reads do not require the lock (mtime-cached, single-writer semantics);
    only :func:`atomic_write_text` callers should acquire it.
    """
    key = path.resolve()
    lock = _write_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _write_locks[key] = lock
    return lock


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically write ``content`` to ``path``.

    Writes to a NamedTemporaryFile in the same directory, fsyncs the file,
    then ``os.replace``s onto the target. Best-effort fsync on the parent
    directory afterwards — errors are swallowed on platforms (e.g. some
    Windows configurations) where dir fsync is unsupported.
    """
    path = Path(path)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "wb") as fh:
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise
    # Best-effort fsync of the parent directory so the rename is durable.
    with contextlib.suppress(OSError, AttributeError):
        dir_fd = os.open(str(parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def compute_version(text: str) -> str:
    """Return the first 16 hex chars of SHA-256(text.encode('utf-8')).

    Used as an optimistic-concurrency version token for instructions.md.
    Deterministic, ~64 bits of entropy — plenty for collision-safety on a
    single-document store. The empty string hashes to a known fixed value
    (``e3b0c44298fc1c14``).
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class StaleVersionError(Exception):
    """Raised by :func:`save_instructions_checked` when the supplied
    ``if_match`` token does not match the current on-disk version.

    The attached fields let callers (and the HTTP layer) return a 409
    response carrying the current content so the client can offer a
    "reload" or "overwrite anyway" choice without re-fetching.
    """

    def __init__(
        self,
        current_version: str,
        current_content: str,
        submitted_version: str | None,
    ) -> None:
        super().__init__(
            f"Stale version: submitted={submitted_version!r}, "
            f"current={current_version!r}"
        )
        self.current_version = current_version
        self.current_content = current_content
        self.submitted_version = submitted_version


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
    target = dest / _INSTRUCTIONS_NAME
    if target.exists():
        return
    template = _template_path(_INSTRUCTIONS_NAME)
    if template.exists():
        shutil.copy2(template, target)
    else:
        atomic_write_text(target, "")


def _maybe_migrate_legacy_memory(settings: Settings) -> None:
    """One-shot merge of legacy ``memory.md`` into ``instructions.md``.

    Idempotent: looks for the migration marker in the current instructions
    content and skips when present. When ``memory.md`` is missing, this is a
    no-op. After a successful merge the old file is renamed to
    ``memory.md.migrated`` so the operator keeps a recoverable copy.
    """
    legacy = _legacy_memory_path(settings)
    # Cheap pre-check outside the lock — keeps the hot path lock-free once
    # migration is done. The authoritative re-check happens inside.
    if not legacy.exists():
        return
    with _migration_lock:
        # Re-check under the lock: another caller may have completed the
        # migration (and renamed the legacy file) while we were waiting.
        if not legacy.exists():
            return
        target = _instructions_path(settings)
        try:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
        except OSError:
            current = ""
        if _MIGRATION_MARKER in current:
            return
        try:
            legacy_text = legacy.read_text(encoding="utf-8")
        except OSError:
            return
        merged = f"{current}\n\n{_MIGRATION_MARKER}\n\n{legacy_text}"
        atomic_write_text(target, merged)
        _invalidate_cache(target)
        archived = legacy.with_suffix(legacy.suffix + ".migrated")
        with contextlib.suppress(OSError):
            os.replace(legacy, archived)


def read_instructions_raw(settings: Settings) -> str:
    ensure_knowledge_files(settings)
    _maybe_migrate_legacy_memory(settings)
    path = _instructions_path(settings)
    if not path.exists():
        return ""
    return _read_cached(path)


def load_instructions(settings: Settings) -> str:
    return truncate_for_prompt(
        read_instructions_raw(settings),
        settings.knowledge_instructions_max_chars,
    )


def _write_instructions_unlocked(settings: Settings, content: str) -> dict[str, Any]:
    """Internal write helper. Assumes the caller holds the per-path write
    lock when concurrent writers are possible. Performs the atomic write,
    cache invalidation, and returns fresh doc metadata.
    """
    from .instructions_cache import invalidate_instructions_cache

    ensure_knowledge_files(settings)
    path = _instructions_path(settings)
    atomic_write_text(path, content)
    _invalidate_cache(path)
    invalidate_instructions_cache()
    return _doc_meta(path, settings.knowledge_instructions_max_chars)


def save_instructions(settings: Settings, content: str) -> dict[str, Any]:
    """Write ``content`` to instructions.md without a version check.

    Kept for in-process callers (CLI, tests, scripts) that need a simple
    synchronous save and do not care about cross-tab races. HTTP routes
    must use :func:`save_instructions_checked` instead so concurrent
    edits get a 409 instead of silently clobbering each other.
    """
    return _write_instructions_unlocked(settings, content)


async def save_instructions_checked(
    settings: Settings,
    content: str,
    if_match: str | None,
) -> dict[str, Any]:
    """Optimistic-concurrency save for instructions.md.

    Acquires the per-path write lock and, under that lock, computes the
    current on-disk version. If ``if_match`` is provided and does not
    match the current version, raises :class:`StaleVersionError` without
    writing. Otherwise performs the atomic write and returns fresh doc
    metadata (which includes the new version).

    Read-then-write happens entirely inside the lock so two concurrent
    writers cannot both observe the same version and both succeed.
    """
    ensure_knowledge_files(settings)
    path = _instructions_path(settings)
    async with get_write_lock(path):
        try:
            current_content = path.read_text(encoding="utf-8")
        except OSError:
            current_content = ""
        current_version = compute_version(current_content)
        if if_match is not None and if_match != current_version:
            raise StaleVersionError(
                current_version=current_version,
                current_content=current_content,
                submitted_version=if_match,
            )
        return _write_instructions_unlocked(settings, content)


@dataclass(frozen=True)
class KnowledgeDocMeta:
    id: str
    path: str
    updated_at: str | None
    char_count: int
    truncated_preview: str
    version: str


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
        "version": compute_version(text),
    }


def list_knowledge_docs(settings: Settings) -> list[dict[str, Any]]:
    ensure_knowledge_files(settings)
    _maybe_migrate_legacy_memory(settings)
    return [
        _doc_meta(_instructions_path(settings), settings.knowledge_instructions_max_chars),
    ]
