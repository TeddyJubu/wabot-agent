from __future__ import annotations

import re

_THINKING_BLOCK = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)


def strip_model_thinking(text: str) -> str:
    """Remove model reasoning blocks from text sent to WhatsApp or shown as final reply."""
    cleaned = _THINKING_BLOCK.sub("", text)
    return cleaned.strip()
