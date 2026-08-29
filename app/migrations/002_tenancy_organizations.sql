-- ORCH-69: multi-tenant foundation (users, organizations, memberships).
-- All future Control Room tables must reference organizations(id) as org_id.
-- Idempotent: IF NOT EXISTS / ON CONFLICT.

CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'standard',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT organizations_slug_format CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$'),
    CONSTRAINT organizations_status_check CHECK (status IN ('active', 'suspended', 'deleted'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_organizations_slug ON organizations (slug);
CREATE INDEX IF NOT EXISTS ix_organizations_status ON organizations (status);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL DEFAULT '',
    external_subject TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_email_format CHECK (position('@' IN email) > 1),
    CONSTRAINT users_status_check CHECK (status IN ('active', 'disabled', 'deleted'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email_lower ON users (lower(email));
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_external_subject
    ON users (external_subject)
    WHERE external_subject IS NOT NULL AND external_subject <> '';

CREATE TABLE IF NOT EXISTS memberships (
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, org_id),
    CONSTRAINT memberships_role_check CHECK (role IN ('owner', 'admin', 'member', 'viewer'))
);

CREATE INDEX IF NOT EXISTS ix_memberships_org ON memberships (org_id);
CREATE INDEX IF NOT EXISTS ix_memberships_user ON memberships (user_id);

-- Bootstrap singleton org so legacy scheduler jobs can attach during cutover.
INSERT INTO organizations (id, name, slug, plan, status)
VALUES (
    '00000000-0000-4000-8000-000000000001',
    'Default',
    'default',
    'standard',
    'active'
)
ON CONFLICT (id) DO NOTHING;

-- slug unique path if id conflict skipped but slug missing (re-run safe via slug)
INSERT INTO organizations (name, slug, plan, status)
SELECT 'Default', 'default', 'standard', 'active'
WHERE NOT EXISTS (SELECT 1 FROM organizations WHERE slug = 'default');
