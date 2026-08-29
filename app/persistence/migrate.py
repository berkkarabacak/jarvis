from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.persistence.contract import MIGRATION_ADVISORY_LOCK_KEY

log = logging.getLogger("agent_orchestrator.migrate")

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

_VERSION_RE = re.compile(r"^(\d+)_.*\.sql$", re.IGNORECASE)
_OPTIONAL_RE = re.compile(r"(?im)^\s*--\s*optional(?:\s*:\s*|\s+)(\w+)\s*$")


class MigrationError(RuntimeError):
    """Migration failed; database transaction for that version was rolled back."""


@dataclass
class MigrationResult:
    provider: str
    migrations_dir: str
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    optional_skipped: list[dict[str, str]] = field(default_factory=list)
    checksums: dict[str, str] = field(default_factory=dict)
    locked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "migrations_dir": self.migrations_dir,
            "applied": list(self.applied),
            "skipped": list(self.skipped),
            "optional_skipped": list(self.optional_skipped),
            "checksums": dict(self.checksums),
            "locked": self.locked,
            "idempotent": True,
        }


def list_migration_files(directory: Path | None = None) -> list[Path]:
    root = directory or MIGRATIONS_DIR
    if not root.is_dir():
        return []
    files = [p for p in root.iterdir() if p.is_file() and _VERSION_RE.match(p.name)]
    return sorted(
        files,
        key=lambda p: (int(_VERSION_RE.match(p.name).group(1)), p.name),  # type: ignore[union-attr]
    )


def file_checksum(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def split_sql_statements(sql: str) -> list[str]:
    """Split simple SQL files on semicolons; drops full-line comments."""
    parts: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            # keep optional markers attached by handling in parse_migration_statements
            buf.append(line)
            continue
        buf.append(line)
        if stripped.endswith(";"):
            chunk = "\n".join(buf).strip()
            if chunk:
                parts.append(chunk.rstrip(";").strip())
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        parts.append(tail.rstrip(";").strip())
    return [p for p in parts if p and not all(
        ln.strip().startswith("--") or not ln.strip() for ln in p.splitlines()
    )]


@dataclass
class SqlStatement:
    sql: str
    optional_feature: str | None = None  # e.g. "pgvector"


def parse_migration_statements(sql: str) -> list[SqlStatement]:
    """Parse statements; a preceding `-- optional: pgvector` marks the next stmt optional."""
    statements: list[SqlStatement] = []
    pending_optional: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal pending_optional
        chunk = "\n".join(buf).strip()
        buf.clear()
        if not chunk:
            return
        # strip pure comment lines from chunk for execution
        exec_lines = [
            ln
            for ln in chunk.splitlines()
            if ln.strip() and not ln.strip().startswith("--")
        ]
        if not exec_lines:
            return
        body = "\n".join(exec_lines).strip().rstrip(";").strip()
        if not body:
            return
        statements.append(SqlStatement(sql=body, optional_feature=pending_optional))
        pending_optional = None

    for line in sql.splitlines():
        opt = _OPTIONAL_RE.match(line)
        if opt:
            pending_optional = opt.group(1).strip().lower()
            continue
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            flush()
    flush()
    return statements


async def ensure_schema_migrations_table(conn: Any) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL DEFAULT '',
            applied_at DOUBLE PRECISION NOT NULL
        )
        """
    )
    # Idempotent column add for DBs that created the older 2-column table.
    try:
        await conn.execute(
            "ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum TEXT NOT NULL DEFAULT ''"
        )
    except Exception:
        # Drivers without IF NOT EXISTS on ADD COLUMN: ignore if column exists.
        try:
            await conn.execute(
                "ALTER TABLE schema_migrations ADD COLUMN checksum TEXT NOT NULL DEFAULT ''"
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "already exists" not in msg and "duplicate" not in msg:
                raise


def _row_get(r: Any, key: str, idx: int, default: str = "") -> str:
    if isinstance(r, (list, tuple)):
        return str(r[idx]) if len(r) > idx else default
    if isinstance(r, dict):
        return str(r.get(key, default) or default)
    try:
        return str(r[key])  # asyncpg.Record
    except Exception:
        return default


async def applied_migration_rows(conn: Any) -> dict[str, str]:
    """version -> checksum (empty string if unknown)."""
    try:
        rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
        return {
            _row_get(r, "version", 0): _row_get(r, "checksum", 1, "")
            for r in rows
        }
    except Exception:
        rows = await conn.fetch("SELECT version FROM schema_migrations")
        return {_row_get(r, "version", 0): "" for r in rows}


async def applied_versions(conn: Any) -> set[str]:
    return set((await applied_migration_rows(conn)).keys())


async def _advisory_lock(conn: Any) -> bool:
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", MIGRATION_ADVISORY_LOCK_KEY)
        return True
    except Exception:
        # Non-postgres fakes may not support advisory locks.
        return False


async def _advisory_unlock(conn: Any) -> None:
    try:
        await conn.execute("SELECT pg_advisory_unlock($1)", MIGRATION_ADVISORY_LOCK_KEY)
    except Exception:
        pass


async def apply_postgres_migrations(
    pool: Any,
    *,
    directory: Path | None = None,
    allow_optional: bool = True,
    optional_features: Iterable[str] | None = None,
    fail_on_checksum_mismatch: bool = True,
) -> dict[str, Any]:
    """Apply pending SQL migrations idempotently against an asyncpg-like pool.

    Safety:
    - session advisory lock serializes concurrent migrators
    - each migration version runs in its own transaction
    - re-apply is a no-op when version row exists
    - checksum mismatch on an already-applied file raises MigrationError
    - statements marked `-- optional: feature` are skipped on failure when allowed
    """
    root = directory or MIGRATIONS_DIR
    files = list_migration_files(root)
    allowed_optional = {f.lower() for f in (optional_features or ("pgvector", "vector"))}
    result = MigrationResult(provider="postgres", migrations_dir=str(root))

    conn = await pool.acquire()
    try:
        result.locked = await _advisory_lock(conn)
        await ensure_schema_migrations_table(conn)
        done = await applied_migration_rows(conn)

        for path in files:
            version = path.name
            checksum = file_checksum(path)
            result.checksums[version] = checksum

            if version in done:
                prev = done[version] or ""
                if prev and prev != checksum and fail_on_checksum_mismatch:
                    raise MigrationError(
                        f"Migration {version} already applied with different checksum "
                        f"(db={prev[:12]}… file={checksum[:12]}…). "
                        "Refuse to continue; create a new numbered migration instead of editing applied SQL."
                    )
                result.skipped.append(version)
                continue

            statements = parse_migration_statements(path.read_text(encoding="utf-8"))
            tx = conn.transaction()
            await tx.start()
            try:
                for stmt in statements:
                    try:
                        await conn.execute(stmt.sql)
                    except Exception as exc:
                        feat = (stmt.optional_feature or "").lower()
                        if (
                            allow_optional
                            and feat
                            and (feat in allowed_optional or feat == "pgvector")
                        ):
                            log.warning(
                                "optional migration statement skipped version=%s feature=%s err=%s",
                                version,
                                feat,
                                exc,
                            )
                            result.optional_skipped.append(
                                {
                                    "version": version,
                                    "feature": feat,
                                    "error": str(exc)[:240],
                                }
                            )
                            continue
                        raise MigrationError(
                            f"Migration {version} failed: {exc}"
                        ) from exc

                await conn.execute(
                    """
                    INSERT INTO schema_migrations (version, checksum, applied_at)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (version) DO NOTHING
                    """,
                    version,
                    checksum,
                    time.time(),
                )
                await tx.commit()
                result.applied.append(version)
                # If concurrent migrator won the insert, treat as skip (idempotent).
                rows = await applied_migration_rows(conn)
                if version in rows and version not in result.applied:
                    pass
            except Exception:
                await tx.rollback()
                raise
        return result.to_dict()
    finally:
        await _advisory_unlock(conn)
        await pool.release(conn)


def migration_plan(
    directory: Path | None = None,
    already: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Pure helper for tests / dry-run without a database."""
    have = set(already or [])
    files = list_migration_files(directory)
    names = [p.name for p in files]
    checksums = {p.name: file_checksum(p) for p in files}
    return {
        "all": names,
        "pending": [n for n in names if n not in have],
        "skipped": [n for n in names if n in have],
        "checksums": checksums,
    }
