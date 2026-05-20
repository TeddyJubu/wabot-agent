from __future__ import annotations

from pathlib import Path

from wabot_agent.config import Settings
from wabot_agent.knowledge_store import (
    ensure_knowledge_files,
    format_contact_facts,
    load_instructions,
    read_global_memory_raw,
    read_instructions_raw,
    save_global_memory,
    save_instructions,
    truncate_for_prompt,
)


def make_settings(tmp_path: Path) -> Settings:
    knowledge_dir = tmp_path / "knowledge"
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_KNOWLEDGE_DIR=knowledge_dir,
        WABOT_AGENT_MCP_CONFIG=None,
        OPENROUTER_API_KEY=None,
    )


def test_ensure_knowledge_files_seeds_templates(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    ensure_knowledge_files(settings)

    instructions = settings.knowledge_dir / "instructions.md"
    memory = settings.knowledge_dir / "memory.md"

    assert instructions.exists()
    assert memory.exists()
    assert "Client instructions" in instructions.read_text(encoding="utf-8")
    assert "Operator knowledge" in memory.read_text(encoding="utf-8")


def test_save_and_load_with_cache(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    save_instructions(settings, "Always greet by first name.")
    save_global_memory(settings, "Office hours: 9–5 PT.")

    assert read_instructions_raw(settings) == "Always greet by first name."
    assert read_global_memory_raw(settings) == "Office hours: 9–5 PT."
    assert load_instructions(settings) == "Always greet by first name."


def test_truncate_for_prompt_adds_suffix(tmp_path: Path) -> None:
    text = "x" * 100
    out = truncate_for_prompt(text, max_chars=20)
    assert out.endswith("… [truncated]")
    assert len(out) <= 20


def test_format_contact_facts_respects_budget() -> None:
    facts = {
        "contact": "+1",
        "facts": [{"key": "name", "value": "Alex"}, {"key": "tz", "value": "US/Pacific"}],
    }
    block = format_contact_facts(facts, max_chars=30)
    assert "name" in block
    assert len(block) <= 30


def test_load_instructions_truncates_for_agent(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={"knowledge_instructions_max_chars": 30}
    )
    save_instructions(settings, "x" * 80)
    loaded = load_instructions(settings)
    assert loaded.endswith("… [truncated]")
    assert len(loaded) <= 30
