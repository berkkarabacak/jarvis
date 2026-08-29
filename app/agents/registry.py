from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any  # noqa: F401 — used in annotations

DEFAULT_AGENT_ID = "scheduler-worker"
DEFAULT_PROJECT_ID = "default"


@dataclass
class AgentType:
    key: str
    name: str
    description: str = ""


# Built-in agent types — register more without schema changes (ORCH-40).
AGENT_TYPES: dict[str, AgentType] = {
    "scheduler_worker": AgentType(
        key="scheduler_worker",
        name="Scheduler Worker",
        description="Default scheduled job runner with durable memory",
    ),
    "researcher": AgentType(
        key="researcher",
        name="Researcher",
        description="Future multi-agent research role (scaffold)",
    ),
    "reviewer": AgentType(
        key="reviewer",
        name="Reviewer",
        description="Future multi-agent review role (scaffold)",
    ),
}


@dataclass
class Agent:
    id: str
    project_id: str
    agent_type: str
    name: str
    config_json: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        try:
            cfg = json.loads(self.config_json or "{}")
        except Exception:
            cfg = {}
        return {
            "id": self.id,
            "project_id": self.project_id,
            "agent_type": self.agent_type,
            "name": self.name,
            "config": cfg,
            "created_at": self.created_at,
        }


class AgentRegistry:
    def __init__(self, db) -> None:
        self.db = db

    def list_types(self) -> list[dict[str, str]]:
        return [
            {"key": t.key, "name": t.name, "description": t.description}
            for t in AGENT_TYPES.values()
        ]

    async def list_agents(self, project_id: str = DEFAULT_PROJECT_ID) -> list[Agent]:
        cur = await self.db.conn.execute(
            "SELECT * FROM agents WHERE project_id = ? ORDER BY created_at ASC",
            (project_id,),
        )
        rows = await cur.fetchall()
        return [_agent_from_row(r) for r in rows]

    async def get_agent(self, agent_id: str) -> Agent | None:
        cur = await self.db.conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        row = await cur.fetchone()
        return _agent_from_row(row) if row else None

    async def ensure_default(self) -> Agent:
        existing = await self.get_agent(DEFAULT_AGENT_ID)
        if existing:
            return existing
        now = time.time()
        await self.db.conn.execute(
            """
            INSERT OR IGNORE INTO projects (id, name, created_at, updated_at)
            VALUES (?, 'Default', ?, ?)
            """,
            (DEFAULT_PROJECT_ID, now, now),
        )
        await self.db.conn.execute(
            """
            INSERT INTO agents (id, project_id, agent_type, name, config_json, created_at)
            VALUES (?, ?, 'scheduler_worker', 'Scheduler Worker', '{}', ?)
            """,
            (DEFAULT_AGENT_ID, DEFAULT_PROJECT_ID, now),
        )
        await self.db.conn.commit()
        agent = await self.get_agent(DEFAULT_AGENT_ID)
        assert agent is not None
        return agent

    async def create_agent(
        self,
        *,
        name: str,
        agent_type: str = "scheduler_worker",
        project_id: str = DEFAULT_PROJECT_ID,
        config: dict[str, Any] | None = None,
        agent_id: str | None = None,
    ) -> Agent:
        if agent_type not in AGENT_TYPES:
            raise ValueError(f"Unknown agent_type: {agent_type}")
        now = time.time()
        aid = agent_id or str(uuid.uuid4())
        await self.db.conn.execute(
            """
            INSERT OR IGNORE INTO projects (id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, project_id, now, now),
        )
        await self.db.conn.execute(
            """
            INSERT INTO agents (id, project_id, agent_type, name, config_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (aid, project_id, agent_type, name, json.dumps(config or {}), now),
        )
        await self.db.conn.commit()
        agent = await self.get_agent(aid)
        assert agent is not None
        return agent


def _agent_from_row(row: Any) -> Agent:
    return Agent(
        id=row["id"],
        project_id=row["project_id"],
        agent_type=row["agent_type"],
        name=row["name"],
        config_json=row["config_json"] or "{}",
        created_at=float(row["created_at"]),
    )
