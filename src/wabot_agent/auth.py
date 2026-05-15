"""Human authentication for FastAPI routes.

Two paths, picked at request time by the `cf_access_required` setting:

1. **Cloudflare Access JWT** when ``settings.cf_access_required=True``.
   The header ``Cf-Access-Jwt-Assertion`` is verified against Cloudflare's
   JWKS for the team domain via :mod:`wabot_agent.cf_access`. On success
   we stash the identity on ``request.state.cf_access_identity`` so the
   handler can decide whether to mint the operator cookie.

2. **Operator token** otherwise. Accepted credentials, all compared with
   ``secrets.compare_digest``:
     - ``X-Operator-Token`` header
     - ``Authorization: Bearer <token>``
     - ``wabot_agent_operator_token`` cookie
     - ``?token=`` query string (legacy bootstrap, used by GET / and /pair on
       first visit before the cookie is set)

When ``settings.operator_token`` is unset, the operator-token path returns
the synthetic source ``"open"`` — preserving today's local-dev behavior
where the dashboard works without any auth.

``AuthIdentity.tenant_id`` is the seam for future multi-tenancy. Today it's
always ``"operator"``; future sub-projects can carry an account UUID
without route changes.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Literal

from fastapi import Cookie, Header, HTTPException, Query, Request, status

from .cf_access import CfAccessConfig, CfAccessError, verify_access_jwt
from .config import Settings

AuthSource = Literal[
    "operator-cookie",
    "operator-header",
    "operator-query",
    "cf-access",
    "open",
]


@dataclass(frozen=True)
class AuthIdentity:
    """The verified identity attached to a request.

    `source` is informational. `tenant_id` is the only field current code
    routes on; everything else is for logs and future multi-tenant work.
    """

    tenant_id: str
    email: str | None
    sub: str | None
    source: AuthSource


_OPERATOR_TENANT_ID = "operator"


def _verify_operator_token(
    settings: Settings,
    x_operator_token: str | None,
    authorization: str | None,
    operator_session: str | None,
) -> AuthSource | None:
    """Return the source that matched, or None if nothing matched.

    When ``settings.operator_token`` is unset, returns the synthetic source
    ``"open"`` — this is the local-dev fall-through that preserves today's
    behaviour.

    All comparisons use ``secrets.compare_digest`` to avoid timing oracles
    on the operator token.
    """
    if not settings.operator_token:
        return "open"
    expected = settings.operator_token
    if x_operator_token is not None and secrets.compare_digest(
        x_operator_token, expected
    ):
        return "operator-header"
    if authorization is not None and authorization.lower().startswith("bearer "):
        candidate = authorization[7:]
        if secrets.compare_digest(candidate, expected):
            return "operator-header"
    if operator_session is not None and secrets.compare_digest(
        operator_session, expected
    ):
        return "operator-cookie"
    return None


def verify_human_factory(settings: Settings):
    """Build a FastAPI dependency bound to a Settings instance.

    Using a factory keeps the dependency pure (no module-level mutable
    state) and lets ``create_app`` wire it once at startup.
    """

    async def verify_human(
        request: Request,
        token: str | None = Query(default=None),
        x_operator_token: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
        operator_session: str | None = Cookie(
            default=None, alias="wabot_agent_operator_token"
        ),
        cf_access_jwt: str | None = Header(
            default=None, alias="Cf-Access-Jwt-Assertion"
        ),
    ) -> AuthIdentity:
        # 1. Cloudflare Access path (required mode).
        if settings.cf_access_required:
            if not cf_access_jwt:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Cloudflare Access required",
                )
            try:
                access = verify_access_jwt(
                    cf_access_jwt,
                    CfAccessConfig(
                        team_domain=settings.cf_access_team_domain,
                        aud=settings.cf_access_aud,
                    ),
                )
            except CfAccessError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Cloudflare Access: {exc}",
                ) from exc
            request.state.cf_access_identity = access
            return AuthIdentity(
                tenant_id=_OPERATOR_TENANT_ID,
                email=access.email,
                sub=access.sub,
                source="cf-access",
            )

        # 2. Operator token path (legacy / local-dev).
        source = _verify_operator_token(
            settings, x_operator_token, authorization, operator_session
        )

        # 2a. Fall back to ?token= query bootstrap.
        if (
            source is None
            and token
            and settings.operator_token
            and secrets.compare_digest(token, settings.operator_token)
        ):
            source = "operator-query"
            request.state.pending_cookie_token = token

        if source is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="operator auth required",
            )

        return AuthIdentity(
            tenant_id=_OPERATOR_TENANT_ID,
            email=None,
            sub=None,
            source=source,
        )

    return verify_human


def maybe_mint_operator_cookie(
    response, request: Request, settings: Settings
) -> None:
    """Mint the operator cookie when the request was authorized via CF Access
    or via the ``?token=`` query bootstrap.

    Idempotent — no-ops if the cookie is already present or if the operator
    token is unset.

    Flag selection:
    - ``HttpOnly`` always — the cookie should never be readable from JS.
    - ``SameSite=Strict`` always — same as the existing ``GET /`` bootstrap.
    - ``Secure`` is True when ``cf_access_required=True``. Under that mode,
      cloudflared terminates TLS at the edge and the only legitimate path to
      this code is via an HTTPS-fronted tunnel; setting Secure=True ensures
      the cookie is refused over plain HTTP in case the FastAPI port is
      ever inadvertently exposed. In legacy operator-token mode the cookie
      may be set over loopback HTTP for local dev, so Secure stays False.
    """
    if not settings.operator_token:
        return
    if request.cookies.get("wabot_agent_operator_token") == settings.operator_token:
        return
    pending = getattr(request.state, "pending_cookie_token", None)
    has_cf_access = getattr(request.state, "cf_access_identity", None) is not None
    if not (pending or has_cf_access):
        return
    response.set_cookie(
        key="wabot_agent_operator_token",
        value=settings.operator_token,
        httponly=True,
        samesite="strict",
        secure=settings.cf_access_required,
        max_age=60 * 60 * 24 * 30,  # 30 days
    )
