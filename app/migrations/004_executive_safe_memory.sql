-- ORCH-69: durable, tenant-scoped executive-safe conversation and memory data.
-- This schema intentionally has no fields for prompts, private reasoning, raw
-- transcripts, commands, tool output, credentials, browser/session data, or paths.
-- Memory is proposal/approval only; approved rows are the sole consumption path.
-- Idempotent: IF NOT EXISTS throughout.

CREATE TABLE IF NOT EXISTS executive_safe_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    role TEXT NOT NULL,
    safe_text TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT executive_safe_messages_role_check
        CHECK (role IN ('user', 'assistant')),
    CONSTRAINT executive_safe_messages_text_len
        CHECK (char_length(safe_text) BETWEEN 1 AND 8000),
    CONSTRAINT executive_safe_messages_conversation_id_check
        CHECK (conversation_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
    CONSTRAINT executive_safe_messages_idempotency_key_check
        CHECK (idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
    CONSTRAINT executive_safe_messages_metadata_object_check
        CHECK (jsonb_typeof(metadata_json) = 'object'),
    CONSTRAINT executive_safe_messages_metadata_keys_check
        CHECK (
            metadata_json - ARRAY[
                'mission_id', 'handoff_id', 'evidence_refs',
                'confidence', 'source', 'schema_version'
            ]::TEXT[] = '{}'::jsonb
        ),
    CONSTRAINT executive_safe_messages_metadata_size_check
        CHECK (octet_length(metadata_json::text) <= 4096),
    CONSTRAINT executive_safe_messages_obvious_unsafe_text_check
        CHECK (
            lower(safe_text) NOT LIKE '%<think>%' AND
            lower(safe_text) NOT LIKE '%chain of thought%' AND
            lower(safe_text) NOT LIKE '%private reasoning%' AND
            lower(safe_text) NOT LIKE '%system prompt%' AND
            lower(safe_text) NOT LIKE '%developer prompt%' AND
            lower(safe_text) NOT LIKE '%raw transcript%' AND
            lower(safe_text) NOT LIKE '%tool output%' AND
            lower(safe_text) NOT LIKE '%tool_output%' AND
            lower(safe_text) NOT LIKE '%browser session%' AND
            lower(safe_text) NOT LIKE '%localstorage%' AND
            lower(safe_text) NOT LIKE '%begin private key%'
        ),
    UNIQUE (org_id, conversation_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_executive_safe_messages_org_conversation
    ON executive_safe_messages (org_id, conversation_id, created_at, id);

CREATE TABLE IF NOT EXISTS executive_memory_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    proposal_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    proposed_role TEXT NOT NULL,
    safe_text TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'proposed',
    proposed_by_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
    approved_by_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    CONSTRAINT executive_memory_items_kind_check
        CHECK (kind IN ('preference', 'decision', 'fact', 'lesson')),
    CONSTRAINT executive_memory_items_role_check
        CHECK (proposed_role IN ('user', 'assistant')),
    CONSTRAINT executive_memory_items_status_check
        CHECK (status IN ('proposed', 'approved')),
    CONSTRAINT executive_memory_items_text_len
        CHECK (char_length(safe_text) BETWEEN 1 AND 4000),
    CONSTRAINT executive_memory_items_proposal_key_check
        CHECK (proposal_key ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
    CONSTRAINT executive_memory_items_metadata_object_check
        CHECK (jsonb_typeof(metadata_json) = 'object'),
    CONSTRAINT executive_memory_items_metadata_keys_check
        CHECK (
            metadata_json - ARRAY[
                'mission_id', 'handoff_id', 'evidence_refs',
                'confidence', 'source', 'schema_version'
            ]::TEXT[] = '{}'::jsonb
        ),
    CONSTRAINT executive_memory_items_metadata_size_check
        CHECK (octet_length(metadata_json::text) <= 4096),
    CONSTRAINT executive_memory_items_obvious_unsafe_text_check
        CHECK (
            lower(safe_text) NOT LIKE '%<think>%' AND
            lower(safe_text) NOT LIKE '%chain of thought%' AND
            lower(safe_text) NOT LIKE '%private reasoning%' AND
            lower(safe_text) NOT LIKE '%system prompt%' AND
            lower(safe_text) NOT LIKE '%developer prompt%' AND
            lower(safe_text) NOT LIKE '%raw transcript%' AND
            lower(safe_text) NOT LIKE '%tool output%' AND
            lower(safe_text) NOT LIKE '%tool_output%' AND
            lower(safe_text) NOT LIKE '%browser session%' AND
            lower(safe_text) NOT LIKE '%localstorage%' AND
            lower(safe_text) NOT LIKE '%begin private key%'
        ),
    CONSTRAINT executive_memory_items_explicit_approval_check
        CHECK (
            (status = 'proposed' AND approved_by_user_id IS NULL AND approved_at IS NULL)
            OR
            (status = 'approved' AND approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL)
        ),
    UNIQUE (org_id, proposal_key)
);

CREATE INDEX IF NOT EXISTS ix_executive_memory_items_org_status
    ON executive_memory_items (org_id, status, proposed_at DESC, id);
