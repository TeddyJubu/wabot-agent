from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("wabot_agent.wabot")


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
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.endpoint}/send",
                    json={"to": to, "text": text},
                    headers=self._headers(),
                )
        except Exception as exc:
            logger.warning(
                "outbound_http",
                extra={
                    "endpoint_path": "/send",
                    "ok": False,
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                    "error_class": type(exc).__name__,
                },
            )
            raise
        logger.info(
            "outbound_http",
            extra={
                "endpoint_path": "/send",
                "status_code": resp.status_code,
                "ok": resp.is_success,
                "latency_ms": int((time.perf_counter() - start) * 1000),
            },
        )
        return self._handle_response(resp)

    async def send_image(self, to: str, path: str, caption: str | None = None) -> dict[str, Any]:
        image_path = Path(path)
        if not image_path.exists():
            raise WabotError(f"Image file does not exist: {image_path}")
        data = {"to": to}
        if caption:
            data["caption"] = caption
        start = time.perf_counter()
        try:
            with image_path.open("rb") as f:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.endpoint}/send-image",
                        data=data,
                        files={"file": (image_path.name, f, "application/octet-stream")},
                        headers=self._headers(),
                    )
        except Exception as exc:
            logger.warning(
                "outbound_http",
                extra={
                    "endpoint_path": "/send-image",
                    "ok": False,
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                    "error_class": type(exc).__name__,
                },
            )
            raise
        logger.info(
            "outbound_http",
            extra={
                "endpoint_path": "/send-image",
                "status_code": resp.status_code,
                "ok": resp.is_success,
                "latency_ms": int((time.perf_counter() - start) * 1000),
            },
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

    async def send_text(self, to: str, text: str) -> dict[str, Any]:
        payload = {"id": f"fake-{len(self.sent) + 1}", "to": to, "text": text}
        self.sent.append({"type": "text", **payload})
        return payload

    async def send_image(self, to: str, path: str, caption: str | None = None) -> dict[str, Any]:
        payload = {"id": f"fake-{len(self.sent) + 1}", "to": to, "path": path, "caption": caption}
        self.sent.append({"type": "image", **payload})
        return payload
