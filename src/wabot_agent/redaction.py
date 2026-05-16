from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SECRET_KEYS = ("key", "token", "secret", "password", "authorization", "cookie")
# Keys whose value is masked via mask_email() rather than replaced with [REDACTED].
EMAIL_KEYS = ("email",)

PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{6,}\d)(?!\d)")
BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
OPENROUTER_KEY_RE = re.compile(r"sk-or-[A-Za-z0-9._-]+")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 7:
        return value
    return f"{digits[:2]}***{digits[-2:]}"


def mask_email(value: str) -> str:
    """Mask an email address as ``first***last@domain``.

    Edge-case behaviour (call-site contract):
      - Empty / non-string-looking input is returned unchanged.
      - Strings with no ``@`` are returned unchanged.
      - Strings with multiple ``@`` only match the canonical form (a single
        ``@`` flanked by RFC-3696-ish runs); the regex's anchored ``fullmatch``
        on the trimmed value rejects anything else and returns the input as-is.
      - Local parts of length ``<= 2`` are fully masked to ``***`` because
        ``a***a`` for ``ab`` would leak both characters.

    The full email is NEVER persisted to logs — auth events emit only a hashed,
    truncated digest of the JWT ``sub`` (``email_hash``). This helper exists to
    scrub stray emails that leak through other fields (free-form log extras,
    error messages) as defence-in-depth.
    """
    if not value or not isinstance(value, str):
        return value
    stripped = value.strip()
    if not EMAIL_RE.fullmatch(stripped):
        return value
    local, _, domain = stripped.partition("@")
    if len(local) <= 2:
        masked_local = "***"
    else:
        masked_local = f"{local[0]}***{local[-1]}"
    return f"{masked_local}@{domain}"


def redact_text(value: str) -> str:
    value = BEARER_RE.sub("Bearer [REDACTED]", value)
    value = OPENROUTER_KEY_RE.sub("sk-or-[REDACTED]", value)
    value = EMAIL_RE.sub(lambda m: mask_email(m.group(0)), value)
    return PHONE_RE.sub(lambda m: mask_phone(m.group(1)), value)


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            lower = key_s.lower()
            if any(marker in lower for marker in SECRET_KEYS):
                out[key_s] = "[REDACTED]"
            elif lower in EMAIL_KEYS and isinstance(item, str):
                out[key_s] = mask_email(item)
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
