from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from agents.tool import ToolContext

from wabot_agent.agent import build_agent_instructions
from wabot_agent.config import Settings
from wabot_agent.events import EventLog
from wabot_agent.mem0_store import _mem0_llm_env
from wabot_agent.memory import InboundMessage, MemoryStore
from wabot_agent.tools import (
    RuntimeContext,
    _mem0_user_id,
    add_mem0_memory,
    search_mem0_memories,
)
from wabot_agent.wabot import FakeWabotClient


def test_mem0_llm_env_strips_openrouter_for_ollama_cloud() -> None:
    settings = Settings(
        model_provider="ollama_cloud",
        ollama_api_key="ollama-test",
        offline_mode=False,
        _env_file=None,
    )
    os.environ["OPENROUTER_API_KEY"] = "sk-or-test"
    try:
        with _mem0_llm_env(settings):
            assert "OPENROUTER_API_KEY" not in os.environ
        assert os.environ.get("OPENROUTER_API_KEY") == "sk-or-test"
    finally:
        os.environ.pop("OPENROUTER_API_KEY", None)


def _group_inbound() -> InboundMessage:
    return InboundMessage(
        id="g1",
        sender="111@s.whatsapp.net",
        text="hi",
        chat="120363@g.us",
        is_group=True,
    )


def test_mem0_user_id_uses_sender_in_groups(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    ctx = ToolContext(
        RuntimeContext(
            settings,
            memory,
            fake_wabot,
            event_log,
            run_id="run-mem0",
            inbound=_group_inbound(),
        ),
        tool_name="x",
        tool_call_id="c",
        tool_arguments="{}",
    )
    assert _mem0_user_id(ctx) == "111@s.whatsapp.net"


@pytest.mark.asyncio
async def test_search_mem0_memories_disabled_is_fast(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    disabled = settings.model_copy(update={"mem0_enabled": False})
    ctx = ToolContext(
        RuntimeContext(
            disabled,
            memory,
            fake_wabot,
            event_log,
            run_id="run-off",
            inbound=_group_inbound(),
        ),
        tool_name="search_mem0_memories",
        tool_call_id="call-off",
        tool_arguments='{"query":"prefs"}',
    )
    with patch("wabot_agent.tools.search_memories_sync") as mock_search:
        result = await search_mem0_memories.on_invoke_tool(ctx, '{"query":"prefs"}')
    assert result["ok"] is False
    assert result["reason"] == "mem0_disabled"
    mock_search.assert_not_called()


@pytest.mark.asyncio
async def test_search_mem0_memories_defaults_to_sender_and_group(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    enabled = settings.model_copy(
        update={
            "mem0_enabled": True,
            "openrouter_api_key": "sk-test",
            "offline_mode": False,
        }
    )
    ctx = ToolContext(
        RuntimeContext(
            enabled,
            memory,
            fake_wabot,
            event_log,
            run_id="run-grp-mem0",
            inbound=_group_inbound(),
        ),
        tool_name="search_mem0_memories",
        tool_call_id="call-grp-mem0",
        tool_arguments='{"query":"prefs"}',
    )
    with patch(
        "wabot_agent.tools.search_memories_sync",
        return_value={"ok": True, "count": 0, "results": []},
    ) as mock_search:
        result = await search_mem0_memories.on_invoke_tool(ctx, '{"query":"prefs"}')
    assert result["ok"] is True
    assert mock_search.call_count == 2
    searched_ids = {c.kwargs["user_id"] for c in mock_search.call_args_list}
    assert searched_ids == {"111@s.whatsapp.net", "120363@g.us"}


@pytest.mark.asyncio
async def test_add_mem0_memory_disabled_is_fast(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    fake_wabot: FakeWabotClient,
) -> None:
    disabled = settings.model_copy(update={"mem0_enabled": False})
    ctx = ToolContext(
        RuntimeContext(disabled, memory, fake_wabot, event_log, run_id="run-add-off"),
        tool_name="add_mem0_memory",
        tool_call_id="call-add-off",
        tool_arguments='{"text":"likes tea"}',
    )
    with patch("wabot_agent.tools.add_memory_sync") as mock_add:
        result = await add_mem0_memory.on_invoke_tool(ctx, '{"text":"likes tea"}')
    assert result["ok"] is False
    assert result["reason"] == "mem0_disabled"
    mock_add.assert_not_called()


def test_build_agent_instructions_omit_mem0_when_disabled() -> None:
    disabled = Settings(mem0_enabled=False, openrouter_api_key="sk-test", offline_mode=False)
    text = build_agent_instructions(disabled, "")
    assert "Memory (mandatory" not in text
    assert "search_mem0_memories" not in text
    assert "recall_contact_memory" in text

    enabled = Settings(
        model_provider="openrouter",
        mem0_enabled=True,
        openrouter_api_key="sk-test",
        offline_mode=False,
    )
    text_on = build_agent_instructions(enabled, "")
    assert "Memory (mandatory" in text_on
    assert "search_mem0_memories" in text_on


def test_build_agent_instructions_include_client_knowledge(tmp_path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "instructions.md").write_text(
        "Always use the company name Acme Corp.",
        encoding="utf-8",
    )
    (knowledge_dir / "memory.md").write_text(
        "Operator timezone: US/Pacific.",
        encoding="utf-8",
    )
    settings = Settings(
        mem0_enabled=False,
        openrouter_api_key="sk-test",
        offline_mode=False,
        knowledge_dir=knowledge_dir,
    )
    text = build_agent_instructions(settings, "")
    assert "## Client instructions" in text
    assert "Acme Corp" in text
    assert "## Operator knowledge" in text
    assert "US/Pacific" in text
