"""WebResearchRepo — web_research_jobs CRUD, claim, complete, fail_stale."""
from __future__ import annotations

import uuid
from typing import Any

from ..redaction import redact
from ._helpers import now_iso


class WebResearchRepo:
    def __init__(self, connect_fn: Any) -> None:
        self._connect = connect_fn

    def count_web_research_jobs(
        self,
        *,
        requester_jid: str | None = None,
        status: str | None = None,
    ) -> int:
        query = "select count(*) as n from web_research_jobs where 1=1"
        params: list[Any] = []
        if requester_jid:
            query += " and requester_jid = ?"
            params.append(requester_jid)
        if status:
            query += " and status = ?"
            params.append(status)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return int(row["n"]) if row else 0

    def create_web_research_job(
        self,
        *,
        requester_jid: str,
        prompt: str,
        title: str | None = None,
        output_format: str = "markdown",
        schema_json: str | None = None,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        created_at = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                insert into web_research_jobs (
                    id, requester_jid, title, prompt, output_format, schema_json,
                    status, created_at, started_at, completed_at, result_path,
                    preview, error, duration_ms, steps
                ) values (?, ?, ?, ?, ?, ?, 'pending', ?, null, null, null, null, null, null, null)
                """,
                (
                    job_id,
                    requester_jid,
                    title,
                    prompt,
                    output_format,
                    schema_json,
                    created_at,
                ),
            )
        return {
            "created": True,
            "id": job_id,
            "status": "pending",
            "title": title,
            "output_format": output_format,
        }

    def get_web_research_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from web_research_jobs where id = ?", (job_id,)
            ).fetchone()
        return redact(dict(row)) if row else None

    def list_web_research_jobs(
        self,
        *,
        requester_jid: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = "select * from web_research_jobs where 1=1"
        params: list[Any] = []
        if requester_jid:
            query += " and requester_jid = ?"
            params.append(requester_jid)
        if status:
            query += " and status = ?"
            params.append(status)
        query += " order by created_at desc limit ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [redact(dict(row)) for row in rows]

    def cancel_web_research_job(
        self, job_id: str, *, requester_jid: str | None = None
    ) -> dict[str, Any]:
        with self._connect() as conn:
            if requester_jid:
                cur = conn.execute(
                    """
                    update web_research_jobs
                    set status = 'cancelled', completed_at = ?
                    where id = ? and requester_jid = ? and status = 'pending'
                    """,
                    (now_iso(), job_id, requester_jid),
                )
            else:
                cur = conn.execute(
                    """
                    update web_research_jobs
                    set status = 'cancelled', completed_at = ?
                    where id = ? and status = 'pending'
                    """,
                    (now_iso(), job_id),
                )
        return {"cancelled": cur.rowcount == 1, "id": job_id}

    def claim_pending_web_research_job(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select id from web_research_jobs
                where status = 'pending'
                order by created_at asc
                limit 1
                """
            ).fetchone()
            if row is None:
                return None
            started = now_iso()
            cur = conn.execute(
                """
                update web_research_jobs
                set status = 'running', started_at = ?
                where id = ? and status = 'pending'
                """,
                (started, row["id"]),
            )
            if cur.rowcount != 1:
                return None
            full = conn.execute(
                "select * from web_research_jobs where id = ?", (row["id"],)
            ).fetchone()
        return dict(full) if full else None

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
        status = "failed" if error else "completed"
        with self._connect() as conn:
            conn.execute(
                """
                update web_research_jobs
                set status = ?, completed_at = ?, result_path = ?, preview = ?,
                    error = ?, duration_ms = ?, steps = ?
                where id = ?
                """,
                (
                    status,
                    now_iso(),
                    result_path,
                    preview,
                    redact(error) if error else None,
                    duration_ms,
                    steps,
                    job_id,
                ),
            )

    def fail_stale_web_research_jobs(self, *, stale_before: str) -> list[str]:
        """Mark running jobs started before stale_before as failed."""
        failed_ids: list[str] = []
        with self._connect() as conn:
            rows = conn.execute(
                """
                select id from web_research_jobs
                where status = 'running' and started_at is not null and started_at < ?
                """,
                (stale_before,),
            ).fetchall()
            for row in rows:
                cur = conn.execute(
                    """
                    update web_research_jobs
                    set status = 'failed', completed_at = ?, error = 'stale_timeout'
                    where id = ? and status = 'running'
                    """,
                    (now_iso(), row["id"]),
                )
                if cur.rowcount == 1:
                    failed_ids.append(str(row["id"]))
        return failed_ids
