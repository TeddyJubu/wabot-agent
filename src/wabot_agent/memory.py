from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
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
                """
            )
            self._ensure_column(
                conn, "processed_messages", "status", "text not null default 'done'"
            )
            self._ensure_column(conn, "processed_messages", "run_id", "text")
            self._ensure_column(conn, "processed_messages", "error", "text")

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
        return {
            "contact_facts": facts,
            "agent_notes": notes,
            "runs": runs,
            "processed_messages": processed,
        }
