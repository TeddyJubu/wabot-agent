"""InboxRepo — inbound_messages, processed_messages, claim/complete/fail/bulk."""
from __future__ import annotations

import sqlite3
from typing import Any

from ..redaction import redact
from ._helpers import now_iso


class InboxRepo:
    def __init__(self, connect_fn: Any) -> None:
        self._connect = connect_fn

    # ------------------------------------------------------------------
    # processed_messages (idempotency)
    # ------------------------------------------------------------------

    def is_processed(self, message_id: str) -> bool:
        with self._connect() as conn:
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
        """Atomically claim a message for processing.

        Uses INSERT ... ON CONFLICT(message_id) DO UPDATE ... WHERE status = 'failed'
        so two concurrent workers racing on the same message_id resolve at the
        SQLite layer: exactly one INSERT wins (rowcount == 1) or the conditional
        UPDATE fires for the failed-retry path, while the loser's UPDATE touches
        zero rows (rowcount == 0). Rows already at 'processing' or 'done' are
        never re-claimed. Closes #51.
        """
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO processed_messages
                    (message_id, sender, processed_at, status, run_id, error)
                VALUES (?, ?, ?, 'processing', NULL, NULL)
                ON CONFLICT(message_id) DO UPDATE SET
                    sender       = excluded.sender,
                    processed_at = excluded.processed_at,
                    status       = 'processing',
                    run_id       = NULL,
                    error        = NULL
                WHERE processed_messages.status = 'failed'
                """,
                (message_id, sender, now_iso()),
            )
            return cur.rowcount > 0

    def complete_message(self, message_id: str, run_id: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                update processed_messages
                set processed_at = ?, status = 'done', run_id = ?, error = null
                where message_id = ?
                """,
                (now_iso(), run_id, message_id),
            )

    def fail_message(self, message_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                update processed_messages
                set processed_at = ?, status = 'failed', error = ?
                where message_id = ?
                """,
                (now_iso(), redact(error), message_id),
            )

    # ------------------------------------------------------------------
    # inbound_messages
    # ------------------------------------------------------------------

    def record_inbound(self, inbound: Any) -> None:
        safe_text = str(redact(inbound.text))
        with self._connect() as conn:
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

    def bulk_record_inbound(self, messages: list[Any]) -> dict[str, Any]:
        """Persist history-sync rows without marking them processed for auto-reply."""
        if not messages:
            return {"stored": 0, "count": 0}
        rows = [
            (
                inbound.id,
                inbound.sender,
                inbound.chat,
                str(redact(inbound.text)),
                inbound.push_name,
                1 if inbound.is_group else 0,
                inbound.timestamp or now_iso(),
                inbound.media_kind,
                inbound.media_mime,
                inbound.media_filename,
                1 if inbound.has_media else 0,
            )
            for inbound in messages
        ]
        sql = """
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
        """
        with self._connect() as conn:
            conn.executemany(sql, rows)
        return {"stored": len(rows), "count": len(messages)}

    def recent_inbound(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
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
        return [_inbound_row_dict(row) for row in rows]

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
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return _inbound_row_dict(row) if row else None


def _inbound_row_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["id"] = payload.pop("message_id", None)
    payload["has_media"] = bool(payload.get("has_media"))
    return redact(payload)
