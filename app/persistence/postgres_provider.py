from __future__ import annotations

import ssl
import time
from dataclasses import dataclass
from typing import Any

from app.persistence.base import DatabaseHealth


@dataclass
class PostgresConfig:
    host: str
    port: int = 5432
    user: str = ""
    password: str = ""
    database: str = ""
    ssl_mode: str = "require"  # disable | require | verify-ca | verify-full
    min_size: int = 1
    max_size: int = 10

    @property
    def dsn_safe(self) -> str:
        return f"{self.user}@{self.host}:{self.port}/{self.database}"


def _ssl_context(ssl_mode: str) -> ssl.SSLContext | bool | None:
    mode = (ssl_mode or "require").strip().lower()
    if mode in ("disable", "off", "false", "0"):
        return None
    if mode in ("allow", "prefer"):
        # asyncpg: True enables SSL without cert verification
        return True
    ctx = ssl.create_default_context()
    if mode in ("require", "required"):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    # verify-ca / verify-full keep default verification
    return ctx


class PostgresDatabaseProvider:
    """TencentDB PostgreSQL / generic Postgres provider (ORCH-69 / D-007).

    Requires optional dependency: asyncpg.
    App data remains on SQLite until repositories are cut over; this provider
    supports health checks, migration runs, and future Control Room tables.
    """

    name = "postgres"

    def __init__(self, cfg: PostgresConfig) -> None:
        self.cfg = cfg
        self._pool: Any = None

    async def connect(self) -> Any:
        try:
            import asyncpg  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "asyncpg not installed. pip install asyncpg to use PostgreSQL."
            ) from exc

        if self._pool is not None:
            return self._pool

        ssl_arg = _ssl_context(self.cfg.ssl_mode)
        self._pool = await asyncpg.create_pool(
            host=self.cfg.host,
            port=int(self.cfg.port or 5432),
            user=self.cfg.user,
            password=self.cfg.password,
            database=self.cfg.database,
            ssl=ssl_arg,
            min_size=max(1, int(self.cfg.min_size or 1)),
            max_size=max(1, int(self.cfg.max_size or 10)),
            command_timeout=60,
        )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def conn(self) -> Any:
        """Pool handle (asyncpg pool). Callers must acquire connections."""
        if self._pool is None:
            raise RuntimeError("PostgreSQL not connected")
        return self._pool

    async def ping(self) -> DatabaseHealth:
        started = time.perf_counter()
        dsn = self.cfg.dsn_safe
        try:
            if self._pool is None:
                await self.connect()
            assert self._pool is not None
            async with self._pool.acquire() as conn:
                val = await conn.fetchval("SELECT 1")
                if val != 1:
                    raise RuntimeError(f"unexpected ping result: {val!r}")
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

    async def fetch_pgvector_status(self) -> dict[str, Any]:
        """Report whether the vector extension is available/installed."""
        if self._pool is None:
            await self.connect()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            installed = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            )
            available = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector')"
            )
        return {
            "extension": "vector",
            "installed": bool(installed),
            "available": bool(available),
        }


async def test_postgres_connection(cfg: PostgresConfig) -> DatabaseHealth:
    """One-shot connection test without retaining the pool on the app."""
    provider = PostgresDatabaseProvider(cfg)
    try:
        return await provider.ping()
    finally:
        await provider.close()
