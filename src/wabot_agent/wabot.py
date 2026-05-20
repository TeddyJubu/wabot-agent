from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


class WabotError(RuntimeError):
    pass


@dataclass(frozen=True)
class WabotHealth:
    reachable: bool
    logged_in: bool | None = None
    connected: bool | None = None
    detail: str | None = None

    @property
    def ready(self) -> bool:
        return bool(self.reachable and self.logged_in and self.connected)


@dataclass(frozen=True)
class WabotPairingQR:
    supported: bool
    reachable: bool
    logged_in: bool | None = None
    connected: bool | None = None
    qr: str | None = None
    event: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None
    detail: str | None = None

    @property
    def qr_available(self) -> bool:
        return bool(self.qr)


class WabotClient:
    def __init__(self, endpoint: str, token: str | None, timeout: float = 60.0):
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.timeout = timeout

    async def health(self) -> WabotHealth:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.endpoint}/health")
        except httpx.HTTPError as exc:
            return WabotHealth(reachable=False, detail=str(exc))
        if resp.status_code != 200:
            return WabotHealth(
                reachable=False,
                detail=f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
        payload = resp.json()
        return WabotHealth(
            reachable=True,
            logged_in=payload.get("logged_in"),
            connected=payload.get("connected"),
            detail=payload.get("detail"),
        )

    async def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.endpoint}{path}",
                json=body,
                headers=self._headers(),
            )
        if resp.status_code >= 400:
            raise WabotError(f"wabot returned HTTP {resp.status_code}: {resp.text[:300]}")
        if not resp.content:
            return {"ok": True}
        return resp.json()

    async def _get_json(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.endpoint}{path}", headers=self._headers())
        if resp.status_code >= 400:
            raise WabotError(f"wabot returned HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.request(
                method,
                f"{self.endpoint}{path}",
                json=json,
                params=params,
                headers=self._headers(),
            )
        return self._handle_response(resp)

    async def _patch_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json("PATCH", path, json=body)

    async def _delete_json(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        return await self._request_json("DELETE", path, params=params)

    async def contacts_lookup(self, phones: list[str]) -> dict[str, Any]:
        return await self._post_json("/contacts/lookup", {"phones": phones})

    async def list_groups(self) -> dict[str, Any]:
        return await self._get_json("/groups")

    async def react_message(
        self,
        chat: str,
        message_id: str,
        reaction: str,
        sender: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "chat": chat,
            "message_id": message_id,
            "reaction": reaction,
        }
        if sender:
            body["sender"] = sender
        return await self._post_json("/messages/react", body)

    async def edit_message(self, chat: str, message_id: str, text: str) -> dict[str, Any]:
        return await self._patch_json(
            "/messages/edit",
            {"chat": chat, "message_id": message_id, "text": text},
        )

    async def revoke_message(
        self, chat: str, message_id: str, sender: str | None = None
    ) -> dict[str, Any]:
        params = {"chat": chat}
        if sender:
            params["sender"] = sender
        return await self._delete_json(f"/messages/{quote(message_id, safe='')}", params)

    async def create_group(self, name: str, participants: list[str]) -> dict[str, Any]:
        return await self._post_json("/groups", {"name": name, "participants": participants})

    async def get_group(self, jid: str) -> dict[str, Any]:
        return await self._get_json(f"/groups/{quote(jid, safe='')}")

    async def get_group_invite(self, jid: str, reset: bool = False) -> dict[str, Any]:
        return await self._post_json(
            f"/groups/{quote(jid, safe='')}/invite",
            {"reset": reset},
        )

    async def join_group(self, invite_link: str) -> dict[str, Any]:
        return await self._post_json("/groups/join", {"invite_link": invite_link})

    async def update_group(
        self,
        jid: str,
        *,
        name: str | None = None,
        topic: str | None = None,
        announce: bool | None = None,
        locked: bool | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if topic is not None:
            body["topic"] = topic
        if announce is not None:
            body["announce"] = announce
        if locked is not None:
            body["locked"] = locked
        return await self._patch_json(f"/groups/{quote(jid, safe='')}", body)

    async def update_group_participants(
        self,
        jid: str,
        participants: list[str],
        *,
        action: str = "add",
    ) -> dict[str, Any]:
        return await self._post_json(
            f"/groups/{quote(jid, safe='')}/participants",
            {"participants": participants, "action": action},
        )

    async def leave_group(self, jid: str) -> dict[str, Any]:
        return await self._post_json(f"/groups/{quote(jid, safe='')}/leave", {})

    async def mark_read(
        self,
        chat: str,
        message_ids: list[str],
        sender: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"chat": chat, "message_ids": message_ids}
        if sender:
            body["sender"] = sender
        if timestamp:
            body["timestamp"] = timestamp
        return await self._post_json("/chats/read", body)

    async def send_typing(
        self, to: str, state: str = "composing", media: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"to": to, "state": state}
        if media:
            body["media"] = media
        return await self._post_json("/presence/typing", body)

    async def mute_chat(
        self, chat: str, mute: bool, duration_hours: int = 0
    ) -> dict[str, Any]:
        return await self._post_json(
            f"/chats/{quote(chat, safe='')}/mute",
            {"mute": mute, "duration_hours": duration_hours},
        )

    async def archive_chat(self, chat: str, archive: bool) -> dict[str, Any]:
        return await self._post_json(
            f"/chats/{quote(chat, safe='')}/archive",
            {"archive": archive},
        )

    async def pin_chat(self, chat: str, pin: bool) -> dict[str, Any]:
        return await self._post_json(
            f"/chats/{quote(chat, safe='')}/pin",
            {"pin": pin},
        )

    async def get_user_info(self, jid: str) -> dict[str, Any]:
        return await self._get_json(f"/users/{quote(jid, safe='')}")

    async def get_user_picture(
        self, jid: str, preview: bool = False, picture_id: str | None = None
    ) -> httpx.Response:
        params: dict[str, str] = {}
        if preview:
            params["preview"] = "true"
        if picture_id:
            params["picture_id"] = picture_id
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.get(
                f"{self.endpoint}/users/{quote(jid, safe='')}/picture",
                params=params or None,
                headers=self._headers(),
            )

    async def inbox_recent(self, limit: int = 20) -> dict[str, Any]:
        if not self.token:
            return {
                "reachable": False,
                "messages": [],
                "detail": "WABOT_TOKEN is not configured and WABOT_TOKEN_FILE was not readable.",
            }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.endpoint}/inbox/recent",
                    params={"limit": limit},
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            return {"reachable": False, "messages": [], "detail": str(exc)}
        if resp.status_code == 404:
            return {
                "reachable": True,
                "messages": [],
                "detail": (
                    "The running wabot daemon does not expose /inbox/recent yet. Upgrade wabot."
                ),
            }
        if resp.status_code == 401:
            return {
                "reachable": True,
                "messages": [],
                "detail": "wabot rejected WABOT_TOKEN with HTTP 401.",
            }
        if resp.status_code != 200:
            return {
                "reachable": False,
                "messages": [],
                "detail": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        payload = resp.json()
        payload["reachable"] = True
        return payload

    async def pairing_qr(self) -> WabotPairingQR:
        if not self.token:
            return WabotPairingQR(
                supported=True,
                reachable=False,
                detail="WABOT_TOKEN is not configured and WABOT_TOKEN_FILE was not readable.",
            )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.endpoint}/pairing/qr", headers=self._headers())
        except httpx.HTTPError as exc:
            return WabotPairingQR(supported=True, reachable=False, detail=str(exc))
        if resp.status_code == 404:
            return WabotPairingQR(
                supported=False,
                reachable=True,
                detail="The running wabot daemon does not expose /pairing/qr yet. Upgrade wabot.",
            )
        if resp.status_code == 401:
            return WabotPairingQR(
                supported=True,
                reachable=True,
                detail="wabot rejected WABOT_TOKEN with HTTP 401.",
            )
        if resp.status_code != 200:
            return WabotPairingQR(
                supported=True,
                reachable=False,
                detail=f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
        payload = resp.json()
        return WabotPairingQR(
            supported=True,
            reachable=True,
            logged_in=payload.get("logged_in"),
            connected=payload.get("connected"),
            qr=payload.get("qr") or None,
            event=payload.get("event") or None,
            updated_at=payload.get("updated_at") or None,
            expires_at=payload.get("expires_at") or None,
            detail=payload.get("detail") or None,
        )

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise WabotError("WABOT_TOKEN is not configured.")
        return {"X-Token": self.token}

    async def send_text(self, to: str, text: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.endpoint}/send",
                json={"to": to, "text": text},
                headers=self._headers(),
            )
        return self._handle_response(resp)

    async def download_media(self, chat: str, message_id: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.get(
                f"{self.endpoint}/media/download",
                params={"chat": chat, "id": message_id},
                headers=self._headers(),
            )

    async def send_media(
        self,
        to: str,
        kind: str,
        path: str,
        caption: str | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        media_path = Path(path)
        if not media_path.exists():
            raise WabotError(f"Media file does not exist: {media_path}")
        data: dict[str, str] = {"to": to, "kind": kind}
        if caption:
            data["caption"] = caption
        if filename:
            data["filename"] = filename
        with media_path.open("rb") as f:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.endpoint}/send-media",
                    data=data,
                    files={"file": (media_path.name, f, "application/octet-stream")},
                    headers=self._headers(),
                )
        return self._handle_response(resp)

    async def send_image(self, to: str, path: str, caption: str | None = None) -> dict[str, Any]:
        image_path = Path(path)
        if not image_path.exists():
            raise WabotError(f"Image file does not exist: {image_path}")
        data = {"to": to}
        if caption:
            data["caption"] = caption
        with image_path.open("rb") as f:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.endpoint}/send-image",
                    data=data,
                    files={"file": (image_path.name, f, "application/octet-stream")},
                    headers=self._headers(),
                )
        return self._handle_response(resp)

    def _handle_response(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 401:
            raise WabotError("wabot rejected WABOT_TOKEN with HTTP 401.")
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            detail = "wabot rate limit hit"
            if retry_after:
                detail += f"; retry after {retry_after}s"
            raise WabotError(detail)
        if resp.status_code == 503:
            raise WabotError("wabot is reachable but WhatsApp is not ready or not linked.")
        if resp.status_code >= 400:
            raise WabotError(f"wabot returned HTTP {resp.status_code}: {resp.text[:300]}")
        if not resp.content:
            return {"ok": True}
        return resp.json()


class FakeWabotClient(WabotClient):
    def __init__(self) -> None:
        super().__init__("http://fake-wabot", "fake-token")
        self.sent: list[dict[str, Any]] = []
        self.typing_calls: list[dict[str, Any]] = []

    async def health(self) -> WabotHealth:
        return WabotHealth(reachable=True, logged_in=True, connected=True, detail="fake")

    async def pairing_qr(self) -> WabotPairingQR:
        return WabotPairingQR(
            supported=True,
            reachable=True,
            logged_in=True,
            connected=True,
            detail="fake",
        )

    async def inbox_recent(self, limit: int = 20) -> dict[str, Any]:
        return {
            "reachable": True,
            "count": 1,
            "messages": [
                {
                    "id": "fake-1",
                    "from": "+15550001111",
                    "chat": "+15550001111",
                    "text": "hello from fake inbox",
                    "timestamp": "2026-05-16T00:00:00Z",
                    "is_group": False,
                }
            ],
            "note": "fake inbox",
        }

    async def contacts_lookup(self, phones: list[str]) -> dict[str, Any]:
        return {
            "results": [
                {"jid": "+15550001111@s.whatsapp.net", "query": phones[0], "is_on": True}
            ]
        }

    async def list_groups(self) -> dict[str, Any]:
        return {"count": 0, "groups": []}

    async def mark_read(
        self,
        chat: str,
        message_ids: list[str],
        sender: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        return {"ok": True, "chat": chat, "marked": len(message_ids)}

    async def send_typing(
        self, to: str, state: str = "composing", media: str | None = None
    ) -> dict[str, Any]:
        self.typing_calls.append({"to": to, "state": state, "media": media})
        return {"ok": True, "to": to, "state": state}

    async def mute_chat(
        self, chat: str, mute: bool, duration_hours: int = 0
    ) -> dict[str, Any]:
        return {"ok": True, "chat": chat, "muted": mute}

    async def archive_chat(self, chat: str, archive: bool) -> dict[str, Any]:
        return {"ok": True, "chat": chat, "archived": archive}

    async def pin_chat(self, chat: str, pin: bool) -> dict[str, Any]:
        return {"ok": True, "chat": chat, "pinned": pin}

    async def get_user_info(self, jid: str) -> dict[str, Any]:
        return {
            "ok": True,
            "user": {
                "jid": jid,
                "status": "Available",
                "picture_id": "fake-pic",
                "verified_name": "Fake User",
            },
        }

    async def get_user_picture(
        self, jid: str, preview: bool = False, picture_id: str | None = None
    ) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "image/jpeg", "X-Picture-ID": "fake-pic"},
            content=b"fake-avatar-bytes",
        )

    async def react_message(
        self,
        chat: str,
        message_id: str,
        reaction: str,
        sender: str | None = None,
    ) -> dict[str, Any]:
        return {"ok": True, "chat": chat, "message_id": message_id, "reaction": reaction}

    async def edit_message(self, chat: str, message_id: str, text: str) -> dict[str, Any]:
        return {"ok": True, "chat": chat, "message_id": message_id}

    async def revoke_message(
        self, chat: str, message_id: str, sender: str | None = None
    ) -> dict[str, Any]:
        return {"ok": True, "chat": chat, "message_id": message_id}

    async def create_group(self, name: str, participants: list[str]) -> dict[str, Any]:
        return {"ok": True, "group": {"jid": "fake@g.us", "name": name}}

    async def get_group(self, jid: str) -> dict[str, Any]:
        return {"ok": True, "group": {"jid": jid, "name": "fake group"}}

    async def get_group_invite(self, jid: str, reset: bool = False) -> dict[str, Any]:
        return {"ok": True, "invite_link": "https://chat.whatsapp.com/fake"}

    async def join_group(self, invite_link: str) -> dict[str, Any]:
        return {"ok": True, "jid": "fake@g.us"}

    async def update_group(
        self,
        jid: str,
        *,
        name: str | None = None,
        topic: str | None = None,
        announce: bool | None = None,
        locked: bool | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "jid": jid,
            "group": {"jid": jid, "name": name or "fake group"},
        }

    async def update_group_participants(
        self,
        jid: str,
        participants: list[str],
        *,
        action: str = "add",
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "jid": jid,
            "action": action,
            "participants": [{"jid": p, "is_admin": False} for p in participants],
        }

    async def leave_group(self, jid: str) -> dict[str, Any]:
        return {"ok": True, "jid": jid, "left": True}

    async def send_text(self, to: str, text: str) -> dict[str, Any]:
        payload = {"id": f"fake-{len(self.sent) + 1}", "to": to, "text": text}
        self.sent.append({"type": "text", **payload})
        return payload

    async def download_media(self, chat: str, message_id: str) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "image/png",
                "X-Media-Kind": "image",
                "Content-Disposition": 'attachment; filename="fake.png"',
            },
            content=b"fake-bytes",
        )

    async def send_media(
        self,
        to: str,
        kind: str,
        path: str,
        caption: str | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "id": f"fake-{len(self.sent) + 1}",
            "to": to,
            "kind": kind,
            "path": path,
            "caption": caption,
            "filename": filename,
        }
        self.sent.append({"type": kind, **payload})
        return payload

    async def send_image(self, to: str, path: str, caption: str | None = None) -> dict[str, Any]:
        payload = {"id": f"fake-{len(self.sent) + 1}", "to": to, "path": path, "caption": caption}
        self.sent.append({"type": "image", **payload})
        return payload
