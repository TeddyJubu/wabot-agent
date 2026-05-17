"""Runtime-mutable settings persisted to a JSON file under data/.

Layered on top of `Settings` loaded from `.env`:
- `.env` is the immutable VPS-bootstrap source of truth (never written to from the API).
- `runtime_overrides.json` is operator-mutable at runtime via `/api/settings`.
- On startup the overrides are applied with `apply_overrides()`.
- On change, the overrides file is rewritten atomically with 0o600 perms.

Only fields in `MUTABLE_FIELDS` are accepted — never path/env/host/port/operator_token/
data dirs. Secrets are stored in plaintext in the overrides file (same trust level as
`.env`); the file lives under `data/` which is gitignored.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .config import Settings

# Fields that may be set at runtime via /api/settings. Anything not in this set
# is ignored when applying overrides — defends against mass-assignment via the API.
MUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "model_provider",
        "openrouter_api_key",
        "openrouter_base_url",
        "openrouter_model",
        "ollama_model",
        "ollama_base_url",
        "ollama_api_key",
        "ollama_cloud_base_url",
        "wabot_endpoint",
        "wabot_token",
        "send_policy",
        "allowed_recipients",
        "owner_numbers",
        "auto_reply_enabled",
        "max_agent_turns",
    }
)

# cf_access_* fields are deliberately NOT in MUTABLE_FIELDS — they configure
# the auth boundary itself, so allowing them to be changed at runtime via the
# API they protect creates a self-referential downgrade path (operator session
# could disable the CF Access gate that's protecting it). They are restart-
# required, same trust level as operator_token.

# Fields whose values are secrets and must be masked when read back over the API.
SECRET_FIELDS: frozenset[str] = frozenset(
    {"openrouter_api_key", "ollama_api_key", "wabot_token"}
)


def load_overrides(path: Path) -> dict[str, Any]:
    """Read overrides from disk. Returns empty dict if missing or unreadable.

    A corrupt overrides file should not block boot; logged via stderr.
    """
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[runtime_overrides] failed to read {path}: {exc}", flush=True)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in MUTABLE_FIELDS}


def save_overrides(path: Path, overrides: dict[str, Any]) -> None:
    """Write overrides atomically with 0o600 perms.

    Sets are coerced to sorted lists for JSON-serialization stability.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable: dict[str, Any] = {}
    for key, value in overrides.items():
        if key not in MUTABLE_FIELDS:
            continue
        if isinstance(value, set):
            serializable[key] = sorted(value)
        else:
            serializable[key] = value

    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".overrides.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(serializable, fh, indent=2, sort_keys=True)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def apply_overrides(settings: Settings, overrides: dict[str, Any]) -> set[str]:
    """Apply overrides onto a live Settings instance. Returns names of fields changed.

    Pydantic `validate_assignment=True` validates each set; invalid values raise
    `ValidationError` and the caller is responsible for surfacing them.
    """
    changed: set[str] = set()
    for key, value in overrides.items():
        if key not in MUTABLE_FIELDS:
            continue
        if not hasattr(settings, key):
            continue
        if getattr(settings, key) != value:
            setattr(settings, key, value)
            changed.add(key)
    return changed


def mask_secret(value: str | None) -> dict[str, Any]:
    """Return a {set, preview} record for a secret field — never the value itself."""
    if not value:
        return {"set": False, "preview": None}
    if len(value) <= 8:
        return {"set": True, "preview": "****"}
    return {"set": True, "preview": f"{value[:4]}…{value[-4:]}"}
