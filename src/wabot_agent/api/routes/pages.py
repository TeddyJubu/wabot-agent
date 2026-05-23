"""Static HTML pages and the favicon endpoint.

Carved out of api/__init__.py as part of MASTER ME-1 Part 3. These routes
serve operator-facing HTML (the dashboard SPA, the pairing page, the
knowledge editor) and the favicon — none of them touch wabot, memory, or
the SSE hub directly. They depend on settings (for static_dir resolution)
and on the auth path (via resolve_human / maybe_mint_operator_cookie) to
gate dashboard access.

The /login GET and POST live in api/routes/auth.py — those are
authentication-flow, not 'page' rendering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from ...auth import (
    AuthIdentity,
    maybe_mint_operator_cookie,
    resolve_human_factory,
)
from ..deps import AppDeps

# api/routes/pages.py → routes → api → wabot_agent → src → project_root
_STATIC_DIR = Path(__file__).resolve().parents[4] / "static"


def _dashboard_file(static_dir: Path) -> FileResponse:
    """Return a FileResponse for the dashboard index.html, or raise 404.

    Duplicated from api/__init__.py (module level) to avoid a circular
    import: __init__ imports routes/pages, so routes/pages cannot import
    back from __init__.  The body is three lines — duplication cost is
    lower than the circular-import risk.
    """
    index = static_dir / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Dashboard not built.")
    return FileResponse(index)


def register_pages_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    resolve_human = resolve_human_factory(settings)
    static_dir = _STATIC_DIR

    @router.get("/favicon.ico", include_in_schema=False, response_model=None)
    async def favicon() -> Response:
        favicon_path = static_dir / "favicon.svg"
        if favicon_path.exists():
            return FileResponse(favicon_path, media_type="image/svg+xml")
        return Response(status_code=204)

    @router.get("/")
    async def dashboard(
        request: Request,
        identity: AuthIdentity | None = Depends(resolve_human),  # noqa: B008
    ) -> Any:
        if identity is None:
            return RedirectResponse(url="/login?next=/", status_code=302)
        file_response = _dashboard_file(static_dir)
        file_response.headers["Cache-Control"] = "no-store"
        maybe_mint_operator_cookie(file_response, request, settings)
        return file_response

    @router.get("/pair")
    async def pair_page(
        request: Request,
        identity: AuthIdentity | None = Depends(resolve_human),  # noqa: B008
    ) -> Any:
        """Mobile-first WhatsApp pairing page.

        Serves the same React bundle as ``/`` — ``web/src/main.tsx`` picks
        ``<PairView />`` when ``window.location.pathname === '/pair'``.
        """
        if identity is None:
            return RedirectResponse(url="/login?next=/pair", status_code=302)
        file_response = _dashboard_file(static_dir)
        file_response.headers["Cache-Control"] = "no-store"
        maybe_mint_operator_cookie(file_response, request, settings)
        return file_response

    @router.get("/knowledge")
    async def knowledge_page(
        request: Request,
        identity: AuthIdentity | None = Depends(resolve_human),  # noqa: B008
    ) -> Any:
        """Knowledge management dashboard (BlockNote editors + contact facts)."""
        if identity is None:
            return RedirectResponse(url="/login?next=/knowledge", status_code=302)
        file_response = _dashboard_file(static_dir)
        file_response.headers["Cache-Control"] = "no-store"
        maybe_mint_operator_cookie(file_response, request, settings)
        return file_response
