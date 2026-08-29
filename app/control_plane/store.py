from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.control_plane.models import (
    AuditEvent,
    LedgerEntry,
    Mission,
    WorkerBoundary,
)
from app.db import Database

CONTROL_PLANE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cp_missions (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL DEFAULT 'default',
    title TEXT NOT NULL,
    brief TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    budget_limit_cents INTEGER NOT NULL DEFAULT 0,
    spend_cents INTEGER NOT NULL DEFAULT 0,
    reserved_cents INTEGER NOT NULL DEFAULT 0,
    deadline_at REAL,
    ended_reason TEXT,
    worker_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    started_at REAL,
    ended_at REAL
);

CREATE INDEX IF NOT EXISTS idx_cp_missions_org_status
    ON cp_missions(org_id, status);

CREATE TABLE IF NOT EXISTS cp_ledger (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    FOREIGN KEY (mission_id) REFERENCES cp_missions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cp_ledger_mission
    ON cp_ledger(mission_id, created_at DESC);

CREATE TABLE IF NOT EXISTS cp_audit_events (
    id TEXT PRIMARY KEY,
    mission_id TEXT,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'control_plane',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cp_audit_mission
    ON cp_audit_events(mission_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cp_audit_type
    ON cp_audit_events(event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS cp_workers (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    status TEXT NOT NULL,
    isolation_mode TEXT NOT NULL DEFAULT 'logical',
    host_hint TEXT NOT NULL DEFAULT 'local-logical',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    terminated_at REAL,
    FOREIGN KEY (mission_id) REFERENCES cp_missions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cp_workers_mission
    ON cp_workers(mission_id, status);
"""


def _mission_from_row(row: Any) -> Mission:
    return Mission(
        id=row["id"],
        org_id=row["org_id"],
        title=row["title"],
        brief=row["brief"] or "",
        status=row["status"],
        budget_limit_cents=int(row["budget_limit_cents"] or 0),
        spend_cents=int(row["spend_cents"] or 0),
        reserved_cents=int(row["reserved_cents"] or 0),
        deadline_at=float(row["deadline_at"]) if row["deadline_at"] is not None else None,
        ended_reason=row["ended_reason"],
        worker_id=row["worker_id"],
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        started_at=float(row["started_at"]) if row["started_at"] is not None else None,
        ended_at=float(row["ended_at"]) if row["ended_at"] is not None else None,
    )


class ControlPlaneStore:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._ready = False

    async def ensure_schema(self) -> None:
        if self._ready:
            return
        await self.db.conn.executescript(CONTROL_PLANE_SCHEMA)
        await self.db.conn.commit()
        self._ready = True

    async def create_mission(
        self,
        *,
        title: str,
        brief: str = "",
        org_id: str = "default",
        budget_limit_cents: int = 0,
        deadline_at: float | None = None,
        mission_id: str | None = None,
    ) -> Mission:
        await self.ensure_schema()
        now = time.time()
        mid = mission_id or str(uuid.uuid4())
        await self.db.conn.execute(
            """
            INSERT INTO cp_missions (
                id, org_id, title, brief, status, budget_limit_cents,
                spend_cents, reserved_cents, deadline_at, ended_reason,
                worker_id, created_at, updated_at, started_at, ended_at
            ) VALUES (?, ?, ?, ?, 'draft', ?, 0, 0, ?, NULL, NULL, ?, ?, NULL, NULL)
            """,
            (
                mid,
                org_id or "default",
                title,
                brief or "",
                max(0, int(budget_limit_cents)),
                deadline_at,
                now,
                now,
            ),
        )
        await self.db.conn.commit()
        mission = await self.get_mission(mid)
        assert mission is not None
        return mission

    async def get_mission(self, mission_id: str) -> Mission | None:
        await self.ensure_schema()
        cur = await self.db.conn.execute(
            "SELECT * FROM cp_missions WHERE id = ?", (mission_id,)
        )
        row = await cur.fetchone()
        return _mission_from_row(row) if row else None

    async def list_missions(
        self, *, org_id: str | None = None, limit: int = 50
    ) -> list[Mission]:
        await self.ensure_schema()
        limit = max(1, min(int(limit), 200))
        if org_id:
            cur = await self.db.conn.execute(
                """
                SELECT * FROM cp_missions
                WHERE org_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (org_id, limit),
            )
        else:
            cur = await self.db.conn.execute(
                "SELECT * FROM cp_missions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cur.fetchall()
        return [_mission_from_row(r) for r in rows]

    async def update_mission_fields(
        self,
        mission_id: str,
        **fields: Any,
    ) -> Mission:
        await self.ensure_schema()
        allowed = {
            "status",
            "spend_cents",
            "reserved_cents",
            "ended_reason",
            "worker_id",
            "started_at",
            "ended_at",
            "budget_limit_cents",
            "deadline_at",
        }
        sets: list[str] = []
        vals: list[Any] = []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k} = ?")
            vals.append(v)
        if not sets:
            mission = await self.get_mission(mission_id)
            if mission is None:
                raise KeyError(mission_id)
            return mission
        sets.append("updated_at = ?")
        vals.append(time.time())
        vals.append(mission_id)
        await self.db.conn.execute(
            f"UPDATE cp_missions SET {', '.join(sets)} WHERE id = ?",
            vals,
        )
        await self.db.conn.commit()
        mission = await self.get_mission(mission_id)
        if mission is None:
            raise KeyError(mission_id)
        return mission

    async def add_ledger_entry(
        self,
        *,
        mission_id: str,
        kind: str,
        amount_cents: int,
        note: str = "",
        entry_id: str | None = None,
    ) -> LedgerEntry:
        await self.ensure_schema()
        eid = entry_id or str(uuid.uuid4())
        now = time.time()
        await self.db.conn.execute(
            """
            INSERT INTO cp_ledger (id, mission_id, kind, amount_cents, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (eid, mission_id, kind, int(amount_cents), note or "", now),
        )
        await self.db.conn.commit()
        return LedgerEntry(
            id=eid,
            mission_id=mission_id,
            kind=kind,
            amount_cents=int(amount_cents),
            note=note or "",
            created_at=now,
        )

    async def list_ledger(self, mission_id: str, *, limit: int = 100) -> list[LedgerEntry]:
        await self.ensure_schema()
        cur = await self.db.conn.execute(
            """
            SELECT * FROM cp_ledger
            WHERE mission_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (mission_id, max(1, min(limit, 500))),
        )
        rows = await cur.fetchall()
        return [
            LedgerEntry(
                id=r["id"],
                mission_id=r["mission_id"],
                kind=r["kind"],
                amount_cents=int(r["amount_cents"]),
                note=r["note"] or "",
                created_at=float(r["created_at"]),
            )
            for r in rows
        ]

    async def append_audit(
        self,
        *,
        event_type: str,
        actor: str = "control_plane",
        mission_id: str | None = None,
        detail: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> AuditEvent:
        await self.ensure_schema()
        eid = event_id or str(uuid.uuid4())
        now = time.time()
        payload = detail or {}
        await self.db.conn.execute(
            """
            INSERT INTO cp_audit_events
                (id, mission_id, event_type, actor, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                eid,
                mission_id,
                event_type,
                actor or "control_plane",
                json.dumps(payload, separators=(",", ":"), default=str),
                now,
            ),
        )
        await self.db.conn.commit()
        return AuditEvent(
            id=eid,
            mission_id=mission_id,
            event_type=event_type,
            actor=actor or "control_plane",
            detail=payload,
            created_at=now,
        )

    async def list_audit(
        self,
        *,
        mission_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        await self.ensure_schema()
        limit = max(1, min(int(limit), 500))
        if mission_id:
            cur = await self.db.conn.execute(
                """
                SELECT * FROM cp_audit_events
                WHERE mission_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (mission_id, limit),
            )
        else:
            cur = await self.db.conn.execute(
                "SELECT * FROM cp_audit_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cur.fetchall()
        out: list[AuditEvent] = []
        for r in rows:
            try:
                detail = json.loads(r["detail_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                detail = {}
            if not isinstance(detail, dict):
                detail = {}
            out.append(
                AuditEvent(
                    id=r["id"],
                    mission_id=r["mission_id"],
                    event_type=r["event_type"],
                    actor=r["actor"] or "control_plane",
                    detail=detail,
                    created_at=float(r["created_at"]),
                )
            )
        return out

    async def list_audit_after(
        self,
        *,
        mission_id: str,
        after_sequence: int = 0,
        event_types: set[str] | frozenset[str],
        limit: int = 100,
    ) -> list[tuple[int, AuditEvent]]:
        """Read append-only audit rows in stable ascending replay order.

        SQLite ``rowid`` stays private behind the opaque V1 cursor. A future
        durable-store adapter may use its own monotonic sequence without
        changing the public contract.
        """

        await self.ensure_schema()
        kinds = tuple(sorted(set(event_types)))
        if not kinds:
            return []
        bounded_limit = max(1, min(int(limit), 500))
        placeholders = ",".join("?" for _ in kinds)
        sql = f"""
            SELECT rowid AS event_sequence, *
            FROM cp_audit_events
            WHERE mission_id = ?
              AND rowid > ?
              AND event_type IN ({placeholders})
            ORDER BY rowid ASC
            LIMIT ?
        """
        params: tuple[Any, ...] = (
            mission_id,
            max(0, int(after_sequence)),
            *kinds,
            bounded_limit,
        )
        cur = await self.db.conn.execute(sql, params)
        rows = await cur.fetchall()
        out: list[tuple[int, AuditEvent]] = []
        for row in rows:
            try:
                detail = json.loads(row["detail_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                detail = {}
            if not isinstance(detail, dict):
                detail = {}
            out.append(
                (
                    int(row["event_sequence"]),
                    AuditEvent(
                        id=row["id"],
                        mission_id=row["mission_id"],
                        event_type=row["event_type"],
                        actor=row["actor"] or "control_plane",
                        detail=detail,
                        created_at=float(row["created_at"]),
                    ),
                )
            )
        return out

    async def audit_sequence(self, event_id: str) -> int:
        await self.ensure_schema()
        cur = await self.db.conn.execute(
            "SELECT rowid AS event_sequence FROM cp_audit_events WHERE id = ?",
            (event_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise KeyError(event_id)
        return int(row["event_sequence"])

    async def create_worker(
        self,
        *,
        mission_id: str,
        isolation_mode: str = "logical",
        host_hint: str = "local-logical",
        metadata: dict[str, Any] | None = None,
        worker_id: str | None = None,
    ) -> WorkerBoundary:
        await self.ensure_schema()
        wid = worker_id or str(uuid.uuid4())
        now = time.time()
        meta = metadata or {}
        await self.db.conn.execute(
            """
            INSERT INTO cp_workers (
                id, mission_id, status, isolation_mode, host_hint,
                metadata_json, created_at, updated_at, terminated_at
            ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, NULL)
            """,
            (
                wid,
                mission_id,
                isolation_mode or "logical",
                host_hint or "local-logical",
                json.dumps(meta, separators=(",", ":"), default=str),
                now,
                now,
            ),
        )
        await self.db.conn.commit()
        worker = await self.get_worker(wid)
        assert worker is not None
        return worker

    async def get_worker(self, worker_id: str) -> WorkerBoundary | None:
        await self.ensure_schema()
        cur = await self.db.conn.execute(
            "SELECT * FROM cp_workers WHERE id = ?", (worker_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        try:
            meta = json.loads(row["metadata_json"] or "{}")
        except Exception:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        return WorkerBoundary(
            id=row["id"],
            mission_id=row["mission_id"],
            status=row["status"],
            isolation_mode=row["isolation_mode"] or "logical",
            host_hint=row["host_hint"] or "local-logical",
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            terminated_at=float(row["terminated_at"])
            if row["terminated_at"] is not None
            else None,
            metadata=meta,
        )

    async def update_worker(
        self,
        worker_id: str,
        *,
        status: str | None = None,
        terminated_at: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkerBoundary:
        await self.ensure_schema()
        worker = await self.get_worker(worker_id)
        if worker is None:
            raise KeyError(worker_id)
        now = time.time()
        new_status = status or worker.status
        new_term = terminated_at if terminated_at is not None else worker.terminated_at
        new_meta = metadata if metadata is not None else worker.metadata
        await self.db.conn.execute(
            """
            UPDATE cp_workers
            SET status = ?, terminated_at = ?, metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_status,
                new_term,
                json.dumps(new_meta or {}, separators=(",", ":"), default=str),
                now,
                worker_id,
            ),
        )
        await self.db.conn.commit()
        updated = await self.get_worker(worker_id)
        assert updated is not None
        return updated

    async def list_workers_for_mission(self, mission_id: str) -> list[WorkerBoundary]:
        await self.ensure_schema()
        cur = await self.db.conn.execute(
            """
            SELECT id FROM cp_workers
            WHERE mission_id = ?
            ORDER BY created_at DESC
            """,
            (mission_id,),
        )
        rows = await cur.fetchall()
        out: list[WorkerBoundary] = []
        for r in rows:
            w = await self.get_worker(r["id"])
            if w:
                out.append(w)
        return out
