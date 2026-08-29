from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.auth.constants import XAI_OAUTH_REDIRECT_HOST, XAI_OAUTH_REDIRECT_PORT

# Keep as literal to avoid circular imports (config must not import llm package).
_DEFAULT_MODEL = "openrouter/auto"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_secret: str = Field(default="dev-secret-change-me", alias="API_SECRET")
    token_encryption_key: str = Field(default="", alias="TOKEN_ENCRYPTION_KEY")
    # When true, refuse startup if API_SECRET/TOKEN_ENCRYPTION_KEY are insecure defaults
    enforce_secure_secrets: bool = Field(default=False, alias="ENFORCE_SECURE_SECRETS")
    database_path: str = Field(default="./data/agent_orchestrator.db", alias="DATABASE_PATH")
    # sqlite (default/dev) | postgres (ORCH-69 target) | tencentdb-mysql (legacy frozen)
    database_provider: str = Field(default="sqlite", alias="DATABASE_PROVIDER")
    # When true, refuse silent SQLite fallback if postgres/mysql selection is incomplete
    database_strict: bool = Field(default=False, alias="DATABASE_STRICT")
    # PostgreSQL / TencentDB PostgreSQL (D-007)
    postgres_host: str = Field(default="", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_user: str = Field(default="", alias="POSTGRES_USER")
    postgres_password: str = Field(default="", alias="POSTGRES_PASSWORD")
    postgres_database: str = Field(default="", alias="POSTGRES_DATABASE")
    postgres_ssl_mode: str = Field(default="require", alias="POSTGRES_SSL_MODE")
    postgres_pgvector_required: bool = Field(default=False, alias="POSTGRES_PGVECTOR_REQUIRED")
    postgres_migrate_on_startup: bool = Field(default=False, alias="POSTGRES_MIGRATE_ON_STARTUP")
    # TencentDB MySQL (ORCH-37) — legacy; frozen for scheduler path only (D-007)
    tencentdb_host: str = Field(default="", alias="TENCENTDB_HOST")
    tencentdb_port: int = Field(default=3306, alias="TENCENTDB_PORT")
    tencentdb_user: str = Field(default="", alias="TENCENTDB_USER")
    tencentdb_password: str = Field(default="", alias="TENCENTDB_PASSWORD")
    tencentdb_database: str = Field(default="", alias="TENCENTDB_DATABASE")
    tencentdb_ssl_mode: str = Field(default="PREFERRED", alias="TENCENTDB_SSL_MODE")
    token_provider: str = Field(default="oauth", alias="TOKEN_PROVIDER")
    xai_api_key: str = Field(default="", alias="XAI_API_KEY")

    # LLM
    llm_provider: str = Field(default="openrouter", alias="LLM_PROVIDER")  # openrouter | xai
    llm_model_mode: str = Field(default="auto", alias="LLM_MODEL_MODE")  # auto | fixed
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    llm_timeout_seconds: int = Field(default=600, alias="LLM_TIMEOUT_SECONDS")
    # Legacy alias for timeout
    grok_timeout_seconds: int = Field(default=600, alias="GROK_TIMEOUT_SECONDS")

    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8787, alias="PORT")
    tz: str = Field(default="UTC", alias="TZ")

    memory_max_chars: int = Field(default=12000, alias="MEMORY_MAX_CHARS")
    memory_versions_keep: int = Field(default=20, alias="MEMORY_VERSIONS_KEEP")
    memory_log_keep: int = Field(default=40, alias="MEMORY_LOG_KEEP")
    memory_log_compact_after: int = Field(default=50, alias="MEMORY_LOG_COMPACT_AFTER")
    memory_prior_runs: int = Field(default=5, alias="MEMORY_PRIOR_RUNS")
    memory_prior_run_chars: int = Field(default=900, alias="MEMORY_PRIOR_RUN_CHARS")
    memory_context_max_chars: int = Field(default=24000, alias="MEMORY_CONTEXT_MAX_CHARS")
    default_model: str = Field(default=_DEFAULT_MODEL, alias="DEFAULT_MODEL")

    oauth_redirect_host: str = Field(default=XAI_OAUTH_REDIRECT_HOST, alias="OAUTH_REDIRECT_HOST")
    oauth_redirect_port: int = Field(default=XAI_OAUTH_REDIRECT_PORT, alias="OAUTH_REDIRECT_PORT")

    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", alias="SMTP_FROM")
    smtp_starttls: bool = Field(default=True, alias="SMTP_STARTTLS")
    smtp_ssl: bool = Field(default=False, alias="SMTP_SSL")

    jira_base: str = Field(default="", alias="JIRA_BASE")
    jira_email: str = Field(default="", alias="JIRA_EMAIL")
    jira_api_token: str = Field(default="", alias="JIRA_API_TOKEN")
    jira_exclude_projects: str = Field(default="HW9K", alias="JIRA_EXCLUDE_PROJECTS")

    # Slack: prefer Bot token (Web API). Webhook optional fallback.
    slack_bot_token: str = Field(default="", alias="SLACK_BOT_TOKEN")
    slack_channel: str = Field(default="", alias="SLACK_CHANNEL")
    slack_workspace: str = Field(default="", alias="SLACK_WORKSPACE")
    slack_webhook_url: str = Field(default="", alias="SLACK_WEBHOOK_URL")
    public_base_url: str = Field(
        default="https://berkkarabacak.com/agent-orchestrator",
        alias="PUBLIC_BASE_URL",
    )

    # Herdr terminal agent runtime (optional job runner)
    herdr_enabled: bool = Field(default=False, alias="HERDR_ENABLED")
    herdr_bin: str = Field(default="herdr", alias="HERDR_BIN")
    herdr_session: str = Field(default="", alias="HERDR_SESSION")
    herdr_timeout_ms: int = Field(default=120_000, alias="HERDR_TIMEOUT_MS")
    herdr_default_kind: str = Field(default="opencode", alias="HERDR_DEFAULT_KIND")

    @property
    def database_path_resolved(self) -> Path:
        return Path(self.database_path).expanduser().resolve()

    def apply_updates(self, updates: dict) -> None:
        """Validate and apply runtime updates to this settings instance.

        Centralizes direct mutation (issue #149): field names are checked,
        values are validated by rebuilding the model, then swapped in.
        Raises ValueError on unknown fields or invalid values.
        """
        field_names = set(type(self).model_fields)
        unknown = sorted(set(updates) - field_names)
        if unknown:
            raise ValueError(f"unknown settings fields: {unknown}")
        merged = {name: getattr(self, name) for name in field_names}
        merged.update(updates)
        validated = type(self)(**merged)
        self.__dict__.update(validated.__dict__)

    @property
    def oauth_redirect_uri(self) -> str:
        return f"http://{self.oauth_redirect_host}:{self.oauth_redirect_port}/callback"

    @property
    def email_configured(self) -> bool:
        return bool((self.smtp_host or "").strip() and (self.smtp_password or "").strip())

    @property
    def slack_configured(self) -> bool:
        from app.notify.slack import slack_mode

        return slack_mode(self) != "none"

    @property
    def slack_mode(self) -> str:
        from app.notify.slack import slack_mode

        return slack_mode(self)


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Well-known placeholder values that must never reach production.
_INSECURE_API_SECRETS = {
    "",
    "dev-secret-change-me",
    "change-me-to-a-long-random-string",
    "change-me",
    "public",
}


def validate_secret_settings(settings: Settings) -> list[str]:
    """Return a list of insecure-secret problems (empty list means OK)."""
    problems: list[str] = []
    if (settings.api_secret or "").strip().lower() in _INSECURE_API_SECRETS:
        problems.append(
            "API_SECRET is unset or a well-known default; set a long random string"
        )
    if not (settings.token_encryption_key or "").strip():
        problems.append(
            "TOKEN_ENCRYPTION_KEY is empty; OAuth tokens would be stored unencrypted "
            "(generate: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\")"
        )
    return problems
