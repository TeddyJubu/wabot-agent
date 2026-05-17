from __future__ import annotations

import csv
import json
import mimetypes
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .config import Settings

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
OFFICE_EXTENSIONS = {".docx", ".pptx", ".xlsx"}


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
    if ext in OFFICE_EXTENSIONS:
        return "office"
    return "binary"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n…(truncated)"


def _read_text_file(path: Path, limit: int) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return _truncate(raw, limit)


def _read_pdf_pypdf(path: Path, limit: int) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", ["pypdf not installed"]
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


def _read_pdf(path: Path, limit: int, *, use_system: bool) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if use_system:
        from .system_tools import pdftotext_extract

        body, sys_warnings = pdftotext_extract(path)
        warnings.extend(sys_warnings)
        if body.strip():
            return _truncate(body, limit), warnings
    body, py_warnings = _read_pdf_pypdf(path, limit)
    warnings.extend(py_warnings)
    return body, warnings


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


def _read_docx(path: Path, limit: int) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        return "", [f"docx read failed: {exc}"]
    root = ET.fromstring(xml_bytes)
    texts = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
    body = "\n".join(texts)
    if not body.strip():
        warnings.append("empty docx or unsupported structure")
    return _truncate(body, limit), warnings


def _process_image(
    path: Path, settings: Settings, excerpt_limit: int
) -> tuple[str, list[str], str]:
    warnings: list[str] = []
    summary = (
        f"Image file ({path.stat().st_size} bytes). "
        "Pixels attach for vision models when enabled."
    )
    excerpt = ""
    if settings.file_use_system_tools and settings.file_ocr_enabled:
        from .system_tools import file_description, tesseract_ocr

        desc = file_description(path)
        if desc:
            excerpt = f"[file(1)]: {desc}\n"
        ocr_text, ocr_warnings = tesseract_ocr(path)
        warnings.extend(ocr_warnings)
        if ocr_text:
            excerpt += _truncate(f"[ocr]: {ocr_text}", excerpt_limit)
            summary += " OCR text extracted on VPS."
    return excerpt, warnings, summary


def _process_audio(path: Path, settings: Settings, excerpt_limit: int) -> tuple[str, list[str], str]:
    warnings: list[str] = []
    meta_line = ""
    if settings.file_use_system_tools:
        from .system_tools import ffprobe_metadata

        meta = ffprobe_metadata(path)
        if meta:
            meta_json = _truncate(json.dumps(meta, ensure_ascii=False), 2000)
            meta_line = f"[ffprobe]: {meta_json}\n"

    excerpt = meta_line
    summary = f"Audio file ({path.stat().st_size} bytes)."
    try:
        from .audio_transcribe import transcribe_audio_file

        text, whisper_warnings = transcribe_audio_file(
            path,
            model_name=settings.whisper_model,
            max_duration_sec=settings.whisper_max_seconds,
            excerpt_limit=excerpt_limit,
        )
        warnings.extend(whisper_warnings)
        if text:
            excerpt += _truncate(f"[transcript]: {text}", excerpt_limit)
            summary += " Transcribed on VPS (faster-whisper)."
    except ImportError:
        warnings.append("faster-whisper not installed — audio transcription skipped")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"transcription failed: {exc}")
    return excerpt, warnings, summary


def _process_video(path: Path, settings: Settings, excerpt_limit: int) -> tuple[str, list[str], str]:
    warnings: list[str] = []
    parts: list[str] = []
    summary = f"Video file ({path.stat().st_size} bytes)."
    if not settings.file_use_system_tools:
        return "", warnings, summary + " Install ffmpeg on VPS for analysis."

    from .system_tools import ffprobe_metadata, ffmpeg_extract_frame, tesseract_ocr

    meta = ffprobe_metadata(path)
    if meta:
        parts.append(f"[ffprobe]: {_truncate(json.dumps(meta, ensure_ascii=False), 2000)}")

    frame_path = path.parent / f".{path.stem}.frame.jpg"
    ok, detail = ffmpeg_extract_frame(path, frame_path, at_sec=1.0)
    if ok:
        ocr_text, ocr_warnings = tesseract_ocr(frame_path)
        warnings.extend(ocr_warnings)
        if ocr_text:
            parts.append(f"[frame ocr @1s]: {_truncate(ocr_text, 2000)}")
        summary += " Frame sampled on VPS."
    elif detail:
        warnings.append(detail)
    try:
        frame_path.unlink(missing_ok=True)
    except OSError:
        pass

    try:
        from .audio_transcribe import transcribe_audio_file

        text, whisper_warnings = transcribe_audio_file(
            path,
            model_name=settings.whisper_model,
            max_duration_sec=settings.whisper_max_seconds,
            excerpt_limit=excerpt_limit // 2,
        )
        warnings.extend(whisper_warnings)
        if text:
            parts.append(f"[audio transcript]: {_truncate(text, excerpt_limit // 2)}")
            summary += " Audio track transcribed."
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"video audio transcript: {exc}")

    return "\n".join(parts), warnings, summary


def process_file_at_path(
    path: Path,
    *,
    mime: str | None = None,
    excerpt_limit: int = 12_000,
    max_bytes: int = 20 * 1024 * 1024,
    settings: Settings | None = None,
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

    cfg = settings or Settings(_env_file=None)
    use_system = cfg.file_use_system_tools
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
    if use_system:
        from .system_tools import file_description

        desc = file_description(path)
        if desc:
            result["file_type"] = desc

    try:
        if kind == "image":
            excerpt, warnings, summary = _process_image(path, cfg, excerpt_limit)
            result["warnings"] = warnings
            result["excerpt"] = excerpt or None
            result["summary"] = summary
        elif kind == "video":
            excerpt, warnings, summary = _process_video(path, cfg, excerpt_limit)
            result["warnings"] = warnings
            result["excerpt"] = excerpt or None
            result["summary"] = summary
        elif kind == "audio":
            excerpt, warnings, summary = _process_audio(path, cfg, excerpt_limit)
            result["warnings"] = warnings
            result["excerpt"] = excerpt or None
            result["summary"] = summary
        elif kind == "pdf":
            excerpt, warnings = _read_pdf(path, excerpt_limit, use_system=use_system)
            result["warnings"] = warnings
            result["excerpt"] = excerpt or None
            result["summary"] = "PDF text extraction on VPS (pdftotext/pypdf)."
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
            if path.suffix.lower() == ".docx":
                excerpt, warnings = _read_docx(path, excerpt_limit)
                result["excerpt"] = excerpt or None
                result["warnings"] = warnings
                result["summary"] = "DOCX text extracted on VPS."
            else:
                result["summary"] = (
                    f"Office file ({path.suffix}). Limited support — convert to PDF/DOCX if needed."
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
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "path": str(path),
            "bytes": size,
            "kind": kind,
            "detail": f"processing failed: {exc}",
        }

    return result
