"""Load ChatGPT / Codex subscription credentials from the Codex CLI auth cache."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import Settings

_CODEX_BASE_URL_HOSTS = frozenset({"chatgpt.com", "www.chatgpt.com"})


@dataclass(frozen=True)
class CodexCredentials:
    access_token: str
    account_id: str | None
    auth_mode: str


def codex_auth_path(settings: Settings) -> Path:
    return settings.codex_auth_path.expanduser()


def require_safe_codex_url(url: str) -> None:
    """Reject Codex base URLs that would send subscription tokens off-host."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"codex_base_url must use https; got scheme '{parsed.scheme}'.")
    host = (parsed.hostname or "").lower().strip("[]")
    if host not in _CODEX_BASE_URL_HOSTS:
        raise ValueError(
            f"codex_base_url must target chatgpt.com; got '{host or url}'."
        )


def codex_token_in_runtime_overrides(settings: Settings) -> bool:
    """True when the operator set codex_access_token via runtime overrides (dashboard)."""
    from .runtime_overrides import load_overrides

    overrides = load_overrides(settings.runtime_overrides_path)
    token = overrides.get("codex_access_token")
    return isinstance(token, str) and bool(token.strip())


def _credentials_from_override(settings: Settings) -> CodexCredentials | None:
    from .runtime_overrides import load_overrides

    overrides = load_overrides(settings.runtime_overrides_path)
    token = overrides.get("codex_access_token")
    if not isinstance(token, str) or not token.strip():
        token = settings.codex_access_token
    if not token or not str(token).strip():
        return None
    account_id = overrides.get("codex_account_id")
    if not isinstance(account_id, str) or not str(account_id).strip():
        account_id = settings.codex_account_id
    return CodexCredentials(
        access_token=str(token).strip(),
        account_id=str(account_id).strip() if account_id else None,
        auth_mode="chatgpt",
    )


def _load_credentials_from_auth_file(settings: Settings) -> CodexCredentials | None:
    path = codex_auth_path(settings)
    if not path.is_file():
        return None
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    tokens = raw.get("tokens")
    if not isinstance(tokens, dict):
        return None
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        return None
    account_id = tokens.get("account_id")
    auth_mode = raw.get("auth_mode")
    return CodexCredentials(
        access_token=access_token.strip(),
        account_id=str(account_id).strip() if account_id else None,
        auth_mode=str(auth_mode) if auth_mode else "chatgpt",
    )


def load_codex_credentials(settings: Settings) -> CodexCredentials | None:
    """Return subscription credentials when available.

  Preference order:
  1. Runtime override token (dashboard paste) when present in overrides.json
  2. Codex CLI auth file (~/.codex/auth.json)
  3. Bootstrap token from .env (CODEX_ACCESS_TOKEN) when no auth file exists
    """
    if codex_token_in_runtime_overrides(settings):
        return _credentials_from_override(settings)

    file_creds = _load_credentials_from_auth_file(settings)
    if file_creds is not None:
        return file_creds

    return _credentials_from_override(settings)


def auth_file_mtime(settings: Settings) -> float | None:
    path = codex_auth_path(settings)
    if not path.is_file():
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def codex_request_headers(credentials: CodexCredentials) -> dict[str, str]:
    headers: dict[str, str] = {}
    if credentials.account_id:
        headers["ChatGPT-Account-Id"] = credentials.account_id
    return headers


def model_provider_explicitly_set(
    overrides: dict[str, Any] | None = None,
) -> bool:
    for key in ("WABOT_AGENT_MODEL_PROVIDER", "VIGNESH_MODEL_PROVIDER", "LLM_PROVIDER"):
        if os.environ.get(key, "").strip():
            return True
    if overrides and "model_provider" in overrides:
        return True
    return False


def detect_model_provider(settings: Settings) -> str:
    """Pick a live provider when WABOT_AGENT_MODEL_PROVIDER is unset."""
    if _load_credentials_from_auth_file(settings) is not None:
        return "codex"
    if settings.openrouter_api_key:
        return "openrouter"
    if settings.ollama_api_key:
        return "ollama_cloud"
    return "openrouter"
