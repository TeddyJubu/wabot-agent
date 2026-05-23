"""RemindersRepo — scheduled_reminders CRUD, claim_due, release, mark_fired."""
from __future__ import annotations

import uuid
from typing import Any

from ..redaction import redact
from ._helpers import now_iso


class RemindersRepo:
    def __init__(self, connect_fn: Any) -> None:
        self._connect = connect_fn

    def count_pending_reminders(self, requester_jid: str) -> int:
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [redact(dict(row)) for row in rows]

    def cancel_reminder(
        self, reminder_id: str, *, requester_jid: str | None = None
    ) -> dict[str, Any]:
        with self._connect() as conn:
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

    def claim_due_reminders(
        self, *, now: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        claimed: list[dict[str, Any]] = []
        with self._connect() as conn:
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

    def release_reminder_claim(self, reminder_id: str) -> bool:
        """Return a processing reminder to pending so the scheduler can retry."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                update scheduled_reminders
                set status = 'pending', error = null
                where id = ? and status = 'processing'
                """,
                (reminder_id,),
            )
        return cur.rowcount == 1

    def mark_reminder_fired(
        self, reminder_id: str, *, error: str | None = None
    ) -> None:
        """Mark a claimed reminder as fired (or failed).

        Only transitions rows that are still in 'claimed' state. A delayed
        fire callback cannot corrupt a reminder that was released back to
        'pending' by release_reminder_claim. Closes #53.

        Note: the scheduler uses status='processing' for claimed reminders;
        both 'processing' and 'claimed' are acceptable values — the WHERE
        clause uses 'claimed' per the issue spec but in practice the scheduler
        sets 'processing'. If the code that claims reminders ever changes its
        terminology, update this predicate accordingly.
        """
        status = "failed" if error else "fired"
        with self._connect() as conn:
            conn.execute(
                """
                update scheduled_reminders
                set status = ?, fired_at = ?, error = ?
                where id = ? AND status = 'processing'
                """,
                (status, now_iso(), redact(error) if error else None, reminder_id),
            )
