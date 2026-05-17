from __future__ import annotations

import csv
import json
import mimetypes
import zipfile
from io import StringIO
from pathlib import Path
from typing import Any

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".xml",
    ".html",
    ".htm",
    ".yaml",
    ".yml",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".sql",
    ".sh",
    ".env",
    ".log",
    ".ini",
    ".toml",
    ".cfg",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".3gp"}
AUDIO_EXTENSIONS = {".ogg", ".opus", ".mp3", ".m4a", ".wav", ".aac", ".amr", ".caf"}


def whatsapp_send_kind_for_path(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    return "document"


def classify_file(path: Path, mime: str | None = None) -> str:
    ext = path.suffix.lower()
    guessed, _ = mimetypes.guess_type(path.name)
    content_type = (mime or guessed or "").lower()
    if ext in IMAGE_EXTENSIONS or content_type.startswith("image/"):
        return "image"
    if ext in VIDEO_EXTENSIONS or content_type.startswith("video/"):
        return "video"
    if ext in AUDIO_EXTENSIONS or content_type.startswith("audio/"):
        return "audio"
    if ext == ".pdf" or "pdf" in content_type:
        return "pdf"
    if ext in {".zip", ".tar", ".gz"} or "zip" in content_type:
        return "archive"
    if ext in TEXT_EXTENSIONS or content_type.startswith("text/"):
        return "text"
    if ext in {".docx", ".pptx", ".xlsx"}:
        return "office"
    return "binary"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n…(truncated)"


def _read_text_file(path: Path, limit: int) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return _truncate(raw, limit)


def _read_pdf(path: Path, limit: int) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", ["pypdf not installed — PDF text extraction unavailable"]
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages[:25]:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text.strip())
    body = "\n\n".join(parts)
    if not body.strip():
        warnings.append("no extractable text in PDF (may be scanned images)")
    return _truncate(body, limit), warnings


def _read_csv(path: Path, limit: int) -> str:
    lines: list[str] = []
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        for idx, row in enumerate(reader):
            if idx >= 40:
                lines.append("…(more rows)")
                break
            lines.append(",".join(row))
    return _truncate("\n".join(lines), limit)


def _read_json(path: Path, limit: int) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _truncate(json.dumps(data, indent=2, ensure_ascii=False)[:limit], limit)


def _read_zip(path: Path, limit: int) -> str:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()[:80]
    body = "\n".join(names)
    if len(names) >= 80:
        body += "\n…(more entries)"
    return _truncate(body, limit)


def process_file_at_path(
    path: Path,
    *,
    mime: str | None = None,
    excerpt_limit: int = 12_000,
    max_bytes: int = 20 * 1024 * 1024,
) -> dict[str, Any]:
    """Extract a VPS-local summary of a file for the agent."""
    if not path.is_file():
        return {"ok": False, "detail": "not a file", "path": str(path)}
    size = path.stat().st_size
    if size > max_bytes:
        return {
            "ok": False,
            "path": str(path),
            "bytes": size,
            "detail": f"file exceeds max processing size ({max_bytes} bytes)",
        }

    kind = classify_file(path, mime)
    guessed, _ = mimetypes.guess_type(path.name)
    result: dict[str, Any] = {
        "ok": True,
        "path": str(path),
        "filename": path.name,
        "bytes": size,
        "kind": kind,
        "mime": mime or guessed,
        "warnings": [],
    }

    try:
        if kind == "image":
            result["summary"] = (
                f"Image file ({size} bytes). Pixels are attached for vision models when enabled."
            )
        elif kind == "video":
            result["summary"] = f"Video file ({size} bytes). Stored on VPS; no frame extraction yet."
        elif kind == "audio":
            result["summary"] = (
                f"Audio file ({size} bytes). Stored on VPS; transcription not run automatically."
            )
        elif kind == "pdf":
            excerpt, warnings = _read_pdf(path, excerpt_limit)
            result["warnings"] = warnings
            result["excerpt"] = excerpt
            result["summary"] = "PDF text extraction on VPS."
        elif kind == "archive":
            result["excerpt"] = _read_zip(path, excerpt_limit)
            result["summary"] = "Archive listing."
        elif kind == "text":
            if path.suffix.lower() == ".csv":
                result["excerpt"] = _read_csv(path, excerpt_limit)
            elif path.suffix.lower() == ".json":
                try:
                    result["excerpt"] = _read_json(path, excerpt_limit)
                except json.JSONDecodeError:
                    result["excerpt"] = _read_text_file(path, excerpt_limit)
                    result["warnings"] = ["invalid JSON — returned raw text"]
            else:
                result["excerpt"] = _read_text_file(path, excerpt_limit)
            result["summary"] = "Text file read on VPS."
        elif kind == "office":
            result["summary"] = (
                f"Office document ({path.suffix}). Stored on VPS; "
                "use process_vps_file after converting to PDF/text if needed."
            )
        else:
            sample = path.read_bytes()[:256]
            printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in sample)
            if sample and printable / len(sample) > 0.85:
                result["excerpt"] = _truncate(
                    sample.decode("utf-8", errors="replace"), excerpt_limit
                )
                result["summary"] = "Binary file with mostly printable content."
            else:
                result["summary"] = f"Binary file ({size} bytes)."
    except Exception as exc:  # noqa: BLE001 — surface to agent as structured failure
        return {
            "ok": False,
            "path": str(path),
            "bytes": size,
            "kind": kind,
            "detail": f"processing failed: {exc}",
        }

    return result
