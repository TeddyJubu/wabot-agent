from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from agents.memory import SessionSettings

from wabot_agent.config import Settings
from wabot_agent.context_management import (
    build_agent_run_config,
    build_agent_session,
    cap_turn_prompt,
    clear_agent_session,
    is_recoverable_codex_session_error,
    make_session_input_callback,
    prune_agent_session_messages,
    prune_codex_session_storage,
    sanitize_codex_session_history,
    split_history_by_token_budget,
    strip_images_from_session_item,
    trim_history_for_tokens,
)
from wabot_agent.memory import MemoryStore
from wabot_agent.thread_summary import summary_message_item


def _settings(tmp_path: Path, **kwargs: object) -> Settings:
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        OPENROUTER_MODEL="openai/gpt-5.2",
        OPENROUTER_API_KEY=None,
        _env_file=None,
        **kwargs,
    )


def _init_agent_messages(db_path: Path, session_id: str, count: int) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "create table if not exists agent_sessions (session_id text primary key)"
    )
    conn.execute(
        """
        create table if not exists agent_messages (
            id integer primary key autoincrement,
            session_id text not null,
            message_data text not null
        )
        """
    )
    conn.execute(
        "insert or ignore into agent_sessions (session_id) values (?)",
        (session_id,),
    )
    for i in range(count):
        conn.execute(
            "insert into agent_messages (session_id, message_data) values (?, ?)",
            (session_id, json.dumps({"role": "user", "content": f"message-{i}"})),
        )
    conn.commit()
    conn.close()


def test_strip_images_from_session_item_removes_image_parts() -> None:
    item = {
        "role": "user",
        "content": [
            {"type": "input_text", "text": "find google logo"},
            {"type": "input_image", "image_url": "data:image/png;base64,abc"},
        ],
    }
    stripped = strip_images_from_session_item(item)
    assert stripped["role"] == "user"
    assert isinstance(stripped["content"], str)
    assert "google logo" in stripped["content"]
    assert "image omitted" in stripped["content"]


def test_cap_turn_prompt_truncates_long_text() -> None:
    text = "x" * 1000
    capped = cap_turn_prompt(text, 500)
    assert len(capped) < len(text)
    assert "truncated" in capped


def test_trim_history_for_tokens_keeps_newest() -> None:
    history = [{"role": "user", "content": "a" * 4000} for _ in range(10)]
    trimmed = trim_history_for_tokens(history, max_tokens=500, reserved_tokens=50)
    assert len(trimmed) < len(history)
    assert trimmed[-1]["content"].startswith("a")


def test_split_history_by_token_budget() -> None:
    history = [{"role": "user", "content": f"msg-{i}"} for i in range(6)]
    dropped, kept = split_history_by_token_budget(history, max_tokens=30, reserved_tokens=0)
    assert len(dropped) > 0
    assert len(kept) > 0
    assert len(dropped) + len(kept) <= len(history)


@pytest.mark.asyncio
async def test_session_input_callback_respects_token_budget(tmp_path: Path) -> None:
    settings = _settings(tmp_path, WABOT_AGENT_SESSION_MAX_HISTORY_TOKENS=200)
    memory = MemoryStore(settings.db_path)
    callback = make_session_input_callback(settings, "contact-1", memory)
    history = [{"role": "user", "content": "old " * 500} for _ in range(8)]
    new_items = [{"role": "user", "content": "new turn"}]
    merged = await callback(history, new_items)
    assert merged[-1]["content"] == "new turn"
    assert len(merged) < len(history) + len(new_items) + 1


@pytest.mark.asyncio
async def test_session_input_callback_injects_saved_summary(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        WABOT_AGENT_SESSION_MAX_HISTORY_TOKENS=0,
        WABOT_AGENT_SESSION_SUMMARY_ENABLED=True,
    )
    memory = MemoryStore(settings.db_path)
    memory.save_session_summary("contact-1", "User name is Alex.")
    callback = make_session_input_callback(settings, "contact-1", memory)
    merged = await callback([], [{"role": "user", "content": "hello"}])
    assert merged[0] == summary_message_item("User name is Alex.")


def test_build_agent_session_sets_limit(tmp_path: Path) -> None:
    settings = _settings(tmp_path, WABOT_AGENT_SESSION_HISTORY_LIMIT=12)
    session = build_agent_session(settings, "contact-1")
    assert session.session_settings is not None
    assert session.session_settings.limit == 12


def test_build_agent_run_config_includes_callback(tmp_path: Path) -> None:
    settings = _settings(tmp_path, WABOT_AGENT_SESSION_MAX_HISTORY_TOKENS=1000)
    memory = MemoryStore(settings.db_path)
    run_config = build_agent_run_config(settings, "contact-1", memory)
    assert run_config.session_input_callback is not None
    assert isinstance(run_config.session_settings, SessionSettings)


def test_prune_agent_session_messages(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    _init_agent_messages(db_path, "s1", 20)
    deleted = prune_agent_session_messages(db_path, "s1", keep_items=5)
    assert deleted == 15
    conn = sqlite3.connect(db_path)
    count = conn.execute(
        "select count(*) from agent_messages where session_id = ?", ("s1",)
    ).fetchone()[0]
    conn.close()
    assert count == 5


def test_sanitize_codex_session_history_drops_reasoning_and_orphan_outputs() -> None:
    history = [
        {"role": "user", "content": "hi"},
        {
            "type": "reasoning",
            "id": "rs_abc123",
            "summary": [{"type": "summary_text", "text": "thinking"}],
        },
        {
            "type": "function_call",
            "call_id": "call_ok",
            "name": "wabot_health",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "call_orphan",
            "output": '{"ok": true}',
        },
    ]
    cleaned = sanitize_codex_session_history(history)
    assert cleaned == [
        {"role": "user", "content": "hi"},
        {
            "type": "function_call",
            "call_id": "call_ok",
            "name": "wabot_health",
            "arguments": "{}",
        },
    ]


def test_is_recoverable_codex_session_error() -> None:
    assert is_recoverable_codex_session_error(
        RuntimeError(
            "No tool call found for function call output with call_id call_x."
        )
    )
    assert is_recoverable_codex_session_error(
        RuntimeError("Item rs_abc not found. Items are not persisted when store is false.")
    )
    assert not is_recoverable_codex_session_error(RuntimeError("rate limit"))


def test_prune_codex_session_storage(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        create table agent_messages (
            id integer primary key autoincrement,
            session_id text not null,
            message_data text not null
        )
        """
    )
    rows = [
        {"role": "user", "content": "hi"},
        {"type": "reasoning", "id": "rs_abc", "summary": []},
        {
            "type": "function_call",
            "call_id": "call_ok",
            "name": "wabot_health",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "call_ok",
            "output": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "call_bad",
            "output": "{}",
        },
    ]
    for row in rows:
        conn.execute(
            "insert into agent_messages (session_id, message_data) values (?, ?)",
            ("operator", json.dumps(row)),
        )
    conn.commit()
    conn.close()
    deleted = prune_codex_session_storage(db_path, "operator")
    assert deleted == 2
    conn = sqlite3.connect(db_path)
    remaining = conn.execute(
        "select message_data from agent_messages where session_id = ? order by id",
        ("operator",),
    ).fetchall()
    conn.close()
    types = [json.loads(r[0]).get("type") or json.loads(r[0]).get("role") for r in remaining]
    assert types == ["user", "function_call", "function_call_output"]


def test_clear_agent_session(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    _init_agent_messages(db_path, "s1", 3)
    deleted = clear_agent_session(db_path, "s1")
    assert deleted == 3
    conn = sqlite3.connect(db_path)
    count = conn.execute(
        "select count(*) from agent_messages where session_id = ?", ("s1",)
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_memory_prune_audit_tables(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "agent.db")
    for i in range(5):
        memory.record_run(f"run-{i}", "+1", f"input-{i}", f"output-{i}")
    deleted = memory.prune_audit_tables(max_inbound=0, max_runs=2, max_tool_events=0)
    assert deleted["runs"] == 3
    assert memory.stats()["runs"] == 2
