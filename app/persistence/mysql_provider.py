from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.persistence.base import DatabaseHealth


@dataclass
class MysqlConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    ssl_mode: str = "PREFERRED"


class TencentDbProvider:
    """TencentDB MySQL-compatible provider (ORCH-37) — LEGACY FROZEN (D-007).

    Do not add Control Room / mission / tenancy schema here.
    Forward path is PostgreSQL + pgvector (ORCH-69).

    Requires optional dependency: aiomysql.
    When not installed or not configured, factory keeps SQLite.
    """

    name = "tencentdb"

    def __init__(self, cfg: MysqlConfig) -> None:
        self.cfg = cfg
        self._conn: Any = None

    async def connect(self) -> Any:
        try:
            import aiomysql  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "aiomysql not installed. pip install aiomysql to use TencentDB."
            ) from exc

        self._conn = await aiomysql.connect(
            host=self.cfg.host,
            port=int(self.cfg.port or 3306),
            user=self.cfg.user,
            password=self.cfg.password,
            db=self.cfg.database,
            autocommit=True,
            charset="utf8mb4",
        )
        return self._conn

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> Any:
        if self._conn is None:
            raise RuntimeError("TencentDB not connected")
        return self._conn

    async def ping(self) -> DatabaseHealth:
        started = time.perf_counter()
        dsn = f"{self.cfg.user}@{self.cfg.host}:{self.cfg.port}/{self.cfg.database}"
        try:
            if self._conn is None:
                await self.connect()
            async with self._conn.cursor() as cur:
                await cur.execute("SELECT 1")
                await cur.fetchone()
            ms = int((time.perf_counter() - started) * 1000)
            return DatabaseHealth(
                provider=self.name,
                ok=True,
                latency_ms=ms,
                detail="SELECT 1 ok",
                path_or_dsn=dsn,
            )
        except Exception as exc:
            ms = int((time.perf_counter() - started) * 1000)
            return DatabaseHealth(
                provider=self.name,
                ok=False,
                latency_ms=ms,
                detail=str(exc)[:300],
                path_or_dsn=dsn,
            )


async def test_tencentdb_connection(cfg: MysqlConfig) -> DatabaseHealth:
    """One-shot connection test without holding a long-lived pool."""
    provider = TencentDbProvider(cfg)
    try:
        return await provider.ping()
    finally:
        await provider.close()
