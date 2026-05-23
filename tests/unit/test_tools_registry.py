"""Shape guard for core_tools() — pins the exact tool-name set.

If a tool is accidentally dropped or renamed during a refactor, this test
catches it before it silently removes a capability from the agent.

Update EXPECTED_TOOL_NAMES intentionally when adding or removing tools.
"""

from __future__ import annotations

from wabot_agent.tools import core_tools

EXPECTED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "wabot_health",
        "list_whatsapp_inbound_messages",
        "get_last_whatsapp_inbound_message",
        "lookup_whatsapp_contacts",
        "list_whatsapp_groups",
        "mark_whatsapp_read",
        "send_whatsapp_typing",
        "send_whatsapp_text",
        "send_whatsapp_image",
        "download_whatsapp_media",
        "process_vps_file",
        "process_whatsapp_attachment",
        "search_web",
        "search_images",
        "fetch_url_to_media",
        "send_whatsapp_file",
        "send_whatsapp_document",
        "send_whatsapp_audio",
        "send_whatsapp_video",
        "react_whatsapp_message",
        "edit_whatsapp_message",
        "revoke_whatsapp_message",
        "create_whatsapp_group",
        "get_whatsapp_group",
        "get_whatsapp_group_invite",
        "join_whatsapp_group",
        "update_whatsapp_group",
        "update_whatsapp_group_participants",
        "leave_whatsapp_group",
        "set_whatsapp_group_picture",
        "mute_whatsapp_chat",
        "archive_whatsapp_chat",
        "pin_whatsapp_chat",
        "get_whatsapp_user_info",
        "download_whatsapp_profile_picture",
        "recall_contact_memory",
        "remember_contact_fact",
        "recall_agent_notes",
        "remember_agent_note",
        "list_local_skills",
        "read_local_skill",
        "create_reminder",
        "list_reminders",
        "cancel_reminder",
        "track_outbound_conversation",
        "get_outbound_task_status",
        "list_outbound_tasks",
        "web_research_health",
        "start_web_research",
        "get_web_research_status",
        "list_web_research_jobs",
        "cancel_web_research",
        "send_task_plan",
        "report_task_step_complete",
        "send_task_progress",
        "mem0_status",
        "search_mem0_memories",
        "add_mem0_memory",
    }
)


def test_core_tools_registry_matches_expected_set() -> None:
    """core_tools() must return the exact expected set of tool names."""
    names = {t.name for t in core_tools()}
    missing = EXPECTED_TOOL_NAMES - names
    extra = names - EXPECTED_TOOL_NAMES
    assert not missing and not extra, (
        f"core_tools() registry changed.\n"
        f"  Missing tools: {sorted(missing)}\n"
        f"  Extra tools: {sorted(extra)}\n"
        "If intentional, update EXPECTED_TOOL_NAMES in this file."
    )


def test_core_tools_order_is_stable() -> None:
    """core_tools() list order must be stable across calls."""
    first = [t.name for t in core_tools()]
    second = [t.name for t in core_tools()]
    assert first == second, "core_tools() returned different order on two calls"


def test_core_tools_count() -> None:
    """core_tools() must return exactly the expected number of tools."""
    assert len(core_tools()) == len(EXPECTED_TOOL_NAMES)
