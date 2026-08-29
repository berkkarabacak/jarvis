from __future__ import annotations

import time
from pathlib import Path

from app.db import Database
from app.persistence.base import DatabaseHealth


class SqliteDatabaseProvider:
    """Thin adapter over existing aiosqlite Database (source of truth for schema)."""

    name = "sqlite"

    def __init__(self, path: Path) -> None:
        self._db = Database(path)
        self._path = path

    async def connect(self):
        return await self._db.connect()

    async def close(self) -> None:
        await self._db.close()

    @property
    def conn(self):
        return self._db.conn

    @property
    def underlying(self) -> Database:
        """Legacy access for stores that still type against Database."""
        return self._db

    async def ping(self) -> DatabaseHealth:
        started = time.perf_counter()
        try:
            cur = await self._db.conn.execute("SELECT 1")
            await cur.fetchone()
            ms = int((time.perf_counter() - started) * 1000)
            return DatabaseHealth(
                provider=self.name,
                ok=True,
                latency_ms=ms,
                detail="SELECT 1 ok",
                path_or_dsn=str(self._path),
            )
        except Exception as exc:
            ms = int((time.perf_counter() - started) * 1000)
            return DatabaseHealth(
                provider=self.name,
                ok=False,
                latency_ms=ms,
                detail=str(exc)[:300],
                path_or_dsn=str(self._path),
            )
