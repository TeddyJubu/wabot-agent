from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Literal

from .config import Settings
from .llm_provider import active_model_id
from .model_routing import ModelPurpose, get_model_for
from .redaction import looks_sensitive, redact

logger = logging.getLogger(__name__)

_memory_lock = threading.Lock()
_memory_instance: Any | None = None
_memory_config_key: str | None = None
_degraded_lock = threading.Lock()
_degraded_until = 0.0
_degraded_reason: str | None = None
_DEGRADED_BACKOFF_SEC = 15 * 60


class Mem0UnavailableError(RuntimeError):
    pass


Mem0LlmProvider = Literal["openai", "openrouter", "ollama", "ollama_cloud"]


def _effective_mem0_llm_provider(settings: Settings) -> Mem0LlmProvider | None:
    if settings.mem0_llm_provider:
        return settings.mem0_llm_provider
    if settings.model_provider == "codex":
        return None
    if settings.model_provider in ("openai", "openrouter", "ollama", "ollama_cloud"):
        return settings.model_provider
    return None


def _current_degraded_reason() -> str | None:
    global _degraded_reason, _degraded_until
    with _degraded_lock:
        if _degraded_reason and time.monotonic() < _degraded_until:
            return _degraded_reason
        _degraded_reason = None
        _degraded_until = 0.0
    return None


def _mark_degraded(reason: str) -> None:
    global _degraded_reason, _degraded_until
    with _degraded_lock:
        _degraded_reason = redact(reason)
        _degraded_until = time.monotonic() + _DEGRADED_BACKOFF_SEC


def _maybe_degrade_from_exception(exc: Exception) -> None:
    text = str(exc)
    lowered = text.lower()
    if "403" in text and (
        "key limit" in lowered
        or "quota" in lowered
        or "rate limit" in lowered
        or "insufficient" in lowered
    ):
        _mark_degraded(text)


def _effective_mem0_llm_provider_or_routed(settings: Settings) -> str | None:
    """Return the effective LLM provider name for Mem0, routing-aware.

    Returns the routed provider name when model_routing[MEMORY_EXTRACTION] is
    set, otherwise falls back to ``_effective_mem0_llm_provider``.
    """
    raw_routing: dict = getattr(settings, "model_routing", {}) or {}
    choice_raw = raw_routing.get(ModelPurpose.MEMORY_EXTRACTION) or raw_routing.get(
        ModelPurpose.MEMORY_EXTRACTION.value
    )
    if choice_raw is not None:
        from .model_routing import _coerce_choice

        return _coerce_choice(choice_raw).provider
    return _effective_mem0_llm_provider(settings)


def mem0_health(settings: Settings) -> dict[str, Any]:
    """Return a redacted, operator-facing Mem0 health summary."""
    provider = _effective_mem0_llm_provider_or_routed(settings)
    degraded_reason = _current_degraded_reason()
    reason: str | None = None
    if not settings.mem0_enabled:
        reason = "mem0_config_disabled"
    elif settings.offline_mode:
        reason = "offline_mode"
    elif degraded_reason:
        reason = f"degraded: {degraded_reason}"
    elif settings.mem0_use_platform and not settings.mem0_api_key:
        reason = "mem0_platform_api_key_missing"
    elif not settings.mem0_use_platform and provider is None:
        reason = "mem0_llm_provider_required_for_codex"
    elif provider == "openai" and not settings.openai_api_key:
        reason = "openai_api_key_missing"
    elif provider == "openrouter" and not settings.openrouter_api_key:
        reason = "openrouter_api_key_missing"
    elif provider == "ollama_cloud" and not settings.ollama_api_key:
        reason = "ollama_api_key_missing"

    return {
        "configured": settings.mem0_enabled,
        "enabled": reason is None,
        "degraded": degraded_reason is not None,
        "reason": reason,
        "use_platform": settings.mem0_use_platform,
        "llm_provider": provider,
        "llm_model": settings.mem0_llm_model,
        "embed_model": _mem0_fastembed_model(settings),
        "path": str(settings.mem0_path),
        "collection": settings.mem0_collection,
        "auto_capture": settings.mem0_auto_capture,
        "inject_on_run": settings.mem0_inject_on_run,
    }


def mem0_enabled(settings: Settings) -> bool:
    if not mem0_health(settings)["enabled"]:
        return False
    if settings.mem0_use_platform:
        return True
    provider = _effective_mem0_llm_provider_or_routed(settings)
    if provider == "openai":
        return bool(settings.openai_api_key)
    if provider == "openrouter":
        return bool(settings.openrouter_api_key)
    if provider == "ollama_cloud":
        return bool(settings.ollama_api_key)
    return True


def _llm_api_key(settings: Settings) -> str | None:
    if settings.mem0_use_platform:
        return settings.mem0_api_key
    provider = _effective_mem0_llm_provider_or_routed(settings)
    if provider == "openai":
        return settings.openai_api_key
    if provider == "openrouter":
        return settings.openrouter_api_key
    if provider == "ollama_cloud":
        return settings.ollama_api_key
    return settings.ollama_api_key or "ollama"


def _config_cache_key(settings: Settings) -> str:
    llm_key, base_url, llm_model = _mem0_openai_llm(settings)
    embed_model = _mem0_fastembed_model(settings)
    return "|".join(
        [
            str(settings.mem0_use_platform),
            str(settings.mem0_path),
            settings.mem0_collection,
            str(settings.mem0_llm_model or llm_model),
            embed_model,
            base_url,
            str(_effective_mem0_llm_provider_or_routed(settings)),
        ]
    )


def _mem0_openai_llm(settings: Settings) -> tuple[str, str, str]:
    """API key, OpenAI-compatible base URL, and model for Mem0 fact extraction.

    Lookup order (Phase 2):
    1. If ``settings.model_routing[MEMORY_EXTRACTION]`` is set, use that
       provider + model — it wins over both ``mem0_llm_provider`` and the
       global ``model_provider``.
    2. Otherwise fall through to the legacy ``mem0_llm_provider`` / global
       provider path (identical to pre-Phase-2 behaviour).

    Mem0 only understands OpenAI-compatible provider configs, so we always
    return ``(api_key, base_url, model)`` regardless of provider — the caller
    passes these into Mem0's ``llm.config`` dict under ``openai_base_url``.
    """
    # Phase-2 routing: check if MEMORY_EXTRACTION is explicitly routed.
    raw_routing: dict = getattr(settings, "model_routing", {}) or {}
    has_routing = (
        ModelPurpose.MEMORY_EXTRACTION in raw_routing
        or ModelPurpose.MEMORY_EXTRACTION.value in raw_routing
    )
    if has_routing:
        resolved = get_model_for(ModelPurpose.MEMORY_EXTRACTION, settings)
        # Codex uses device-flow auth — Mem0 cannot call Codex directly.
        if resolved.provider == "codex":
            raise Mem0UnavailableError(
                "model_routing[MEMORY_EXTRACTION] points at 'codex' which is not "
                "supported by the Mem0 LLM config; use openai, openrouter, or ollama."
            )
        api_key = resolved.api_key or ""
        base_url = resolved.base_url or settings.openai_base_url
        model = resolved.model_id
        # If the operator set mem0_llm_model as an additional override, honour it.
        if settings.mem0_llm_model:
            model = settings.mem0_llm_model
        return (api_key, base_url, model)

    # Legacy path (pre-Phase-2): mem0_llm_provider override or global provider.
    provider = _effective_mem0_llm_provider(settings)
    if provider is None:
        raise Mem0UnavailableError(
            "mem0 LLM provider required for codex; set WABOT_AGENT_MEM0_LLM_PROVIDER"
        )
    if provider == "openai":
        return (
            settings.openai_api_key or "",
            settings.openai_base_url,
            settings.mem0_llm_model or settings.openai_model,
        )
    if provider == "openrouter":
        return (
            settings.openrouter_api_key or "",
            settings.openrouter_base_url,
            settings.mem0_llm_model or settings.openrouter_model,
        )
    if provider in ("ollama", "ollama_cloud"):
        return (
            settings.ollama_api_key or "ollama",
            settings.ollama_cloud_base_url
            if provider == "ollama_cloud"
            else settings.ollama_base_url,
            settings.mem0_llm_model or active_model_id(settings),
        )
    raise Mem0UnavailableError(f"unsupported mem0 LLM provider: {provider}")


def _mem0_fastembed_model(settings: Settings) -> str:
    """Local ONNX embedder model (Ollama Cloud has no /v1/embeddings)."""
    model = settings.mem0_embed_model
    if model == "text-embedding-3-small":
        return "BAAI/bge-small-en-v1.5"
    return model


def _mem0_embedding_dims(settings: Settings) -> int:
    if _mem0_use_fastembed(settings):
        # BAAI/bge-small-en-v1.5 → 384; override via WABOT_AGENT_MEM0_EMBED_MODEL if needed.
        model = _mem0_fastembed_model(settings)
        if "bge-small" in model:
            return 384
        if "gte-large" in model:
            return 1024
        return 384
    return 1536


def _mem0_use_fastembed(settings: Settings) -> bool:
    # When Phase-2 routing explicitly points MEMORY_EXTRACTION at openai or openrouter,
    # those providers have an /embeddings endpoint — no need for local fastembed.
    raw_routing: dict = getattr(settings, "model_routing", {}) or {}
    has_routing = (
        ModelPurpose.MEMORY_EXTRACTION in raw_routing
        or ModelPurpose.MEMORY_EXTRACTION.value in raw_routing
    )
    if has_routing:
        from .model_routing import _coerce_choice

        choice_raw = raw_routing.get(ModelPurpose.MEMORY_EXTRACTION) or raw_routing.get(
            ModelPurpose.MEMORY_EXTRACTION.value
        )
        choice = _coerce_choice(choice_raw)
        return choice.provider in ("ollama", "ollama_cloud")
    provider = _effective_mem0_llm_provider(settings)
    return provider in (None, "ollama", "ollama_cloud")


@contextmanager
def _mem0_llm_env(settings: Settings):
    """Keep Mem0 from inheriting OpenRouter env unless that provider is selected."""
    if _effective_mem0_llm_provider_or_routed(settings) == "openrouter":
        yield
        return
    saved = {
        key: os.environ.pop(key)
        for key in ("OPENROUTER_API_KEY", "OPENROUTER_API_BASE")
        if key in os.environ
    }
    try:
        yield
    finally:
        os.environ.update(saved)


def build_mem0_config(settings: Settings) -> dict[str, Any]:
    """Build Mem0 OSS config (local Qdrant + LLM + embedder)."""
    if settings.mem0_use_platform:
        api_key = _llm_api_key(settings)
        if not api_key:
            raise Mem0UnavailableError("no API key for mem0 platform")
        return {"api_key": api_key}

    api_key, base_url, llm_model = _mem0_openai_llm(settings)
    # Finding 4 fix: use the routing-aware provider check so that local Ollama
    # (which needs no API key) does not erroneously raise when MEMORY_EXTRACTION
    # is routed to "ollama" but the global provider is something else.
    # We use the provider spec's secret_field to determine whether a key is
    # required: secret_field=None means the provider is local and keyless.
    effective_provider = _effective_mem0_llm_provider_or_routed(settings)
    if not api_key:
        from .providers import get_registry

        spec = get_registry().get(effective_provider or "")
        provider_requires_key = spec is None or spec.secret_field is not None
        if provider_requires_key:
            raise Mem0UnavailableError("no API key for mem0 LLM")

    settings.mem0_path.mkdir(parents=True, exist_ok=True)

    embedder: dict[str, Any]
    if _mem0_use_fastembed(settings):
        embedder = {
            "provider": "fastembed",
            "config": {"model": _mem0_fastembed_model(settings)},
        }
    else:
        embedder = {
            "provider": "openai",
            "config": {
                "model": settings.mem0_embed_model,
                "api_key": api_key,
                "openai_base_url": base_url,
            },
        }

    return {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "path": str(settings.mem0_path),
                "collection_name": settings.mem0_collection,
                "on_disk": True,
                "embedding_model_dims": _mem0_embedding_dims(settings),
            },
        },
        "llm": {
            "provider": "openai",
            "config": {
                "model": llm_model,
                "api_key": api_key,
                "openai_base_url": base_url,
                "temperature": 0.1,
            },
        },
        "embedder": embedder,
    }


def get_mem0_memory(settings: Settings) -> Any:
    """Return a process-wide Mem0 Memory instance (lazy init)."""
    global _memory_instance, _memory_config_key

    if not mem0_enabled(settings):
        raise Mem0UnavailableError("mem0 is disabled or missing credentials")

    # Mem0 defaults to ~/.mem0; on VPS HOME is the app dir which may not be writable.
    mem0_home = settings.data_dir / "mem0"
    mem0_home.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MEM0_DIR", str(mem0_home.resolve()))

    key = _config_cache_key(settings)
    with _memory_lock:
        if _memory_instance is not None and _memory_config_key == key:
            return _memory_instance

        from mem0 import Memory

        config = build_mem0_config(settings)
        with _mem0_llm_env(settings):
            if settings.mem0_use_platform:
                _memory_instance = Memory(api_key=config["api_key"])
            else:
                _memory_instance = Memory.from_config(config)
        _memory_config_key = key
        return _memory_instance


def reset_mem0_memory_for_tests() -> None:
    global _memory_instance, _memory_config_key, _degraded_reason, _degraded_until
    with _memory_lock:
        _memory_instance = None
        _memory_config_key = None
    with _degraded_lock:
        _degraded_reason = None
        _degraded_until = 0.0


def _normalize_user_id(user_id: str) -> str:
    return user_id.strip() or "unknown"


def _format_search_results(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for entry in payload.get("results") or []:
        if not isinstance(entry, dict):
            continue
        memory_text = str(entry.get("memory") or entry.get("text") or "").strip()
        if not memory_text:
            continue
        rows.append(
            {
                "memory": memory_text,
                "id": str(entry.get("id") or ""),
                "score": str(entry.get("score") or ""),
            }
        )
    return rows


def search_memories_sync(
    settings: Settings,
    *,
    user_id: str,
    query: str,
    top_k: int | None = None,
) -> dict[str, Any]:
    if not query.strip():
        return {"ok": False, "reason": "empty_query", "results": []}
    try:
        memory = get_mem0_memory(settings)
    except (Mem0UnavailableError, Exception) as exc:  # noqa: BLE001
        _maybe_degrade_from_exception(exc)
        logger.warning("mem0 init/search unavailable: %s", exc)
        return {"ok": False, "reason": redact(str(exc)), "results": []}

    limit = top_k if top_k is not None else settings.mem0_top_k
    try:
        payload = memory.search(
            query=query,
            filters={"user_id": _normalize_user_id(user_id)},
            top_k=limit,
        )
    except Exception as exc:  # noqa: BLE001
        _maybe_degrade_from_exception(exc)
        logger.warning("mem0 search failed: %s", exc)
        return {"ok": False, "reason": redact(str(exc)), "results": []}

    results = _format_search_results(payload if isinstance(payload, dict) else {})
    return {"ok": True, "count": len(results), "results": results}


def add_memory_sync(
    settings: Settings,
    *,
    user_id: str,
    messages: list[dict[str, str]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if looks_sensitive(" ".join(m.get("content", "") for m in messages)):
        return {"ok": False, "reason": "sensitive_content"}

    try:
        memory = get_mem0_memory(settings)
    except (Mem0UnavailableError, Exception) as exc:  # noqa: BLE001
        _maybe_degrade_from_exception(exc)
        logger.warning("mem0 init/add unavailable: %s", exc)
        return {"ok": False, "reason": redact(str(exc))}

    try:
        result = memory.add(
            messages,
            user_id=_normalize_user_id(user_id),
            metadata=metadata or {},
        )
    except Exception as exc:  # noqa: BLE001
        _maybe_degrade_from_exception(exc)
        logger.warning("mem0 add failed: %s", exc)
        return {"ok": False, "reason": redact(str(exc))}

    return {"ok": True, "result": redact(result) if isinstance(result, dict) else {}}


def add_turn_sync(
    settings: Settings,
    *,
    user_id: str,
    user_text: str,
    assistant_text: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not user_text.strip() and not assistant_text.strip():
        return {"ok": False, "reason": "empty_turn"}
    messages = [
        {"role": "user", "content": user_text.strip()},
        {"role": "assistant", "content": assistant_text.strip()},
    ]
    meta = {"source": "wabot-agent", **(metadata or {})}
    return add_memory_sync(settings, user_id=user_id, messages=messages, metadata=meta)


def format_memories_for_prompt(results: list[dict[str, str]], *, max_chars: int) -> str:
    if not results:
        return ""
    lines = [f"- {row['memory']}" for row in results if row.get("memory")]
    if not lines:
        return ""
    block = "Relevant long-term memories (Mem0):\n" + "\n".join(lines)
    if len(block) <= max_chars:
        return block + "\n\n"
    trimmed = block[: max_chars - 20].rsplit("\n", 1)[0]
    return trimmed + "\n…\n\n"


async def search_memories(
    settings: Settings,
    *,
    user_id: str,
    query: str,
    top_k: int | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        search_memories_sync,
        settings,
        user_id=user_id,
        query=query,
        top_k=top_k,
    )


async def add_turn(
    settings: Settings,
    *,
    user_id: str,
    user_text: str,
    assistant_text: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        add_turn_sync,
        settings,
        user_id=user_id,
        user_text=user_text,
        assistant_text=assistant_text,
        metadata=metadata,
    )


def _mem0_search_query(prompt: str, *, max_len: int = 512) -> str:
    for line in reversed(prompt.splitlines()):
        stripped = line.strip()
        if stripped.lower().startswith("- text:"):
            value = stripped.split(":", 1)[-1].strip()
            if value:
                return value[:max_len]
        if stripped.lower().startswith("text:"):
            value = stripped.split(":", 1)[-1].strip()
            if value:
                return value[:max_len]
    tail = prompt.strip()
    if len(tail) <= max_len:
        return tail
    return tail[-max_len:]


async def inject_mem0_context(
    settings: Settings,
    prompt: str,
    *,
    user_ids: list[str],
) -> str:
    if not settings.mem0_inject_on_run:
        return prompt
    query = _mem0_search_query(prompt)
    active_ids = [user_id.strip() for user_id in user_ids if user_id.strip()]
    if not active_ids:
        return prompt
    searched_list = await asyncio.gather(
        *[
            search_memories(settings, user_id=user_id, query=query)
            for user_id in active_ids
        ],
        return_exceptions=True,
    )
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for searched in searched_list:
        if isinstance(searched, BaseException):
            continue
        if not searched.get("ok"):
            continue
        for row in searched.get("results") or []:
            text = str(row.get("memory") or "").strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(row)
    prefix = format_memories_for_prompt(
        merged,
        max_chars=settings.mem0_prompt_max_chars,
    )
    return prefix + prompt if prefix else prompt


async def capture_turn_mem0(
    settings: Settings,
    *,
    user_id: str,
    user_text: str,
    assistant_text: str,
    run_id: str | None = None,
) -> None:
    if not settings.mem0_auto_capture:
        return
    meta = {"run_id": run_id} if run_id else None
    await add_turn(
        settings,
        user_id=user_id,
        user_text=user_text,
        assistant_text=assistant_text,
        metadata=meta,
    )
