"""Pure-ASGI request_id middleware.

Honors an inbound ``X-Request-ID`` header when it matches a safe character class
and length bound; otherwise mints a fresh ``uuid4().hex[:12]``. Sets
``request_id_var`` for the lifetime of the request so downstream code — route
handlers, the agent runner, tools, the wabot client — emits log records
correlated by ``request_id``. Echoes the header on the response.

Emits one ``request`` log record on completion. ``/health`` and ``/ready`` are
downgraded to ``DEBUG`` so uptime-check noise doesn't dominate the INFO stream
(operator decision — see ``docs/superpowers/plans/2026-05-16-issue-10-…``).

Long-lived streaming responses (``/api/stream``, ``/api/chat/stream``) still
emit a single ``request`` record at completion. v1 deliberately skips
phase=start/end sub-request timing for those.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .logging_config import request_id_var

logger = logging.getLogger("wabot_agent.middleware")

# Anything matching this regex is honored verbatim; otherwise we mint a fresh
# ID. The bounds keep attackers from polluting correlation IDs with traffic-
# splitting characters or absurd lengths.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{12,64}$")

# Routes whose `request` log line is emitted at DEBUG, not INFO. journalctl's
# default INFO stream stays free of uptime-check noise.
_DEBUG_ROUTES: frozenset[str] = frozenset({"/health", "/ready"})


def _mint_request_id() -> str:
    return uuid.uuid4().hex[:12]


def _is_valid_request_id(value: str) -> bool:
    return bool(_REQUEST_ID_RE.fullmatch(value))


def _client_ip_label(scope: Scope) -> str:
    """Return ``loopback`` for 127.0.0.1/::1, ``remote`` otherwise.

    We never log the raw remote IP — under Cloudflare Tunnel the visible
    address is the tunnel endpoint, which is uninteresting; for direct
    loopback access there's only one possible value.
    """
    client = scope.get("client")
    if not client:
        return "unknown"
    host = client[0] if isinstance(client, (tuple, list)) else None
    if host in ("127.0.0.1", "::1", "localhost"):
        return "loopback"
    return "remote"


class RequestIdMiddleware:
    """Stamp ``request_id`` on every request, log one ``request`` record on exit.

    Pure ASGI (no Starlette ``BaseHTTPMiddleware``) so streaming response bodies
    aren't buffered — the middleware only wraps ``send`` to inject the response
    header, never the message bodies themselves.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Extract X-Request-ID, validate. Header names from the ASGI scope are
        # bytes and already lowercased per the ASGI spec.
        inbound: str | None = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                try:
                    inbound = value.decode("latin-1")
                except UnicodeDecodeError:
                    inbound = None
                break

        if inbound and _is_valid_request_id(inbound):
            request_id = inbound
            source = "header"
        else:
            request_id = _mint_request_id()
            source = "minted"

        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status_code: int = 500  # default if the response never starts

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 500))
                headers: list[tuple[bytes, bytes]] = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        route = scope.get("path", "")
        method = scope.get("method", "")

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "request",
                extra={
                    "route": route,
                    "method": method,
                    "status": 500,
                    "latency_ms": latency_ms,
                    "client_ip": _client_ip_label(scope),
                    "request_id_source": source,
                },
            )
            request_id_var.reset(token)
            raise
        else:
            latency_ms = int((time.perf_counter() - start) * 1000)
            # /health and /ready are hit every minute by VPS uptime checks. Logging
            # them at INFO would drown the actual interesting records, so we
            # downgrade to DEBUG. Operators can flip log_level=DEBUG temporarily
            # if they need to debug the readiness path.
            if route in _DEBUG_ROUTES and status_code < 500:
                level = logging.DEBUG
            elif status_code >= 500:
                level = logging.WARNING
            else:
                level = logging.INFO
            logger.log(
                level,
                "request",
                extra={
                    "route": route,
                    "method": method,
                    "status": status_code,
                    "latency_ms": latency_ms,
                    "client_ip": _client_ip_label(scope),
                    "request_id_source": source,
                },
            )
        finally:
            request_id_var.reset(token)
