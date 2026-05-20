from __future__ import annotations

from pathlib import Path

from wabot_agent.agent import build_agent_instructions
from wabot_agent.config import Settings
from wabot_agent.knowledge_store import format_agent_notes
from wabot_agent.mem0_store import format_memories_for_prompt
from wabot_agent.memory import MemoryStore


def test_format_agent_notes_truncates() -> None:
    notes = [{"key": "rule", "value": "always confirm sends"}]
    out = format_agent_notes(notes, 2000)
    assert "rule" in out
    assert "confirm sends" in out


def test_format_memories_for_prompt_states_dashboard_precedence() -> None:
    block = format_memories_for_prompt(
        [{"memory": "User likes tea"}], max_chars=4000
    )
    assert "Mem0" in block
    assert "prefer those dashboard layers" in block


def test_build_agent_instructions_knowledge_layers_and_mem0(tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "instructions.md").write_text("Use brand Acme.", encoding="utf-8")
    db = tmp_path / "agent.db"
    memory = MemoryStore(db)
    memory.remember_agent_note("escalation", "page the owner for refunds")

    settings = Settings(
        mem0_enabled=True,
        openrouter_api_key="sk-test",
        offline_mode=False,
        knowledge_dir=knowledge_dir,
        db_path=db,
        _env_file=None,
    )
    text = build_agent_instructions(settings, "", memory=memory)
    assert "Knowledge layers" in text
    assert "Client instructions" in text
    assert "Acme" in text
    assert "## Agent notes" in text
    assert "escalation" in text
    assert "search_mem0_memories" in text
    assert "Notes tab" in text


def test_build_agent_instructions_sqlite_mentions_knowledge_dashboard() -> None:
    settings = Settings(mem0_enabled=False, offline_mode=True, _env_file=None)
    text = build_agent_instructions(settings, "")
    assert "Knowledge layers" in text
    assert "Contacts** tab" in text
    assert "search_mem0_memories" not in text
