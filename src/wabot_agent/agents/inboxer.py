"""Inboxer specialist — reads the inbox, looks up contacts, lists skills, checks health.

This subagent is read-only. It surfaces information about the current WhatsApp
state: recent inbound messages, contact lookups, available local skills, and
wabot daemon health. It does not send messages or modify any state.
"""

from __future__ import annotations

from agents import Agent
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from ..config import Settings
from ..model_routing import ModelPurpose
from ..models import build_model, model_settings
from ..tools.health import wabot_health
from ..tools.inbox import (
    get_last_whatsapp_inbound_message,
    list_whatsapp_inbound_messages,
    lookup_whatsapp_contacts,
)
from ..tools.skills import list_local_skills, read_local_skill

INBOXER_INSTRUCTIONS = f"""{RECOMMENDED_PROMPT_PREFIX}

You are the inboxer specialist for wabot-agent. You surface information about
the current WhatsApp state — recent messages, contacts, installed skills, and
daemon health. You are read-only.

## What you handle

### Inbox
- List recent inbound WhatsApp messages (list_whatsapp_inbound_messages)
- Get the last inbound message from a specific sender
  (get_last_whatsapp_inbound_message)

### Contacts
- Look up WhatsApp contact info by phone number or JID
  (lookup_whatsapp_contacts)

### Skills
- List installed local skills (list_local_skills)
- Read a specific skill's definition (read_local_skill)

### Health
- Check whether wabot daemon is running and WhatsApp is linked
  (wabot_health)

## What you do NOT do
- Send messages (use the comms specialist)
- Write to memory (use the memory_keeper specialist)
- Search the web (use the scraper specialist)
- Create reminders or track tasks (use the scheduler specialist)

## Return contract
Return a concise, structured summary:
- Inbox: list of messages with sender, timestamp, and text snippet.
- Contact lookup: name, JID, profile status.
- Health: wabot status, WhatsApp link state.
- Skills: list of skill names and brief descriptions.

## Examples
- "Who messaged in the last hour?" → call list_whatsapp_inbound_messages,
  return the relevant entries.
- "Look up +14155551234" → call lookup_whatsapp_contacts, return the contact
  details.
- "Is wabot healthy?" → call wabot_health, return the status summary.
- "What skills are installed?" → call list_local_skills, return the list.
"""


def build_inboxer(settings: Settings) -> Agent:
    """Build the inboxer specialist agent."""
    return Agent(
        name="inboxer",
        instructions=INBOXER_INSTRUCTIONS,
        model=build_model(settings, purpose=ModelPurpose.CHAT),
        model_settings=model_settings(settings, purpose=ModelPurpose.CHAT),
        tools=[
            # Inbox
            list_whatsapp_inbound_messages,
            get_last_whatsapp_inbound_message,
            lookup_whatsapp_contacts,
            # Skills
            list_local_skills,
            read_local_skill,
            # Health
            wabot_health,
        ],
    )
