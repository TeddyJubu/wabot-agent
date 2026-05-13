from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SECRET_KEYS = ("key", "token", "secret", "password", "authorization", "cookie")
PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{6,}\d)(?!\d)")
BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
OPENROUTER_KEY_RE = re.compile(r"sk-or-[A-Za-z0-9._-]+")


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 7:
        return value
    return f"{digits[:2]}***{digits[-2:]}"


def redact_text(value: str) -> str:
    value = BEARER_RE.sub("Bearer [REDACTED]", value)
    value = OPENROUTER_KEY_RE.sub("sk-or-[REDACTED]", value)
    return PHONE_RE.sub(lambda m: mask_phone(m.group(1)), value)


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            if any(marker in key_s.lower() for marker in SECRET_KEYS):
                out[key_s] = "[REDACTED]"
            else:
                out[key_s] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


def looks_sensitive(value: str) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in SECRET_KEYS):
        return True
    if OPENROUTER_KEY_RE.search(value) or BEARER_RE.search(value):
        return True
    return False

