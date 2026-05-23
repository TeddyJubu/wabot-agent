"""AuditRepo — runs, tool_events, session_summaries, stats, pruning."""
from __future__ import annotations

import json
from typing import Any

from ..redaction import redact
from ._helpers import now_iso


class AuditRepo:
    def __init__(self, connect_fn: Any) -> None:
        self._connect = connect_fn

    # ------------------------------------------------------------------
    # runs
    # ------------------------------------------------------------------

    def record_run(
        self, run_id: str, sender: str | None, user_input: str, final_output: str
    ) -> None:
        safe_input = str(redact(user_input))
        safe_output = str(redact(final_output))
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into runs (run_id, sender, user_input, final_output, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (run_id, sender, safe_input, safe_output, now_iso()),
            )

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
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

    # ------------------------------------------------------------------
    # tool_events
    # ------------------------------------------------------------------

    def record_tool_event(
        self, run_id: str, name: str, payload: dict[str, Any]
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into tool_events (run_id, name, payload, created_at)
                values (?, ?, ?, ?)
                """,
                (run_id, name, json.dumps(redact(payload), sort_keys=True), now_iso()),
            )

    # ------------------------------------------------------------------
    # session_summaries
    # ------------------------------------------------------------------

    def get_session_summary(self, session_id: str) -> str | None:
        with self._connect() as conn:
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
        with self._connect() as conn:
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

    # ------------------------------------------------------------------
    # stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                select
                  (select count(*) from contact_facts) as contact_facts,
                  (select count(*) from agent_notes) as agent_notes,
                  (select count(*) from runs) as runs,
                  (select count(*) from processed_messages) as processed_messages,
                  (select count(*) from inbound_messages) as inbound_messages,
                  (select count(*) from tool_events) as tool_events
                """
            ).fetchone()
        return {
            "contact_facts": int(row["contact_facts"]),
            "agent_notes": int(row["agent_notes"]),
            "runs": int(row["runs"]),
            "processed_messages": int(row["processed_messages"]),
            "inbound_messages": int(row["inbound_messages"]),
            "tool_events": int(row["tool_events"]),
        }

    # ------------------------------------------------------------------
    # pruning
    # ------------------------------------------------------------------

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
        with self._connect() as conn:
            inbound_count = conn.execute(
                "select count(*) from inbound_messages"
            ).fetchone()[0]
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

            events_count = conn.execute(
                "select count(*) from tool_events"
            ).fetchone()[0]
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
