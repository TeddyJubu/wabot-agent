"""Cross-route helpers: URL guards, inbound auth, wabot call wrapping.

Carved out of ``api/__init__.py`` as part of MASTER ME-1. None of these
functions capture state from ``create_app``'s closure; they're pure utilities
used by route handlers (or by the runtime-settings PATCH path).

The URL guards (``_require_loopback_url`` and the ``_require_safe_*_url``
family) defend operator-token-redirection attacks called out in CLAUDE.md
and MASTER Part I §3:

* ``wabot_endpoint`` must point at loopback so the WABOT_TOKEN bearer cannot
  be redirected to an attacker-controlled host.
* ``ollama_base_url`` (local) must be loopback for the same reason.
* ``ollama_cloud_base_url`` must be HTTPS to ``ollama.com``.
* ``openrouter_base_url`` (and other API URLs) cannot drop to plain HTTP
  except for loopback — otherwise the API key leaks on the wire.

``_verify_inbound_auth`` is the inbound-webhook token check. It's wrapped in
a ``Depends``-able closure inside ``create_app`` so the ``settings`` closure
is captured; the raw function lives here so it can be reused or unit-tested.

``_wabot_call`` is the single chokepoint for the
``try: redact(await wabot.X(...)) / except WabotError -> HTTP 502`` pattern
used by every group/admin handler (see PR #45 / QW-2).
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException

from ..config import Settings
from ..redaction import redact
from ..wabot import WabotError

_LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})


def _safe_next_path(next_path: str) -> str:
    """Restrict an open-redirect ``next`` query param to same-origin paths.

    Returns ``next_path`` if it starts with a single ``/`` (and not ``//``,
    which is interpreted as a protocol-relative URL); otherwise ``"/"``.
    """
    if next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return "/"


def _require_loopback_url(field: str, url: str) -> None:
    """Reject URLs whose host is not loopback. Defends the wabot bearer token
    from being redirected to an arbitrary host by an operator-token holder."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().strip("[]")
    if host not in _LOOPBACK_HOSTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field} must point at loopback (localhost, 127.0.0.1, or ::1); "
                f"got '{host or url}'."
            ),
        )


def _require_safe_ollama_local_url(field: str, url: str) -> None:
    """Ollama local must be loopback — the daemon holds cloud credentials."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail=f"{field} must use http or https; got scheme '{parsed.scheme}'.",
        )
    host = (parsed.hostname or "").lower().strip("[]")
    if host not in _LOOPBACK_HOSTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field} must point at the local Ollama daemon on loopback; "
                f"got '{host or url}'."
            ),
        )


def _require_safe_ollama_cloud_url(field: str, url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(
            status_code=400,
            detail=f"{field} must use https; got scheme '{parsed.scheme}'.",
        )
    host = (parsed.hostname or "").lower().strip("[]")
    if host not in ("ollama.com", "www.ollama.com"):
        raise HTTPException(
            status_code=400,
            detail=f"{field} must target ollama.com; got '{host or url}'.",
        )


def _require_safe_openrouter_url(field: str, url: str) -> None:
    """Allow https://anywhere or http://loopback. Plain HTTP to a remote host
    would leak the API key in cleartext."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail=f"{field} must use http or https; got scheme '{parsed.scheme}'.",
        )
    host = (parsed.hostname or "").lower().strip("[]")
    if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field} over plain HTTP is only allowed for loopback hosts; "
                f"use https for '{host or url}'."
            ),
        )


def _verify_inbound_auth(settings: Settings, authorization: str | None) -> None:
    """Reject inbound webhook requests that lack the WABOT_INBOUND_TOKEN bearer.

    This is the safety-critical chokepoint for ``/whatsapp/*`` routes. When
    ``WABOT_INBOUND_TOKEN`` is unset AND ``settings.requires_inbound_token()``
    returns False (local dev + loopback), requests proceed unauthenticated;
    in every other case a missing or mismatched bearer raises HTTP 401.
    """
    token = (settings.wabot_inbound_token or "").strip()
    if not token:
        if settings.requires_inbound_token():
            raise HTTPException(status_code=401, detail="unauthorized")
        return
    expected = f"Bearer {token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


async def _wabot_call(coro: Awaitable[Any]) -> Any:
    """Run a ``wabot.*`` coroutine, redact the response, and map ``WabotError`` to HTTP 502.

    Hand-rolled 5-line try/except blocks for every group/admin handler are easy to
    drift over time (different status codes, missing redact, swallowed errors).
    Funnelling through this single helper keeps the 502 mapping uniform and the
    redaction unmissable.
    """
    try:
        return redact(await coro)
    except WabotError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


__all__ = [
    "_LOOPBACK_HOSTS",
    "_require_loopback_url",
    "_require_safe_ollama_cloud_url",
    "_require_safe_ollama_local_url",
    "_require_safe_openrouter_url",
    "_safe_next_path",
    "_verify_inbound_auth",
    "_wabot_call",
]
