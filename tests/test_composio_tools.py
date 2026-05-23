from __future__ import annotations

from unittest.mock import MagicMock, patch

from wabot_agent.agent import build_agent_instructions
from wabot_agent.composio_tools import (
    build_composio_prompt_context,
    composio_enabled,
    composio_session_user_id,
    load_composio_tools,
    reset_composio_client_for_tests,
)
from wabot_agent.config import Settings
from wabot_agent.memory import MemoryStore


def test_composio_enabled_requires_flag_and_key() -> None:
    off = Settings(
        composio_enabled=False,
        composio_api_key="ak_test",
        offline_mode=False,
        _env_file=None,
    )
    assert composio_enabled(off) is False
    on = Settings(
        composio_enabled=True,
        composio_api_key="ak_test",
        offline_mode=False,
        _env_file=None,
    )
    assert composio_enabled(on) is True


def test_load_composio_tools_creates_session_and_persists_id(tmp_path) -> None:
    reset_composio_client_for_tests()
    memory = MemoryStore(tmp_path / "db.sqlite3")
    settings = Settings(
        composio_enabled=True,
        composio_api_key="ak_test",
        offline_mode=False,
        _env_file=None,
    )
    mock_tool = MagicMock()
    mock_tool.name = "COMPOSIO_SEARCH_TOOLS"
    mock_session = MagicMock()
    mock_session.session_id = "trs_test123"
    mock_session.tools.return_value = [mock_tool]
    mock_composio = MagicMock()
    mock_composio.create.return_value = mock_session

    with patch("wabot_agent.composio_tools._get_composio_client", return_value=mock_composio):
        tools = load_composio_tools(settings, user_id="user_abc", memory=memory)

    assert len(tools) == 1
    mock_composio.create.assert_called_once_with(user_id="user_abc")
    facts = memory.recall_contact("user_abc")["facts"]
    assert any(f["key"] == "composio_session_id" and f["value"] == "trs_test123" for f in facts)


def test_load_composio_tools_caches_per_user(tmp_path) -> None:
    reset_composio_client_for_tests()
    memory = MemoryStore(tmp_path / "db2.sqlite3")
    settings = Settings(
        composio_enabled=True,
        composio_api_key="ak_test",
        offline_mode=False,
        _env_file=None,
    )
    mock_session = MagicMock()
    mock_session.session_id = "trs_cached"
    mock_session.tools.return_value = [MagicMock(name="COMPOSIO_SEARCH_TOOLS")]
    mock_composio = MagicMock()
    mock_composio.create.return_value = mock_session

    with patch("wabot_agent.composio_tools._get_composio_client", return_value=mock_composio):
        first = load_composio_tools(settings, user_id="user_cache", memory=memory)
        second = load_composio_tools(settings, user_id="user_cache", memory=memory)

    assert first is second
    mock_session.tools.assert_called_once()


def test_load_composio_tools_can_reuse_configured_owner_session(tmp_path) -> None:
    reset_composio_client_for_tests()
    memory = MemoryStore(tmp_path / "db-owner.sqlite3")
    memory.remember_contact_fact(
        "owner-calendar",
        "composio_session_id",
        "trs_owner",
        source="test",
    )
    settings = Settings(
        composio_enabled=True,
        composio_api_key="ak_test",
        composio_user_id="owner-calendar",
        offline_mode=False,
        _env_file=None,
    )
    mock_session = MagicMock()
    mock_session.tools.return_value = [MagicMock(name="COMPOSIO_SEARCH_TOOLS")]
    mock_composio = MagicMock()
    mock_composio.use.return_value = mock_session

    with patch("wabot_agent.composio_tools._get_composio_client", return_value=mock_composio):
        load_composio_tools(settings, user_id="stranger-contact", memory=memory)

    mock_composio.use.assert_called_once_with("trs_owner")
    mock_composio.create.assert_not_called()
    assert composio_session_user_id(settings, "stranger-contact") == "owner-calendar"


def test_build_agent_instructions_mention_composio_when_enabled() -> None:
    settings = Settings(
        composio_enabled=True,
        composio_api_key="ak_test",
        offline_mode=False,
        _env_file=None,
    )
    text = build_agent_instructions(settings, "")
    assert "COMPOSIO_MANAGE_CONNECTIONS" in text
    assert "Never hallucinate" in text
    assert "composio-gmail-calendar" in text
    assert "verify the owner's availability" in text
    assert "attendee's availability" in text


def test_build_agent_instructions_include_basic_appointment_booking_workflow() -> None:
    settings = Settings(
        composio_enabled=False,
        offline_mode=False,
        _env_file=None,
    )
    text = build_agent_instructions(settings, "")
    assert "Appointment booking" in text
    assert "contact the attendee" in text
    assert "only create a calendar" in text


def test_build_composio_prompt_context_only_when_tools_loaded() -> None:
    assert build_composio_prompt_context(tools_loaded=False) == ""
    loaded = build_composio_prompt_context(tools_loaded=True)
    assert "COMPOSIO_SEARCH_TOOLS" in loaded
    assert "appointment" in loaded
    assert "booking" in loaded
    assert "never invent" in loaded.lower()
