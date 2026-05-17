from __future__ import annotations

from pathlib import Path

from .config import Settings


def safe_media_segment(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._@-" else "_" for ch in value)
    return cleaned[:120] or "unknown"


def filename_from_content_disposition(header: str) -> str | None:
    if not header:
        return None
    marker = 'filename="'
    if marker in header:
        start = header.index(marker) + len(marker)
        end = header.find('"', start)
        if end > start:
            return header[start:end]
    return None


def media_path_allowed(settings: Settings, path: str) -> tuple[bool, Path | None, str | None]:
    try:
        media_root = settings.media_dir.resolve()
        candidate = Path(path).expanduser().resolve()
    except OSError as exc:
        return False, None, str(exc)
    if media_root not in candidate.parents and candidate != media_root:
        return False, None, f"Files must live under {settings.media_dir}."
    if not candidate.exists() or not candidate.is_file():
        return False, None, "File does not exist."
    return True, candidate, None


def workspace_path_allowed(settings: Settings, path: str) -> tuple[bool, Path | None, str | None]:
    """Allow reads under media_dir or data_dir (for processed outputs)."""
    try:
        roots = {settings.media_dir.resolve(), settings.data_dir.resolve()}
        candidate = Path(path).expanduser().resolve()
    except OSError as exc:
        return False, None, str(exc)
    if not any(root in candidate.parents or candidate == root for root in roots):
        return False, None, f"Path must be under {settings.media_dir} or {settings.data_dir}."
    if not candidate.exists() or not candidate.is_file():
        return False, None, "File does not exist."
    return True, candidate, None
