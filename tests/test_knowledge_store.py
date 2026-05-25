from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest

from wabot_agent.config import Settings
from wabot_agent.knowledge_store import (
    _MIGRATION_MARKER,
    StaleVersionError,
    atomic_write_text,
    compute_version,
    ensure_knowledge_files,
    format_contact_facts,
    get_write_lock,
    load_instructions,
    read_instructions_raw,
    save_instructions,
    save_instructions_checked,
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


def test_ensure_knowledge_files_seeds_template(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    ensure_knowledge_files(settings)

    instructions = settings.knowledge_dir / "instructions.md"
    memory = settings.knowledge_dir / "memory.md"

    assert instructions.exists()
    # Legacy memory.md is no longer seeded — it's only present when migrated.
    assert not memory.exists()
    body = instructions.read_text(encoding="utf-8")
    assert "Client instructions" in body
    # Operator-knowledge headings now live inside instructions.md.
    assert "Operator knowledge" in body


def test_save_and_load_with_cache(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    save_instructions(settings, "Always greet by first name.")

    assert read_instructions_raw(settings) == "Always greet by first name."
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


def test_atomic_write_text_replaces_file(tmp_path: Path) -> None:
    target = tmp_path / "atomic.md"
    atomic_write_text(target, "first")
    assert target.read_text(encoding="utf-8") == "first"
    atomic_write_text(target, "second")
    assert target.read_text(encoding="utf-8") == "second"
    # No leftover temp files in the directory.
    assert list(tmp_path.glob(".atomic.md.*.tmp")) == []


def test_legacy_memory_md_is_migrated_into_instructions(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    knowledge_dir = settings.knowledge_dir
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    (knowledge_dir / "instructions.md").write_text(
        "## Rules\nBe polite.", encoding="utf-8"
    )
    (knowledge_dir / "memory.md").write_text(
        "Operator timezone: US/Pacific.", encoding="utf-8"
    )

    text = read_instructions_raw(settings)
    assert "Be polite" in text
    assert _MIGRATION_MARKER in text
    assert "US/Pacific" in text

    # memory.md is renamed (not deleted) so the operator has a recoverable copy.
    assert not (knowledge_dir / "memory.md").exists()
    assert (knowledge_dir / "memory.md.migrated").exists()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    knowledge_dir = settings.knowledge_dir
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    (knowledge_dir / "instructions.md").write_text("base", encoding="utf-8")
    (knowledge_dir / "memory.md").write_text("extra", encoding="utf-8")

    first = read_instructions_raw(settings)
    # Simulate a fresh memory.md showing up after migration — it should be
    # ignored because the marker is already present in instructions.md.
    (knowledge_dir / "memory.md").write_text("ignored", encoding="utf-8")
    second = read_instructions_raw(settings)
    assert first == second
    assert second.count(_MIGRATION_MARKER) == 1


def test_concurrent_writes_under_lock_yield_one_winner(tmp_path: Path) -> None:
    """10 concurrent writers must not interleave/tear the file."""
    target = tmp_path / "concurrent.md"
    writers = 10
    expected_values = {f"writer-{i}" for i in range(writers)}

    async def _do_write(i: int) -> None:
        async with get_write_lock(target):
            atomic_write_text(target, f"writer-{i}")

    async def _run_all() -> None:
        await asyncio.gather(*(_do_write(i) for i in range(writers)))

    asyncio.run(_run_all())

    assert target.exists()
    final = target.read_text(encoding="utf-8")
    # Whoever wrote last wins, but the content must be exactly one of the
    # 10 candidate strings — never a torn / interleaved blob.
    assert final in expected_values
    # No leftover .tmp siblings from atomic_write_text in the directory.
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_atomic_write_crash_preserves_original_and_cleans_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If os.replace fails mid-write, the original file is untouched and no
    .tmp sibling is left behind."""
    target = tmp_path / "instructions.md"
    atomic_write_text(target, "original")
    assert target.read_text(encoding="utf-8") == "original"

    real_replace = os.replace
    calls: dict[str, int] = {"n": 0}

    def flaky_replace(src, dst, *args, **kwargs):
        # Only fail when atomic_write_text replaces onto our target — let any
        # unrelated os.replace (e.g. fixtures) succeed.
        if str(dst) == str(target) and calls["n"] == 0:
            calls["n"] += 1
            raise OSError("simulated crash")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr("wabot_agent.knowledge_store.os.replace", flaky_replace)

    with pytest.raises(OSError, match="simulated crash"):
        atomic_write_text(target, "new content")

    # Original content survives.
    assert target.read_text(encoding="utf-8") == "original"
    # No .tmp sibling left in the directory.
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_legacy_memory_md_migration_merges_and_renames(tmp_path: Path) -> None:
    """Explicit migration round-trip covering content, marker, rename, and
    second-call idempotency.

    Variant test below covers the post-migration state where instructions.md
    already has the marker and memory.md.migrated already exists.
    """
    settings = make_settings(tmp_path)
    knowledge_dir = settings.knowledge_dir
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    (knowledge_dir / "instructions.md").write_text("INSTR", encoding="utf-8")
    (knowledge_dir / "memory.md").write_text("MEM", encoding="utf-8")

    first = load_instructions(settings)
    assert "INSTR" in first
    assert "MEM" in first
    assert _MIGRATION_MARKER in first

    on_disk = (knowledge_dir / "instructions.md").read_text(encoding="utf-8")
    assert "INSTR" in on_disk
    assert "MEM" in on_disk
    assert _MIGRATION_MARKER in on_disk
    assert not (knowledge_dir / "memory.md").exists()
    assert (knowledge_dir / "memory.md.migrated").exists()

    # Idempotency: a second read must not double-insert the marker or rewrite
    # the file with new content.
    after_first = (knowledge_dir / "instructions.md").read_text(encoding="utf-8")
    second = load_instructions(settings)
    after_second = (knowledge_dir / "instructions.md").read_text(encoding="utf-8")
    assert after_first == after_second
    assert second.count(_MIGRATION_MARKER) == 1


# ---------------------------------------------------------------------------
# Optimistic-concurrency / If-Match guard.
# ---------------------------------------------------------------------------


def test_compute_version_is_deterministic_and_stable() -> None:
    """Same input → same 16-hex-char hash; empty string has the known
    SHA-256 prefix; different inputs produce different tokens."""
    a = compute_version("hello world")
    b = compute_version("hello world")
    assert a == b
    assert len(a) == 16
    assert all(c in "0123456789abcdef" for c in a)

    # Empty string -> known SHA-256("") prefix.
    empty = compute_version("")
    assert empty == "e3b0c44298fc1c14"

    # Different inputs -> different tokens.
    assert compute_version("hello world!") != a


def test_save_instructions_checked_succeeds_without_if_match(tmp_path: Path) -> None:
    """Backward compat: callers without an If-Match always succeed and
    overwrite whatever's on disk."""
    settings = make_settings(tmp_path)
    save_instructions(settings, "seed")

    meta = asyncio.run(
        save_instructions_checked(settings, "no-if-match", if_match=None)
    )
    assert read_instructions_raw(settings) == "no-if-match"
    assert meta["version"] == compute_version("no-if-match")


def test_save_instructions_checked_succeeds_with_matching_if_match(
    tmp_path: Path,
) -> None:
    """Happy path: client sends the current version, save proceeds."""
    settings = make_settings(tmp_path)
    save_instructions(settings, "v1")
    current = compute_version("v1")

    meta = asyncio.run(save_instructions_checked(settings, "v2", if_match=current))
    assert read_instructions_raw(settings) == "v2"
    assert meta["version"] == compute_version("v2")


def test_save_instructions_checked_raises_on_stale_if_match(tmp_path: Path) -> None:
    """If-Match does not match → StaleVersionError carrying all three
    attributes."""
    settings = make_settings(tmp_path)
    save_instructions(settings, "current")
    current_version = compute_version("current")

    stale = "0" * 16
    with pytest.raises(StaleVersionError) as exc_info:
        asyncio.run(save_instructions_checked(settings, "would-clobber", if_match=stale))
    err = exc_info.value
    assert err.current_version == current_version
    assert err.current_content == "current"
    assert err.submitted_version == stale


def test_save_instructions_checked_does_not_write_on_stale(tmp_path: Path) -> None:
    """File content must be untouched after a StaleVersionError raise."""
    settings = make_settings(tmp_path)
    save_instructions(settings, "untouched")
    instructions_path = settings.knowledge_dir / "instructions.md"
    mtime_before = instructions_path.stat().st_mtime

    with pytest.raises(StaleVersionError):
        asyncio.run(
            save_instructions_checked(
                settings, "would-clobber", if_match="deadbeefdeadbeef"
            )
        )

    assert instructions_path.read_text(encoding="utf-8") == "untouched"
    assert instructions_path.stat().st_mtime == mtime_before


def test_concurrent_save_one_wins_other_gets_stale(tmp_path: Path) -> None:
    """Two coroutines read version V, both submit If-Match=V — exactly
    one wins, the other raises StaleVersionError. This is the race the
    guard exists to prevent (CLI tab + browser tab against the same
    file)."""
    settings = make_settings(tmp_path)
    save_instructions(settings, "shared-seed")
    shared_version = compute_version("shared-seed")

    results: list[tuple[str, dict[str, Any] | StaleVersionError]] = []

    async def _writer(label: str, content: str) -> None:
        try:
            meta = await save_instructions_checked(settings, content, if_match=shared_version)
            results.append((label, meta))
        except StaleVersionError as exc:
            results.append((label, exc))

    async def _run() -> None:
        await asyncio.gather(_writer("A", "from-A"), _writer("B", "from-B"))

    asyncio.run(_run())

    successes = [r for r in results if not isinstance(r[1], StaleVersionError)]
    failures = [r for r in results if isinstance(r[1], StaleVersionError)]
    assert len(successes) == 1, results
    assert len(failures) == 1, results

    # Winner's content landed on disk; failure carries the post-winner
    # version (i.e. the loser saw the freshly-updated state).
    winner_label, winner_meta = successes[0]
    final = (settings.knowledge_dir / "instructions.md").read_text(encoding="utf-8")
    expected = "from-A" if winner_label == "A" else "from-B"
    assert final == expected
    assert isinstance(winner_meta, dict)
    assert winner_meta["version"] == compute_version(expected)

    _, loser_exc = failures[0]
    assert isinstance(loser_exc, StaleVersionError)
    assert loser_exc.submitted_version == shared_version
    assert loser_exc.current_version == compute_version(expected)


def test_post_migration_state_is_a_noop(tmp_path: Path) -> None:
    """When instructions.md already carries the marker AND memory.md was
    previously renamed to memory.md.migrated, load_instructions must not
    touch any file."""
    settings = make_settings(tmp_path)
    knowledge_dir = settings.knowledge_dir
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    instructions_path = knowledge_dir / "instructions.md"
    archived_path = knowledge_dir / "memory.md.migrated"
    instructions_text = f"INSTR\n\n{_MIGRATION_MARKER}\n\nMEM"
    instructions_path.write_text(instructions_text, encoding="utf-8")
    archived_path.write_text("MEM", encoding="utf-8")
    instructions_mtime_before = instructions_path.stat().st_mtime
    archived_mtime_before = archived_path.stat().st_mtime

    out = load_instructions(settings)
    assert _MIGRATION_MARKER in out
    assert out.count(_MIGRATION_MARKER) == 1

    # Files untouched (content + mtime).
    assert instructions_path.read_text(encoding="utf-8") == instructions_text
    assert archived_path.read_text(encoding="utf-8") == "MEM"
    assert instructions_path.stat().st_mtime == instructions_mtime_before
    assert archived_path.stat().st_mtime == archived_mtime_before
    # memory.md must remain absent.
    assert not (knowledge_dir / "memory.md").exists()
