from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from .config import Settings
from .context_management import _item_to_text, cap_turn_prompt, estimate_items_tokens
from .llm_provider import (
    active_model_id,
    llm_default_headers,
    resolved_llm_api_key,
    resolved_llm_base_url,
)

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM = """You compress WhatsApp agent conversation history for long-running threads.
Produce a concise factual summary the agent can use on the next turn.
Include: who said what (user vs assistant), decisions, preferences, open tasks, file/media topics,
and anything needed to continue without re-reading the full thread.
Do not invent facts. Use short paragraphs or bullets. No markdown code fences."""


def history_items_to_transcript(items: list[Any], *, max_item_chars: int = 2000) -> str:
    lines: list[str] = []
    for item in items:
        text = _item_to_text(item).strip()
        if not text:
            continue
        if len(text) > max_item_chars:
            text = text[:max_item_chars] + "…"
        role = "message"
        if isinstance(item, dict):
            role = str(item.get("role") or item.get("type") or "message")
        lines.append(f"{role}: {text}")
    return "\n\n".join(lines)


def _fallback_summary(
    items: list[Any],
    *,
    prior_summary: str | None,
    max_chars: int,
) -> str:
    parts: list[str] = []
    if prior_summary:
        parts.append(prior_summary.strip())
    transcript = history_items_to_transcript(items, max_item_chars=600)
    if transcript:
        parts.append(transcript)
    combined = "\n\n".join(parts)
    return cap_turn_prompt(combined, max_chars)


def summary_message_item(summary: str) -> dict[str, str]:
    return {
        "role": "user",
        "content": f"[Earlier conversation summary]\n{summary.strip()}",
    }


async def summarize_thread(
    settings: Settings,
    dropped_items: list[Any],
    *,
    prior_summary: str | None = None,
) -> str:
    """Summarize dropped history, optionally merging with an existing summary."""
    if not dropped_items and not prior_summary:
        return ""

    max_chars = settings.session_summary_max_chars
    if not settings.live_model_enabled:
        return _fallback_summary(
            dropped_items, prior_summary=prior_summary, max_chars=max_chars
        )

    transcript = history_items_to_transcript(dropped_items)
    user_parts: list[str] = []
    if prior_summary:
        user_parts.append(f"Existing summary:\n{prior_summary.strip()}\n")
    if transcript:
        user_parts.append(f"New messages to fold in:\n{transcript}")
    if not user_parts:
        return cap_turn_prompt(prior_summary or "", max_chars)

    model = settings.session_summary_model or active_model_id(settings)
    user_text = "\n".join(user_parts)
    try:
        if settings.model_provider == "codex":
            from .codex_auth import codex_request_headers, load_codex_credentials

            credentials = load_codex_credentials(settings)
            if credentials is None:
                raise RuntimeError("codex credentials are not configured")
            client = AsyncOpenAI(
                api_key=credentials.access_token,
                base_url=resolved_llm_base_url(settings),
                default_headers=codex_request_headers(credentials),
            )
            stream = await client.responses.create(
                model=model,
                instructions=_SUMMARY_SYSTEM,
                input=[{"role": "user", "content": user_text}],
                store=False,
                stream=True,
            )
            content_parts: list[str] = []
            async for event in stream:
                if event.type == "response.output_text.delta":
                    content_parts.append(event.delta)
            content = "".join(content_parts)
        else:
            client = AsyncOpenAI(
                api_key=resolved_llm_api_key(settings),
                base_url=resolved_llm_base_url(settings),
                default_headers=llm_default_headers(settings),
            )
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM},
                    {"role": "user", "content": user_text},
                ],
                max_tokens=settings.session_summary_max_output_tokens,
                temperature=0.2,
            )
            content = response.choices[0].message.content if response.choices else None
    except Exception as exc:
        logger.warning("session_summary_llm_failed: %s", exc)
        return _fallback_summary(
            dropped_items, prior_summary=prior_summary, max_chars=max_chars
        )
    if not content or not content.strip():
        return _fallback_summary(
            dropped_items, prior_summary=prior_summary, max_chars=max_chars
        )
    return cap_turn_prompt(content.strip(), max_chars)


def should_summarize_dropped(settings: Settings, dropped_items: list[Any]) -> bool:
    if not settings.session_summary_enabled or not dropped_items:
        return False
    min_tokens = settings.session_summary_min_dropped_tokens
    if min_tokens <= 0:
        return True
    return estimate_items_tokens(dropped_items) >= min_tokens
