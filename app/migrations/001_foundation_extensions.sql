-- ORCH-69 foundation: extensions for Control Room Postgres.
-- Target: PostgreSQL (TencentDB PostgreSQL or compatible).
-- Idempotent: IF NOT EXISTS throughout.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- optional: pgvector
-- Semantic memory (D-007). Skipped when host has no vector extension and
-- POSTGRES_PGVECTOR_REQUIRED is false (migrator treats optional failures as skip).
CREATE EXTENSION IF NOT EXISTS "vector";
