"""Agents CRUD + one-shot test API — Phase 3a.

8 endpoints under /api/agents.  All require the operator token (same
dependency as /api/settings).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from ...agents_service import (
    create_agent,
    delete_agent,
    get_agent,
    list_agents,
    run_agent_one_shot,
    set_agent_skills,
    set_agent_tools,
    update_agent,
)
from ...auth import verify_human_factory
from ..agent_schemas import (
    AgentCreate,
    AgentDetail,
    AgentSkillsUpdate,
    AgentSummary,
    AgentTestRequest,
    AgentTestResponse,
    AgentToolsUpdate,
    AgentUpdate,
)
from ..deps import AppDeps


def register_agents_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    memory = deps.memory
    human_dependency = Depends(verify_human_factory(settings))

    # -----------------------------------------------------------------------
    # GET /api/agents — list all agents
    # -----------------------------------------------------------------------

    @router.get(
        "/api/agents",
        response_model=list[AgentSummary],
        dependencies=[human_dependency],
        tags=["agents"],
    )
    async def list_agents_route() -> list[dict]:
        return list_agents(memory)

    # -----------------------------------------------------------------------
    # POST /api/agents — create a new agent
    # -----------------------------------------------------------------------

    @router.post(
        "/api/agents",
        response_model=AgentDetail,
        status_code=201,
        dependencies=[human_dependency],
        tags=["agents"],
    )
    async def create_agent_route(body: AgentCreate) -> dict:
        try:
            return create_agent(memory, body.model_dump())
        except ValueError as exc:
            msg = str(exc)
            if "already exists" in msg:
                raise HTTPException(status_code=409, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc

    # -----------------------------------------------------------------------
    # GET /api/agents/{slug} — get one agent
    # -----------------------------------------------------------------------

    @router.get(
        "/api/agents/{slug}",
        response_model=AgentDetail,
        dependencies=[human_dependency],
        tags=["agents"],
    )
    async def get_agent_route(slug: str) -> dict:
        result = get_agent(memory, slug)
        if result is None:
            raise HTTPException(status_code=404, detail=f"agent {slug!r} not found")
        return result

    # -----------------------------------------------------------------------
    # PATCH /api/agents/{slug} — partial update
    # -----------------------------------------------------------------------

    @router.patch(
        "/api/agents/{slug}",
        response_model=AgentDetail,
        dependencies=[human_dependency],
        tags=["agents"],
    )
    async def update_agent_route(slug: str, body: AgentUpdate) -> dict:
        try:
            result = update_agent(
                memory, slug, body.model_dump(exclude_unset=True)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail=f"agent {slug!r} not found")
        return result

    # -----------------------------------------------------------------------
    # DELETE /api/agents/{slug}
    # -----------------------------------------------------------------------

    @router.delete(
        "/api/agents/{slug}",
        status_code=204,
        dependencies=[human_dependency],
        tags=["agents"],
    )
    async def delete_agent_route(slug: str) -> Response:
        result = delete_agent(memory, slug)
        if result is None:
            raise HTTPException(status_code=404, detail=f"agent {slug!r} not found")
        if result is False:
            raise HTTPException(
                status_code=409,
                detail=f"agent {slug!r} is a builtin agent and cannot be deleted",
            )
        return Response(status_code=204)

    # -----------------------------------------------------------------------
    # PUT /api/agents/{slug}/tools — replace tool set
    # -----------------------------------------------------------------------

    @router.put(
        "/api/agents/{slug}/tools",
        response_model=AgentDetail,
        dependencies=[human_dependency],
        tags=["agents"],
    )
    async def set_agent_tools_route(slug: str, body: AgentToolsUpdate) -> dict:
        try:
            result = set_agent_tools(memory, slug, body.tool_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail=f"agent {slug!r} not found")
        return result

    # -----------------------------------------------------------------------
    # PUT /api/agents/{slug}/skills — replace skill set
    # -----------------------------------------------------------------------

    @router.put(
        "/api/agents/{slug}/skills",
        response_model=AgentDetail,
        dependencies=[human_dependency],
        tags=["agents"],
    )
    async def set_agent_skills_route(slug: str, body: AgentSkillsUpdate) -> dict:
        try:
            result = set_agent_skills(memory, slug, body.skill_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail=f"agent {slug!r} not found")
        return result

    # -----------------------------------------------------------------------
    # POST /api/agents/{slug}/test — one-shot run
    # -----------------------------------------------------------------------

    @router.post(
        "/api/agents/{slug}/test",
        response_model=AgentTestResponse,
        dependencies=[human_dependency],
        tags=["agents"],
    )
    async def test_agent_route(slug: str, body: AgentTestRequest) -> dict:
        return run_agent_one_shot(memory, settings, slug, body.prompt)
