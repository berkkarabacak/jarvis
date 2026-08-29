from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.persistence.base import DatabaseHealth, DatabaseProvider
from app.persistence.config_validation import (
    DatabaseConfigError,
    validate_database_settings,
)
from app.persistence.sqlite_provider import SqliteDatabaseProvider

if TYPE_CHECKING:
    from app.config import Settings

log = logging.getLogger("agent_orchestrator.persistence")


def build_database(settings: "Settings", *, strict: bool | None = None) -> DatabaseProvider:
    """Build the platform DatabaseProvider from settings.

    Validates configuration first. When DATABASE_STRICT is set (or strict=True),
    incomplete postgres/mysql selection raises DatabaseConfigError instead of
    silently using SQLite.
    """
    validation = validate_database_settings(settings, strict=strict)
    use_strict = bool(settings.database_strict) if strict is None else bool(strict)
    if not validation.ok and use_strict:
        raise DatabaseConfigError(validation)
    if not validation.ok and validation.provider == "sqlite" and validation.fallback_reason == "unknown_provider":
        raise DatabaseConfigError(validation)

    if validation.will_use == "postgres":
        from app.persistence.postgres_provider import PostgresConfig, PostgresDatabaseProvider

        return PostgresDatabaseProvider(
            PostgresConfig(
                host=settings.postgres_host.strip(),
                port=int(settings.postgres_port or 5432),
                user=(settings.postgres_user or "").strip(),
                password=settings.postgres_password or "",
                database=(settings.postgres_database or "").strip(),
                ssl_mode=(settings.postgres_ssl_mode or "require"),
            )
        )

    if validation.will_use == "tencentdb":
        from app.persistence.mysql_provider import MysqlConfig, TencentDbProvider

        return TencentDbProvider(
            MysqlConfig(
                host=(settings.tencentdb_host or "").strip(),
                port=int(settings.tencentdb_port or 3306),
                user=(settings.tencentdb_user or "").strip(),
                password=settings.tencentdb_password or "",
                database=(settings.tencentdb_database or "").strip(),
                ssl_mode=settings.tencentdb_ssl_mode or "PREFERRED",
            )
        )

    if validation.fallback_reason:
        log.warning(
            "database provider fallback to sqlite reason=%s requested=%s",
            validation.fallback_reason,
            validation.provider,
        )
    return SqliteDatabaseProvider(settings.database_path_resolved)


def build_app_data_database(settings: "Settings", platform: DatabaseProvider) -> DatabaseProvider:
    """Repositories still require SQLite `Database.underlying`.

    When platform is postgres/mysql, keep a separate SQLite data provider so the
    scheduler continues to work while Control Room schema lives on Postgres.
    """
    name = (getattr(platform, "name", "") or "").lower()
    if name in ("postgres", "postgresql", "pg", "tencentdb", "mysql", "tidb"):
        if not hasattr(platform, "underlying"):
            return SqliteDatabaseProvider(settings.database_path_resolved)
    return platform


async def database_health(db: DatabaseProvider) -> DatabaseHealth:
    try:
        return await db.ping()
    except Exception as exc:
        return DatabaseHealth(
            provider=getattr(db, "name", "unknown"),
            ok=False,
            detail=str(exc)[:300],
        )


async def run_platform_migrations(
    platform: DatabaseProvider,
    settings: "Settings",
) -> dict[str, Any] | None:
    """Run SQL migrations when platform is Postgres and migrate-on-start is enabled."""
    name = (getattr(platform, "name", "") or "").lower()
    if name not in ("postgres", "postgresql", "pg"):
        return None
    if not bool(getattr(settings, "postgres_migrate_on_startup", False)):
        return None
    from app.persistence.migrate import apply_postgres_migrations

    pool = getattr(platform, "conn", None)
    if pool is None:
        await platform.connect()
        pool = platform.conn
    allow_vector = not bool(getattr(settings, "postgres_pgvector_required", False))
    return await apply_postgres_migrations(
        pool,
        allow_optional=allow_vector or True,
        optional_features=("pgvector", "vector") if allow_vector else (),
        fail_on_checksum_mismatch=True,
    )
