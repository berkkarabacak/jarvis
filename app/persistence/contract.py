from __future__ import annotations

"""Stable persistence contract for Control Room agents (ORCH-69).

Other epics (ORCH-70+) should depend on these symbols rather than importing
sqlite/mysql internals directly.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from app.persistence.base import DatabaseHealth, DatabaseProvider

Dialect = Literal["sqlite", "postgres", "mysql"]

# Advisory lock key space reserved for Agent Orchestrator migrations (arbitrary stable int).
MIGRATION_ADVISORY_LOCK_KEY = 690_069


@dataclass(frozen=True)
class PersistenceContract:
    """What callers may rely on across providers."""

    version: str = "1.3.0"
    dialects: tuple[Dialect, ...] = ("sqlite", "postgres", "mysql")
    default_dialect: Dialect = "sqlite"
    target_dialect: Dialect = "postgres"
    app_data_dialect_today: Dialect = "sqlite"
    migrations_dir: str = "app/migrations"
    migrations_table: str = "schema_migrations"
    org_scope_required: bool = True  # future tables must carry org_id
    cross_org_not_found: bool = True  # leak-safe 404
    secrets_never_in_dsn_logs: bool = True
    tenancy_tables: tuple[str, ...] = ("organizations", "users", "memberships")
    safe_memory_tables: tuple[str, ...] = (
        "executive_safe_messages",
        "executive_memory_items",
    )
    public_access_schema_version: int = 1
    public_access_tables: tuple[str, ...] = (
        "account_sessions",
        "account_resource_bindings",
        "account_usage_windows",
    )
    bootstrap_org_slug: str = "default"
    member_roles: tuple[str, ...] = ("owner", "admin", "member", "viewer")
    notes: tuple[str, ...] = (
        "Job/run/memory repositories still use SQLite Database.underlying until cutover.",
        "Postgres provider is the platform store for tenancy, audit, artifacts, events.",
        (
            "When DATABASE_PROVIDER=postgres, app.state.db_provider is Postgres; "
            "app.state.data_provider remains SQLite for legacy stores."
        ),
        "Apply Control Room DDL only via app/persistence/migrate.py SQL files.",
        "Tenancy: app.tenancy.TenancyStore on platform Postgres (migration 002).",
        "Executive safe memory: app.persistence.SafeMemoryRepository (migration 004).",
        (
            "Public account boundary: AccountPrincipalV1 plus opaque hash-only "
            "sessions, ownership bindings, and usage windows (migration 005)."
        ),
        "Legacy API_SECRET remains the service/admin boundary; it is never a browser credential.",
        "Only approved memory items may be consumed; proposals cannot execute code or deploy.",
        "Cross-org access raises TenantNotFound → HTTP 404.",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "dialects": list(self.dialects),
            "default_dialect": self.default_dialect,
            "target_dialect": self.target_dialect,
            "app_data_dialect_today": self.app_data_dialect_today,
            "migrations_dir": self.migrations_dir,
            "migrations_table": self.migrations_table,
            "org_scope_required": self.org_scope_required,
            "cross_org_not_found": self.cross_org_not_found,
            "secrets_never_in_dsn_logs": self.secrets_never_in_dsn_logs,
            "tenancy_tables": list(self.tenancy_tables),
            "safe_memory_tables": list(self.safe_memory_tables),
            "public_access_schema_version": self.public_access_schema_version,
            "public_access_tables": list(self.public_access_tables),
            "bootstrap_org_slug": self.bootstrap_org_slug,
            "member_roles": list(self.member_roles),
            "notes": list(self.notes),
        }


PERSISTENCE_CONTRACT = PersistenceContract()


@runtime_checkable
class PlatformDatabase(Protocol):
    """Platform DB used for health, migrations, and future org-scoped repos."""

    name: str

    async def connect(self) -> Any: ...

    async def close(self) -> None: ...

    async def ping(self) -> DatabaseHealth: ...


def dialect_for_provider(provider: DatabaseProvider | Any) -> Dialect:
    name = (getattr(provider, "name", None) or "sqlite").strip().lower()
    if name in ("postgres", "postgresql", "pg"):
        return "postgres"
    if name in ("tencentdb", "mysql", "tidb"):
        return "mysql"
    return "sqlite"
