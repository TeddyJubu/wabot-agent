from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .recipients import recipients_match
from .redaction import looks_sensitive, redact


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


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


class MemoryStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            # WAL is enabled once at _init_db (persisted in the DB file).
            # These two pragmas are per-connection: synchronous=NORMAL pairs with
            # WAL for fast commits with crash-safe durability, and busy_timeout
            # lets writers wait briefly instead of failing with 'database is locked'
            # when the dashboard SSE/runs reader races with run_agent writes.
            conn.execute("pragma synchronous=NORMAL")
            conn.execute("pragma busy_timeout=5000")
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            # Persisted on the DB file; survives subsequent connections.
            conn.execute("pragma journal_mode=WAL")
            conn.executescript(
                """
                create table if not exists contact_facts (
                    contact text not null,
                    key text not null,
                    value text not null,
                    source text not null,
                    updated_at text not null,
                    primary key (contact, key)
                );
                create table if not exists agent_notes (
                    key text primary key,
                    value text not null,
                    updated_at text not null
                );
                create table if not exists processed_messages (
                    message_id text primary key,
                    sender text,
                    processed_at text not null,
                    status text not null default 'done',
                    run_id text,
                    error text
                );
                create table if not exists runs (
                    run_id text primary key,
                    sender text,
                    user_input text,
                    final_output text,
                    created_at text not null
                );
                create table if not exists tool_events (
                    id integer primary key autoincrement,
                    run_id text,
                    name text not null,
                    payload text not null,
                    created_at text not null
                );
                create table if not exists inbound_messages (
                    message_id text primary key,
                    sender text not null,
                    chat text,
                    text text not null,
                    push_name text,
                    is_group integer not null default 0,
                    received_at text not null
                );
                create table if not exists session_summaries (
                    session_id text primary key,
                    summary text not null,
                    updated_at text not null
                );
                create table if not exists scheduled_reminders (
                    id text primary key,
                    requester_jid text not null,
                    target_jid text,
                    message text not null,
                    due_at text not null,
                    status text not null default 'pending',
                    created_at text not null,
                    fired_at text,
                    error text,
                    idempotency_key text unique
                );
                create index if not exists idx_scheduled_reminders_status_due
                    on scheduled_reminders (status, due_at);
                create table if not exists outbound_tasks (
                    id text primary key,
                    owner_jid text not null,
                    target_jid text not null,
                    chat_jid text not null,
                    prompt_summary text,
                    status text not null default 'awaiting_reply',
                    sent_message_id text,
                    sent_at text not null,
                    reply_message_id text,
                    reply_text text,
                    reply_at text,
                    notify_owner integer not null default 1,
                    expires_at text not null
                );
                create index if not exists idx_outbound_tasks_status_expires
                    on outbound_tasks (status, expires_at);
                """
            )
            self._ensure_column(
                conn, "processed_messages", "status", "text not null default 'done'"
            )
            self._ensure_column(conn, "processed_messages", "run_id", "text")
            self._ensure_column(conn, "processed_messages", "error", "text")
            self._ensure_column(conn, "inbound_messages", "media_kind", "text")
            self._ensure_column(conn, "inbound_messages", "media_mime", "text")
            self._ensure_column(conn, "inbound_messages", "media_filename", "text")
            self._ensure_column(conn, "inbound_messages", "has_media", "integer not null default 0")

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        rows = conn.execute(f"pragma table_info({table})").fetchall()
        if column not in {row["name"] for row in rows}:
            conn.execute(f"alter table {table} add column {column} {definition}")

    def is_processed(self, message_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                select 1 from processed_messages
                where message_id = ? and status in ('processing', 'done')
                """,
                (message_id,),
            ).fetchone()
            return row is not None

    def mark_processed(self, message_id: str, sender: str) -> None:
        if self.claim_message(message_id, sender):
            self.complete_message(message_id, run_id=None)

    def claim_message(self, message_id: str, sender: str) -> bool:
        with self.connect() as conn:
            existing = conn.execute(
                """
                select status from processed_messages where message_id = ?
                """,
                (message_id,),
            ).fetchone()
            if existing and existing["status"] in {"processing", "done"}:
                return False
            if existing and existing["status"] == "failed":
                conn.execute(
                    """
                    update processed_messages
                    set sender = ?, processed_at = ?, status = 'processing',
                        run_id = null, error = null
                    where message_id = ?
                    """,
                    (sender, now_iso(), message_id),
                )
                return True
            conn.execute(
                """
                insert into processed_messages (message_id, sender, processed_at, status)
                values (?, ?, ?, 'processing')
                """,
                (message_id, sender, now_iso()),
            )
            return True

    def complete_message(self, message_id: str, run_id: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                update processed_messages
                set processed_at = ?, status = 'done', run_id = ?, error = null
                where message_id = ?
                """,
                (now_iso(), run_id, message_id),
            )

    def fail_message(self, message_id: str, error: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                update processed_messages
                set processed_at = ?, status = 'failed', error = ?
                where message_id = ?
                """,
                (now_iso(), redact(error), message_id),
            )

    def remember_contact_fact(
        self, contact: str, key: str, value: str, source: str
    ) -> dict[str, Any]:
        if looks_sensitive(value) or looks_sensitive(key):
            return {"stored": False, "reason": "Refused to store sensitive-looking material."}
        with self.connect() as conn:
            conn.execute(
                """
                insert into contact_facts (contact, key, value, source, updated_at)
                values (?, ?, ?, ?, ?)
                on conflict(contact, key) do update set
                  value = excluded.value,
                  source = excluded.source,
                  updated_at = excluded.updated_at
                """,
                (contact, key, value, source, now_iso()),
            )
        return {"stored": True, "contact": contact, "key": key}

    def recall_contact(self, contact: str) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select key, value, source, updated_at
                from contact_facts
                where contact = ?
                order by updated_at desc
                limit 50
                """,
                (contact,),
            ).fetchall()
        return {
            "contact": contact,
            "facts": [
                {
                    "key": row["key"],
                    "value": row["value"],
                    "source": row["source"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ],
        }

    def remember_agent_note(self, key: str, value: str) -> dict[str, Any]:
        if looks_sensitive(value) or looks_sensitive(key):
            return {"stored": False, "reason": "Refused to store sensitive-looking material."}
        with self.connect() as conn:
            conn.execute(
                """
                insert into agent_notes (key, value, updated_at)
                values (?, ?, ?)
                on conflict(key) do update set
                  value = excluded.value,
                  updated_at = excluded.updated_at
                """,
                (key, value, now_iso()),
            )
        return {"stored": True, "key": key}

    def agent_notes(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "select key, value, updated_at from agent_notes order by updated_at desc limit 100"
            ).fetchall()
        return [dict(row) for row in rows]

    def bulk_record_inbound(self, messages: list[InboundMessage]) -> dict[str, Any]:
        """Persist history-sync rows without marking them processed for auto-reply."""
        stored = 0
        for inbound in messages:
            self.record_inbound(inbound)
            stored += 1
        return {"stored": stored, "count": len(messages)}

    def record_inbound(self, inbound: InboundMessage) -> None:
        safe_text = str(redact(inbound.text))
        with self.connect() as conn:
            conn.execute(
                """
                insert into inbound_messages (
                    message_id, sender, chat, text, push_name, is_group, received_at,
                    media_kind, media_mime, media_filename, has_media
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(message_id) do update set
                  sender = excluded.sender,
                  chat = excluded.chat,
                  text = excluded.text,
                  push_name = excluded.push_name,
                  is_group = excluded.is_group,
                  received_at = excluded.received_at,
                  media_kind = excluded.media_kind,
                  media_mime = excluded.media_mime,
                  media_filename = excluded.media_filename,
                  has_media = excluded.has_media
                """,
                (
                    inbound.id,
                    inbound.sender,
                    inbound.chat,
                    safe_text,
                    inbound.push_name,
                    1 if inbound.is_group else 0,
                    inbound.timestamp or now_iso(),
                    inbound.media_kind,
                    inbound.media_mime,
                    inbound.media_filename,
                    1 if inbound.has_media else 0,
                ),
            )

    def recent_inbound(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select message_id, sender, chat, text, push_name, is_group, received_at,
                       media_kind, media_mime, media_filename, has_media
                from inbound_messages
                order by received_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [self._inbound_row_dict(row) for row in rows]

    def last_inbound(self, contact: str | None = None) -> dict[str, Any] | None:
        query = """
            select message_id, sender, chat, text, push_name, is_group, received_at,
                   media_kind, media_mime, media_filename, has_media
            from inbound_messages
        """
        params: tuple[Any, ...]
        if contact:
            query += " where sender = ? or chat = ?"
            params = (contact, contact, 1)
        else:
            params = (1,)
        query += " order by received_at desc limit ?"
        with self.connect() as conn:
            row = conn.execute(query, params).fetchone()
        return self._inbound_row_dict(row) if row else None

    def _inbound_row_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["id"] = payload.pop("message_id", None)
        payload["has_media"] = bool(payload.get("has_media"))
        return redact(payload)

    def record_run(
        self, run_id: str, sender: str | None, user_input: str, final_output: str
    ) -> None:
        safe_input = str(redact(user_input))
        safe_output = str(redact(final_output))
        with self.connect() as conn:
            conn.execute(
                """
                insert or replace into runs (run_id, sender, user_input, final_output, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (run_id, sender, safe_input, safe_output, now_iso()),
            )

    def get_session_summary(self, session_id: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "select summary from session_summaries where session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        summary = str(row["summary"]).strip()
        return summary or None

    def save_session_summary(self, session_id: str, summary: str) -> None:
        text = summary.strip()
        if not text:
            return
        with self.connect() as conn:
            conn.execute(
                """
                insert into session_summaries (session_id, summary, updated_at)
                values (?, ?, ?)
                on conflict(session_id) do update set
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
                """,
                (session_id, text, now_iso()),
            )

    def record_tool_event(self, run_id: str, name: str, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into tool_events (run_id, name, payload, created_at)
                values (?, ?, ?, ?)
                """,
                (run_id, name, json.dumps(redact(payload), sort_keys=True), now_iso()),
            )

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select run_id, sender, user_input, final_output, created_at
                from runs
                order by created_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [redact(dict(row)) for row in rows]

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            facts = conn.execute("select count(*) from contact_facts").fetchone()[0]
            notes = conn.execute("select count(*) from agent_notes").fetchone()[0]
            runs = conn.execute("select count(*) from runs").fetchone()[0]
            processed = conn.execute("select count(*) from processed_messages").fetchone()[0]
            inbound = conn.execute("select count(*) from inbound_messages").fetchone()[0]
            tool_events = conn.execute("select count(*) from tool_events").fetchone()[0]
        return {
            "contact_facts": facts,
            "agent_notes": notes,
            "runs": runs,
            "processed_messages": processed,
            "inbound_messages": inbound,
            "tool_events": tool_events,
        }

    def prune_audit_tables(
        self,
        *,
        max_inbound: int,
        max_runs: int,
        max_tool_events: int,
    ) -> dict[str, int]:
        """Delete oldest audit rows beyond configured caps (contact facts untouched)."""
        deleted: dict[str, int] = {
            "inbound_messages": 0,
            "runs": 0,
            "tool_events": 0,
        }
        with self.connect() as conn:
            inbound_count = conn.execute("select count(*) from inbound_messages").fetchone()[0]
            if max_inbound > 0 and inbound_count > max_inbound:
                excess = inbound_count - max_inbound
                cur = conn.execute(
                    """
                    delete from inbound_messages
                    where message_id in (
                        select message_id from inbound_messages
                        order by received_at asc
                        limit ?
                    )
                    """,
                    (excess,),
                )
                deleted["inbound_messages"] = cur.rowcount

            runs_count = conn.execute("select count(*) from runs").fetchone()[0]
            if max_runs > 0 and runs_count > max_runs:
                excess = runs_count - max_runs
                cur = conn.execute(
                    """
                    delete from runs
                    where run_id in (
                        select run_id from runs
                        order by created_at asc
                        limit ?
                    )
                    """,
                    (excess,),
                )
                deleted["runs"] = cur.rowcount

            events_count = conn.execute("select count(*) from tool_events").fetchone()[0]
            if max_tool_events > 0 and events_count > max_tool_events:
                excess = events_count - max_tool_events
                cur = conn.execute(
                    """
                    delete from tool_events
                    where id in (
                        select id from tool_events
                        order by id asc
                        limit ?
                    )
                    """,
                    (excess,),
                )
                deleted["tool_events"] = cur.rowcount
        return deleted

    def count_pending_reminders(self, requester_jid: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                select count(*) from scheduled_reminders
                where requester_jid = ? and status = 'pending'
                """,
                (requester_jid,),
            ).fetchone()
        return int(row[0]) if row else 0

    def create_reminder(
        self,
        *,
        requester_jid: str,
        message: str,
        due_at: str,
        target_jid: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        reminder_id = str(uuid.uuid4())
        created_at = now_iso()
        with self.connect() as conn:
            if idempotency_key:
                existing = conn.execute(
                    """
                    select id, status, due_at, target_jid
                    from scheduled_reminders
                    where idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    return {
                        "created": False,
                        "id": existing["id"],
                        "status": existing["status"],
                        "due_at": existing["due_at"],
                        "target_jid": existing["target_jid"],
                        "reason": "idempotency_key_exists",
                    }
            conn.execute(
                """
                insert into scheduled_reminders (
                    id, requester_jid, target_jid, message, due_at, status,
                    created_at, fired_at, error, idempotency_key
                ) values (?, ?, ?, ?, ?, 'pending', ?, null, null, ?)
                """,
                (
                    reminder_id,
                    requester_jid,
                    target_jid,
                    message,
                    due_at,
                    created_at,
                    idempotency_key,
                ),
            )
        return {
            "created": True,
            "id": reminder_id,
            "status": "pending",
            "due_at": due_at,
            "target_jid": target_jid or requester_jid,
        }

    def list_reminders(
        self,
        *,
        requester_jid: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = """
            select id, requester_jid, target_jid, message, due_at, status,
                   created_at, fired_at, error
            from scheduled_reminders
            where 1=1
        """
        params: list[Any] = []
        if requester_jid:
            query += " and requester_jid = ?"
            params.append(requester_jid)
        if status:
            query += " and status = ?"
            params.append(status)
        query += " order by due_at asc limit ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [redact(dict(row)) for row in rows]

    def cancel_reminder(self, reminder_id: str, *, requester_jid: str | None = None) -> dict[str, Any]:
        with self.connect() as conn:
            if requester_jid:
                cur = conn.execute(
                    """
                    update scheduled_reminders
                    set status = 'cancelled'
                    where id = ? and requester_jid = ? and status = 'pending'
                    """,
                    (reminder_id, requester_jid),
                )
            else:
                cur = conn.execute(
                    """
                    update scheduled_reminders
                    set status = 'cancelled'
                    where id = ? and status = 'pending'
                    """,
                    (reminder_id,),
                )
        return {"cancelled": cur.rowcount == 1, "id": reminder_id}

    def claim_due_reminders(self, *, now: str, limit: int = 20) -> list[dict[str, Any]]:
        claimed: list[dict[str, Any]] = []
        with self.connect() as conn:
            rows = conn.execute(
                """
                select id from scheduled_reminders
                where status = 'pending' and due_at <= ?
                order by due_at asc
                limit ?
                """,
                (now, limit),
            ).fetchall()
            for row in rows:
                cur = conn.execute(
                    """
                    update scheduled_reminders
                    set status = 'processing'
                    where id = ? and status = 'pending'
                    """,
                    (row["id"],),
                )
                if cur.rowcount != 1:
                    continue
                full = conn.execute(
                    """
                    select id, requester_jid, target_jid, message, due_at, status,
                           created_at, fired_at, error
                    from scheduled_reminders where id = ?
                    """,
                    (row["id"],),
                ).fetchone()
                if full is not None:
                    claimed.append(dict(full))
        return claimed

    def mark_reminder_fired(self, reminder_id: str, *, error: str | None = None) -> None:
        status = "failed" if error else "fired"
        with self.connect() as conn:
            conn.execute(
                """
                update scheduled_reminders
                set status = ?, fired_at = ?, error = ?
                where id = ?
                """,
                (status, now_iso(), redact(error) if error else None, reminder_id),
            )

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
        task_id = str(uuid.uuid4())
        sent_at = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                insert into outbound_tasks (
                    id, owner_jid, target_jid, chat_jid, prompt_summary, status,
                    sent_message_id, sent_at, reply_message_id, reply_text, reply_at,
                    notify_owner, expires_at
                ) values (?, ?, ?, ?, ?, 'awaiting_reply', ?, ?, null, null, null, ?, ?)
                """,
                (
                    task_id,
                    owner_jid,
                    target_jid,
                    chat_jid,
                    prompt_summary,
                    sent_message_id,
                    sent_at,
                    1 if notify_owner else 0,
                    expires_at,
                ),
            )
        return {"created": True, "id": task_id, "status": "awaiting_reply", "expires_at": expires_at}

    def get_outbound_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "select * from outbound_tasks where id = ?", (task_id,)
            ).fetchone()
        return redact(dict(row)) if row else None

    def list_outbound_tasks(
        self,
        *,
        owner_jid: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = "select * from outbound_tasks where 1=1"
        params: list[Any] = []
        if owner_jid:
            query += " and owner_jid = ?"
            params.append(owner_jid)
        if status:
            query += " and status = ?"
            params.append(status)
        query += " order by sent_at desc limit ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [redact(dict(row)) for row in rows]

    def find_pending_outbound_task(
        self, *, sender: str, chat: str | None, is_group: bool
    ) -> dict[str, Any] | None:
        now = now_iso()
        with self.connect() as conn:
            rows = conn.execute(
                """
                select * from outbound_tasks
                where status = 'awaiting_reply' and expires_at > ?
                order by sent_at desc
                """,
                (now,),
            ).fetchall()
        chat_jid = (chat or sender).strip()
        for row in rows:
            task = dict(row)
            if is_group:
                if not recipients_match(str(task["chat_jid"]), chat_jid):
                    continue
                target = str(task["target_jid"])
                if "@g.us" not in target.lower() and not recipients_match(target, sender):
                    continue
            else:
                if not recipients_match(str(task["target_jid"]), sender):
                    continue
                if task.get("chat_jid") and not recipients_match(
                    str(task["chat_jid"]), chat_jid
                ):
                    continue
            return redact(task)
        return None

    def complete_outbound_task(
        self,
        task_id: str,
        *,
        reply_text: str,
        reply_message_id: str | None = None,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            cur = conn.execute(
                """
                update outbound_tasks
                set status = 'completed',
                    reply_text = ?,
                    reply_message_id = ?,
                    reply_at = ?
                where id = ? and status = 'awaiting_reply'
                """,
                (redact(reply_text), reply_message_id, now_iso(), task_id),
            )
        return {"completed": cur.rowcount == 1, "id": task_id}

    def expire_outbound_tasks(self, *, now: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select * from outbound_tasks
                where status = 'awaiting_reply' and expires_at <= ?
                """,
                (now,),
            ).fetchall()
            expired: list[dict[str, Any]] = []
            for row in rows:
                cur = conn.execute(
                    """
                    update outbound_tasks
                    set status = 'expired'
                    where id = ? and status = 'awaiting_reply'
                    """,
                    (row["id"],),
                )
                if cur.rowcount == 1:
                    expired.append(dict(row))
        return [redact(task) for task in expired]

    @staticmethod
    def outbound_expires_at(*, days: int) -> str:
        return (datetime.now(UTC) + timedelta(days=max(1, days))).isoformat()
