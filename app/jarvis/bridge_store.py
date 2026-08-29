"""SQLite task store for agent bridge ==GRoK== (ORCH-287)."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


TERMINAL = frozenset({"done", "failed", "cancelled"})


class BridgeStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bridge_tasks (
                  id TEXT PRIMARY KEY,
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL,
                  source TEXT NOT NULL,
                  goal TEXT NOT NULL,
                  status TEXT NOT NULL,
                  priority TEXT,
                  context_json TEXT,
                  result_json TEXT,
                  error TEXT,
                  confirm_json TEXT,
                  tools_json TEXT
                );
                CREATE TABLE IF NOT EXISTS bridge_events (
                  id TEXT PRIMARY KEY,
                  task_id TEXT NOT NULL,
                  ts REAL NOT NULL,
                  kind TEXT NOT NULL,
                  message TEXT,
                  payload_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_bridge_tasks_status ON bridge_tasks(status);
                CREATE INDEX IF NOT EXISTS idx_bridge_events_task ON bridge_events(task_id, ts);
                """
            )

    def create_task(
        self,
        *,
        goal: str,
        source: str,
        priority: str = "normal",
        context: dict | None = None,
    ) -> dict[str, Any]:
        tid = "tsk_" + uuid.uuid4().hex[:16]
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO bridge_tasks(
                  id, created_at, updated_at, source, goal, status, priority,
                  context_json, result_json, error, confirm_json, tools_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    tid,
                    now,
                    now,
                    source,
                    goal,
                    "queued",
                    priority,
                    json.dumps(context or {}),
                    None,
                    None,
                    None,
                    "[]",
                ),
            )
        self.add_event(tid, "status", "queued")
        return self.get_task(tid)  # type: ignore[return-value]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM bridge_tasks WHERE id=?", (task_id,)
            ).fetchone()
            if not row:
                return None
            events = conn.execute(
                "SELECT ts, kind, message, payload_json FROM bridge_events "
                "WHERE task_id=? ORDER BY ts ASC LIMIT 100",
                (task_id,),
            ).fetchall()
        return self._row_to_task(row, events)

    def list_tasks(
        self, *, status: str | None = None, limit: int = 20, source: str | None = None
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        q = "SELECT * FROM bridge_tasks WHERE 1=1"
        params: list[Any] = []
        if status:
            q += " AND status=?"
            params.append(status)
        if source:
            q += " AND source=?"
            params.append(source)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(q, params).fetchall()
        return [self._row_to_task(r, []) for r in rows]

    def set_status(self, task_id: str, status: str, *, error: str | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE bridge_tasks SET status=?, error=?, updated_at=? WHERE id=?",
                (status, error, time.time(), task_id),
            )
        self.add_event(task_id, "status", status)

    def set_confirm(self, task_id: str, confirm: dict | None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE bridge_tasks SET confirm_json=?, status=?, updated_at=? WHERE id=?",
                (
                    json.dumps(confirm) if confirm else None,
                    "needs_confirm" if confirm else "running",
                    time.time(),
                    task_id,
                ),
            )
        if confirm:
            self.add_event(task_id, "status", "needs_confirm", payload=confirm)

    def set_result(self, task_id: str, result: dict, tools_used: list[str]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE bridge_tasks SET status=?, result_json=?, tools_json=?,
                  confirm_json=NULL, error=NULL, updated_at=? WHERE id=?
                """,
                ("done", json.dumps(result), json.dumps(tools_used), time.time(), task_id),
            )
        self.add_event(task_id, "result", result.get("summary") or "done", payload=result)

    def add_event(
        self,
        task_id: str,
        kind: str,
        message: str = "",
        payload: dict | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO bridge_events(id, task_id, ts, kind, message, payload_json)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()),
                    task_id,
                    time.time(),
                    kind,
                    message[:500],
                    json.dumps(payload) if payload else None,
                ),
            )

    def _row_to_task(self, row: sqlite3.Row, events: list) -> dict[str, Any]:
        progress = []
        for e in events:
            if e["kind"] == "progress" or e["kind"] == "status":
                progress.append(
                    {
                        "ts": e["ts"],
                        "message": e["message"] or e["kind"],
                        "kind": e["kind"],
                    }
                )
        result = json.loads(row["result_json"]) if row["result_json"] else None
        confirm = json.loads(row["confirm_json"]) if row["confirm_json"] else None
        context = json.loads(row["context_json"]) if row["context_json"] else {}
        tools = json.loads(row["tools_json"]) if row["tools_json"] else []
        return {
            "task_id": row["id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "source": row["source"],
            "goal": row["goal"],
            "status": row["status"],
            "priority": row["priority"],
            "context": context,
            "progress": progress,
            "result": result,
            "error": row["error"],
            "confirm": confirm,
            "tools_used": tools,
        }
