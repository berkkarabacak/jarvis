-- ORCH-69: org-scoped API keys + append-only audit events (platform Postgres).
-- Secrets: only key_hash + key_prefix stored — never plaintext API keys.
-- Idempotent.

CREATE TABLE IF NOT EXISTS org_api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    scopes TEXT[] NOT NULL DEFAULT ARRAY['mission.read']::TEXT[],
    created_by UUID REFERENCES users (id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'active',
    CONSTRAINT org_api_keys_status_check CHECK (status IN ('active', 'revoked')),
    CONSTRAINT org_api_keys_prefix_len CHECK (char_length(key_prefix) BETWEEN 6 AND 16)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_org_api_keys_hash ON org_api_keys (key_hash);
CREATE INDEX IF NOT EXISTS ix_org_api_keys_org ON org_api_keys (org_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS ix_org_api_keys_prefix ON org_api_keys (key_prefix);

CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    actor_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
    actor_key_id UUID REFERENCES org_api_keys (id) ON DELETE SET NULL,
    actor_type TEXT NOT NULL DEFAULT 'system',
    event_type TEXT NOT NULL,
    resource_type TEXT NOT NULL DEFAULT '',
    resource_id TEXT NOT NULL DEFAULT '',
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT audit_events_actor_type_check
        CHECK (actor_type IN ('user', 'api_key', 'system', 'control_plane'))
);

CREATE INDEX IF NOT EXISTS ix_audit_events_org_created
    ON audit_events (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_events_org_type
    ON audit_events (org_id, event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_events_resource
    ON audit_events (org_id, resource_type, resource_id);
