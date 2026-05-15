"""Cloudflare Access JWT verification.

Cloudflare Access fronts the FastAPI service via Cloudflare Tunnel. Every
authenticated request carries a ``Cf-Access-Jwt-Assertion`` header signed by
Cloudflare with RS256, with ``iss`` = the team domain and ``aud`` = the
Application Audience tag. We verify both, plus expiry, against the JWKS
fetched from ``https://<team-domain>/cdn-cgi/access/certs``.

The fetcher is injectable so tests can supply a static JWKS without hitting
the network. The JWKS is cached in a module-level dict keyed by team domain;
``clear_jwks_cache()`` is provided as a test helper.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx
import jwt
from jwt import InvalidTokenError, PyJWK


class CfAccessError(Exception):
    """Raised when a Cloudflare Access JWT cannot be verified."""


@dataclass(frozen=True)
class CfAccessConfig:
    team_domain: str | None
    aud: str | None
    jwks_ttl_seconds: int = 21600  # 6 hours


@dataclass(frozen=True)
class AccessIdentity:
    email: str | None
    sub: str | None
    aud: str


# Module-level cache keyed by team_domain. Bounded by the number of distinct
# Cloudflare teams the service ever talks to — in practice exactly one.
_jwks_cache: dict[str, tuple[dict, float]] = {}


class JwksFetcher(Protocol):
    def __call__(self, team_domain: str) -> dict: ...


def _default_fetcher(team_domain: str) -> dict:
    url = f"https://{team_domain}/cdn-cgi/access/certs"
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise CfAccessError(f"JWKS fetch failed for {team_domain}: {exc}") from exc
    try:
        return resp.json()
    except ValueError as exc:
        raise CfAccessError(f"JWKS response was not JSON: {exc}") from exc


def _get_jwks(
    team_domain: str,
    ttl: int,
    fetcher: Callable[[str], dict],
) -> dict:
    now = time.monotonic()
    cached = _jwks_cache.get(team_domain)
    if cached is not None and (now - cached[1]) < ttl:
        return cached[0]
    jwks = fetcher(team_domain)
    _jwks_cache[team_domain] = (jwks, now)
    return jwks


def _find_key(jwks: dict, kid: str) -> PyJWK:
    for k in jwks.get("keys", []):
        if k.get("kid") == kid:
            return PyJWK(k)
    raise CfAccessError(f"Unknown signing kid: {kid}")


def verify_access_jwt(
    token: str,
    cfg: CfAccessConfig,
    *,
    fetcher: Callable[[str], dict] | None = None,
) -> AccessIdentity:
    """Verify a Cloudflare Access JWT and return the identity claims.

    Raises :class:`CfAccessError` on any failure.

    Defence-in-depth:
    - Algorithm pinned to RS256 (no ``none``, no symmetric fallback).
    - ``iss`` pinned to ``https://<team-domain>`` (rejects tokens from other CF teams).
    - ``aud`` matches the configured Application Audience.
    - ``exp`` required and enforced by PyJWT.

    The default fetcher is resolved at call time so tests can swap it via
    ``monkeypatch.setattr(cf_access, "_default_fetcher", ...)``.
    """
    if fetcher is None:
        fetcher = _default_fetcher
    if not cfg.team_domain:
        raise CfAccessError("cf_access team_domain is not configured")
    if not cfg.aud:
        raise CfAccessError("cf_access aud is not configured")

    try:
        header = jwt.get_unverified_header(token)
    except InvalidTokenError as exc:
        raise CfAccessError(f"Malformed JWT: {exc}") from exc

    kid = header.get("kid")
    if not kid:
        raise CfAccessError("JWT missing kid header")

    jwks = _get_jwks(cfg.team_domain, cfg.jwks_ttl_seconds, fetcher)
    pyjwk = _find_key(jwks, kid)

    try:
        jwt.decode(
            token,
            pyjwk.key,
            algorithms=["RS256"],
            audience=cfg.aud,
            issuer=f"https://{cfg.team_domain}",
            options={"require": ["aud", "iss", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise CfAccessError(f"Token expired: {exc}") from exc
    except jwt.InvalidAudienceError as exc:
        raise CfAccessError(f"Invalid audience: {exc}") from exc
    except jwt.InvalidIssuerError as exc:
        raise CfAccessError(f"Invalid issuer: {exc}") from exc
    except InvalidTokenError as exc:
        raise CfAccessError(f"Invalid JWT: {exc}") from exc

    # `jwt.decode` returns the claims; re-decode without verification to pull
    # the email/sub (already validated above; this avoids a double-verify pass).
    claims = jwt.decode(token, options={"verify_signature": False})
    return AccessIdentity(
        email=claims.get("email"),
        sub=claims.get("sub"),
        aud=cfg.aud,
    )


def clear_jwks_cache() -> None:
    """Test helper: drop the module-level JWKS cache."""
    _jwks_cache.clear()
