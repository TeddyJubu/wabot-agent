"""secrets_service — safe read/write for runtime secrets (Phase 5).

Handles the runtime_secrets.json file that sits alongside runtime_overrides.json
under data/. This file holds secrets that the operator sets at runtime (e.g.
COMPOSIO_API_KEY) and that should never go into the git-tracked .env.

Security rules:
- The value is NEVER logged. Any log line that mentions the key uses a masked
  representation: first 3 chars + "…(masked)".
- Writes are atomic: write to a tmpfile, chmod 0600, then os.replace().
- WABOT_AGENT_ALLOW_ENV_WRITE=true opt-in writes/updates a .env line as well.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Settings

logger = logging.getLogger(__name__)

_SECRETS_FILENAME = "runtime_secrets.json"


def _secrets_path(settings: Settings) -> Path:
    return settings.data_dir / _SECRETS_FILENAME


def read_runtime_secrets(settings: Settings) -> dict[str, str]:
    """Read runtime_secrets.json; returns empty dict on any error."""
    path = _secrets_path(settings)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("runtime_secrets: failed to read %s: %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: str(v) for k, v in raw.items() if isinstance(v, str)}


def write_runtime_secret(settings: Settings, key: str, value: str) -> None:
    """Atomically add/update key in runtime_secrets.json with mode 0o600.

    The value is NEVER written to logs. Only a masked prefix is logged.
    """
    path = _secrets_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = read_runtime_secrets(settings)
    existing[key] = value

    masked = (value[:3] + "…(masked)") if len(value) > 3 else "(masked)"
    logger.debug("runtime_secrets: writing key=%s value=%s", key, masked)

    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".secrets.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def delete_runtime_secret(settings: Settings, key: str) -> None:
    """Remove key from runtime_secrets.json (no-op if key absent)."""
    existing = read_runtime_secrets(settings)
    if key not in existing:
        return
    del existing[key]
    path = _secrets_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".secrets.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def maybe_write_env_file(settings: Settings, key: str, value: str) -> bool:
    """If WABOT_AGENT_ALLOW_ENV_WRITE=true, update .env file atomically.

    Searches for the project root .env by walking up from data_dir.
    Matches an existing KEY=... line and replaces it, or appends.
    Returns True if written, False otherwise.

    The value is NEVER logged.
    """
    if os.environ.get("WABOT_AGENT_ALLOW_ENV_WRITE", "").lower() != "true":
        return False

    # Locate .env: check data_dir parent and its parents up to 3 levels
    candidates = [
        settings.data_dir.parent / ".env",
        settings.data_dir.parent.parent / ".env",
    ]
    env_path: Path | None = None
    for c in candidates:
        if c.exists():
            env_path = c
            break
    if env_path is None:
        # Create alongside data_dir's parent
        env_path = settings.data_dir.parent / ".env"

    try:
        existing_text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    except OSError:
        existing_text = ""

    lines = existing_text.splitlines(keepends=True)
    new_line = f"{key}={value}\n"
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            new_lines.append(new_line)
            found = True
        else:
            new_lines.append(line)
    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(new_line)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=env_path.parent, prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines(new_lines)
        os.chmod(tmp, 0o600)
        os.replace(tmp, env_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    masked = (value[:3] + "…(masked)") if len(value) > 3 else "(masked)"
    logger.debug("runtime_secrets: wrote %s=%s to .env at %s", key, masked, env_path)
    return True
