from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.db import Database

log = logging.getLogger("agent_orchestrator.store.jobs")


def _is_unique_violation(exc: Exception) -> bool:
    """True for a UNIQUE constraint breach across sqlite/postgres drivers."""
    text = str(exc).lower()
    return "unique constraint failed" in text or "duplicate key value" in text


@dataclass
class Job:
    id: str
    name: str
    prompt_template: str
    schedule: str | None
    model: str
    memory_doc: str
    memory_version: int
    enabled: bool
    created_at: float
    updated_at: float
    notify_email: str = ""
    slack_on_success: bool = False
    slack_on_failure: bool = True
    model_mode: str = "inherit"
    runner: str = "llm"
    herdr_agent_kind: str = ""
    herdr_agent_name: str = ""
    herdr_cwd: str = ""
    herdr_workspace_label: str = ""
    herdr_extra_args: str = "[]"

    def to_dict(self, include_memory: bool = True) -> dict[str, Any]:
        import json as _json

        try:
            extra = _json.loads(self.herdr_extra_args or "[]")
            if not isinstance(extra, list):
                extra = []
        except Exception:
            extra = []
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "prompt_template": self.prompt_template,
            "schedule": self.schedule,
            "model": self.model,
            "model_mode": self.model_mode or "inherit",
            "runner": (self.runner or "llm").lower(),
            "herdr": {
                "agent_kind": self.herdr_agent_kind or "",
                "agent_name": self.herdr_agent_name or "",
                "cwd": self.herdr_cwd or "",
                "workspace_label": self.herdr_workspace_label or "",
                "extra_args": extra,
            },
            "memory_version": self.memory_version,
            "enabled": self.enabled,
            "notify_email": self.notify_email or "",
            "slack_on_success": bool(self.slack_on_success),
            "slack_on_failure": bool(self.slack_on_failure),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_memory:
            data["memory_doc"] = self.memory_doc
        return data


@dataclass
class Run:
    id: str
    job_id: str
    status: str
    started_at: float
    finished_at: float | None
    input_snapshot: str | None
    result: str | None
    raw_response: str | None
    error: str | None
    tokens_in: int | None
    tokens_out: int | None
    idempotency_key: str | None
    llm_provider: str | None = None
    model_requested: str | None = None
    model_effective: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "input_snapshot": self.input_snapshot,
            "result": self.result,
            "error": self.error,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "idempotency_key": self.idempotency_key,
            "llm_provider": self.llm_provider,
            "model_requested": self.model_requested,
            "model_effective": self.model_effective,
        }


def _job_from_row(row: Any) -> Job:
    keys = row.keys()
    return Job(
        id=row["id"],
        name=row["name"],
        prompt_template=row["prompt_template"],
        schedule=row["schedule"],
        model=row["model"],
        memory_doc=row["memory_doc"] or "",
        memory_version=int(row["memory_version"] or 0),
        enabled=bool(row["enabled"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        notify_email=(row["notify_email"] if "notify_email" in keys else "") or "",
        slack_on_success=bool(row["slack_on_success"]) if "slack_on_success" in keys else False,
        slack_on_failure=bool(row["slack_on_failure"]) if "slack_on_failure" in keys else True,
        model_mode=(row["model_mode"] if "model_mode" in keys else "inherit") or "inherit",
        runner=(row["runner"] if "runner" in keys else "llm") or "llm",
        herdr_agent_kind=(row["herdr_agent_kind"] if "herdr_agent_kind" in keys else "") or "",
        herdr_agent_name=(row["herdr_agent_name"] if "herdr_agent_name" in keys else "") or "",
        herdr_cwd=(row["herdr_cwd"] if "herdr_cwd" in keys else "") or "",
        herdr_workspace_label=(row["herdr_workspace_label"] if "herdr_workspace_label" in keys else "") or "",
        herdr_extra_args=(row["herdr_extra_args"] if "herdr_extra_args" in keys else "[]") or "[]",
    )


def _run_from_row(row: Any) -> Run:
    keys = row.keys()
    return Run(
        id=row["id"],
        job_id=row["job_id"],
        status=row["status"],
        started_at=float(row["started_at"]),
        finished_at=float(row["finished_at"]) if row["finished_at"] is not None else None,
        input_snapshot=row["input_snapshot"],
        result=row["result"],
        raw_response=row["raw_response"],
        error=row["error"],
        tokens_in=row["tokens_in"],
        tokens_out=row["tokens_out"],
        idempotency_key=row["idempotency_key"],
        llm_provider=(row["llm_provider"] if "llm_provider" in keys else None),
        model_requested=(row["model_requested"] if "model_requested" in keys else None),
        model_effective=(row["model_effective"] if "model_effective" in keys else None),
    )


class JobStore:
    def __init__(self, db: Database, memory_versions_keep: int = 20) -> None:
        self.db = db
        self.memory_versions_keep = memory_versions_keep

    async def list_jobs(self) -> list[Job]:
        cur = await self.db.conn.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        rows = await cur.fetchall()
        return [_job_from_row(r) for r in rows]

    async def get_job(self, job_id: str) -> Job | None:
        cur = await self.db.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cur.fetchone()
        return _job_from_row(row) if row else None

    async def create_job(
        self,
        *,
        name: str,
        prompt_template: str,
        model: str,
        schedule: str | None = None,
        memory_doc: str = "",
        enabled: bool = True,
        notify_email: str = "",
        slack_on_success: bool = False,
        slack_on_failure: bool = True,
        model_mode: str = "inherit",
        runner: str = "llm",
        herdr_agent_kind: str = "",
        herdr_agent_name: str = "",
        herdr_cwd: str = "",
        herdr_workspace_label: str = "",
        herdr_extra_args: str | list | None = None,
        job_id: str | None = None,
    ) -> Job:
        import json as _json

        now = time.time()
        jid = job_id or str(uuid.uuid4())
        mode = (model_mode or "inherit").strip().lower() or "inherit"
        runner_v = (runner or "llm").strip().lower() or "llm"
        if isinstance(herdr_extra_args, list):
            extra_s = _json.dumps(herdr_extra_args)
        elif isinstance(herdr_extra_args, str) and herdr_extra_args.strip():
            extra_s = herdr_extra_args
        else:
            extra_s = "[]"
        await self.db.conn.execute(
            """
            INSERT INTO jobs (
                id, name, prompt_template, schedule, model, memory_doc,
                memory_version, enabled, created_at, updated_at, notify_email,
                slack_on_success, slack_on_failure, model_mode,
                runner, herdr_agent_kind, herdr_agent_name, herdr_cwd,
                herdr_workspace_label, herdr_extra_args
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                jid,
                name,
                prompt_template,
                schedule,
                model,
                memory_doc or "",
                1 if enabled else 0,
                now,
                now,
                (notify_email or "").strip(),
                1 if slack_on_success else 0,
                1 if slack_on_failure else 0,
                mode,
                runner_v,
                herdr_agent_kind or "",
                herdr_agent_name or "",
                herdr_cwd or "",
                herdr_workspace_label or "",
                extra_s,
            ),
        )
        if memory_doc:
            await self.db.conn.execute(
                """
                INSERT INTO memory_versions (job_id, version, body, created_at)
                VALUES (?, 0, ?, ?)
                """,
                (jid, memory_doc, now),
            )
        await self.db.conn.commit()
        job = await self.get_job(jid)
        assert job is not None
        return job

    async def update_memory(self, job_id: str, memory_doc: str) -> Job:
        """Write short working memory only on explicit success path. Always versions."""
        from app.memory.sanitize import sanitize_text

        memory_doc = sanitize_text(memory_doc or "")
        conn = self.db.conn
        await conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cur.fetchone()
            if row is None:
                await conn.execute("ROLLBACK")
                raise KeyError(f"job not found: {job_id}")
            new_version = int(row["memory_version"] or 0) + 1
            now = time.time()
            await conn.execute(
                """
                UPDATE jobs
                SET memory_doc = ?, memory_version = ?, updated_at = ?
                WHERE id = ?
                """,
                (memory_doc, new_version, now, job_id),
            )
            await conn.execute(
                """
                INSERT INTO memory_versions (job_id, version, body, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (job_id, new_version, memory_doc, now),
            )
            # prune old versions
            await conn.execute(
                """
                DELETE FROM memory_versions
                WHERE job_id = ?
                  AND version < (
                    SELECT MAX(version) - ? FROM memory_versions WHERE job_id = ?
                  )
                """,
                (job_id, self.memory_versions_keep - 1, job_id),
            )
            await conn.execute("COMMIT")
        except Exception:
            try:
                await conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        job = await self.get_job(job_id)
        assert job is not None
        return job

    async def find_run_by_idempotency(self, job_id: str, key: str) -> Run | None:
        if not key:
            return None
        cur = await self.db.conn.execute(
            """
            SELECT * FROM runs
            WHERE job_id = ? AND idempotency_key = ?
            ORDER BY started_at DESC LIMIT 1
            """,
            (job_id, key),
        )
        row = await cur.fetchone()
        return _run_from_row(row) if row else None

    async def create_run(
        self,
        *,
        job_id: str,
        status: str,
        input_snapshot: str | None = None,
        idempotency_key: str | None = None,
        run_id: str | None = None,
    ) -> Run:
        rid = run_id or str(uuid.uuid4())
        now = time.time()
        try:
            await self.db.conn.execute(
                """
                INSERT INTO runs (
                    id, job_id, status, started_at, input_snapshot, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (rid, job_id, status, now, input_snapshot, idempotency_key),
            )
            await self.db.conn.commit()
        except Exception as exc:
            # Concurrent trigger lost the race against the partial unique index
            # idx_runs_idempotency: return the winner's run instead of crashing.
            if idempotency_key and _is_unique_violation(exc):
                existing = await self.find_run_by_idempotency(job_id, idempotency_key)
                if existing is not None:
                    return existing
            raise
        run = await self.get_run(rid)
        assert run is not None
        return run

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        result: str | None = None,
        raw_response: str | None = None,
        error: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        llm_provider: str | None = None,
        model_requested: str | None = None,
        model_effective: str | None = None,
    ) -> Run:
        now = time.time()
        await self.db.conn.execute(
            """
            UPDATE runs SET
                status = ?,
                finished_at = ?,
                result = ?,
                raw_response = ?,
                error = ?,
                tokens_in = ?,
                tokens_out = ?,
                llm_provider = COALESCE(?, llm_provider),
                model_requested = COALESCE(?, model_requested),
                model_effective = COALESCE(?, model_effective)
            WHERE id = ?
            """,
            (
                status,
                now,
                result,
                raw_response,
                error,
                tokens_in,
                tokens_out,
                llm_provider,
                model_requested,
                model_effective,
                run_id,
            ),
        )
        await self.db.conn.commit()
        run = await self.get_run(run_id)
        assert run is not None
        return run

    async def get_run(self, run_id: str) -> Run | None:
        cur = await self.db.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        row = await cur.fetchone()
        return _run_from_row(row) if row else None

    async def list_runs(self, job_id: str, limit: int = 50) -> list[Run]:
        cur = await self.db.conn.execute(
            """
            SELECT * FROM runs
            WHERE job_id = ?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (job_id, limit),
        )
        rows = await cur.fetchall()
        return [_run_from_row(r) for r in rows]

    async def last_run_any(self) -> Run | None:
        cur = await self.db.conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
        )
        row = await cur.fetchone()
        return _run_from_row(row) if row else None

    async def last_run_for_job(self, job_id: str) -> Run | None:
        cur = await self.db.conn.execute(
            """
            SELECT * FROM runs
            WHERE job_id = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (job_id,),
        )
        row = await cur.fetchone()
        return _run_from_row(row) if row else None

    async def update_job(
        self,
        job_id: str,
        *,
        name: str | None = None,
        prompt_template: str | None = None,
        model: str | None = None,
        schedule: str | None = None,
        enabled: bool | None = None,
        notify_email: str | None = None,
        slack_on_success: bool | None = None,
        slack_on_failure: bool | None = None,
        model_mode: str | None = None,
        runner: str | None = None,
        herdr_agent_kind: str | None = None,
        herdr_agent_name: str | None = None,
        herdr_cwd: str | None = None,
        herdr_workspace_label: str | None = None,
        herdr_extra_args: str | list | None = None,
        clear_schedule: bool = False,
    ) -> Job:
        import json as _json

        job = await self.get_job(job_id)
        if job is None:
            raise KeyError(f"job not found: {job_id}")
        now = time.time()
        new_name = name if name is not None else job.name
        new_prompt = prompt_template if prompt_template is not None else job.prompt_template
        new_model = model if model is not None else job.model
        if clear_schedule:
            new_schedule = None
        elif schedule is not None:
            new_schedule = schedule
        else:
            new_schedule = job.schedule
        new_enabled = job.enabled if enabled is None else enabled
        new_email = job.notify_email if notify_email is None else (notify_email or "").strip()
        new_ss = job.slack_on_success if slack_on_success is None else bool(slack_on_success)
        new_sf = job.slack_on_failure if slack_on_failure is None else bool(slack_on_failure)
        new_mode = job.model_mode if model_mode is None else (model_mode or "inherit").strip().lower()
        new_runner = job.runner if runner is None else (runner or "llm").strip().lower()
        new_kind = job.herdr_agent_kind if herdr_agent_kind is None else (herdr_agent_kind or "")
        new_aname = job.herdr_agent_name if herdr_agent_name is None else (herdr_agent_name or "")
        new_cwd = job.herdr_cwd if herdr_cwd is None else (herdr_cwd or "")
        new_label = (
            job.herdr_workspace_label
            if herdr_workspace_label is None
            else (herdr_workspace_label or "")
        )
        if herdr_extra_args is None:
            new_extra = job.herdr_extra_args or "[]"
        elif isinstance(herdr_extra_args, list):
            new_extra = _json.dumps(herdr_extra_args)
        else:
            new_extra = herdr_extra_args or "[]"
        await self.db.conn.execute(
            """
            UPDATE jobs
            SET name = ?, prompt_template = ?, model = ?, schedule = ?,
                enabled = ?, notify_email = ?, slack_on_success = ?, slack_on_failure = ?,
                model_mode = ?, runner = ?, herdr_agent_kind = ?, herdr_agent_name = ?,
                herdr_cwd = ?, herdr_workspace_label = ?, herdr_extra_args = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_name,
                new_prompt,
                new_model,
                new_schedule,
                1 if new_enabled else 0,
                new_email,
                1 if new_ss else 0,
                1 if new_sf else 0,
                new_mode,
                new_runner,
                new_kind,
                new_aname,
                new_cwd,
                new_label,
                new_extra,
                now,
                job_id,
            ),
        )
        await self.db.conn.commit()
        updated = await self.get_job(job_id)
        assert updated is not None
        return updated

    async def delete_job(self, job_id: str) -> bool:
        """Delete job definition but keep run history for the dashboard."""
        job = await self.get_job(job_id)
        if job is None:
            return False
        # Preserve runs: re-point to a tombstone name via jobs table removal
        # after detaching FK by temporarily disabling foreign keys.
        await self.db.conn.execute("PRAGMA foreign_keys=OFF")
        try:
            await self.db.conn.execute("DELETE FROM memory_versions WHERE job_id = ?", (job_id,))
            await self.db.conn.execute("DELETE FROM memory_log WHERE job_id = ?", (job_id,))
            await self.db.conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            await self.db.conn.commit()
        finally:
            await self.db.conn.execute("PRAGMA foreign_keys=ON")
        return True

    async def recent_runs(self, limit: int = 30) -> list[Run]:
        cur = await self.db.conn.execute(
            """
            SELECT * FROM runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        return [_run_from_row(r) for r in rows]

    async def list_job_names(self) -> dict[str, str]:
        cur = await self.db.conn.execute("SELECT id, name FROM jobs")
        rows = await cur.fetchall()
        return {r["id"]: r["name"] for r in rows}

    async def append_memory_log(
        self,
        job_id: str,
        *,
        kind: str,
        body: str,
        created_at: float | None = None,
    ) -> int:
        from app.memory.sanitize import sanitize_text

        ts = created_at if created_at is not None else time.time()
        clean = sanitize_text(body, max_chars=4000)
        cur = await self.db.conn.execute(
            """
            INSERT INTO memory_log (job_id, kind, body, created_at, compacted)
            VALUES (?, ?, ?, ?, 0)
            """,
            (job_id, kind or "note", clean, ts),
        )
        await self.db.conn.commit()
        return int(cur.lastrowid or 0)

    async def list_memory_log(self, job_id: str, limit: int = 40) -> list[dict]:
        from datetime import datetime, timezone

        cur = await self.db.conn.execute(
            """
            SELECT id, job_id, kind, body, created_at, compacted
            FROM memory_log
            WHERE job_id = ? AND compacted = 0
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (job_id, limit),
        )
        rows = await cur.fetchall()
        out: list[dict] = []
        for r in rows:
            ts = float(r["created_at"])
            label = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            out.append(
                {
                    "id": r["id"],
                    "job_id": r["job_id"],
                    "kind": r["kind"],
                    "body": r["body"],
                    "created_at": ts,
                    "created_label": label,
                    "compacted": bool(r["compacted"]),
                }
            )
        return out

    async def count_memory_log(self, job_id: str, *, active_only: bool = True) -> int:
        if active_only:
            cur = await self.db.conn.execute(
                "SELECT COUNT(*) AS c FROM memory_log WHERE job_id = ? AND compacted = 0",
                (job_id,),
            )
        else:
            cur = await self.db.conn.execute(
                "SELECT COUNT(*) AS c FROM memory_log WHERE job_id = ?",
                (job_id,),
            )
        row = await cur.fetchone()
        return int(row["c"] if row else 0)

    async def compact_memory_log(
        self,
        job_id: str,
        *,
        keep_recent: int = 20,
        compact_after: int = 50,
    ) -> bool:
        """When active log is large, fold older entries into one compaction note.

        Safe: never deletes without writing a replacement summary first.
        Only touches this job_id.
        """
        from app.memory.sanitize import sanitize_text, summarize_for_log

        active = await self.count_memory_log(job_id, active_only=True)
        if active < compact_after:
            return False

        cur = await self.db.conn.execute(
            """
            SELECT id, kind, body, created_at
            FROM memory_log
            WHERE job_id = ? AND compacted = 0
            ORDER BY created_at DESC, id DESC
            """,
            (job_id,),
        )
        rows = await cur.fetchall()
        if len(rows) <= keep_recent:
            return False

        recent = rows[:keep_recent]
        older = rows[keep_recent:]
        # Build summary from older entries (oldest first for readability)
        chunks: list[str] = []
        for r in reversed(older):
            chunks.append(f"- [{r['kind']}] {summarize_for_log(r['body'], max_chars=240)}")
        summary = sanitize_text(
            "Compacted older memory log entries:\n" + "\n".join(chunks),
            max_chars=6000,
        )

        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            # Mark older as compacted only after we can insert summary
            await self.db.conn.execute(
                """
                INSERT INTO memory_log (job_id, kind, body, created_at, compacted)
                VALUES (?, 'compaction', ?, ?, 0)
                """,
                (job_id, summary, time.time()),
            )
            older_ids = [r["id"] for r in older]
            if older_ids:
                placeholders = ",".join("?" * len(older_ids))
                await self.db.conn.execute(
                    f"UPDATE memory_log SET compacted = 1 WHERE id IN ({placeholders})",
                    older_ids,
                )
            # Ensure recent stay active
            recent_ids = [r["id"] for r in recent]
            if recent_ids:
                placeholders = ",".join("?" * len(recent_ids))
                await self.db.conn.execute(
                    f"UPDATE memory_log SET compacted = 0 WHERE id IN ({placeholders})",
                    recent_ids,
                )
            await self.db.conn.execute("COMMIT")
        except Exception:
            try:
                await self.db.conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        return True

    async def update_memory_safe(self, job_id: str, memory_doc: str) -> "Job":
        """Update short memory only if new content is non-empty after sanitize."""
        from app.memory.sanitize import sanitize_text

        clean = sanitize_text(memory_doc, max_chars=None)
        if not clean.strip():
            job = await self.get_job(job_id)
            if job is None:
                raise KeyError(f"job not found: {job_id}")
            return job
        return await self.update_memory(job_id, clean)


