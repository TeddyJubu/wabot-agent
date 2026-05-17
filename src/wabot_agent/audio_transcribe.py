from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path

from .config import Settings
from .system_tools import ffmpeg_to_wav

_whisper_lock = threading.Lock()


@lru_cache(maxsize=4)
def _whisper_model(model_name: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device="cpu", compute_type=compute_type)


def resolve_whisper_model(settings: Settings, *, is_owner: bool) -> str:
    """Owners get the higher-quality model; everyone else uses the default (tiny)."""
    if is_owner and settings.whisper_model_owner.strip():
        return settings.whisper_model_owner.strip()
    return settings.whisper_model.strip()


def transcribe_audio_file(
    path: Path,
    *,
    model_name: str = "tiny",
    compute_type: str = "int8",
    max_duration_sec: int = 90,
    excerpt_limit: int = 12_000,
) -> tuple[str, list[str]]:
    """Transcribe audio using faster-whisper (CPU, int8). Converts to 16kHz mono WAV first."""
    warnings: list[str] = []
    if model_name != "tiny":
        warnings.append(f"whisper model: {model_name}")
    work_dir = path.parent / ".transcribe"
    work_dir.mkdir(parents=True, exist_ok=True)
    wav_path = work_dir / f"{path.stem}.16k.wav"

    ok, detail = ffmpeg_to_wav(path, wav_path, max_duration_sec=max_duration_sec)
    if not ok:
        return "", [detail or "audio conversion failed"]
    if max_duration_sec > 0:
        warnings.append(f"transcribed first {max_duration_sec}s only")

    try:
        with _whisper_lock:
            model = _whisper_model(model_name, compute_type)
            segments, _info = model.transcribe(
                str(wav_path),
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            parts = [segment.text.strip() for segment in segments if segment.text.strip()]
    except Exception as exc:  # noqa: BLE001
        return "", [f"whisper failed: {exc}"]
    finally:
        try:
            wav_path.unlink(missing_ok=True)
        except OSError:
            pass

    text = " ".join(parts).strip()
    if not text:
        warnings.append("no speech detected")
    if len(text) > excerpt_limit:
        text = text[: excerpt_limit - 20] + " …(truncated)"
    return text, warnings
