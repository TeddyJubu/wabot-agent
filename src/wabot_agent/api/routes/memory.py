"""Memory + knowledge + runs routes — operator-facing reads + writes against
the MemoryStore facade and the knowledge file store.

Carved out of api/__init__.py as part of MASTER ME-1 Part 6. All routes
gate on dependencies=[human_dependency]. Memory routes go through the
MemoryStore facade (post-ME-3 split — contacts, audit, etc.). Knowledge
routes read/write the operator's instructions.md and memory.md under
data/knowledge/ via the knowledge_store helpers.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ...auth import verify_human_factory
from ...knowledge_store import (
    list_knowledge_docs,
    read_global_memory_raw,
    read_instructions_raw,
    save_global_memory,
    save_instructions,
)
from ...redaction import redact
from ..deps import AppDeps
from ..schemas import KnowledgeContentBody, MemoryFactBody


def register_memory_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    memory = deps.memory
    human_dependency = Depends(verify_human_factory(settings))

    @router.get("/api/memory/agent-notes", dependencies=[human_dependency])
    async def list_agent_notes() -> dict[str, Any]:
        # Top-level keys must not contain SECRET_KEYS substrings (e.g. "notes" → "key").
        return {"items": memory.agent_notes()}

    @router.put("/api/memory/agent-notes", dependencies=[human_dependency])
    async def upsert_agent_note(body: MemoryFactBody) -> dict[str, Any]:
        from ...instructions_cache import invalidate_instructions_cache

        result = memory.remember_agent_note(body.key, body.value)
        invalidate_instructions_cache()
        return redact(result)

    @router.delete("/api/memory/agent-notes/{key}", dependencies=[human_dependency])
    async def delete_agent_note_route(key: str) -> dict[str, Any]:
        from ...instructions_cache import invalidate_instructions_cache

        result = memory.delete_agent_note(key)
        invalidate_instructions_cache()
        return redact(result)

    @router.get("/api/memory/{contact}", dependencies=[human_dependency])
    async def contact_memory(contact: str) -> dict[str, Any]:
        return redact(memory.recall_contact(contact))

    @router.get("/api/knowledge", dependencies=[human_dependency])
    async def knowledge_index() -> dict[str, Any]:
        return {
            "docs": list_knowledge_docs(settings),
            "budgets": {
                "instructions": settings.knowledge_instructions_max_chars,
                "memory": settings.knowledge_memory_max_chars,
                "contact": settings.knowledge_contact_max_chars,
            },
        }

    @router.get("/api/knowledge/instructions", dependencies=[human_dependency])
    async def knowledge_instructions_get() -> dict[str, Any]:
        docs = list_knowledge_docs(settings)
        meta = docs[0] if docs else {}
        return {"content": read_instructions_raw(settings), **meta}

    @router.put("/api/knowledge/instructions", dependencies=[human_dependency])
    async def knowledge_instructions_put(body: KnowledgeContentBody) -> dict[str, Any]:
        meta = save_instructions(settings, body.content)
        return {"ok": True, **meta}

    @router.get("/api/knowledge/memory", dependencies=[human_dependency])
    async def knowledge_memory_get() -> dict[str, Any]:
        docs = list_knowledge_docs(settings)
        meta = docs[1] if len(docs) > 1 else {}
        return {"content": read_global_memory_raw(settings), **meta}

    @router.put("/api/knowledge/memory", dependencies=[human_dependency])
    async def knowledge_memory_put(body: KnowledgeContentBody) -> dict[str, Any]:
        meta = save_global_memory(settings, body.content)
        return {"ok": True, **meta}

    @router.get("/api/knowledge/contacts", dependencies=[human_dependency])
    async def knowledge_contacts() -> dict[str, Any]:
        return {"contacts": memory.list_contacts_with_facts()}

    @router.put("/api/memory/{contact}/facts", dependencies=[human_dependency])
    async def upsert_contact_fact(contact: str, body: MemoryFactBody) -> dict[str, Any]:
        result = memory.remember_contact_fact(
            contact, body.key, body.value, source="dashboard"
        )
        return redact(result)

    @router.delete("/api/memory/{contact}/facts/{key}", dependencies=[human_dependency])
    async def delete_contact_fact_route(contact: str, key: str) -> dict[str, Any]:
        return redact(memory.delete_contact_fact(contact, key))

    @router.get("/api/runs", dependencies=[human_dependency])
    async def recent_runs(limit: int = Query(default=20, ge=0, le=100)) -> list[dict[str, Any]]:
        return memory.recent_runs(limit=limit)
