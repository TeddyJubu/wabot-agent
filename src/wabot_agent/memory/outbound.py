"""OutboundTasksRepo — outbound_tasks CRUD, expire, complete, find_pending."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from ..recipients import recipients_match
from ..redaction import redact
from ._helpers import now_iso


class OutboundTasksRepo:
    def __init__(self, connect_fn: Any) -> None:
        self._connect = connect_fn

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
        with self._connect() as conn:
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
        return {
            "created": True,
            "id": task_id,
            "status": "awaiting_reply",
            "expires_at": expires_at,
        }

    def get_outbound_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
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
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [redact(dict(row)) for row in rows]

    def find_pending_outbound_task(
        self, *, sender: str, chat: str | None, is_group: bool
    ) -> dict[str, Any] | None:
        now = now_iso()
        chat_jid = (chat or sender).strip()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from outbound_tasks
                where status = 'awaiting_reply' and expires_at > ?
                  and (target_jid = ? or chat_jid = ?)
                order by sent_at desc
                """,
                (now, sender.strip(), chat_jid),
            ).fetchall()
        chat_jid = (chat or sender).strip()
        for row in rows:
            task = dict(row)
            if is_group:
                if not recipients_match(str(task["chat_jid"]), chat_jid):
                    continue
                target = str(task["target_jid"])
                if "@g.us" not in target.lower() and not recipients_match(
                    target, sender
                ):
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
        with self._connect() as conn:
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
        with self._connect() as conn:
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
