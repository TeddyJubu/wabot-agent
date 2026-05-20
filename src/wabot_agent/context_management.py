from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from agents import RunConfig, SQLiteSession
from agents.memory import SessionInputCallback, SessionSettings

from .config import Settings

_CHARS_PER_TOKEN = 4
_IMAGE_OMITTED = "[image omitted from context to save tokens]"
_IMAGE_PART_TYPES = frozenset(
    {"input_image", "image_url", "image", "image_file", "input_image_url"}
)
_TRUNCATED = "\n\n[… truncated for context limits …]"


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _item_to_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    try:
        return json.dumps(item, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(item)


def estimate_item_tokens(item: Any) -> int:
    return estimate_tokens(_item_to_text(item))


def estimate_items_tokens(items: list[Any]) -> int:
    return sum(estimate_item_tokens(item) for item in items)


def cap_turn_prompt(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = max_chars - len(_TRUNCATED)
    if head < 256:
        return text[:max_chars]
    return text[:head] + _TRUNCATED


def _shrink_content_part(part: Any, remaining_chars: int) -> Any:
    if remaining_chars <= 0:
        return None
    if isinstance(part, str):
        if len(part) <= remaining_chars:
            return part
        return part[:remaining_chars] + _TRUNCATED
    if not isinstance(part, dict):
        text = str(part)
        if len(text) <= remaining_chars:
            return text
        return text[:remaining_chars] + _TRUNCATED

    part = copy.deepcopy(part)
    part_type = part.get("type")
    if part_type in {"input_image", "image_url", "image"}:
        for key in ("image_url", "url", "data", "source"):
            if key in part:
                part[key] = _IMAGE_OMITTED
        return part

    for key in ("text", "output", "content", "input"):
        if key in part and isinstance(part[key], str) and len(part[key]) > remaining_chars:
            part[key] = part[key][:remaining_chars] + _TRUNCATED
    return part


def is_recoverable_codex_session_error(exc: BaseException) -> bool:
    """True when replayed SQLite history is incompatible with Codex store=false."""
    msg = str(exc).lower()
    return (
        "no tool call found for function call output" in msg
        or "not persisted when `store` is set to false" in msg
        or "items are not persisted when" in msg
    )


def sanitize_codex_session_history(items: list[Any]) -> list[Any]:
    """Drop reasoning rows and orphan tool outputs from replayed session history.

    Codex uses store=false, so reasoning items (rs_*) are not valid on replay.
    Orphan function_call_output rows break the Responses API input validator.
    """
    result: list[Any] = []
    open_calls: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            result.append(item)
            continue
        typ = str(item.get("type") or "")
        item_id = str(item.get("id") or "")
        if typ == "reasoning" or item_id.startswith("rs_"):
            continue
        if typ == "function_call":
            call_id = item.get("call_id")
            if call_id:
                open_calls.add(str(call_id))
            result.append(item)
            continue
        if typ == "function_call_output":
            call_id = item.get("call_id")
            if call_id and str(call_id) in open_calls:
                result.append(item)
                open_calls.discard(str(call_id))
            continue
        result.append(item)
    return result


def prune_codex_session_storage(db_path: Path | str, session_id: str) -> int:
    """Remove reasoning and orphan tool rows persisted by the Agents SDK."""
    path = Path(db_path)
    if not path.exists():
        return 0

    conn = sqlite3.connect(path)
    try:
        conn.execute("pragma busy_timeout=5000")
        rows = conn.execute(
            """
            select id, message_data from agent_messages
            where session_id = ?
            order by id asc
            """,
            (session_id,),
        ).fetchall()
        open_calls: set[str] = set()
        delete_ids: list[int] = []
        for row_id, raw in rows:
            try:
                item = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(item, dict):
                continue
            typ = str(item.get("type") or "")
            item_id = str(item.get("id") or "")
            if typ == "reasoning" or item_id.startswith("rs_"):
                delete_ids.append(row_id)
                continue
            if typ == "function_call":
                call_id = item.get("call_id")
                if call_id:
                    open_calls.add(str(call_id))
                continue
            if typ == "function_call_output":
                call_id = item.get("call_id")
                if not call_id or str(call_id) not in open_calls:
                    delete_ids.append(row_id)
                else:
                    open_calls.discard(str(call_id))
        for row_id in delete_ids:
            conn.execute("delete from agent_messages where id = ?", (row_id,))
        conn.commit()
        return len(delete_ids)
    finally:
        conn.close()


def clear_agent_session(db_path: Path | str, session_id: str) -> int:
    """Delete SDK session history and summary for one session. Returns rows deleted."""
    path = Path(db_path)
    if not path.exists():
        return 0
    conn = sqlite3.connect(path)
    try:
        conn.execute("pragma busy_timeout=5000")
        cur = conn.execute(
            "delete from agent_messages where session_id = ?", (session_id,)
        )
        deleted = cur.rowcount or 0
        try:
            conn.execute(
                "delete from session_summaries where session_id = ?", (session_id,)
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()
        return deleted
    finally:
        conn.close()


def strip_images_from_session_item(item: Any) -> Any:
    """Convert stored multimodal turns to plain text (avoids invalid image errors on replay)."""
    if not isinstance(item, dict):
        return item

    content = item.get("content")
    if isinstance(content, str):
        return item
    if not isinstance(content, list):
        if item.get("type") in _IMAGE_PART_TYPES:
            return {"role": item.get("role", "user"), "content": _IMAGE_OMITTED}
        return item

    text_parts: list[str] = []
    had_image = False
    for part in content:
        if isinstance(part, str):
            text_parts.append(part)
            continue
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type", ""))
        if part_type in _IMAGE_PART_TYPES or "image_url" in part:
            had_image = True
            continue
        for key in ("text", "input_text", "output_text", "content"):
            value = part.get(key)
            if isinstance(value, str) and value.strip():
                text_parts.append(value.strip())

    role = item.get("role", "user")
    body = "\n".join(text_parts).strip()
    if had_image:
        body = f"{body}\n{_IMAGE_OMITTED}" if body else _IMAGE_OMITTED
    return {"role": role, "content": body or _IMAGE_OMITTED}


def shrink_item_for_context(item: Any, max_chars: int) -> Any:
    if max_chars <= 0:
        return item
    if isinstance(item, str):
        return cap_turn_prompt(item, max_chars)
    if not isinstance(item, dict):
        return cap_turn_prompt(str(item), max_chars)

    shrunk = copy.deepcopy(item)
    content = shrunk.get("content")
    if isinstance(content, str):
        shrunk["content"] = cap_turn_prompt(content, max_chars)
        return shrunk
    if isinstance(content, list):
        parts: list[Any] = []
        remaining = max_chars
        for part in content:
            piece = _shrink_content_part(part, remaining)
            if piece is None:
                continue
            parts.append(piece)
            remaining -= len(_item_to_text(piece))
            if remaining <= 0:
                break
        shrunk["content"] = parts
        return shrunk

    serialized = _item_to_text(shrunk)
    if len(serialized) <= max_chars:
        return shrunk
    role = shrunk.get("role", "user")
    return {"role": role, "content": cap_turn_prompt(serialized, max_chars)}


def trim_history_for_tokens(
    history: list[Any],
    *,
    max_tokens: int,
    reserved_tokens: int = 0,
) -> list[Any]:
    """Keep the newest history items that fit within a token budget."""
    _dropped, kept = split_history_by_token_budget(
        history, max_tokens=max_tokens, reserved_tokens=reserved_tokens
    )
    return kept


def split_history_by_token_budget(
    history: list[Any],
    *,
    max_tokens: int,
    reserved_tokens: int = 0,
) -> tuple[list[Any], list[Any]]:
    """Split history into (dropped_oldest, kept_newest) under a token budget."""
    if not history:
        return [], []
    if max_tokens <= 0:
        return list(history), []

    budget = max(0, max_tokens - reserved_tokens)
    if budget <= 0:
        return list(history), []

    kept_reversed: list[Any] = []
    used = 0
    for item in reversed(history):
        tokens = estimate_item_tokens(item)
        if used + tokens <= budget:
            kept_reversed.append(item)
            used += tokens
            continue
        remaining_chars = max(0, (budget - used) * _CHARS_PER_TOKEN)
        if remaining_chars >= 256:
            kept_reversed.append(shrink_item_for_context(item, remaining_chars))
        break

    kept = list(reversed(kept_reversed))
    if len(kept) >= len(history):
        return [], kept
    dropped = history[: len(history) - len(kept)]
    return dropped, kept


def fetch_agent_messages_before_cutoff(
    db_path: Path | str,
    session_id: str,
    *,
    keep_items: int,
) -> list[Any]:
    """Load agent_messages rows that would be removed by prune_agent_session_messages."""
    path = Path(db_path)
    if not path.exists() or keep_items <= 0:
        return []

    conn = sqlite3.connect(path)
    try:
        conn.execute("pragma busy_timeout=5000")
        row = conn.execute(
            """
            select id from agent_messages
            where session_id = ?
            order by id desc
            limit 1 offset ?
            """,
            (session_id, keep_items - 1),
        ).fetchone()
        if row is None:
            return []
        cutoff_id = row[0]
        rows = conn.execute(
            """
            select message_data from agent_messages
            where session_id = ? and id < ?
            order by id asc
            """,
            (session_id, cutoff_id),
        ).fetchall()
    finally:
        conn.close()

    items: list[Any] = []
    for (message_data,) in rows:
        try:
            items.append(json.loads(message_data))
        except (json.JSONDecodeError, TypeError):
            continue
    return items


async def _maybe_update_session_summary(
    settings: Settings,
    memory: Any,
    session_key: str,
    dropped_items: list[Any],
) -> str | None:
    from .thread_summary import should_summarize_dropped, summarize_thread

    if not should_summarize_dropped(settings, dropped_items):
        return memory.get_session_summary(session_key)

    prior = memory.get_session_summary(session_key)
    summary = await summarize_thread(settings, dropped_items, prior_summary=prior)
    if summary:
        memory.save_session_summary(session_key, summary)
        return summary
    return prior


def make_session_input_callback(
    settings: Settings,
    session_key: str,
    memory: Any,
) -> SessionInputCallback:
    """Merge session history + new turn, with optional LLM summary of dropped turns."""
    from .thread_summary import summary_message_item

    async def _callback(
        history: list[Any],
        new_items: list[Any],
    ) -> list[Any]:
        summary = memory.get_session_summary(session_key)
        prefix: list[Any] = []
        if summary:
            prefix.append(summary_message_item(summary))

        reserved = estimate_items_tokens(new_items) + estimate_items_tokens(prefix)
        dropped: list[Any] = []
        kept = history
        if settings.session_max_history_tokens > 0:
            dropped, kept = split_history_by_token_budget(
                history,
                max_tokens=settings.session_max_history_tokens,
                reserved_tokens=reserved,
            )

        if dropped:
            updated = await _maybe_update_session_summary(
                settings, memory, session_key, dropped
            )
            if updated:
                prefix = [summary_message_item(updated)]

        # History must be text-only: replayed data: URLs break Ollama/OpenRouter vision.
        prefix = [strip_images_from_session_item(item) for item in prefix]
        kept = [strip_images_from_session_item(item) for item in kept]
        if settings.model_provider == "codex":
            prefix = sanitize_codex_session_history(prefix)
            kept = sanitize_codex_session_history(kept)

        return prefix + kept + new_items

    return _callback


def build_agent_session(settings: Settings, session_key: str) -> SQLiteSession:
    limit = settings.session_history_item_limit
    session_settings = SessionSettings(limit=limit if limit > 0 else None)
    return SQLiteSession(
        session_id=session_key,
        db_path=Path(settings.db_path),
        session_settings=session_settings,
    )


def build_agent_run_config(
    settings: Settings,
    session_key: str,
    memory: Any,
) -> RunConfig:
    limit = settings.session_history_item_limit
    session_settings = (
        SessionSettings(limit=limit) if limit > 0 else None
    )
    use_callback = (
        settings.session_max_history_tokens > 0 or settings.session_summary_enabled
    )
    callback = (
        make_session_input_callback(settings, session_key, memory)
        if use_callback
        else None
    )
    return RunConfig(
        tracing_disabled=True,
        workflow_name="wabot-agent",
        session_input_callback=callback,
        session_settings=session_settings,
    )


def prune_agent_session_messages(
    db_path: Path | str,
    session_id: str,
    *,
    keep_items: int,
) -> int:
    """Drop oldest SDK session rows beyond keep_items. Returns rows deleted."""
    if keep_items <= 0:
        return 0

    path = Path(db_path)
    if not path.exists():
        return 0

    conn = sqlite3.connect(path)
    try:
        conn.execute("pragma busy_timeout=5000")
        row = conn.execute(
            """
            select id from agent_messages
            where session_id = ?
            order by id desc
            limit 1 offset ?
            """,
            (session_id, keep_items - 1),
        ).fetchone()
        if row is None:
            return 0
        cutoff_id = row[0]
        cursor = conn.execute(
            """
            delete from agent_messages
            where session_id = ? and id < ?
            """,
            (session_id, cutoff_id),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def maybe_prune_codex_session_storage(settings: Settings, session_key: str) -> int:
    if settings.model_provider != "codex":
        return 0
    return prune_codex_session_storage(settings.db_path, session_key)


async def prune_session_storage(
    settings: Settings,
    session_key: str,
    memory: Any,
) -> int:
    keep = settings.session_db_keep_items
    if keep <= 0:
        return 0

    if settings.session_summary_enabled:
        to_summarize = await asyncio.to_thread(
            fetch_agent_messages_before_cutoff,
            settings.db_path,
            session_key,
            keep_items=keep,
        )
        if to_summarize:
            await _maybe_update_session_summary(
                settings, memory, session_key, to_summarize
            )

    return await asyncio.to_thread(
        prune_agent_session_messages,
        settings.db_path,
        session_key,
        keep_items=keep,
    )


_prune_counter = 0
_prune_lock = threading.Lock()


def should_prune_audit_tables(settings: Settings) -> bool:
    global _prune_counter
    every = settings.context_prune_every_runs
    if every <= 0:
        return False
    with _prune_lock:
        _prune_counter += 1
        return _prune_counter % every == 0


def maybe_prune_audit_tables(
    memory: Any,
    settings: Settings,
    *,
    force: bool = False,
) -> dict[str, int] | None:
    if not force and not should_prune_audit_tables(settings):
        return None
    return memory.prune_audit_tables(
        max_inbound=settings.context_max_inbound_rows,
        max_runs=settings.context_max_runs,
        max_tool_events=settings.context_max_tool_events,
    )
