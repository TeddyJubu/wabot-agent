"""wabot_agent.memory package — split from the monolithic memory.py (ME-3).

Public surface is identical to the pre-split memory.py so all callers
(agent.py, api/, tools/, auto_reply.py, auth.py, context_management.py)
continue to work without changes.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._db import get_thread_connection
from ._helpers import now_iso
from ._migrations import ensure_column, init_schema
from ._seed import import_mcp_config_file, seed_builtin_subagents, seed_tools_catalog
from .audit import AuditRepo
from .contacts import ContactFactsRepo
from .inbox import InboxRepo
from .outbound import OutboundTasksRepo
from .reminders import RemindersRepo
from .research import WebResearchRepo

if TYPE_CHECKING:
    from ..config import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclass and helper functions that callers import directly
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InboundMessage:
    id: str
    sender: str
    chat: str | None
    text: str
    timestamp: str | None = None
    push_name: str | None = None
    is_group: bool = False
    media_kind: str | None = None
    media_mime: str | None = None
    media_filename: str | None = None
    has_media: bool = False


def canonical_whatsapp_id(value: str | None) -> str:
    """Stable identity for WhatsApp JIDs that may include device suffixes.

    WhatsApp can send the same one-to-one contact as both ``123@lid`` and
    ``123:31@lid``.  For memory/session continuity those should be one person.
    Group JIDs are left unchanged.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "@" not in raw:
        return raw
    local, domain = raw.split("@", 1)
    domain_lower = domain.lower()
    if domain_lower in {"lid", "s.whatsapp.net"} and ":" in local:
        local = local.split(":", 1)[0]
    return f"{local}@{domain}"


def inbound_person_memory_id(inbound: InboundMessage) -> str:
    """Stable person scope for Mem0 and SQLite facts."""
    if not inbound.is_group and inbound.chat:
        return canonical_whatsapp_id(inbound.chat)
    return canonical_whatsapp_id(inbound.sender)


def inbound_chat_session_id(inbound: InboundMessage) -> str:
    """Per-thread agent session id (group chat JID in groups, stable DM chat JID in DMs)."""
    if inbound.is_group:
        return canonical_whatsapp_id(inbound.chat or inbound.sender)
    return canonical_whatsapp_id(inbound.chat or inbound.sender)


def inbound_memory_user_ids(inbound: InboundMessage) -> list[str]:
    """Mem0 recall ids: always the sender; also the group JID in group chats."""
    person = inbound_person_memory_id(inbound)
    if inbound.is_group:
        chat = inbound_chat_session_id(inbound)
        if chat and chat != person:
            return [person, chat]
    return [person]


def inbound_memory_contact_id(inbound: InboundMessage) -> str:
    """Scope for durable memory tools (sender JID, not group chat)."""
    return inbound_person_memory_id(inbound)


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class MemoryStore:
    """Thin facade that composes the domain repos.

    Every public method name is identical to the pre-split monolith so all
    callers keep working without changes.
    """

    def __init__(self, path: Path | str, settings: Settings | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # Initialise schema on the main-thread connection, then run seeds.
        with self._lock:
            conn = get_thread_connection(self.path, self._lock)
            init_schema(conn)
            conn.commit()

            try:
                seed_builtin_subagents(conn)
                conn.commit()
            except KeyboardInterrupt:
                raise
            except Exception:
                logger.warning("seed_builtin_subagents failed; skipping", exc_info=True)

            try:
                seed_tools_catalog(conn)
                conn.commit()
            except KeyboardInterrupt:
                raise
            except Exception:
                logger.warning("seed_tools_catalog failed; skipping", exc_info=True)

            try:
                import_mcp_config_file(conn, settings)
                conn.commit()
            except KeyboardInterrupt:
                raise
            except Exception:
                logger.warning("import_mcp_config_file failed; skipping", exc_info=True)

        # Instantiate repos — each receives self.connect as its connection factory
        self._audit = AuditRepo(self.connect)
        self._contacts = ContactFactsRepo(self.connect)
        self._inbox = InboxRepo(self.connect)
        self._reminders = RemindersRepo(self.connect)
        self._outbound = OutboundTasksRepo(self.connect)
        self._research = WebResearchRepo(self.connect)

    # ------------------------------------------------------------------
    # Connection management (kept on the facade for context_management.py
    # and any caller that held a reference to store.connect)
    # ------------------------------------------------------------------

    def _thread_connection(self):  # type: ignore[return]
        return get_thread_connection(self.path, self._lock)

    @contextmanager
    def connect(self) -> Iterator[Any]:
        with self._lock:
            conn = get_thread_connection(self.path, self._lock)
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    # Keep for backward compat (test_memory.py calls store._ensure_column)
    def _ensure_column(
        self, conn: Any, table: str, column: str, definition: str
    ) -> None:
        ensure_column(conn, table, column, definition)

    # ------------------------------------------------------------------
    # Audit delegates
    # ------------------------------------------------------------------

    def record_run(
        self, run_id: str, sender: str | None, user_input: str, final_output: str
    ) -> None:
        return self._audit.record_run(run_id, sender, user_input, final_output)

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._audit.recent_runs(limit)

    def record_tool_event(self, run_id: str, name: str, payload: dict[str, Any]) -> None:
        return self._audit.record_tool_event(run_id, name, payload)

    def get_session_summary(self, session_id: str) -> str | None:
        return self._audit.get_session_summary(session_id)

    def save_session_summary(self, session_id: str, summary: str) -> None:
        return self._audit.save_session_summary(session_id, summary)

    def stats(self) -> dict[str, int]:
        return self._audit.stats()

    def prune_audit_tables(
        self,
        *,
        max_inbound: int,
        max_runs: int,
        max_tool_events: int,
    ) -> dict[str, int]:
        return self._audit.prune_audit_tables(
            max_inbound=max_inbound,
            max_runs=max_runs,
            max_tool_events=max_tool_events,
        )

    # ------------------------------------------------------------------
    # Contact / notes delegates
    # ------------------------------------------------------------------

    def remember_contact_fact(
        self, contact: str, key: str, value: str, source: str
    ) -> dict[str, Any]:
        return self._contacts.remember_contact_fact(contact, key, value, source)

    def recall_contact(self, contact: str) -> dict[str, Any]:
        return self._contacts.recall_contact(contact)

    def get_contact_fact(self, contact: str, key: str) -> str | None:
        return self._contacts.get_contact_fact(contact, key)

    def delete_contact_fact(self, contact: str, key: str) -> dict[str, Any]:
        return self._contacts.delete_contact_fact(contact, key)

    def list_contacts_with_facts(self) -> list[dict[str, Any]]:
        return self._contacts.list_contacts_with_facts()

    def remember_agent_note(self, key: str, value: str) -> dict[str, Any]:
        return self._contacts.remember_agent_note(key, value)

    def agent_notes(self) -> list[dict[str, Any]]:
        return self._contacts.agent_notes()

    def agent_notes_max_updated_at(self) -> str:
        return self._contacts.agent_notes_max_updated_at()

    def delete_agent_note(self, key: str) -> dict[str, Any]:
        return self._contacts.delete_agent_note(key)

    # ------------------------------------------------------------------
    # Inbox delegates
    # ------------------------------------------------------------------

    def is_processed(self, message_id: str) -> bool:
        return self._inbox.is_processed(message_id)

    def mark_processed(self, message_id: str, sender: str) -> None:
        return self._inbox.mark_processed(message_id, sender)

    def claim_message(self, message_id: str, sender: str) -> bool:
        return self._inbox.claim_message(message_id, sender)

    def complete_message(self, message_id: str, run_id: str | None) -> None:
        return self._inbox.complete_message(message_id, run_id)

    def fail_message(self, message_id: str, error: str) -> None:
        return self._inbox.fail_message(message_id, error)

    def record_inbound(self, inbound: InboundMessage) -> None:
        return self._inbox.record_inbound(inbound)

    def bulk_record_inbound(self, messages: list[InboundMessage]) -> dict[str, Any]:
        return self._inbox.bulk_record_inbound(messages)

    def recent_inbound(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._inbox.recent_inbound(limit)

    def last_inbound(self, contact: str | None = None) -> dict[str, Any] | None:
        return self._inbox.last_inbound(contact)

    # ------------------------------------------------------------------
    # Reminders delegates
    # ------------------------------------------------------------------

    def count_pending_reminders(self, requester_jid: str) -> int:
        return self._reminders.count_pending_reminders(requester_jid)

    def create_reminder(
        self,
        *,
        requester_jid: str,
        message: str,
        due_at: str,
        target_jid: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._reminders.create_reminder(
            requester_jid=requester_jid,
            message=message,
            due_at=due_at,
            target_jid=target_jid,
            idempotency_key=idempotency_key,
        )

    def list_reminders(
        self,
        *,
        requester_jid: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self._reminders.list_reminders(
            requester_jid=requester_jid,
            status=status,
            limit=limit,
        )

    def cancel_reminder(
        self, reminder_id: str, *, requester_jid: str | None = None
    ) -> dict[str, Any]:
        return self._reminders.cancel_reminder(reminder_id, requester_jid=requester_jid)

    def claim_due_reminders(self, *, now: str, limit: int = 20) -> list[dict[str, Any]]:
        return self._reminders.claim_due_reminders(now=now, limit=limit)

    def release_reminder_claim(self, reminder_id: str) -> bool:
        return self._reminders.release_reminder_claim(reminder_id)

    def mark_reminder_fired(self, reminder_id: str, *, error: str | None = None) -> None:
        return self._reminders.mark_reminder_fired(reminder_id, error=error)

    # ------------------------------------------------------------------
    # Outbound tasks delegates
    # ------------------------------------------------------------------

    def create_outbound_task(
        self,
        *,
        owner_jid: str,
        target_jid: str,
        chat_jid: str,
        prompt_summary: str | None = None,
        sent_message_id: str | None = None,
        notify_owner: bool = True,
        expires_at: str,
    ) -> dict[str, Any]:
        return self._outbound.create_outbound_task(
            owner_jid=owner_jid,
            target_jid=target_jid,
            chat_jid=chat_jid,
            prompt_summary=prompt_summary,
            sent_message_id=sent_message_id,
            notify_owner=notify_owner,
            expires_at=expires_at,
        )

    def get_outbound_task(self, task_id: str) -> dict[str, Any] | None:
        return self._outbound.get_outbound_task(task_id)

    def list_outbound_tasks(
        self,
        *,
        owner_jid: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self._outbound.list_outbound_tasks(
            owner_jid=owner_jid, status=status, limit=limit
        )

    def find_pending_outbound_task(
        self, *, sender: str, chat: str | None, is_group: bool
    ) -> dict[str, Any] | None:
        return self._outbound.find_pending_outbound_task(
            sender=sender, chat=chat, is_group=is_group
        )

    def complete_outbound_task(
        self,
        task_id: str,
        *,
        reply_text: str,
        reply_message_id: str | None = None,
    ) -> dict[str, Any]:
        return self._outbound.complete_outbound_task(
            task_id, reply_text=reply_text, reply_message_id=reply_message_id
        )

    def expire_outbound_tasks(self, *, now: str) -> list[dict[str, Any]]:
        return self._outbound.expire_outbound_tasks(now=now)

    @staticmethod
    def outbound_expires_at(*, days: int) -> str:
        return OutboundTasksRepo.outbound_expires_at(days=days)

    # ------------------------------------------------------------------
    # Web research delegates
    # ------------------------------------------------------------------

    def count_web_research_jobs(
        self,
        *,
        requester_jid: str | None = None,
        status: str | None = None,
    ) -> int:
        return self._research.count_web_research_jobs(
            requester_jid=requester_jid, status=status
        )

    def create_web_research_job(
        self,
        *,
        requester_jid: str,
        prompt: str,
        title: str | None = None,
        output_format: str = "markdown",
        schema_json: str | None = None,
    ) -> dict[str, Any]:
        return self._research.create_web_research_job(
            requester_jid=requester_jid,
            prompt=prompt,
            title=title,
            output_format=output_format,
            schema_json=schema_json,
        )

    def get_web_research_job(self, job_id: str) -> dict[str, Any] | None:
        return self._research.get_web_research_job(job_id)

    def list_web_research_jobs(
        self,
        *,
        requester_jid: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self._research.list_web_research_jobs(
            requester_jid=requester_jid, status=status, limit=limit
        )

    def cancel_web_research_job(
        self, job_id: str, *, requester_jid: str | None = None
    ) -> dict[str, Any]:
        return self._research.cancel_web_research_job(
            job_id, requester_jid=requester_jid
        )

    def claim_pending_web_research_job(self) -> dict[str, Any] | None:
        return self._research.claim_pending_web_research_job()

    def complete_web_research_job(
        self,
        job_id: str,
        *,
        error: str | None,
        result_path: str | None,
        preview: str | None,
        duration_ms: int | None = None,
        steps: int | None = None,
    ) -> None:
        return self._research.complete_web_research_job(
            job_id,
            error=error,
            result_path=result_path,
            preview=preview,
            duration_ms=duration_ms,
            steps=steps,
        )

    def fail_stale_web_research_jobs(self, *, stale_before: str) -> list[str]:
        return self._research.fail_stale_web_research_jobs(stale_before=stale_before)


# ---------------------------------------------------------------------------
# Public re-exports (match the pre-split surface exactly)
# ---------------------------------------------------------------------------

__all__ = [
    # Core classes
    "MemoryStore",
    "InboundMessage",
    # Helper functions (imported by tests and callers)
    "now_iso",
    "canonical_whatsapp_id",
    "inbound_person_memory_id",
    "inbound_chat_session_id",
    "inbound_memory_user_ids",
    "inbound_memory_contact_id",
    # Repo classes (available for advanced use / testing)
    "AuditRepo",
    "ContactFactsRepo",
    "InboxRepo",
    "OutboundTasksRepo",
    "RemindersRepo",
    "WebResearchRepo",
]
