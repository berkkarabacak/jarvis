from __future__ import annotations

import time
from typing import Any

from app.db import Database


class NotifyDiagnostics:
    """Persists non-secret notification diagnostics (never stores webhook URL)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def ensure_schema(self) -> None:
        await self.db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notify_diagnostics (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                slack_configured_hint INTEGER NOT NULL DEFAULT 0,
                slack_last_ok INTEGER,
                slack_last_diagnostic TEXT,
                slack_last_at REAL,
                updated_at REAL NOT NULL DEFAULT 0
            )
            """
        )
        await self.db.conn.execute(
            """
            INSERT OR IGNORE INTO notify_diagnostics (id, updated_at) VALUES (1, 0)
            """
        )
        await self.db.conn.commit()

    async def record_slack(
        self,
        *,
        configured: bool,
        ok: bool | None,
        diagnostic: str | None,
    ) -> None:
        await self.ensure_schema()
        now = time.time()
        await self.db.conn.execute(
            """
            UPDATE notify_diagnostics SET
                slack_configured_hint = ?,
                slack_last_ok = ?,
                slack_last_diagnostic = ?,
                slack_last_at = ?,
                updated_at = ?
            WHERE id = 1
            """,
            (
                1 if configured else 0,
                None if ok is None else (1 if ok else 0),
                (diagnostic or "")[:500] or None,
                now,
                now,
            ),
        )
        await self.db.conn.commit()

    async def snapshot(self, *, slack_configured: bool, email_configured: bool) -> dict[str, Any]:
        await self.ensure_schema()
        cur = await self.db.conn.execute("SELECT * FROM notify_diagnostics WHERE id = 1")
        row = await cur.fetchone()
        last_ok = None
        diag = None
        last_at = None
        if row is not None:
            if row["slack_last_ok"] is not None:
                last_ok = bool(row["slack_last_ok"])
            diag = row["slack_last_diagnostic"]
            last_at = row["slack_last_at"]
        return {
            "slack_configured": bool(slack_configured),
            "email_configured": bool(email_configured),
            "slack_last_ok": last_ok,
            "slack_last_diagnostic": diag,
            "slack_last_at": last_at,
            # Never include webhook URL
        }
