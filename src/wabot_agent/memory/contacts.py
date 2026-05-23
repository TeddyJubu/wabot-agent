"""ContactFactsRepo — contact_facts, agent_notes, list_contacts_with_facts."""
from __future__ import annotations

from typing import Any

from ..redaction import looks_sensitive
from ._helpers import now_iso


class ContactFactsRepo:
    def __init__(self, connect_fn: Any) -> None:
        self._connect = connect_fn

    # ------------------------------------------------------------------
    # contact_facts
    # ------------------------------------------------------------------

    def remember_contact_fact(
        self, contact: str, key: str, value: str, source: str
    ) -> dict[str, Any]:
        if looks_sensitive(value) or looks_sensitive(key):
            return {"stored": False, "reason": "Refused to store sensitive-looking material."}
        with self._connect() as conn:
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
        with self._connect() as conn:
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

    def get_contact_fact(self, contact: str, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select value from contact_facts
                where contact = ? and key = ?
                """,
                (contact, key),
            ).fetchone()
        if row is None:
            return None
        value = str(row["value"] or "").strip()
        return value or None

    def delete_contact_fact(self, contact: str, key: str) -> dict[str, Any]:
        with self._connect() as conn:
            cur = conn.execute(
                "delete from contact_facts where contact = ? and key = ?",
                (contact, key),
            )
        return {"deleted": cur.rowcount == 1, "contact": contact, "key": key}

    def list_contacts_with_facts(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select contact, count(*) as fact_count, max(updated_at) as updated_at
                from contact_facts
                group by contact
                order by updated_at desc
                """
            ).fetchall()
        return [
            {
                "contact": row["contact"],
                "fact_count": int(row["fact_count"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # agent_notes
    # ------------------------------------------------------------------

    def remember_agent_note(self, key: str, value: str) -> dict[str, Any]:
        if looks_sensitive(value) or looks_sensitive(key):
            return {"stored": False, "reason": "Refused to store sensitive-looking material."}
        with self._connect() as conn:
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
        with self._connect() as conn:
            rows = conn.execute(
                "select key, value, updated_at from agent_notes order by updated_at desc limit 100"
            ).fetchall()
        return [dict(row) for row in rows]

    def agent_notes_max_updated_at(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "select max(updated_at) as m from agent_notes"
            ).fetchone()
        if row is None or row["m"] is None:
            return ""
        return str(row["m"])

    def delete_agent_note(self, key: str) -> dict[str, Any]:
        with self._connect() as conn:
            cur = conn.execute("delete from agent_notes where key = ?", (key,))
        return {"deleted": cur.rowcount == 1, "key": key}
