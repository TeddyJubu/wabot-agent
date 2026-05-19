from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import contextmanager
from typing import Any

from .config import Settings
from .llm_provider import active_model_id
from .redaction import looks_sensitive, redact

logger = logging.getLogger(__name__)

_memory_lock = threading.Lock()
_memory_instance: Any | None = None
_memory_config_key: str | None = None


class Mem0UnavailableError(RuntimeError):
    pass


def mem0_enabled(settings: Settings) -> bool:
    if not settings.mem0_enabled:
        return False
    if settings.offline_mode:
        return False
    if settings.mem0_use_platform:
        return bool(settings.mem0_api_key)
    if settings.model_provider == "codex":
        # Mem0 uses Chat Completions; keep it on OpenRouter when configured.
        if settings.openrouter_api_key:
            return True
        from .codex_auth import load_codex_credentials

        return load_codex_credentials(settings) is not None
    if settings.model_provider == "openrouter":
        return bool(settings.openrouter_api_key)
    if settings.model_provider == "ollama_cloud":
        return bool(settings.ollama_api_key)
    return True


def _llm_api_key(settings: Settings) -> str | None:
    if settings.mem0_use_platform:
        return settings.mem0_api_key
    if settings.model_provider == "codex":
        from .codex_auth import load_codex_credentials

        creds = load_codex_credentials(settings)
        return creds.access_token if creds else None
    if settings.model_provider == "openrouter":
        return settings.openrouter_api_key
    if settings.model_provider == "ollama_cloud":
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
            settings.model_provider,
        ]
    )


def _mem0_openai_llm(settings: Settings) -> tuple[str, str, str]:
    """API key, OpenAI-compatible base URL, and model for Mem0 fact extraction."""
    if settings.model_provider == "codex":
        if settings.openrouter_api_key:
            return (
                settings.openrouter_api_key,
                settings.openrouter_base_url,
                settings.mem0_llm_model or settings.openrouter_model,
            )
        from .codex_auth import load_codex_credentials

        creds = load_codex_credentials(settings)
        return (
            creds.access_token if creds else "",
            settings.codex_base_url,
            settings.mem0_llm_model or settings.codex_model,
        )
    if settings.model_provider == "openrouter":
        return (
            settings.openrouter_api_key or "",
            settings.openrouter_base_url,
            settings.mem0_llm_model or settings.openrouter_model,
        )
    if settings.model_provider in ("ollama", "ollama_cloud"):
        return (
            settings.ollama_api_key or "ollama",
            settings.ollama_cloud_base_url
            if settings.model_provider == "ollama_cloud"
            else settings.ollama_base_url,
            settings.mem0_llm_model or active_model_id(settings),
        )
    return (
        settings.ollama_api_key or "ollama",
        settings.ollama_base_url,
        settings.mem0_llm_model or settings.ollama_model,
    )


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
    return settings.model_provider in ("codex", "ollama", "ollama_cloud")


@contextmanager
def _mem0_llm_env(settings: Settings):
    """Mem0's OpenAI LLM uses OpenRouter whenever OPENROUTER_API_KEY is set."""
    if settings.model_provider in ("codex", "openrouter"):
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
    if not api_key and settings.model_provider != "ollama":
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
    global _memory_instance, _memory_config_key
    with _memory_lock:
        _memory_instance = None
        _memory_config_key = None


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
        logger.warning("mem0 init/add unavailable: %s", exc)
        return {"ok": False, "reason": redact(str(exc))}

    try:
        result = memory.add(
            messages,
            user_id=_normalize_user_id(user_id),
            metadata=metadata or {},
        )
    except Exception as exc:  # noqa: BLE001
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


async def inject_mem0_context(
    settings: Settings,
    prompt: str,
    *,
    user_ids: list[str],
) -> str:
    if not settings.mem0_inject_on_run:
        return prompt
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for user_id in user_ids:
        if not user_id.strip():
            continue
        searched = await search_memories(settings, user_id=user_id, query=prompt)
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
