from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class AgentMessage:
    id: int
    run_id: str
    agent_id: str | None
    role: str
    content: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
        }


class MessageStore:
    """Persist agent message threads per run (ORCH-39)."""

    def __init__(self, db) -> None:
        self.db = db

    async def append(
        self,
        *,
        run_id: str,
        role: str,
        content: str,
        agent_id: str | None = None,
    ) -> AgentMessage:
        now = time.time()
        cur = await self.db.conn.execute(
            """
            INSERT INTO agent_messages (run_id, agent_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, agent_id, role, content or "", now),
        )
        await self.db.conn.commit()
        mid = cur.lastrowid
        msg = await self.get(int(mid))
        assert msg is not None
        return msg

    async def get(self, message_id: int) -> AgentMessage | None:
        cur = await self.db.conn.execute(
            "SELECT * FROM agent_messages WHERE id = ?", (message_id,)
        )
        row = await cur.fetchone()
        return _from_row(row) if row else None

    async def list_for_run(self, run_id: str) -> list[AgentMessage]:
        cur = await self.db.conn.execute(
            """
            SELECT * FROM agent_messages
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        )
        rows = await cur.fetchall()
        return [_from_row(r) for r in rows]

    async def append_many(
        self,
        *,
        run_id: str,
        messages: list[dict[str, str]],
        agent_id: str | None = None,
    ) -> list[AgentMessage]:
        out: list[AgentMessage] = []
        for m in messages:
            out.append(
                await self.append(
                    run_id=run_id,
                    role=m.get("role") or "user",
                    content=m.get("content") or "",
                    agent_id=agent_id,
                )
            )
        return out


def _from_row(row: Any) -> AgentMessage:
    return AgentMessage(
        id=int(row["id"]),
        run_id=row["run_id"],
        agent_id=row["agent_id"],
        role=row["role"],
        content=row["content"] or "",
        created_at=float(row["created_at"]),
    )
