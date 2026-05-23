# ruff: noqa: I001
"""wabot_agent.tools package — split from the monolithic tools.py (ME-2).

Public surface is intentionally identical to the old tools.py so all callers
(agent.py, api/__init__.py, and tests) import without changes.

The imports below are grouped by tool family with comment headers so the
layout matches MASTER ME-2's mapping at a glance. The file-level `noqa: I001`
above keeps ruff from alphabetising the whole block (which would dissolve
the grouping). Unused-import (F401) noise is silenced by adding the
re-exported names to ``__all__`` at the bottom of the file.
"""

from __future__ import annotations

from typing import Any

# --- back-compat symbols that callers import directly ---
from ._common import (
    RuntimeContext,
    _apply_send_policy_gate,
    _chat_send_or_block,
    _dry_run_block,
    _inbound_reply_destination,
    _invoke_chat_message_action,
    _invoke_chat_state_action,
    _is_owner_session,
    _is_send_allowed,
    _maybe_auto_track_outbound,
    _media_path_allowed,
    _mem0_user_id,
    _mem0_user_ids,
    _owner_progress_allowed,
    _requester_jid,
    _resolve_progress_destination,
    _send_whatsapp_media,
    _wabot_ready_or_block,
)

# --- health ---
from .health import wabot_health

# --- inbox ---
from .inbox import (
    _inbox_payload,
    get_last_whatsapp_inbound_message,
    list_whatsapp_inbound_messages,
    lookup_whatsapp_contacts,
)

# --- groups (includes list_whatsapp_groups + group management + user-info) ---
from .groups import (
    create_whatsapp_group,
    get_whatsapp_group,
    get_whatsapp_group_invite,
    get_whatsapp_user_info,
    join_whatsapp_group,
    leave_whatsapp_group,
    list_whatsapp_groups,
    set_whatsapp_group_picture,
    update_whatsapp_group,
    update_whatsapp_group_participants,
)

# --- messaging (send / react / edit / revoke / typing / read / chat-state) ---
from .messaging import (
    archive_whatsapp_chat,
    edit_whatsapp_message,
    mark_whatsapp_read,
    mute_whatsapp_chat,
    pin_whatsapp_chat,
    react_whatsapp_message,
    revoke_whatsapp_message,
    send_whatsapp_audio,
    send_whatsapp_document,
    send_whatsapp_file,
    send_whatsapp_image,
    send_whatsapp_text,
    send_whatsapp_typing,
    send_whatsapp_video,
)

# --- media ---
from .media import (
    download_whatsapp_media,
    download_whatsapp_profile_picture,
    fetch_url_to_media,
    process_vps_file,
    process_whatsapp_attachment,
)

# --- memory ---
from .memory import (
    add_mem0_memory,
    mem0_status,
    recall_agent_notes,
    recall_contact_memory,
    remember_agent_note,
    remember_contact_fact,
    search_mem0_memories,
)

# --- mem0 helpers re-exported from mem0_store so tests can mock.patch them
#     at the `wabot_agent.tools` namespace (pre-split layout). The
#     `tools/memory.py` tool functions also look these up via the package
#     module so patches at `wabot_agent.tools.search_memories_sync` actually
#     intercept the call the tool makes. ---
from ..mem0_store import add_memory_sync, search_memories_sync

# --- skills ---
from .skills import list_local_skills, read_local_skill

# --- web ---
from .web import (
    cancel_web_research,
    get_web_research_status,
    list_web_research_jobs,
    search_images,
    search_web,
    start_web_research,
    web_research_health,
)

# --- scheduling ---
from .scheduling import (
    cancel_reminder,
    create_reminder,
    get_outbound_task_status,
    list_outbound_tasks,
    list_reminders,
    track_outbound_conversation,
)

# Also re-export _parse_due_at_iso — it's imported in tests/test_reminders.py
from .scheduling import _parse_due_at_iso

# --- progress ---
from .progress import (
    maybe_send_task_started_ack,
    report_task_step_complete,
    send_task_plan,
    send_task_progress,
)


def core_tools() -> list[Any]:
    """Return the canonical list of agent tools in registration order.

    The order is preserved from the pre-split tools.py to avoid breaking
    any tests that assert positional behaviour.
    """
    return [
        wabot_health,
        list_whatsapp_inbound_messages,
        get_last_whatsapp_inbound_message,
        lookup_whatsapp_contacts,
        list_whatsapp_groups,
        mark_whatsapp_read,
        send_whatsapp_typing,
        send_whatsapp_text,
        send_whatsapp_image,
        download_whatsapp_media,
        process_vps_file,
        process_whatsapp_attachment,
        search_web,
        search_images,
        fetch_url_to_media,
        send_whatsapp_file,
        send_whatsapp_document,
        send_whatsapp_audio,
        send_whatsapp_video,
        react_whatsapp_message,
        edit_whatsapp_message,
        revoke_whatsapp_message,
        create_whatsapp_group,
        get_whatsapp_group,
        get_whatsapp_group_invite,
        join_whatsapp_group,
        update_whatsapp_group,
        update_whatsapp_group_participants,
        leave_whatsapp_group,
        set_whatsapp_group_picture,
        mute_whatsapp_chat,
        archive_whatsapp_chat,
        pin_whatsapp_chat,
        get_whatsapp_user_info,
        download_whatsapp_profile_picture,
        recall_contact_memory,
        remember_contact_fact,
        recall_agent_notes,
        remember_agent_note,
        list_local_skills,
        read_local_skill,
        create_reminder,
        list_reminders,
        cancel_reminder,
        track_outbound_conversation,
        get_outbound_task_status,
        list_outbound_tasks,
        web_research_health,
        start_web_research,
        get_web_research_status,
        list_web_research_jobs,
        cancel_web_research,
        send_task_plan,
        report_task_step_complete,
        send_task_progress,
        mem0_status,
        search_mem0_memories,
        add_mem0_memory,
    ]


__all__ = [
    # Registration function
    "core_tools",
    # Back-compat critical exports
    "RuntimeContext",
    "maybe_send_task_started_ack",
    "_is_send_allowed",
    # All public tool functions
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
    # Private helpers re-exported for back-compat with test imports
    "_parse_due_at_iso",
    "_mem0_user_id",
    "_mem0_user_ids",
    "_inbox_payload",
    # Send-policy / chat-state / progress helpers re-exported for callers
    # that import from `wabot_agent.tools` (api/__init__.py, auto_reply,
    # web_research, tests/test_owner_policy.py and friends).
    "_apply_send_policy_gate",
    "_chat_send_or_block",
    "_dry_run_block",
    "_inbound_reply_destination",
    "_invoke_chat_message_action",
    "_invoke_chat_state_action",
    "_is_owner_session",
    "_maybe_auto_track_outbound",
    "_media_path_allowed",
    "_owner_progress_allowed",
    "_requester_jid",
    "_resolve_progress_destination",
    "_send_whatsapp_media",
    "_wabot_ready_or_block",
    # Mem0 sync helpers — tests mock.patch these at the `wabot_agent.tools`
    # namespace; tools/memory.py uses late lookup via the package module so
    # patches actually intercept the call.
    "add_memory_sync",
    "search_memories_sync",
]
