from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.persistence.config_validation import (
    DatabaseConfigError,
    validate_database_settings,
)
from app.persistence.contract import PERSISTENCE_CONTRACT, dialect_for_provider
from app.persistence.factory import build_app_data_database, build_database
from app.persistence.migrate import (
    MigrationError,
    apply_postgres_migrations,
    file_checksum,
    list_migration_files,
    migration_plan,
    parse_migration_statements,
    split_sql_statements,
)
from app.persistence.postgres_provider import PostgresConfig, PostgresDatabaseProvider
from app.persistence.sqlite_provider import SqliteDatabaseProvider


def test_migration_files_include_foundation_extensions():
    files = list_migration_files()
    names = [p.name for p in files]
    assert any(n.startswith("001_") for n in names)
    assert "001_foundation_extensions.sql" in names


def test_migration_plan_pending_and_skip():
    plan = migration_plan(already=["001_foundation_extensions.sql"])
    assert "001_foundation_extensions.sql" in plan["skipped"]
    assert "001_foundation_extensions.sql" not in plan["pending"]
    assert plan["checksums"]["001_foundation_extensions.sql"]


def test_split_sql_statements_skips_comments():
    sql = """
    -- comment
    CREATE EXTENSION IF NOT EXISTS "pgcrypto";
    CREATE EXTENSION IF NOT EXISTS "vector";
    """
    parts = split_sql_statements(sql)
    assert len(parts) == 2
    assert "pgcrypto" in parts[0]
    assert "vector" in parts[1]


def test_parse_optional_pgvector_marker():
    sql = Path("app/migrations/001_foundation_extensions.sql").read_text(encoding="utf-8")
    stmts = parse_migration_statements(sql)
    assert any("pgcrypto" in s.sql for s in stmts)
    vector_stmts = [s for s in stmts if "vector" in s.sql.lower()]
    assert vector_stmts
    assert vector_stmts[0].optional_feature in ("pgvector", "vector")


def test_build_database_defaults_to_sqlite(tmp_path: Path):
    settings = Settings.model_validate(
        {
            "DATABASE_PATH": str(tmp_path / "t.db"),
            "DATABASE_PROVIDER": "sqlite",
        }
    )
    db = build_database(settings)
    assert isinstance(db, SqliteDatabaseProvider)
    assert db.name == "sqlite"


def test_build_database_postgres_when_configured():
    settings = Settings.model_validate(
        {
            "DATABASE_PROVIDER": "postgres",
            "POSTGRES_HOST": "db.example.internal",
            "POSTGRES_USER": "orch",
            "POSTGRES_DATABASE": "control_room",
            "POSTGRES_PASSWORD": "secret",
        }
    )
    db = build_database(settings)
    assert isinstance(db, PostgresDatabaseProvider)
    assert db.name == "postgres"
    assert db.cfg.host == "db.example.internal"
    assert db.cfg.port == 5432


def test_build_database_postgres_falls_back_without_host(tmp_path: Path):
    settings = Settings.model_validate(
        {
            "DATABASE_PATH": str(tmp_path / "t.db"),
            "DATABASE_PROVIDER": "postgres",
            "POSTGRES_HOST": "",
            "POSTGRES_USER": "orch",
            "POSTGRES_DATABASE": "control_room",
        }
    )
    db = build_database(settings)
    assert isinstance(db, SqliteDatabaseProvider)
    v = validate_database_settings(settings)
    assert v.will_use == "sqlite"
    assert v.fallback_reason == "postgres_incomplete"
    assert any(i.code == "postgres_fallback_sqlite" for i in v.issues)


def test_strict_postgres_incomplete_raises(tmp_path: Path):
    settings = Settings.model_validate(
        {
            "DATABASE_PATH": str(tmp_path / "t.db"),
            "DATABASE_PROVIDER": "postgres",
            "DATABASE_STRICT": True,
            "POSTGRES_HOST": "",
            "POSTGRES_USER": "orch",
            "POSTGRES_DATABASE": "control_room",
        }
    )
    v = validate_database_settings(settings)
    assert not v.ok
    with pytest.raises(DatabaseConfigError):
        build_database(settings)


def test_postgres_ssl_and_port_validation():
    settings = Settings.model_validate(
        {
            "DATABASE_PROVIDER": "postgres",
            "DATABASE_STRICT": True,
            "POSTGRES_HOST": "h",
            "POSTGRES_USER": "u",
            "POSTGRES_DATABASE": "d",
            "POSTGRES_PORT": 99999,
            "POSTGRES_SSL_MODE": "not-a-mode",
        }
    )
    v = validate_database_settings(settings)
    assert not v.ok
    codes = {i.code for i in v.errors}
    assert "postgres_port_invalid" in codes
    assert "postgres_ssl_invalid" in codes


def test_postgres_config_dsn_safe_hides_password():
    cfg = PostgresConfig(
        host="h",
        user="u",
        password="super-secret",
        database="d",
    )
    assert "super-secret" not in cfg.dsn_safe
    assert cfg.dsn_safe == "u@h:5432/d"


def test_app_data_stays_sqlite_when_platform_postgres(tmp_path: Path):
    settings = Settings.model_validate(
        {
            "DATABASE_PATH": str(tmp_path / "app.db"),
            "DATABASE_PROVIDER": "postgres",
            "POSTGRES_HOST": "h",
            "POSTGRES_USER": "u",
            "POSTGRES_DATABASE": "d",
            "POSTGRES_PASSWORD": "p",
        }
    )
    platform = build_database(settings)
    data = build_app_data_database(settings, platform)
    assert isinstance(platform, PostgresDatabaseProvider)
    assert isinstance(data, SqliteDatabaseProvider)
    assert dialect_for_provider(platform) == "postgres"
    assert dialect_for_provider(data) == "sqlite"


def test_persistence_contract_stable():
    c = PERSISTENCE_CONTRACT.to_dict()
    assert c["version"] == "1.3.0"
    assert c["target_dialect"] == "postgres"
    assert c["org_scope_required"] is True
    assert "organizations" in c["tenancy_tables"]
    assert "executive_safe_messages" in c["safe_memory_tables"]
    assert c["public_access_schema_version"] == 1
    assert "account_sessions" in c["public_access_tables"]
    assert Path("docs/persistence-contract.md").is_file()


def test_decisions_document_d006_d007():
    text = Path("docs/decisions.md").read_text(encoding="utf-8")
    assert "## D-006" in text
    assert "## D-007" in text
    assert "pgvector" in text


# --- fake asyncpg pool for migration idempotence ---


class _FakeTx:
    def __init__(self, conn: "_FakeConn") -> None:
        self.conn = conn

    async def start(self) -> None:
        self.conn._tx_depth += 1

    async def commit(self) -> None:
        self.conn._tx_depth = max(0, self.conn._tx_depth - 1)
        self.conn.commits += 1

    async def rollback(self) -> None:
        self.conn._tx_depth = max(0, self.conn._tx_depth - 1)
        self.conn.rollbacks += 1
        # drop uncommitted versions
        self.conn.rows = dict(self.conn._committed_rows)


class _FakeConn:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}
        self._committed_rows: dict[str, str] = {}
        self.executions: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self._tx_depth = 0
        self.fail_features: set[str] = set()
        self.locked = False

    def transaction(self) -> _FakeTx:
        return _FakeTx(self)

    async def execute(self, sql: str, *args: Any) -> str:
        text = " ".join(sql.split())
        self.executions.append(text)
        low = text.lower()
        if "pg_advisory_lock" in low:
            self.locked = True
            return "OK"
        if "pg_advisory_unlock" in low:
            self.locked = False
            return "OK"
        if low.startswith("create table if not exists schema_migrations"):
            return "OK"
        if "alter table schema_migrations add column" in low:
            return "OK"
        if "create extension" in low and "vector" in low and "vector" in self.fail_features:
            raise RuntimeError("extension \"vector\" is not available")
        if "insert into schema_migrations" in low:
            version, checksum = str(args[0]), str(args[1])
            if version in self.rows:
                return "OK"
            self.rows[version] = checksum
            if self._tx_depth == 0:
                self._committed_rows[version] = checksum
            else:
                # commit copies rows
                pass
            return "OK"
        return "OK"

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, str]]:
        if self._tx_depth > 0:
            # on commit, merge
            pass
        source = self.rows if self._tx_depth > 0 else self._committed_rows
        # During open tx, rows holds working set; keep them aligned on commit
        if self._tx_depth == 0:
            source = self._committed_rows
        else:
            source = self.rows
        return [{"version": k, "checksum": v} for k, v in source.items()]


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn

    async def acquire(self) -> _FakeConn:
        return self.conn

    async def release(self, conn: _FakeConn) -> None:
        if conn._tx_depth == 0:
            conn._committed_rows = dict(conn.rows)


@pytest.mark.asyncio
async def test_migrations_idempotent_on_fake_pool(tmp_path: Path):
    # copy real migration into temp dir
    src = Path("app/migrations/001_foundation_extensions.sql")
    d = tmp_path / "migs"
    d.mkdir()
    target = d / src.name
    target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    conn = _FakeConn()
    pool = _FakePool(conn)

    # fix commit to persist rows
    async def commit() -> None:
        conn._tx_depth = max(0, conn._tx_depth - 1)
        conn.commits += 1
        conn._committed_rows = dict(conn.rows)

    orig_tx = conn.transaction

    def transaction() -> _FakeTx:
        tx = orig_tx()

        async def _commit() -> None:
            await commit()

        tx.commit = _commit  # type: ignore[method-assign]
        return tx

    conn.transaction = transaction  # type: ignore[method-assign]

    first = await apply_postgres_migrations(pool, directory=d)
    assert src.name in first["applied"]
    assert first["skipped"] == []

    second = await apply_postgres_migrations(pool, directory=d)
    assert second["applied"] == []
    assert src.name in second["skipped"]


@pytest.mark.asyncio
async def test_migration_checksum_mismatch_raises(tmp_path: Path):
    d = tmp_path / "migs"
    d.mkdir()
    path = d / "001_foundation_extensions.sql"
    path.write_text("CREATE EXTENSION IF NOT EXISTS \"pgcrypto\";\n", encoding="utf-8")

    conn = _FakeConn()
    pool = _FakePool(conn)

    async def commit() -> None:
        conn._tx_depth = max(0, conn._tx_depth - 1)
        conn.commits += 1
        conn._committed_rows = dict(conn.rows)

    def transaction() -> _FakeTx:
        tx = _FakeTx(conn)

        async def _commit() -> None:
            await commit()

        async def _rollback() -> None:
            conn._tx_depth = max(0, conn._tx_depth - 1)
            conn.rollbacks += 1
            conn.rows = dict(conn._committed_rows)

        tx.commit = _commit  # type: ignore[method-assign]
        tx.rollback = _rollback  # type: ignore[method-assign]
        return tx

    conn.transaction = transaction  # type: ignore[method-assign]

    await apply_postgres_migrations(pool, directory=d)
    # edit applied file
    path.write_text(
        "CREATE EXTENSION IF NOT EXISTS \"pgcrypto\";\n-- changed\n",
        encoding="utf-8",
    )
    with pytest.raises(MigrationError, match="checksum"):
        await apply_postgres_migrations(pool, directory=d)


@pytest.mark.asyncio
async def test_optional_vector_failure_still_records_migration(tmp_path: Path):
    d = tmp_path / "migs"
    d.mkdir()
    path = d / "001_foundation_extensions.sql"
    path.write_text(
        'CREATE EXTENSION IF NOT EXISTS "pgcrypto";\n'
        "-- optional: pgvector\n"
        'CREATE EXTENSION IF NOT EXISTS "vector";\n',
        encoding="utf-8",
    )
    conn = _FakeConn()
    conn.fail_features.add("vector")
    pool = _FakePool(conn)

    async def commit() -> None:
        conn._tx_depth = max(0, conn._tx_depth - 1)
        conn.commits += 1
        conn._committed_rows = dict(conn.rows)

    def transaction() -> _FakeTx:
        tx = _FakeTx(conn)

        async def _commit() -> None:
            await commit()

        async def _rollback() -> None:
            conn._tx_depth = max(0, conn._tx_depth - 1)
            conn.rollbacks += 1
            conn.rows = dict(conn._committed_rows)

        tx.commit = _commit  # type: ignore[method-assign]
        tx.rollback = _rollback  # type: ignore[method-assign]
        return tx

    conn.transaction = transaction  # type: ignore[method-assign]

    result = await apply_postgres_migrations(pool, directory=d, allow_optional=True)
    assert path.name in result["applied"]
    assert result["optional_skipped"]
    # idempotent second run
    result2 = await apply_postgres_migrations(pool, directory=d)
    assert path.name in result2["skipped"]


def test_file_checksum_stable(tmp_path: Path):
    p = tmp_path / "x.sql"
    p.write_bytes(b"abc")
    assert file_checksum(p) == hashlib.sha256(b"abc").hexdigest()
