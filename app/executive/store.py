from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.executive.handoff import HandoffPacket, parse_handoff
from app.executive.scopes import normalize_memory_scope
from app.memory.sanitize import sanitize_text


@dataclass
class StoredHandoff:
    """Persisted handoff row with mission/session scope metadata."""

    id: str
    mission_id: str
    session_id: str
    packet: HandoffPacket
    memory_scope: str
    created_at: float
    seq: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mission_id": self.mission_id,
            "session_id": self.session_id,
            "memory_scope": self.memory_scope,
            "created_at": self.created_at,
            "seq": self.seq,
            "packet": self.packet.to_dict(),
        }


@runtime_checkable
class HandoffStore(Protocol):
    """Persistence port for structured handoffs (ORCH-71).

    Control-plane DB adapters implement this later; executive runtime depends
    only on the protocol — no Prime Agent or provider credentials.
    """

    async def append(
        self,
        *,
        mission_id: str,
        session_id: str,
        packet: HandoffPacket | dict[str, Any] | str,
        memory_scope: str = "team",
    ) -> StoredHandoff: ...

    async def get(self, handoff_id: str) -> StoredHandoff | None: ...

    async def list_for_mission(
        self,
        mission_id: str,
        *,
        memory_scope: str | None = None,
        session_id: str | None = None,
        limit: int = 200,
    ) -> list[StoredHandoff]: ...

    async def list_for_session(self, session_id: str, *, limit: int = 200) -> list[StoredHandoff]: ...


class InMemoryHandoffStore:
    """Process-local handoff store for tests and pre-control-plane runtime."""

    def __init__(self) -> None:
        self._items: dict[str, StoredHandoff] = {}
        self._seq_by_mission: dict[str, int] = {}

    async def append(
        self,
        *,
        mission_id: str,
        session_id: str,
        packet: HandoffPacket | dict[str, Any] | str,
        memory_scope: str = "team",
    ) -> StoredHandoff:
        mid = sanitize_text((mission_id or "").strip(), max_chars=120)
        sid = sanitize_text((session_id or "").strip(), max_chars=120)
        if not mid:
            raise ValueError("mission_id is required")
        if not sid:
            raise ValueError("session_id is required")
        scope = normalize_memory_scope(memory_scope)
        pkt = packet if isinstance(packet, HandoffPacket) else parse_handoff(packet)
        seq = self._seq_by_mission.get(mid, 0) + 1
        self._seq_by_mission[mid] = seq
        row = StoredHandoff(
            id=str(uuid.uuid4()),
            mission_id=mid,
            session_id=sid,
            packet=pkt,
            memory_scope=scope,
            created_at=time.time(),
            seq=seq,
        )
        self._items[row.id] = row
        return row

    async def get(self, handoff_id: str) -> StoredHandoff | None:
        return self._items.get(handoff_id)

    async def list_for_mission(
        self,
        mission_id: str,
        *,
        memory_scope: str | None = None,
        session_id: str | None = None,
        limit: int = 200,
    ) -> list[StoredHandoff]:
        scope = normalize_memory_scope(memory_scope) if memory_scope else None
        rows = [r for r in self._items.values() if r.mission_id == mission_id]
        if scope is not None:
            rows = [r for r in rows if r.memory_scope == scope]
        if session_id is not None:
            rows = [r for r in rows if r.session_id == session_id]
        rows.sort(key=lambda r: (r.seq, r.created_at))
        lim = max(1, min(int(limit), 1000))
        return rows[-lim:]

    async def list_for_session(self, session_id: str, *, limit: int = 200) -> list[StoredHandoff]:
        rows = [r for r in self._items.values() if r.session_id == session_id]
        rows.sort(key=lambda r: (r.created_at, r.seq))
        lim = max(1, min(int(limit), 1000))
        return rows[-lim:]


class SqliteHandoffStore:
    """SQLite-backed handoff store (durable until control-plane Postgres lands)."""

    def __init__(self, db: Any) -> None:
        self.db = db

    async def ensure_schema(self) -> None:
        await self.db.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS executive_handoffs (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                memory_scope TEXT NOT NULL,
                seq INTEGER NOT NULL,
                packet_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_exec_handoffs_mission_seq
                ON executive_handoffs(mission_id, seq);
            CREATE INDEX IF NOT EXISTS idx_exec_handoffs_session
                ON executive_handoffs(session_id, created_at);
            """
        )
        await self.db.conn.commit()

    async def append(
        self,
        *,
        mission_id: str,
        session_id: str,
        packet: HandoffPacket | dict[str, Any] | str,
        memory_scope: str = "team",
    ) -> StoredHandoff:
        mid = sanitize_text((mission_id or "").strip(), max_chars=120)
        sid = sanitize_text((session_id or "").strip(), max_chars=120)
        if not mid:
            raise ValueError("mission_id is required")
        if not sid:
            raise ValueError("session_id is required")
        scope = normalize_memory_scope(memory_scope)
        pkt = packet if isinstance(packet, HandoffPacket) else parse_handoff(packet)

        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self.db.conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS m FROM executive_handoffs WHERE mission_id = ?",
                (mid,),
            )
            row = await cur.fetchone()
            seq = int(row["m"] if row is not None else 0) + 1
            hid = str(uuid.uuid4())
            now = time.time()
            await self.db.conn.execute(
                """
                INSERT INTO executive_handoffs
                    (id, mission_id, session_id, memory_scope, seq, packet_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (hid, mid, sid, scope, seq, pkt.to_json(), now),
            )
            await self.db.conn.commit()
        except Exception:
            try:
                await self.db.conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

        return StoredHandoff(
            id=hid,
            mission_id=mid,
            session_id=sid,
            packet=pkt,
            memory_scope=scope,
            created_at=now,
            seq=seq,
        )

    async def get(self, handoff_id: str) -> StoredHandoff | None:
        cur = await self.db.conn.execute(
            "SELECT * FROM executive_handoffs WHERE id = ?",
            (handoff_id,),
        )
        row = await cur.fetchone()
        return _row_to_stored(row) if row else None

    async def list_for_mission(
        self,
        mission_id: str,
        *,
        memory_scope: str | None = None,
        session_id: str | None = None,
        limit: int = 200,
    ) -> list[StoredHandoff]:
        lim = max(1, min(int(limit), 1000))
        sql = "SELECT * FROM executive_handoffs WHERE mission_id = ?"
        params: list[Any] = [mission_id]
        if memory_scope is not None:
            sql += " AND memory_scope = ?"
            params.append(normalize_memory_scope(memory_scope))
        if session_id is not None:
            sql += " AND session_id = ?"
            params.append(session_id)
        sql += " ORDER BY seq ASC LIMIT ?"
        params.append(lim)
        cur = await self.db.conn.execute(sql, tuple(params))
        rows = await cur.fetchall()
        return [_row_to_stored(r) for r in rows]

    async def list_for_session(self, session_id: str, *, limit: int = 200) -> list[StoredHandoff]:
        lim = max(1, min(int(limit), 1000))
        cur = await self.db.conn.execute(
            """
            SELECT * FROM executive_handoffs
            WHERE session_id = ?
            ORDER BY created_at ASC, seq ASC
            LIMIT ?
            """,
            (session_id, lim),
        )
        rows = await cur.fetchall()
        return [_row_to_stored(r) for r in rows]


def _row_to_stored(row: Any) -> StoredHandoff:
    import json

    raw = row["packet_json"]
    data = json.loads(raw) if isinstance(raw, str) else raw
    return StoredHandoff(
        id=row["id"],
        mission_id=row["mission_id"],
        session_id=row["session_id"],
        packet=parse_handoff(data),
        memory_scope=row["memory_scope"],
        created_at=float(row["created_at"]),
        seq=int(row["seq"]),
    )
