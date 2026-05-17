from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(
    args: list[str],
    *,
    timeout: float = 90.0,
    input_bytes: bytes | None = None,
) -> tuple[int, str, str]:
    proc = subprocess.run(
        args,
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    return proc.returncode, stdout, stderr


def file_description(path: Path) -> str | None:
    if not tool_available("file"):
        return None
    code, out, _ = run_command(["file", "-b", str(path)], timeout=10.0)
    return out.strip() if code == 0 and out.strip() else None


def pdftotext_extract(path: Path, *, max_pages: int = 25) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not tool_available("pdftotext"):
        return "", ["pdftotext not installed"]
    with tempfile.TemporaryDirectory(prefix="wabot-pdf-") as tmp:
        out_txt = Path(tmp) / "out.txt"
        args = [
            "pdftotext",
            "-enc",
            "UTF-8",
            "-f",
            "1",
            "-l",
            str(max_pages),
            str(path),
            str(out_txt),
        ]
        code, _, err = run_command(args, timeout=60.0)
        if code != 0:
            return "", [f"pdftotext failed: {err.strip()[:200]}"]
        if not out_txt.exists():
            warnings.append("pdftotext produced no output (scanned PDF?)")
            return "", warnings
        return out_txt.read_text(encoding="utf-8", errors="replace"), warnings


def tesseract_ocr(path: Path, *, lang: str = "eng") -> tuple[str, list[str]]:
    if not tool_available("tesseract"):
        return "", ["tesseract not installed"]
    code, out, err = run_command(
        ["tesseract", str(path), "stdout", "-l", lang, "--psm", "auto"],
        timeout=120.0,
    )
    if code != 0:
        return "", [f"tesseract failed: {err.strip()[:200]}"]
    return out.strip(), []


def ffprobe_metadata(path: Path) -> dict[str, Any] | None:
    if not tool_available("ffprobe"):
        return None
    code, out, _ = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,bit_rate:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(path),
        ],
        timeout=30.0,
    )
    if code != 0 or not out.strip():
        return None
    try:
        import json

        return json.loads(out)
    except json.JSONDecodeError:
        return {"raw": out[:500]}


def ffmpeg_to_wav(
    path: Path, dest: Path, *, max_duration_sec: int = 90
) -> tuple[bool, str | None]:
    if not tool_available("ffmpeg"):
        return False, "ffmpeg not installed"
    dest.parent.mkdir(parents=True, exist_ok=True)
    code, _, err = run_command(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-t",
            str(max_duration_sec),
            "-af",
            "highpass=f=80,lowpass=f=8000,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(dest),
        ],
        timeout=float(max_duration_sec + 30),
    )
    if code != 0 or not dest.exists():
        return False, err.strip()[:200] or "ffmpeg conversion failed"
    return True, None


def ffmpeg_extract_frame(path: Path, dest: Path, *, at_sec: float = 1.0) -> tuple[bool, str | None]:
    if not tool_available("ffmpeg"):
        return False, "ffmpeg not installed"
    dest.parent.mkdir(parents=True, exist_ok=True)
    code, _, err = run_command(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(at_sec),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-q:v",
            "4",
            str(dest),
        ],
        timeout=45.0,
    )
    if code != 0 or not dest.exists():
        return False, err.strip()[:200] or "ffmpeg frame extract failed"
    return True, None
