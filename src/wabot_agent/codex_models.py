"""Curated Codex / ChatGPT subscription model and reasoning options for the dashboard."""

from __future__ import annotations

from typing import Literal

# https://developers.openai.com/codex/models
CODEX_MODEL_CHOICES: tuple[str, ...] = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2",
    "gpt-5.1-codex",
    "o4-mini",
    "o3",
)

CodexReasoningEffort = Literal[
    "default", "none", "minimal", "low", "medium", "high", "xhigh"
]

CODEX_REASONING_EFFORT_CHOICES: tuple[CodexReasoningEffort, ...] = (
    "default",
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)

CODEX_REASONING_LABELS: dict[CodexReasoningEffort, str] = {
    "default": "Default (no extra reasoning block)",
    "none": "None — fastest",
    "minimal": "Minimal",
    "low": "Low",
    "medium": "Medium (Codex default for gpt-5.5)",
    "high": "High — deeper thinking",
    "xhigh": "Extra high — slowest, strongest",
}


def normalize_codex_model(model: str) -> str:
    return model.strip()


def codex_model_choices_for_settings(current_model: str) -> list[str]:
    """Known models plus the active value when it is custom."""
    current = normalize_codex_model(current_model)
    if current and current not in CODEX_MODEL_CHOICES:
        return [current, *CODEX_MODEL_CHOICES]
    return list(CODEX_MODEL_CHOICES)
