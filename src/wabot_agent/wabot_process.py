from __future__ import annotations

import asyncio
import os
import signal
import time
from pathlib import Path
from urllib.parse import urlparse

from .config import Settings


class WabotRestartError(RuntimeError):
    pass


def _port_from_endpoint(endpoint: str) -> int:
    parsed = urlparse(endpoint)
    if parsed.port is not None:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    return 80


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[wabot_process] could not read {path}: {exc}", flush=True)
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


async def _pids_on_port(port: int) -> list[int]:
    proc = await asyncio.create_subprocess_exec(
        "lsof",
        "-ti",
        f"tcp:{port}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    pids: list[int] = []
    for part in stdout.decode().strip().split():
        if part.isdigit():
            pids.append(int(part))
    return pids


async def _kill_port_listeners(port: int) -> None:
    for pid in await _pids_on_port(port):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    if await _pids_on_port(port):
        await asyncio.sleep(0.5)
        for pid in await _pids_on_port(port):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                continue
    await asyncio.sleep(0.5)


async def _wait_for_port_listen(port: int, *, timeout_sec: float = 30.0) -> bool:
    """Return True once something is listening on tcp:port (e.g. systemd restarted wabot)."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if await _pids_on_port(port):
            return True
        await asyncio.sleep(0.5)
    return False


def _http_addr_from_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{host}:{port}"


async def _start_from_home(home: Path, settings: Settings | None = None) -> None:
    binary = home / "wabot"
    if not binary.is_file():
        raise WabotRestartError(f"wabot binary not found at {binary}")

    env = os.environ.copy()
    env_file = home / "wabot.env"
    if env_file.is_file():
        env.update(_load_env_file(env_file))
    if settings is not None:
        token = settings.resolved_wabot_token
        if token:
            env.setdefault("WABOT_TOKEN", token)
        env.setdefault("WABOT_HTTP_ADDR", _http_addr_from_endpoint(settings.wabot_endpoint))
    for key in ("WABOT_TOKEN", "WABOT_HTTP_ADDR", "WABOT_INBOUND_URL"):
        if key not in env and key in os.environ:
            env[key] = os.environ[key]

    await asyncio.create_subprocess_exec(
        str(binary),
        cwd=str(home),
        env=env,
        start_new_session=True,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


async def _run_restart_command(command: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "sh",
        "-c",
        command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = (stderr or b"").decode(errors="replace").strip() or "unknown error"
        raise WabotRestartError(detail)


async def restart_wabot_daemon(settings: Settings) -> None:
    if settings.wabot_restart_command:
        await _run_restart_command(settings.wabot_restart_command)
        return

    home = settings.wabot_home
    if home is None:
        raise WabotRestartError(
            "Set WABOT_AGENT_WABOT_HOME to your wabot install directory, "
            "or WABOT_AGENT_WABOT_RESTART_COMMAND for a custom restart script."
        )

    home = home.expanduser().resolve()
    port = _port_from_endpoint(settings.wabot_endpoint)
    await _kill_port_listeners(port)
    # Production VPS runs wabot under systemd (User=wabot). Prefer letting the
    # service manager restart the daemon instead of spawning a sibling process
    # as the agent user (which cannot read store.db and races systemd).
    if await _wait_for_port_listen(port, timeout_sec=30.0):
        return
    await _start_from_home(home, settings)


async def wait_for_fresh_pairing(
    pairing_probe,
    *,
    timeout_sec: float = 45.0,
    poll_interval_sec: float = 0.5,
):
    deadline = time.monotonic() + timeout_sec
    last = None
    while time.monotonic() < deadline:
        last = await pairing_probe()
        if last.qr or last.logged_in:
            return last
        await asyncio.sleep(poll_interval_sec)
    return last if last is not None else await pairing_probe()
