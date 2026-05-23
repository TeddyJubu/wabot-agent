"""WhatsApp group management routes.

Carved out of api/__init__.py as part of MASTER ME-1 Part 4.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ...auth import verify_human_factory
from ..dependencies import _wabot_call
from ..deps import AppDeps
from ..schemas import (
    GroupCreateRequest,
    GroupInviteRequest,
    GroupJoinRequest,
    GroupParticipantsRequest,
    GroupUpdateRequest,
)


def register_groups_routes(router: APIRouter, deps: AppDeps) -> None:
    settings = deps.settings
    wabot = deps.wabot

    verify_human = verify_human_factory(settings)
    human_dependency = Depends(verify_human)

    @router.get("/api/whatsapp/groups", dependencies=[human_dependency])
    async def list_whatsapp_groups_api() -> dict[str, Any]:
        return await _wabot_call(wabot.list_groups())

    @router.post("/api/whatsapp/groups", dependencies=[human_dependency])
    async def create_whatsapp_group_api(body: GroupCreateRequest) -> dict[str, Any]:
        return await _wabot_call(wabot.create_group(body.name, body.participants))

    @router.get("/api/whatsapp/groups/{group_jid}", dependencies=[human_dependency])
    async def get_whatsapp_group_api(group_jid: str) -> dict[str, Any]:
        return await _wabot_call(wabot.get_group(group_jid))

    @router.patch("/api/whatsapp/groups/{group_jid}", dependencies=[human_dependency])
    async def update_whatsapp_group_api(
        group_jid: str, body: GroupUpdateRequest
    ) -> dict[str, Any]:
        if (
            body.name is None
            and body.topic is None
            and body.announce is None
            and body.locked is None
        ):
            raise HTTPException(
                status_code=400,
                detail="provide at least one of name, topic, announce, locked",
            )
        return await _wabot_call(
            wabot.update_group(
                group_jid,
                name=body.name,
                topic=body.topic,
                announce=body.announce,
                locked=body.locked,
            )
        )

    @router.post(
        "/api/whatsapp/groups/{group_jid}/participants",
        dependencies=[human_dependency],
    )
    async def update_whatsapp_group_participants_api(
        group_jid: str, body: GroupParticipantsRequest
    ) -> dict[str, Any]:
        return await _wabot_call(
            wabot.update_group_participants(
                group_jid, body.participants, action=body.action
            )
        )

    @router.post("/api/whatsapp/groups/{group_jid}/leave", dependencies=[human_dependency])
    async def leave_whatsapp_group_api(group_jid: str) -> dict[str, Any]:
        return await _wabot_call(wabot.leave_group(group_jid))

    @router.post(
        "/api/whatsapp/groups/{group_jid}/picture",
        dependencies=[human_dependency],
    )
    async def set_whatsapp_group_picture_api(
        group_jid: str,
        file: Annotated[UploadFile, File()],
    ) -> dict[str, Any]:
        suffix = Path(file.filename or "group.jpg").suffix or ".jpg"
        tmp = settings.media_dir / f"group-picture-upload-{secrets.token_hex(8)}{suffix}"
        try:
            data = await file.read()
            if not data:
                raise HTTPException(status_code=400, detail="empty file")
            tmp.write_bytes(data)
            return await _wabot_call(wabot.set_group_picture(group_jid, str(tmp)))
        finally:
            tmp.unlink(missing_ok=True)

    @router.delete(
        "/api/whatsapp/groups/{group_jid}/picture",
        dependencies=[human_dependency],
    )
    async def remove_whatsapp_group_picture_api(group_jid: str) -> dict[str, Any]:
        return await _wabot_call(wabot.remove_group_picture(group_jid))

    @router.post(
        "/api/whatsapp/groups/{group_jid}/invite",
        dependencies=[human_dependency],
    )
    async def get_whatsapp_group_invite_api(
        group_jid: str, body: GroupInviteRequest
    ) -> dict[str, Any]:
        return await _wabot_call(wabot.get_group_invite(group_jid, reset=body.reset))

    @router.post("/api/whatsapp/groups/join", dependencies=[human_dependency])
    async def join_whatsapp_group_api(body: GroupJoinRequest) -> dict[str, Any]:
        return await _wabot_call(wabot.join_group(body.invite_link))
