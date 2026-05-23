"""Scheduler specialist — manages reminders, outbound tracking, and task progress.

This subagent owns all time-sensitive and progress-related operations:
creating and cancelling WhatsApp reminders, tracking outbound follow-up
conversations, and reporting multi-step task progress updates.

It does NOT send general-purpose messages or fetch from the web.
"""

from __future__ import annotations

from agents import Agent
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from ..config import Settings
from ..model_routing import ModelPurpose
from ..models import build_model, model_settings
from ..tools.progress import (
    report_task_step_complete,
    send_task_plan,
    send_task_progress,
)
from ..tools.scheduling import (
    cancel_reminder,
    create_reminder,
    get_outbound_task_status,
    list_outbound_tasks,
    list_reminders,
    track_outbound_conversation,
)

SCHEDULER_INSTRUCTIONS = f"""{RECOMMENDED_PROMPT_PREFIX}

You are the scheduler specialist for wabot-agent. You manage time-based
reminders, outbound conversation tracking, and multi-step task progress.

## What you handle

### Reminders
- Create WhatsApp reminders (create_reminder) — use ISO 8601 for due_at
- List pending reminders (list_reminders)
- Cancel a reminder (cancel_reminder)

### Outbound task tracking
- Track an outbound conversation awaiting a reply (track_outbound_conversation)
- List all tracked outbound tasks (list_outbound_tasks)
- Check the status of a specific outbound task (get_outbound_task_status)

### Multi-step task progress
- Post a task plan to WhatsApp (send_task_plan) — call before heavy work
- Report a step complete (report_task_step_complete) — after each step
- Post a progress update (send_task_progress) — for long silent stretches

## What you do NOT do
- Send general-purpose messages (use the comms specialist)
- Search the web (use the scraper specialist)
- Read or recall memory (use the memory_keeper specialist)

## Return contract
Return a structured confirmation:
- Reminder created: "Reminder set for 2026-06-01T09:00:00Z: 'Call John.'"
- Outbound tracked: "Tracking outbound to +1234 (task ID abc)."
- Progress posted: "Task plan sent with 4 steps."

## Examples
- "Remind me to follow up with Alice at 3pm tomorrow" → call create_reminder
  with due_at in ISO format, return confirmation.
- "List all pending reminders" → call list_reminders, return the list.
- "Track the conversation with +447700900123 about the invoice" →
  call track_outbound_conversation, return the task ID.
"""


def build_scheduler(settings: Settings) -> Agent:
    """Build the scheduler specialist agent."""
    return Agent(
        name="scheduler",
        instructions=SCHEDULER_INSTRUCTIONS,
        model=build_model(settings, purpose=ModelPurpose.CHAT),
        model_settings=model_settings(settings, purpose=ModelPurpose.CHAT),
        tools=[
            # Scheduling
            create_reminder,
            list_reminders,
            cancel_reminder,
            track_outbound_conversation,
            get_outbound_task_status,
            list_outbound_tasks,
            # Progress
            send_task_plan,
            report_task_step_complete,
            send_task_progress,
        ],
    )
