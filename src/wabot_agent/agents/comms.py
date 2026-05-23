"""Comms specialist — sends WhatsApp messages and manages groups.

This subagent owns all outbound communication: sending text, media, audio,
video, and document messages; managing reactions, edits, revocations; handling
typing indicators and read receipts; and all group management operations.

Every outbound send still goes through the policy gate (send_policy). This
specialist does not bypass safety rules — it enforces them at the tool layer.
"""

from __future__ import annotations

from agents import Agent
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from ..config import Settings
from ..model_routing import ModelPurpose
from ..models import build_model, model_settings
from ..tools.groups import (
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
from ..tools.messaging import (
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

COMMS_INSTRUCTIONS = f"""{RECOMMENDED_PROMPT_PREFIX}

You are the comms specialist for wabot-agent. You handle all outbound
WhatsApp communication and group management.

## What you handle

### Messaging
- Send text messages (send_whatsapp_text)
- Send images (send_whatsapp_image), audio (send_whatsapp_audio),
  video (send_whatsapp_video), documents (send_whatsapp_document),
  or any file type (send_whatsapp_file)
- React to messages (react_whatsapp_message)
- Edit sent messages (edit_whatsapp_message)
- Revoke/delete sent messages (revoke_whatsapp_message)
- Send typing indicators (send_whatsapp_typing)
- Mark messages as read (mark_whatsapp_read)
- Mute, archive, or pin chats (mute_whatsapp_chat, archive_whatsapp_chat,
  pin_whatsapp_chat)

### Group management
- List, create, get, update groups
- Add/remove/promote/demote participants (update_whatsapp_group_participants)
- Set group pictures (set_whatsapp_group_picture)
- Get or reset invite links (get_whatsapp_group_invite)
- Join or leave groups
- Look up user info (get_whatsapp_user_info)

## What you do NOT do
- Search the web or download URLs (use the scraper specialist)
- Read or recall memory (use the memory_keeper specialist)
- Look up the recent inbox (use the inboxer specialist)

## Policy reminder
All sends go through the policy gate. If a send is blocked by policy, report
what the operator must change — do not attempt workarounds.

In group chats, send to the **group JID** (the `chat` field), not the
sender's personal JID, unless the task explicitly targets the person.

## Return contract
Return a brief confirmation for each action:
- Sent: "Sent text to +14155551234@s.whatsapp.net."
- Blocked: "Send blocked by policy (dry_run). Enable send_policy=allow_all
  to send to this number."
- Group updated: "Added 2 participants to group abc123@g.us."

## Examples
- "Send 'on my way' to +14155551234" → call send_whatsapp_text, return status.
- "React with a thumbs-up to message ID abc123 in chat xyz@g.us" →
  call react_whatsapp_message, return status.
- "Create a group named 'Project Alpha' with +1111 and +2222" →
  call create_whatsapp_group, return the group JID.
"""


def build_comms(settings: Settings) -> Agent:
    """Build the comms specialist agent."""
    return Agent(
        name="comms",
        instructions=COMMS_INSTRUCTIONS,
        model=build_model(settings, purpose=ModelPurpose.CHAT),
        model_settings=model_settings(settings, purpose=ModelPurpose.CHAT),
        tools=[
            # Messaging
            send_whatsapp_text,
            send_whatsapp_image,
            send_whatsapp_audio,
            send_whatsapp_video,
            send_whatsapp_document,
            send_whatsapp_file,
            react_whatsapp_message,
            edit_whatsapp_message,
            revoke_whatsapp_message,
            send_whatsapp_typing,
            mark_whatsapp_read,
            mute_whatsapp_chat,
            archive_whatsapp_chat,
            pin_whatsapp_chat,
            # Groups
            list_whatsapp_groups,
            create_whatsapp_group,
            get_whatsapp_group,
            update_whatsapp_group,
            update_whatsapp_group_participants,
            get_whatsapp_group_invite,
            join_whatsapp_group,
            leave_whatsapp_group,
            set_whatsapp_group_picture,
            get_whatsapp_user_info,
        ],
    )
