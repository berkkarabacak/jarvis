from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from app.config import Settings

ProviderName = Literal["sqlite", "postgres", "tencentdb"]

ALLOWED_PROVIDERS = frozenset(
    {
        "sqlite",
        "postgres",
        "postgresql",
        "pg",
        "tencentdb-postgres",
        "tencentdb",
        "mysql",
        "tidb",
        "tencentdb-mysql",
    }
)

POSTGRES_SSL_MODES = frozenset(
    {
        "disable",
        "off",
        "false",
        "0",
        "allow",
        "prefer",
        "require",
        "required",
        "verify-ca",
        "verify_ca",
        "verify-full",
        "verify_full",
    }
)


@dataclass
class ConfigIssue:
    code: str
    message: str
    field: str | None = None
    severity: str = "error"  # error | warning

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "severity": self.severity,
        }


@dataclass
class DatabaseConfigValidation:
    ok: bool
    provider: ProviderName
    normalized_provider: str
    issues: list[ConfigIssue] = field(default_factory=list)
    postgres_ready: bool = False
    mysql_ready: bool = False
    will_use: ProviderName = "sqlite"
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "normalized_provider": self.normalized_provider,
            "postgres_ready": self.postgres_ready,
            "mysql_ready": self.mysql_ready,
            "will_use": self.will_use,
            "fallback_reason": self.fallback_reason,
            "issues": [i.to_dict() for i in self.issues],
        }

    @property
    def errors(self) -> list[ConfigIssue]:
        return [i for i in self.issues if i.severity == "error"]


def normalize_provider(raw: str | None) -> str:
    return (raw or "sqlite").strip().lower() or "sqlite"


def canonical_provider(raw: str | None) -> ProviderName:
    p = normalize_provider(raw)
    if p in ("postgres", "postgresql", "pg", "tencentdb-postgres"):
        return "postgres"
    if p in ("tencentdb", "mysql", "tidb", "tencentdb-mysql"):
        return "tencentdb"
    return "sqlite"


def _port_ok(port: Any, *, default: int) -> tuple[bool, int]:
    try:
        value = int(port if port is not None else default)
    except (TypeError, ValueError):
        return False, default
    return 1 <= value <= 65535, value


class DatabaseConfigError(ValueError):
    """Raised when strict database configuration is invalid."""

    def __init__(self, validation: DatabaseConfigValidation) -> None:
        self.validation = validation
        msgs = "; ".join(i.message for i in validation.errors) or "invalid database configuration"
        super().__init__(msgs)


def validate_database_settings(
    settings: "Settings",
    *,
    strict: bool | None = None,
) -> DatabaseConfigValidation:
    """Validate DATABASE_* / POSTGRES_* / TENCENTDB_* without connecting.

    When strict (DATABASE_STRICT=true): selecting postgres/mysql without complete
    credentials is an error — no silent SQLite fallback.
    """
    raw = normalize_provider(getattr(settings, "database_provider", None))
    issues: list[ConfigIssue] = []

    if raw not in ALLOWED_PROVIDERS:
        issues.append(
            ConfigIssue(
                code="provider_unknown",
                field="DATABASE_PROVIDER",
                message=f"Unknown DATABASE_PROVIDER={raw!r}; expected sqlite|postgres|tencentdb",
            )
        )
        return DatabaseConfigValidation(
            ok=False,
            provider="sqlite",
            normalized_provider=raw,
            issues=issues,
            will_use="sqlite",
            fallback_reason="unknown_provider",
        )

    provider = canonical_provider(raw)
    if strict is None:
        strict = bool(getattr(settings, "database_strict", False))

    pg_host = (getattr(settings, "postgres_host", None) or "").strip()
    pg_user = (getattr(settings, "postgres_user", None) or "").strip()
    pg_db = (getattr(settings, "postgres_database", None) or "").strip()
    pg_pass = (getattr(settings, "postgres_password", None) or "").strip()
    pg_ssl = (getattr(settings, "postgres_ssl_mode", None) or "require").strip().lower()
    pg_port_ok, _pg_port = _port_ok(getattr(settings, "postgres_port", None), default=5432)

    pg_fields_present = bool(pg_host and pg_user and pg_db)
    postgres_ready = pg_fields_present and pg_port_ok and pg_ssl in POSTGRES_SSL_MODES

    if provider == "postgres" or pg_host or pg_user or pg_db:
        # Incomplete postgres is an error only in strict mode; otherwise warn + fallback.
        sev = "error" if (provider == "postgres" and strict) else "warning"
        if not pg_host:
            issues.append(
                ConfigIssue(
                    code="postgres_host_missing",
                    field="POSTGRES_HOST",
                    message="POSTGRES_HOST is required for PostgreSQL",
                    severity=sev,
                )
            )
        if not pg_user:
            issues.append(
                ConfigIssue(
                    code="postgres_user_missing",
                    field="POSTGRES_USER",
                    message="POSTGRES_USER is required for PostgreSQL",
                    severity=sev,
                )
            )
        if not pg_db:
            issues.append(
                ConfigIssue(
                    code="postgres_database_missing",
                    field="POSTGRES_DATABASE",
                    message="POSTGRES_DATABASE is required for PostgreSQL",
                    severity=sev,
                )
            )
        if not pg_port_ok:
            issues.append(
                ConfigIssue(
                    code="postgres_port_invalid",
                    field="POSTGRES_PORT",
                    message="POSTGRES_PORT must be an integer 1-65535",
                    severity=sev,
                )
            )
        if pg_ssl not in POSTGRES_SSL_MODES:
            issues.append(
                ConfigIssue(
                    code="postgres_ssl_invalid",
                    field="POSTGRES_SSL_MODE",
                    message=f"POSTGRES_SSL_MODE={pg_ssl!r} is not supported",
                    severity=sev,
                )
            )
        if pg_fields_present and not pg_pass:
            issues.append(
                ConfigIssue(
                    code="postgres_password_empty",
                    field="POSTGRES_PASSWORD",
                    message="POSTGRES_PASSWORD is empty (ok only for trust/peer auth)",
                    severity="warning",
                )
            )

    my_host = (getattr(settings, "tencentdb_host", None) or "").strip()
    my_user = (getattr(settings, "tencentdb_user", None) or "").strip()
    my_db = (getattr(settings, "tencentdb_database", None) or "").strip()
    my_port_ok, _ = _port_ok(getattr(settings, "tencentdb_port", None), default=3306)
    mysql_ready = bool(my_host and my_user and my_db and my_port_ok)

    if provider == "tencentdb" and not mysql_ready:
        my_sev = "error" if strict else "warning"
        if not my_host:
            issues.append(
                ConfigIssue(
                    code="mysql_host_missing",
                    field="TENCENTDB_HOST",
                    message="TENCENTDB_HOST required when DATABASE_PROVIDER=tencentdb",
                    severity=my_sev,
                )
            )
        if not my_user:
            issues.append(
                ConfigIssue(
                    code="mysql_user_missing",
                    field="TENCENTDB_USER",
                    message="TENCENTDB_USER required when DATABASE_PROVIDER=tencentdb",
                    severity=my_sev,
                )
            )
        if not my_db:
            issues.append(
                ConfigIssue(
                    code="mysql_database_missing",
                    field="TENCENTDB_DATABASE",
                    message="TENCENTDB_DATABASE required when DATABASE_PROVIDER=tencentdb",
                    severity=my_sev,
                )
            )
        if not my_port_ok:
            issues.append(
                ConfigIssue(
                    code="mysql_port_invalid",
                    field="TENCENTDB_PORT",
                    message="TENCENTDB_PORT must be 1-65535",
                    severity=my_sev,
                )
            )

    will_use: ProviderName = "sqlite"
    fallback_reason: str | None = None

    if provider == "sqlite":
        will_use = "sqlite"
    elif provider == "postgres":
        if postgres_ready:
            will_use = "postgres"
        else:
            will_use = "sqlite"
            fallback_reason = "postgres_incomplete"
            if strict:
                issues.append(
                    ConfigIssue(
                        code="postgres_strict_incomplete",
                        field="DATABASE_PROVIDER",
                        message=(
                            "DATABASE_STRICT=true refuses SQLite fallback when "
                            "DATABASE_PROVIDER=postgres is incomplete/invalid"
                        ),
                    )
                )
            else:
                issues.append(
                    ConfigIssue(
                        code="postgres_fallback_sqlite",
                        field="DATABASE_PROVIDER",
                        message="PostgreSQL incomplete/invalid; platform handle falls back to SQLite",
                        severity="warning",
                    )
                )
    else:  # tencentdb
        if mysql_ready:
            will_use = "tencentdb"
        else:
            will_use = "sqlite"
            fallback_reason = "mysql_incomplete"
            if strict:
                issues.append(
                    ConfigIssue(
                        code="mysql_strict_incomplete",
                        field="DATABASE_PROVIDER",
                        message="DATABASE_STRICT=true refuses SQLite fallback for incomplete tencentdb config",
                    )
                )
            else:
                issues.append(
                    ConfigIssue(
                        code="mysql_fallback_sqlite",
                        field="DATABASE_PROVIDER",
                        message="TencentDB MySQL incomplete; falling back to SQLite",
                        severity="warning",
                    )
                )

    error_issues = [i for i in issues if i.severity == "error"]
    ok = len(error_issues) == 0
    return DatabaseConfigValidation(
        ok=ok,
        provider=provider,
        normalized_provider=raw,
        issues=issues,
        postgres_ready=postgres_ready,
        mysql_ready=mysql_ready,
        will_use=will_use,
        fallback_reason=fallback_reason,
    )
