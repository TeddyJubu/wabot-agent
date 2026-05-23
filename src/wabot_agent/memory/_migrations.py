"""Schema initialisation and additive column migrations for the memory package."""
from __future__ import annotations

import sqlite3


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes (idempotent via CREATE IF NOT EXISTS)."""
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
        create table if not exists web_research_jobs (
            id text primary key,
            requester_jid text not null,
            title text,
            prompt text not null,
            output_format text not null default 'markdown',
            schema_json text,
            status text not null default 'pending',
            created_at text not null,
            started_at text,
            completed_at text,
            result_path text,
            preview text,
            error text,
            duration_ms integer,
            steps integer
        );
        create index if not exists idx_web_research_jobs_status
            on web_research_jobs (status, created_at);
        """
    )
    ensure_column(conn, "processed_messages", "status", "text not null default 'done'")
    ensure_column(conn, "processed_messages", "run_id", "text")
    ensure_column(conn, "processed_messages", "error", "text")
    ensure_column(conn, "inbound_messages", "media_kind", "text")
    ensure_column(conn, "inbound_messages", "media_mime", "text")
    ensure_column(conn, "inbound_messages", "media_filename", "text")
    ensure_column(
        conn, "inbound_messages", "has_media", "integer not null default 0"
    )
    conn.commit()


def ensure_column(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    """Add *column* to *table* if it doesn't already exist (additive only)."""
    rows = conn.execute(f"pragma table_info({table})").fetchall()
    if column not in {row["name"] for row in rows}:
        conn.execute(f"alter table {table} add column {column} {definition}")
