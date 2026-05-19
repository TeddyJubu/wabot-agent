"""Start ChatGPT / Codex device-code login via the Codex CLI for the dashboard."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass
from typing import Literal

from .codex_auth import (
    auth_file_mtime,
    codex_auth_path,
    ensure_codex_home,
    load_codex_credentials,
)
from .config import Settings
from .runtime_overrides import clear_codex_token_override

logger = logging.getLogger(__name__)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_DEVICE_URL_RE = re.compile(r"https://auth\.openai\.com/codex/device")
_DEVICE_CODE_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4,8})\b")

DeviceLoginStatus = Literal["idle", "pending", "complete", "failed"]


@dataclass
class DeviceLoginSession:
    status: DeviceLoginStatus = "idle"
    url: str | None = None
    code: str | None = None
    detail: str | None = None


_session = DeviceLoginSession()
_task: asyncio.Task[None] | None = None
_proc: asyncio.subprocess.Process | None = None
_lock = asyncio.Lock()
_auth_mtime_at_start: float | None = None


def codex_cli_available() -> bool:
    return shutil.which("codex") is not None


def parse_device_auth_output(text: str) -> tuple[str, str] | None:
    """Extract device URL and one-time code from `codex login --device-auth` output."""
    clean = _ANSI_RE.sub("", text)
    url_match = _DEVICE_URL_RE.search(clean)
    if not url_match:
        return None
    code_match = None
    for line in clean.splitlines():
        match = _DEVICE_CODE_RE.search(line.strip())
        if match and "http" not in line:
            code_match = match
            break
    if code_match is None:
        return None
    return url_match.group(0), code_match.group(1)


def device_login_view(settings: Settings) -> dict[str, object]:
    global _session
    creds = load_codex_credentials(settings)
    logged_in = creds is not None and _session.status != "pending"
    if logged_in and _session.status == "failed":
        _session = DeviceLoginSession(status="idle")
    return {
        "cli_available": codex_cli_available(),
        "logged_in": logged_in,
        "auth_mode": creds.auth_mode if creds else None,
        "auth_path": str(codex_auth_path(settings)),
        "session": {
            "status": _session.status,
            "url": _session.url,
            "code": _session.code,
            "detail": _session.detail,
        },
    }


async def start_device_login(settings: Settings) -> DeviceLoginSession:
    global _task, _proc, _session, _auth_mtime_at_start

    if not codex_cli_available():
        _session = DeviceLoginSession(
            status="failed",
            detail="Codex CLI not found on PATH. Install it, then try again.",
        )
        return _session

    async with _lock:
        await _stop_device_login_locked()

        _auth_mtime_at_start = auth_file_mtime(settings)
        _session = DeviceLoginSession(status="pending")
        _task = asyncio.create_task(_run_device_login(settings))
        _task.add_done_callback(_device_login_task_done)
        return _session


async def poll_device_login(settings: Settings, *, wait_seconds: float = 0) -> DeviceLoginSession:
    if wait_seconds > 0 and _session.status == "pending" and not _session.code:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        while loop.time() < deadline:
            if _session.code or _session.status != "pending":
                break
            await asyncio.sleep(0.2)
    return _session


async def cancel_device_login() -> DeviceLoginSession:
    global _session
    async with _lock:
        await _stop_device_login_locked()
        if _session.status == "pending":
            _session = DeviceLoginSession(status="idle", detail="Sign-in cancelled.")
        return _session


async def _stop_device_login_locked() -> None:
    global _task, _proc
    if _proc is not None and _proc.returncode is None:
        _proc.terminate()
        try:
            await asyncio.wait_for(_proc.wait(), timeout=3)
        except TimeoutError:
            _proc.kill()
            await _proc.wait()
    _proc = None
    if _task is not None and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None


def _auth_file_refreshed(settings: Settings) -> bool:
    if _auth_mtime_at_start is None:
        return False
    current = auth_file_mtime(settings)
    if current is None:
        return False
    return current > _auth_mtime_at_start


def _device_login_task_done(task: asyncio.Task[None]) -> None:
    global _session
    if task.cancelled():
        return
    exc = task.exception()
    if exc is None:
        return
    logger.exception("codex device login task failed")
    _session = DeviceLoginSession(
        status="failed",
        url=_session.url,
        code=_session.code,
        detail=str(exc),
    )


async def _run_device_login(settings: Settings) -> None:
    global _proc, _session

    try:
        codex_home = ensure_codex_home(settings)
    except OSError as exc:
        _session = DeviceLoginSession(
            status="failed",
            detail=f"Cannot create Codex config directory: {exc}",
        )
        return

    env = os.environ.copy()
    auth_path = codex_auth_path(settings)
    env["CODEX_HOME"] = str(codex_home)

    try:
        _proc = await asyncio.create_subprocess_exec(
            "codex",
            "login",
            "--device-auth",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
    except OSError as exc:
        _session = DeviceLoginSession(status="failed", detail=f"Could not start codex: {exc}")
        return

    assert _proc.stdout is not None
    chunks: list[str] = []
    try:
        while True:
            line = await _proc.stdout.readline()
            if not line:
                break
            chunks.append(line.decode("utf-8", errors="replace"))
            parsed = parse_device_auth_output("".join(chunks))
            if parsed is not None:
                url, code = parsed
                _session.url = url
                _session.code = code
    finally:
        returncode = await _proc.wait()
        _proc = None

    combined = _ANSI_RE.sub("", "".join(chunks))
    creds = load_codex_credentials(settings)
    login_succeeded = (
        creds is not None
        and (
            "Successfully logged in" in combined
            or (returncode == 0 and _auth_file_refreshed(settings))
        )
    )
    if login_succeeded:
        clear_codex_token_override(settings)
        _session = DeviceLoginSession(
            status="complete",
            url=_session.url,
            code=_session.code,
            detail=None,
        )
        return

    detail = _failure_detail(combined, returncode)
    _session = DeviceLoginSession(
        status="failed",
        url=_session.url,
        code=_session.code,
        detail=detail,
    )
    logger.warning("codex device login failed: %s", detail)


def _failure_detail(output: str, returncode: int) -> str:
    """Short operator-facing message — never dump raw CLI banners."""
    lower = output.lower()
    if "permission denied" in lower:
        return "Could not write Codex credentials. Check data/codex permissions on the server."
    if "path does not exist" in lower and "codex_home" in lower:
        return "Codex config directory is missing. Restart wabot-agent and try again."
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    for line in reversed(lines):
        if line.startswith("Error") or "error:" in line.lower():
            return line[:240]
    if returncode != 0:
        return f"Codex login exited with code {returncode}."
    return "Sign-in did not complete. Try again or paste an access token below."
