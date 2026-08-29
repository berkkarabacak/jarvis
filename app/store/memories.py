from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.agents.registry import DEFAULT_AGENT_ID, DEFAULT_PROJECT_ID


@dataclass
class Memory:
    id: str
    project_id: str
    scope: str
    owner_agent_id: str | None
    title: str
    body: str
    version: int
    created_at: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scope": self.scope,
            "owner_agent_id": self.owner_agent_id,
            "title": self.title,
            "body": self.body,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class MemoryAccessDenied(PermissionError):
    pass


class MemoryStore:
    """Shared + private agent memory with ACL (ORCH-38)."""

    def __init__(self, db) -> None:
        self.db = db

    async def create(
        self,
        *,
        scope: str,
        body: str,
        title: str = "",
        project_id: str = DEFAULT_PROJECT_ID,
        owner_agent_id: str | None = None,
        actor_agent_id: str = DEFAULT_AGENT_ID,
    ) -> Memory:
        scope = (scope or "").strip().lower()
        if scope not in ("shared", "private"):
            raise ValueError("scope must be shared or private")
        if scope == "private" and not owner_agent_id:
            owner_agent_id = actor_agent_id
        if scope == "private" and owner_agent_id != actor_agent_id:
            # Creating private memory for another agent requires admin — deny for now
            raise MemoryAccessDenied("Cannot create private memory for another agent")

        mid = str(uuid.uuid4())
        now = time.time()
        await self.db.conn.execute(
            """
            INSERT INTO memories (
                id, project_id, scope, owner_agent_id, title, body, version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                mid,
                project_id,
                scope,
                owner_agent_id if scope == "private" else None,
                title or "",
                body or "",
                now,
                now,
            ),
        )
        if scope == "shared":
            # Owner-less shared: grant read to creator by default
            await self.db.conn.execute(
                """
                INSERT OR REPLACE INTO memory_acl (memory_id, agent_id, can_read, can_write)
                VALUES (?, ?, 1, 1)
                """,
                (mid, actor_agent_id),
            )
        await self.db.conn.commit()
        mem = await self.get(mid, actor_agent_id=actor_agent_id)
        assert mem is not None
        return mem

    async def get(self, memory_id: str, *, actor_agent_id: str) -> Memory | None:
        cur = await self.db.conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
        row = await cur.fetchone()
        if not row:
            return None
        mem = _from_row(row)
        if not await self.can_read(mem, actor_agent_id):
            raise MemoryAccessDenied("No read access to this memory")
        return mem

    async def list_for_agent(
        self,
        *,
        actor_agent_id: str,
        project_id: str = DEFAULT_PROJECT_ID,
        scope: str | None = None,
    ) -> list[Memory]:
        cur = await self.db.conn.execute(
            "SELECT * FROM memories WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        )
        rows = await cur.fetchall()
        out: list[Memory] = []
        for row in rows:
            mem = _from_row(row)
            if scope and mem.scope != scope:
                continue
            if await self.can_read(mem, actor_agent_id):
                out.append(mem)
        return out

    async def can_read(self, mem: Memory, agent_id: str) -> bool:
        if mem.scope == "private":
            return mem.owner_agent_id == agent_id
        # shared: readable by all agents in project unless ACL row denies
        cur = await self.db.conn.execute(
            "SELECT can_read FROM memory_acl WHERE memory_id = ? AND agent_id = ?",
            (mem.id, agent_id),
        )
        row = await cur.fetchone()
        if row is None:
            return True  # default allow for shared
        return bool(row["can_read"])

    async def can_write(self, mem: Memory, agent_id: str) -> bool:
        if mem.scope == "private":
            return mem.owner_agent_id == agent_id
        cur = await self.db.conn.execute(
            "SELECT can_write FROM memory_acl WHERE memory_id = ? AND agent_id = ?",
            (mem.id, agent_id),
        )
        row = await cur.fetchone()
        if row is None:
            return False  # shared writes require explicit ACL
        return bool(row["can_write"])

    async def update(
        self,
        memory_id: str,
        *,
        actor_agent_id: str,
        body: str | None = None,
        title: str | None = None,
    ) -> Memory:
        mem = await self.get(memory_id, actor_agent_id=actor_agent_id)
        if mem is None:
            raise KeyError("memory not found")
        if not await self.can_write(mem, actor_agent_id):
            raise MemoryAccessDenied("No write access to this memory")
        now = time.time()
        new_body = mem.body if body is None else body
        new_title = mem.title if title is None else title
        new_version = mem.version + 1
        await self.db.conn.execute(
            """
            UPDATE memories SET body = ?, title = ?, version = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_body, new_title, new_version, now, memory_id),
        )
        await self.db.conn.commit()
        updated = await self.get(memory_id, actor_agent_id=actor_agent_id)
        assert updated is not None
        return updated

    async def set_acl(
        self,
        memory_id: str,
        *,
        actor_agent_id: str,
        target_agent_id: str,
        can_read: bool = True,
        can_write: bool = False,
    ) -> None:
        mem = await self.get(memory_id, actor_agent_id=actor_agent_id)
        if mem is None:
            raise KeyError("memory not found")
        if mem.scope != "shared":
            raise ValueError("ACL only applies to shared memories")
        if not await self.can_write(mem, actor_agent_id):
            raise MemoryAccessDenied("Need write access to change ACL")
        await self.db.conn.execute(
            """
            INSERT OR REPLACE INTO memory_acl (memory_id, agent_id, can_read, can_write)
            VALUES (?, ?, ?, ?)
            """,
            (memory_id, target_agent_id, 1 if can_read else 0, 1 if can_write else 0),
        )
        await self.db.conn.commit()

    async def context_for_agent(
        self,
        *,
        actor_agent_id: str,
        project_id: str = DEFAULT_PROJECT_ID,
        max_chars: int = 8000,
    ) -> str:
        """Build injectable context: shared (allowed) + private for this agent."""
        items = await self.list_for_agent(
            actor_agent_id=actor_agent_id, project_id=project_id
        )
        parts: list[str] = []
        used = 0
        for m in items:
            chunk = f"### [{m.scope}] {m.title or m.id[:8]}\n{m.body}\n"
            if used + len(chunk) > max_chars:
                break
            parts.append(chunk)
            used += len(chunk)
        if not parts:
            return ""
        return "## Agent memory bank\n" + "\n".join(parts)

    async def counts(self, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, int]:
        cur = await self.db.conn.execute(
            """
            SELECT scope, COUNT(*) AS c FROM memories
            WHERE project_id = ? GROUP BY scope
            """,
            (project_id,),
        )
        rows = await cur.fetchall()
        out = {"shared": 0, "private": 0}
        for r in rows:
            out[str(r["scope"])] = int(r["c"])
        return out


def _from_row(row: Any) -> Memory:
    return Memory(
        id=row["id"],
        project_id=row["project_id"],
        scope=row["scope"],
        owner_agent_id=row["owner_agent_id"],
        title=row["title"] or "",
        body=row["body"] or "",
        version=int(row["version"] or 1),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )
