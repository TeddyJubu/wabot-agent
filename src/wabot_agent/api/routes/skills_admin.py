"""Skills admin endpoints — Phase 4.

All endpoints require the operator token.
Prefix: /api/skills
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile

from ...auth import verify_human_factory
from ...skills_service import (
    delete_skill,
    install_from_registry,
    install_from_zip,
    list_skills,
    registry_search,
    scan_local,
)
from ..deps import AppDeps
from ..skill_schemas import (
    SkillInstallRegistryRequest,
    SkillRegistryEntry,
    SkillRow,
    SkillScanResponse,
)

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB hard cap


def register_skills_admin_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    memory = deps.memory
    human_dependency = Depends(verify_human_factory(settings))

    # -----------------------------------------------------------------------
    # GET /api/skills
    # -----------------------------------------------------------------------

    @router.get(
        "/api/skills",
        response_model=list[SkillRow],
        dependencies=[human_dependency],
        tags=["skills"],
    )
    async def list_skills_route() -> list[dict]:
        return list_skills(memory)

    # -----------------------------------------------------------------------
    # POST /api/skills/scan
    # -----------------------------------------------------------------------

    @router.post(
        "/api/skills/scan",
        response_model=SkillScanResponse,
        dependencies=[human_dependency],
        tags=["skills"],
    )
    async def scan_skills_route() -> dict:
        return scan_local(memory, settings)

    # -----------------------------------------------------------------------
    # POST /api/skills/install/zip
    # -----------------------------------------------------------------------

    @router.post(
        "/api/skills/install/zip",
        response_model=SkillRow,
        status_code=201,
        dependencies=[human_dependency],
        tags=["skills"],
    )
    async def install_skill_zip_route(file: UploadFile) -> dict:
        # Check content-length if provided by the client.
        content_length = file.size
        if content_length is not None and content_length > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"upload size {content_length} exceeds the 50 MB limit",
            )

        # Save to a temporary file so we can pass a Path to the service.
        with tempfile.NamedTemporaryFile(suffix=".skill", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            bytes_written = 0
            while True:
                chunk = await file.read(1024 * 64)  # 64 KB chunks
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > _MAX_UPLOAD_BYTES:
                    tmp_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail="upload exceeds the 50 MB limit",
                    )
                tmp.write(chunk)

        try:
            result = install_from_zip(memory, settings, tmp_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"install failed: {exc}"
            ) from exc
        finally:
            tmp_path.unlink(missing_ok=True)

        return result

    # -----------------------------------------------------------------------
    # POST /api/skills/install/registry
    # -----------------------------------------------------------------------

    @router.post(
        "/api/skills/install/registry",
        response_model=SkillRow,
        status_code=201,
        dependencies=[human_dependency],
        tags=["skills"],
    )
    async def install_skill_registry_route(body: SkillInstallRegistryRequest) -> dict:
        try:
            return install_from_registry(memory, settings, body.registry_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # -----------------------------------------------------------------------
    # DELETE /api/skills/{slug}
    # -----------------------------------------------------------------------

    @router.delete(
        "/api/skills/{slug}",
        status_code=204,
        dependencies=[human_dependency],
        tags=["skills"],
    )
    async def delete_skill_route(slug: str) -> Response:
        result = delete_skill(memory, settings, slug)
        if not result:
            raise HTTPException(status_code=404, detail=f"skill {slug!r} not found")
        return Response(status_code=204)

    # -----------------------------------------------------------------------
    # GET /api/skills/registry/search
    # -----------------------------------------------------------------------

    @router.get(
        "/api/skills/registry/search",
        response_model=list[SkillRegistryEntry],
        dependencies=[human_dependency],
        tags=["skills"],
    )
    async def search_skills_registry_route(
        q: str = Query(default="", description="Search query"),
    ) -> list[dict]:
        return registry_search(q)
