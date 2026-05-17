from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import Settings
from .system_tools import ffmpeg_to_wav, ffprobe_metadata

_whisper_lock = threading.Lock()


@dataclass(frozen=True)
class WhisperOptions:
    model_name: str
    compute_type: str
    beam_size: int
    language: str | None
    vad_filter: bool
    initial_prompt: str | None


@lru_cache(maxsize=4)
def _whisper_model(model_name: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device="cpu", compute_type=compute_type)


def resolve_whisper_model(settings: Settings, *, is_owner: bool) -> str:
    """Owners get the higher-quality model; everyone else uses the default (tiny)."""
    if is_owner and settings.whisper_model_owner.strip():
        return settings.whisper_model_owner.strip()
    return settings.whisper_model.strip()


def resolve_whisper_options(settings: Settings, *, is_owner: bool) -> WhisperOptions:
    beam = (
        settings.whisper_beam_size_owner if is_owner else settings.whisper_beam_size
    )
    language = (settings.whisper_language or "").strip() or None
    prompt = (settings.whisper_initial_prompt or "").strip() or None
    return WhisperOptions(
        model_name=resolve_whisper_model(settings, is_owner=is_owner),
        compute_type=settings.whisper_compute_type.strip() or "int8",
        beam_size=max(1, beam),
        language=language,
        vad_filter=settings.whisper_vad_filter,
        initial_prompt=prompt,
    )


def _audio_duration_sec(path: Path) -> float | None:
    meta = ffprobe_metadata(path)
    if not meta:
        return None
    try:
        return float(meta.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        return None


def transcribe_audio_file(
    path: Path,
    *,
    options: WhisperOptions,
    max_duration_sec: int = 90,
    excerpt_limit: int = 12_000,
) -> tuple[str, list[str]]:
    """Transcribe audio using faster-whisper (CPU). Converts to 16kHz mono WAV first."""
    warnings: list[str] = []
    if options.model_name != "tiny":
        warnings.append(f"whisper model: {options.model_name}")
    if options.language:
        warnings.append(f"whisper language: {options.language}")

    work_dir = path.parent / ".transcribe"
    work_dir.mkdir(parents=True, exist_ok=True)
    wav_path = work_dir / f"{path.stem}.16k.wav"

    ok, detail = ffmpeg_to_wav(path, wav_path, max_duration_sec=max_duration_sec)
    if not ok:
        return "", [detail or "audio conversion failed"]
    if max_duration_sec > 0:
        warnings.append(f"transcribed first {max_duration_sec}s only")

    duration = _audio_duration_sec(path)
    use_vad = options.vad_filter
    if duration is not None and duration < 12:
        # Short WhatsApp voice notes: VAD often clips the only speech segment.
        use_vad = False
        warnings.append("vad off (short clip)")

    try:
        with _whisper_lock:
            model = _whisper_model(options.model_name, options.compute_type)
            segments, info = model.transcribe(
                str(wav_path),
                beam_size=options.beam_size,
                language=options.language,
                initial_prompt=options.initial_prompt,
                vad_filter=use_vad,
                condition_on_previous_text=False,
                temperature=0.0,
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
                no_speech_threshold=0.5,
            )
            parts = [segment.text.strip() for segment in segments if segment.text.strip()]
            if info.language and not options.language:
                warnings.append(f"detected language: {info.language}")
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
