from __future__ import annotations

import aiosqlite
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_tokens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token_enc TEXT NOT NULL DEFAULT '',
    refresh_token_enc TEXT NOT NULL DEFAULT '',
    expires_at REAL NOT NULL DEFAULT 0,
    token_endpoint TEXT NOT NULL DEFAULT '',
    redirect_uri TEXT NOT NULL DEFAULT '',
    token_type TEXT NOT NULL DEFAULT 'Bearer',
    needs_reauth INTEGER NOT NULL DEFAULT 0,
    provider_type TEXT NOT NULL DEFAULT 'oauth',
    updated_at REAL NOT NULL DEFAULT 0,
    last_refresh_at REAL,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    prompt_template TEXT NOT NULL,
    schedule TEXT,
    model TEXT NOT NULL,
    model_mode TEXT NOT NULL DEFAULT 'inherit',
    memory_doc TEXT NOT NULL DEFAULT '',
    memory_version INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    notify_email TEXT NOT NULL DEFAULT '',
    slack_on_success INTEGER NOT NULL DEFAULT 0,
    slack_on_failure INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    UNIQUE (job_id, version)
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    input_snapshot TEXT,
    result TEXT,
    raw_response TEXT,
    error TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    idempotency_key TEXT,
    llm_provider TEXT,
    model_requested TEXT,
    model_effective TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idempotency
    ON runs(job_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL AND idempotency_key != '';

CREATE INDEX IF NOT EXISTS idx_runs_job_started ON runs(job_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_versions_job ON memory_versions(job_id, version DESC);

CREATE TABLE IF NOT EXISTS oauth_pending (
    state TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    nonce TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    compacted INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memory_log_job_created
    ON memory_log(job_id, created_at DESC);

-- Multi-agent + shared/private memory (ORCH-38/39/40) — SQLite now, MySQL later
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT 'default',
    agent_type TEXT NOT NULL DEFAULT 'scheduler_worker',
    name TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agents_project ON agents(project_id);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT 'default',
    scope TEXT NOT NULL CHECK (scope IN ('shared', 'private')),
    owner_agent_id TEXT,
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (owner_agent_id) REFERENCES agents(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_project_scope ON memories(project_id, scope);
CREATE INDEX IF NOT EXISTS idx_memories_owner ON memories(owner_agent_id);

CREATE TABLE IF NOT EXISTS memory_acl (
    memory_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    can_read INTEGER NOT NULL DEFAULT 1,
    can_write INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (memory_id, agent_id),
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    agent_id TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_messages_run ON agent_messages(run_id);
CREATE INDEX IF NOT EXISTS idx_agent_messages_agent ON agent_messages(agent_id);

-- ORCH-69 public account/session compatibility store. The current production
-- app-data provider is SQLite; the equivalent durable target is migration 005.
CREATE TABLE IF NOT EXISTS public_accounts (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    account_kind TEXT NOT NULL DEFAULT 'guest',
    status TEXT NOT NULL DEFAULT 'active',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS public_organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS public_memberships (
    user_id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'owner',
    created_at REAL NOT NULL,
    PRIMARY KEY (user_id, org_id),
    FOREIGN KEY (user_id) REFERENCES public_accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (org_id) REFERENCES public_organizations(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_public_memberships_guest_org
    ON public_memberships(org_id);

CREATE TABLE IF NOT EXISTS public_account_sessions (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    revoked_at REAL,
    FOREIGN KEY (user_id) REFERENCES public_accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (org_id) REFERENCES public_organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, org_id) REFERENCES public_memberships(user_id, org_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_public_account_sessions_user
    ON public_account_sessions(user_id, expires_at DESC);
CREATE INDEX IF NOT EXISTS ix_public_account_sessions_active
    ON public_account_sessions(expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS public_resource_bindings (
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (resource_type, resource_id),
    FOREIGN KEY (owner_user_id) REFERENCES public_accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (org_id) REFERENCES public_organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (owner_user_id, org_id)
        REFERENCES public_memberships(user_id, org_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_public_resource_bindings_owner
    ON public_resource_bindings(org_id, owner_user_id, resource_type);

CREATE TABLE IF NOT EXISTS public_usage_quotas (
    subject_key TEXT NOT NULL,
    quota_name TEXT NOT NULL,
    hour_start INTEGER NOT NULL,
    hour_used INTEGER NOT NULL,
    day_start INTEGER NOT NULL,
    day_used INTEGER NOT NULL,
    hourly_limit INTEGER NOT NULL,
    daily_limit INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (subject_key, quota_name),
    CHECK (hour_used >= 0),
    CHECK (day_used >= 0),
    CHECK (hourly_limit > 0),
    CHECK (daily_limit > 0)
);

CREATE INDEX IF NOT EXISTS ix_public_usage_quotas_cleanup
    ON public_usage_quotas(day_start);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> aiosqlite.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self.path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL;")
            await self._conn.execute("PRAGMA foreign_keys=ON;")
            await self._conn.executescript(SCHEMA)
            await self._migrate(self._conn)
            await self._conn.commit()
        return self._conn

    async def _migrate(self, conn: aiosqlite.Connection) -> None:
        cur = await conn.execute("PRAGMA table_info(jobs)")
        cols = {row[1] for row in await cur.fetchall()}
        if "notify_email" not in cols:
            await conn.execute(
                "ALTER TABLE jobs ADD COLUMN notify_email TEXT NOT NULL DEFAULT ''"
            )
        if "slack_on_success" not in cols:
            await conn.execute(
                "ALTER TABLE jobs ADD COLUMN slack_on_success INTEGER NOT NULL DEFAULT 0"
            )
        if "slack_on_failure" not in cols:
            # Default: failure alerts only
            await conn.execute(
                "ALTER TABLE jobs ADD COLUMN slack_on_failure INTEGER NOT NULL DEFAULT 1"
            )
        if "model_mode" not in cols:
            await conn.execute(
                "ALTER TABLE jobs ADD COLUMN model_mode TEXT NOT NULL DEFAULT 'inherit'"
            )

        cur = await conn.execute("PRAGMA table_info(runs)")
        run_cols = {row[1] for row in await cur.fetchall()}
        if "llm_provider" not in run_cols:
            await conn.execute("ALTER TABLE runs ADD COLUMN llm_provider TEXT")
        if "model_requested" not in run_cols:
            await conn.execute("ALTER TABLE runs ADD COLUMN model_requested TEXT")
        if "model_effective" not in run_cols:
            await conn.execute("ALTER TABLE runs ADD COLUMN model_effective TEXT")

        # App settings (non-secret + encrypted secrets)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL DEFAULT 0
            )
            """
        )

        # Ensure multi-agent tables exist (for DBs created before this migration)
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL DEFAULT 'default',
                agent_type TEXT NOT NULL DEFAULT 'scheduler_worker',
                name TEXT NOT NULL,
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agents_project ON agents(project_id);
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL DEFAULT 'default',
                scope TEXT NOT NULL,
                owner_agent_id TEXT,
                title TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memories_project_scope ON memories(project_id, scope);
            CREATE INDEX IF NOT EXISTS idx_memories_owner ON memories(owner_agent_id);
            CREATE TABLE IF NOT EXISTS memory_acl (
                memory_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                can_read INTEGER NOT NULL DEFAULT 1,
                can_write INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (memory_id, agent_id)
            );
            CREATE TABLE IF NOT EXISTS agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                agent_id TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agent_messages_run ON agent_messages(run_id);
            """
        )

        # Seed default project + scheduler agent
        import time as _time

        now = _time.time()
        await conn.execute(
            """
            INSERT OR IGNORE INTO projects (id, name, created_at, updated_at)
            VALUES ('default', 'Default', ?, ?)
            """,
            (now, now),
        )
        await conn.execute(
            """
            INSERT OR IGNORE INTO agents (id, project_id, agent_type, name, config_json, created_at)
            VALUES ('scheduler-worker', 'default', 'scheduler_worker', 'Scheduler Worker', '{}', ?)
            """,
            (now,),
        )

        cur = await conn.execute("PRAGMA table_info(jobs)")
        job_cols = {row[1] for row in await cur.fetchall()}
        if "agent_id" not in job_cols:
            await conn.execute(
                "ALTER TABLE jobs ADD COLUMN agent_id TEXT NOT NULL DEFAULT 'scheduler-worker'"
            )
        if "project_id" not in job_cols:
            await conn.execute(
                "ALTER TABLE jobs ADD COLUMN project_id TEXT NOT NULL DEFAULT 'default'"
            )
        if "runner" not in job_cols:
            await conn.execute(
                "ALTER TABLE jobs ADD COLUMN runner TEXT NOT NULL DEFAULT 'llm'"
            )
        if "herdr_agent_kind" not in job_cols:
            await conn.execute(
                "ALTER TABLE jobs ADD COLUMN herdr_agent_kind TEXT NOT NULL DEFAULT ''"
            )
        if "herdr_agent_name" not in job_cols:
            await conn.execute(
                "ALTER TABLE jobs ADD COLUMN herdr_agent_name TEXT NOT NULL DEFAULT ''"
            )
        if "herdr_cwd" not in job_cols:
            await conn.execute(
                "ALTER TABLE jobs ADD COLUMN herdr_cwd TEXT NOT NULL DEFAULT ''"
            )
        if "herdr_workspace_label" not in job_cols:
            await conn.execute(
                "ALTER TABLE jobs ADD COLUMN herdr_workspace_label TEXT NOT NULL DEFAULT ''"
            )
        if "herdr_extra_args" not in job_cols:
            await conn.execute(
                "ALTER TABLE jobs ADD COLUMN herdr_extra_args TEXT NOT NULL DEFAULT '[]'"
            )

        # ORCH-71 executive handoffs (structured, auditable)
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS executive_handoffs (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                memory_scope TEXT NOT NULL,
                seq INTEGER NOT NULL,
                packet_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_exec_handoffs_mission_seq
                ON executive_handoffs(mission_id, seq);
            CREATE INDEX IF NOT EXISTS idx_exec_handoffs_session
                ON executive_handoffs(session_id, created_at);
            """
        )


    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected")
        return self._conn
