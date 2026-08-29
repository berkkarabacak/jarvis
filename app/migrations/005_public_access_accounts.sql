-- ORCH-69: public account sessions, ownership, and deterministic usage windows.
-- Browser session plaintext is never stored; token_hash is SHA-256 of a
-- 256-bit opaque token. Current production uses the SQLite compatibility
-- adapter; these tables are the additive PostgreSQL durability contract.

CREATE TABLE IF NOT EXISTS account_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash TEXT NOT NULL,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    CONSTRAINT account_sessions_membership_fk
        FOREIGN KEY (user_id, org_id)
        REFERENCES memberships (user_id, org_id) ON DELETE CASCADE,
    CONSTRAINT account_sessions_token_hash_len CHECK (char_length(token_hash) = 64),
    CONSTRAINT account_sessions_expiry_order CHECK (expires_at > created_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_account_sessions_token_hash
    ON account_sessions (token_hash);
CREATE INDEX IF NOT EXISTS ix_account_sessions_user_active
    ON account_sessions (user_id, expires_at DESC)
    WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_account_sessions_expiry
    ON account_sessions (expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS account_resource_bindings (
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    org_id UUID NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    owner_user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (resource_type, resource_id),
    CONSTRAINT account_resource_membership_fk
        FOREIGN KEY (owner_user_id, org_id)
        REFERENCES memberships (user_id, org_id) ON DELETE CASCADE,
    CONSTRAINT account_resource_type_len
        CHECK (char_length(resource_type) BETWEEN 1 AND 64),
    CONSTRAINT account_resource_id_len
        CHECK (char_length(resource_id) BETWEEN 1 AND 160)
);

CREATE INDEX IF NOT EXISTS ix_account_resource_bindings_owner
    ON account_resource_bindings (org_id, owner_user_id, resource_type);

CREATE TABLE IF NOT EXISTS account_usage_windows (
    subject_key TEXT NOT NULL,
    quota_name TEXT NOT NULL,
    window_kind TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    used BIGINT NOT NULL,
    limit_value BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (subject_key, quota_name, window_kind, window_start),
    CONSTRAINT account_usage_window_kind
        CHECK (window_kind IN ('hour', 'day')),
    CONSTRAINT account_usage_nonnegative CHECK (used >= 0),
    CONSTRAINT account_usage_limit_positive CHECK (limit_value > 0),
    CONSTRAINT account_usage_subject_len CHECK (char_length(subject_key) BETWEEN 16 AND 160),
    CONSTRAINT account_usage_quota_name_len CHECK (char_length(quota_name) BETWEEN 2 AND 64)
);

CREATE INDEX IF NOT EXISTS ix_account_usage_windows_cleanup
    ON account_usage_windows (window_start, window_kind);
