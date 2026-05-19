"""Multi-step task detection and WhatsApp progress message formatting."""

from __future__ import annotations

import re

_MULTI_STEP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bthen\b.*\bthen\b", re.I),
    re.compile(r"\b(and then|after that|step\s*\d|first,|second,|third,)\b", re.I),
    re.compile(r"\b(research|scrape|crawl|find all|compile|analyze|investigate)\b", re.I),
    re.compile(r"\b(multiple|several|each of|every|all of the)\b", re.I),
    re.compile(r"\b(download|upload|send|message|email|schedule|remind)\b.*\b(and|then)\b", re.I),
    re.compile(r"^\s*\d+[\.\)]\s+\S", re.M),
    re.compile(r"\n\s*[-*]\s+\S"),
)

TASK_STARTED_ACK = (
    "Got it — this looks like a multi-step task. I'll post a short plan here, "
    "then message you after each step completes."
)


def looks_like_multi_step_task(text: str) -> bool:
    """Heuristic: long or structurally complex requests that deserve progress pings."""
    stripped = (text or "").strip()
    if len(stripped) < 80:
        return False
    if len(stripped) >= 280:
        return True
    hits = sum(1 for pattern in _MULTI_STEP_PATTERNS if pattern.search(stripped))
    return hits >= 2 or (len(stripped) >= 160 and hits >= 1)


def format_task_plan(title: str, steps: list[str]) -> str:
    clean_title = title.strip() or "Plan"
    lines = [f"📋 {clean_title}"]
    for index, step in enumerate(steps, start=1):
        label = step.strip()
        if label:
            lines.append(f"{index}. {label}")
    lines.append("\nStarting step 1…")
    return "\n".join(lines)


def format_step_complete(
    step_number: int,
    step_title: str,
    status_summary: str,
    *,
    total_steps: int | None = None,
) -> str:
    prefix = f"✅ Step {step_number}"
    if total_steps is not None and total_steps > 0:
        prefix = f"✅ Step {step_number}/{total_steps}"
    title = step_title.strip() or "Done"
    detail = status_summary.strip()
    if detail:
        return f"{prefix}: {title}\n{detail}"
    return f"{prefix}: {title}"
