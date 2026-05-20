from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from wabot_agent.agent import (
    _prepare_agent_turn,
    run_agent_streamed,
)
from wabot_agent.config import Settings
from wabot_agent.events import EventLog
from wabot_agent.instructions_cache import (
    cached_build_agent_instructions,
    cached_render_skill_summary,
    invalidate_instructions_cache,
)
from wabot_agent.media_download import MediaDownloadResult
from wabot_agent.mem0_store import _mem0_search_query, inject_mem0_context
from wabot_agent.memory import InboundMessage, MemoryStore


def test_get_contact_fact(memory: MemoryStore) -> None:
    memory.remember_contact_fact("+1", "composio_session_id", "sess-abc", "test")
    assert memory.get_contact_fact("+1", "composio_session_id") == "sess-abc"
    assert memory.get_contact_fact("+1", "missing") is None


def test_bulk_record_inbound_single_transaction(memory: MemoryStore) -> None:
    messages = [
        InboundMessage(
            id=f"hist-{i}",
            sender=f"+{i}",
            chat=None,
            text=f"message {i}",
        )
        for i in range(100)
    ]
    result = memory.bulk_record_inbound(messages)
    assert result["stored"] == 100
    assert result["count"] == 100
    assert memory.stats()["inbound_messages"] == 100


def test_mem0_search_query_prefers_inbound_text() -> None:
    prompt = (
        "Inbound WhatsApp message:\n"
        "- message_id: abc\n"
        "- sender: +1\n"
        "- text: Please remember my dog's name is Max\n"
        "- has_media: false\n"
    )
    query = _mem0_search_query(prompt, max_len=512)
    assert "Max" in query
    assert len(query) <= 512


@pytest.mark.asyncio
async def test_inject_mem0_context_gather(
    settings: Settings,
    memory: MemoryStore,
) -> None:
    enabled = settings.model_copy(update={"mem0_enabled": True, "mem0_inject_on_run": True})
    calls: list[str] = []

    async def fake_search(_settings, *, user_id: str, query: str) -> dict:
        calls.append(f"{user_id}:{query}")
        return {"ok": True, "results": [{"memory": f"fact for {user_id}"}]}

    with patch("wabot_agent.mem0_store.search_memories", side_effect=fake_search):
        out = await inject_mem0_context(
            enabled,
            "Inbound WhatsApp message:\n- text: hello there\n",
            user_ids=["alice", "bob"],
        )
    assert len(calls) == 2
    assert "alice" in calls[0]
    assert "bob" in calls[1]
    assert "fact for alice" in out or "fact for bob" in out


@pytest.mark.asyncio
async def test_prepare_agent_turn_downloads_media_once(
    settings: Settings,
    memory: MemoryStore,
    event_log: EventLog,
    tmp_path: Path,
) -> None:
    inbound = InboundMessage(
        id="img-1",
        sender="+1",
        chat="+1",
        text="photo?",
        has_media=True,
        media_kind="image",
        media_mime="image/png",
    )
    downloaded = MediaDownloadResult(
        ok=True,
        path=tmp_path / "img.png",
        bytes=4,
        media_kind="image",
        mime="image/png",
    )
    downloaded.path.write_bytes(b"\x89PNG")
    calls = 0

    async def fake_download(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return downloaded

    with patch(
        "wabot_agent.agent.download_inbound_media",
        side_effect=fake_download,
    ):
        with patch(
            "wabot_agent.agent.prepare_runner_input",
            new_callable=AsyncMock,
            return_value="text-only",
        ) as prep:
            await _prepare_agent_turn(
                "hi",
                settings=settings.model_copy(
                    update={"file_process_inbound": True, "vision_attach_images": True}
                ),
                memory=memory,
                event_log=event_log,
                inbound=inbound,
            )
            prep.assert_awaited_once()
            assert prep.await_args.kwargs.get("downloaded") is downloaded
    assert calls == 1


def test_instructions_cache_skips_rereads(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "demo"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("demo skill", encoding="utf-8")
    settings = Settings(skills_dir=skills_dir, _env_file=None)

    invalidate_instructions_cache()
    build_calls = 0

    def counting_build(**_kwargs: object) -> str:
        nonlocal build_calls
        build_calls += 1
        return "cached instructions"

    summary_one = cached_render_skill_summary(skills_dir)
    summary_two = cached_render_skill_summary(skills_dir)
    assert summary_one == summary_two

    cached_build_agent_instructions(
        settings,
        memory=None,
        build_fn=counting_build,
        build_kwargs={"settings": settings, "skill_summary": summary_one},
    )
    cached_build_agent_instructions(
        settings,
        memory=None,
        build_fn=counting_build,
        build_kwargs={"settings": settings, "skill_summary": summary_two},
    )
    assert build_calls == 1


def test_instructions_cache_busts_on_agent_notes(
    memory: MemoryStore,
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("demo skill", encoding="utf-8")
    settings = Settings(skills_dir=skills_dir, _env_file=None)

    invalidate_instructions_cache()
    build_calls = 0

    def counting_build(**_kwargs: object) -> str:
        nonlocal build_calls
        build_calls += 1
        return "cached instructions"

    summary = cached_render_skill_summary(skills_dir)
    kwargs = {"settings": settings, "skill_summary": summary, "memory": memory}
    cached_build_agent_instructions(
        settings,
        memory=memory,
        build_fn=counting_build,
        build_kwargs=kwargs,
    )
    cached_build_agent_instructions(
        settings,
        memory=memory,
        build_fn=counting_build,
        build_kwargs=kwargs,
    )
    assert build_calls == 1

    memory.remember_agent_note("policy", "reply briefly")
    cached_build_agent_instructions(
        settings,
        memory=memory,
        build_fn=counting_build,
        build_kwargs=kwargs,
    )
    assert build_calls == 2


def test_bulk_record_inbound_completes_quickly(memory: MemoryStore) -> None:
    messages = [
        InboundMessage(
            id=f"hist-{i}",
            sender=f"+{i}",
            chat=None,
            text=f"message {i}",
        )
        for i in range(200)
    ]
    started = time.perf_counter()
    memory.bulk_record_inbound(messages)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0


@pytest.mark.asyncio
async def test_stream_translation_yields_before_completion() -> None:
    from wabot_agent.agent import _translate_stream_event

    gate = asyncio.Event()
    first_delta = asyncio.Event()

    class DeltaData:
        type = "response.output_text.delta"
        delta = "tok"

    class DeltaEvent:
        type = "raw_response_event"
        data = DeltaData()

    class FakeStreamResult:
        final_output = "toktok"

        async def stream_events(self):
            yield DeltaEvent()
            first_delta.set()
            await gate.wait()
            yield DeltaEvent()

    received: list[dict] = []

    async def consume():
        state: dict[str, str] = {}
        async for event in FakeStreamResult().stream_events():
            for payload in _translate_stream_event(event, state):
                received.append(payload)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_delta.wait(), timeout=2.0)
    assert received and received[0]["type"] == "delta"
    gate.set()
    await asyncio.wait_for(task, timeout=2.0)


def test_run_agent_streamed_yields_inline() -> None:
    import inspect

    source = inspect.getsource(run_agent_streamed)
    assert "streamed_events" not in source
    assert "yield payload" in source
