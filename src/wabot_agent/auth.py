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
     - ``?token=`` query string (legacy bootstrap, still supported)
     - ``POST /api/auth/login`` with ``dashboard_password`` or operator token

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
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def request_is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    forwarded = request.headers.get("x-forwarded-proto", "")
    return forwarded.split(",")[0].strip().lower() == "https"


def password_grants_dashboard_access(settings: Settings, password: str) -> bool:
    """True when password matches the optional dashboard PIN or operator token."""
    if settings.dashboard_password and secrets.compare_digest(
        password, settings.dashboard_password
    ):
        return True
    if settings.operator_token and secrets.compare_digest(
        password, settings.operator_token
    ):
        return True
    return False


def mint_operator_session_cookie(
    response, request: Request, settings: Settings
) -> None:
    """Set the HttpOnly operator session cookie (idempotent)."""
    if not settings.operator_token:
        return
    if request.cookies.get("wabot_agent_operator_token") == settings.operator_token:
        return
    response.set_cookie(
        key="wabot_agent_operator_token",
        value=settings.operator_token,
        httponly=True,
        samesite="strict",
        secure=settings.cf_access_required or request_is_https(request),
        max_age=_COOKIE_MAX_AGE,
    )


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


def resolve_human_factory(settings: Settings):
    """Like ``verify_human_factory`` but returns ``None`` instead of raising."""

    verify_human = verify_human_factory(settings)

    async def resolve_human(
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
    ) -> AuthIdentity | None:
        try:
            return await verify_human(
                request=request,
                token=token,
                x_operator_token=x_operator_token,
                authorization=authorization,
                operator_session=operator_session,
                cf_access_jwt=cf_access_jwt,
            )
        except HTTPException as exc:
            if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                # CF Access mode must 401 so the edge can challenge, not /login.
                if settings.cf_access_required:
                    raise
                return None
            raise

    return resolve_human


def maybe_mint_operator_cookie(
    response, request: Request, settings: Settings
) -> None:
    """Mint the operator cookie when the request was authorized via CF Access
    or via the ``?token=`` query bootstrap.

    Idempotent — no-ops if the cookie is already present or if the operator
    token is unset.
    """
    if not settings.operator_token:
        return
    if request.cookies.get("wabot_agent_operator_token") == settings.operator_token:
        return
    pending = getattr(request.state, "pending_cookie_token", None)
    has_cf_access = getattr(request.state, "cf_access_identity", None) is not None
    if not (pending or has_cf_access):
        return
    mint_operator_session_cookie(response, request, settings)


LOGIN_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>wabot — sign in</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body {
      margin: 0; min-height: 100dvh; display: grid; place-items: center;
      background: #0f1419; color: #e7e9ea;
    }
    form {
      width: min(22rem, 92vw); padding: 1.75rem; border-radius: 12px;
      background: #15202b; box-shadow: 0 8px 32px rgba(0,0,0,.35);
    }
    h1 { margin: 0 0 .25rem; font-size: 1.25rem; font-weight: 600; }
    p { margin: 0 0 1.25rem; font-size: .9rem; color: #8b98a5; }
    label { display: block; font-size: .85rem; margin-bottom: .35rem; }
    input {
      width: 100%; box-sizing: border-box; padding: .65rem .75rem;
      border: 1px solid #38444d; border-radius: 8px; background: #0f1419;
      color: inherit; font-size: 1rem;
    }
    button {
      margin-top: 1rem; width: 100%; padding: .7rem; border: 0; border-radius: 8px;
      background: #1d9bf0; color: #fff; font-size: 1rem; font-weight: 600;
      cursor: pointer;
    }
    button:hover { background: #1a8cd8; }
    .err { margin-top: .75rem; color: #f4212e; font-size: .85rem; }
  </style>
</head>
<body>
  <form method="post" action="/api/auth/login">
    <input type="hidden" name="next" value="{next}" />
    <h1>wabot dashboard</h1>
    <p>Enter your dashboard password to continue.</p>
    <label for="password">Password</label>
    <input id="password" name="password" type="password"
      autocomplete="current-password" autofocus required />
    {error}
    <button type="submit">Sign in</button>
  </form>
</body>
</html>
"""


def render_login_page(*, error_html: str = "", next_path: str = "/") -> str:
    safe_next = next_path if next_path.startswith("/") and not next_path.startswith("//") else "/"
    return (
        LOGIN_PAGE_HTML.replace("{error}", error_html).replace("{next}", safe_next)
    )
