from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.persistence.migrate import list_migration_files, parse_migration_statements
from app.tenancy.errors import TenantAccessError, TenantNotFound
from app.tenancy.memory_db import MemoryPool
from app.tenancy.models import (
    BOOTSTRAP_ORG_ID,
    BOOTSTRAP_ORG_SLUG,
    role_allows,
    require_org_id,
)
from app.tenancy.scope import TenantContext
from app.tenancy.store import TenancyStore


def test_tenancy_migration_present():
    names = [p.name for p in list_migration_files()]
    assert "002_tenancy_organizations.sql" in names
    sql = Path("app/migrations/002_tenancy_organizations.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS organizations" in sql
    assert "CREATE TABLE IF NOT EXISTS users" in sql
    assert "CREATE TABLE IF NOT EXISTS memberships" in sql
    assert "default" in sql
    stmts = parse_migration_statements(sql)
    assert len(stmts) >= 5


def test_role_capabilities():
    assert role_allows("owner", "members.manage")
    assert role_allows("admin", "budget.manage")
    assert role_allows("member", "mission.run")
    assert not role_allows("viewer", "mission.run")
    assert role_allows("viewer", "mission.read")
    assert not role_allows("member", "members.manage")


def test_require_org_id_guard():
    with pytest.raises(ValueError, match="org_id"):
        require_org_id(None)
    assert require_org_id(BOOTSTRAP_ORG_ID) == BOOTSTRAP_ORG_ID


def test_tenant_context_require():
    ctx = TenantContext(user_id=uuid4(), org_id=BOOTSTRAP_ORG_ID, role="viewer")
    ctx.require("mission.read")
    with pytest.raises(TenantAccessError):
        ctx.require("mission.run")


@pytest.mark.asyncio
async def test_tenancy_store_bootstrap_and_membership():
    pool = MemoryPool()
    store = TenancyStore(pool)

    boot = await store.get_bootstrap_org()
    assert boot.slug == BOOTSTRAP_ORG_SLUG
    assert boot.id == BOOTSTRAP_ORG_ID

    other = await store.create_organization(name="Acme", slug="acme-co")
    assert other.slug == "acme-co"

    user = await store.create_user(email="ceo@acme.test", display_name="CEO")
    mem = await store.add_membership(user_id=user.id, org_id=other.id, role="owner")
    assert mem.role == "owner"

    ctx = await store.tenant_context(user.id, other.id)
    assert ctx.role == "owner"
    members = await store.list_org_members(other.id, actor=ctx)
    assert len(members) == 1
    assert members[0]["email"] == "ceo@acme.test"


@pytest.mark.asyncio
async def test_cross_org_is_not_found():
    pool = MemoryPool()
    store = TenancyStore(pool)
    org_a = await store.create_organization(name="A", slug="org-a1")
    org_b = await store.create_organization(name="B", slug="org-b1")
    user = await store.create_user(email="u@x.test")
    await store.add_membership(user_id=user.id, org_id=org_a.id, role="member")

    with pytest.raises(TenantNotFound):
        await store.require_membership(user.id, org_b.id)

    with pytest.raises(TenantNotFound):
        await store.tenant_context(user.id, org_b.id)

    ctx = await store.tenant_context(user.id, org_a.id)
    with pytest.raises(TenantNotFound):
        await store.list_org_members(org_b.id, actor=ctx)


@pytest.mark.asyncio
async def test_missing_org_is_not_found():
    pool = MemoryPool()
    store = TenancyStore(pool)
    with pytest.raises(TenantNotFound):
        await store.require_organization(uuid4())


def test_api_key_migration_present():
    names = [p.name for p in list_migration_files()]
    assert "003_org_api_keys_audit.sql" in names
    sql = Path("app/migrations/003_org_api_keys_audit.sql").read_text(encoding="utf-8")
    assert "org_api_keys" in sql
    assert "key_hash" in sql
    assert "audit_events" in sql
    assert "key_hash" in sql and "password" not in sql.lower()
    # No column stores raw secrets
    assert "api_key_plain" not in sql.lower()
    assert "secret_value" not in sql.lower()


def test_key_hash_helpers():
    from app.tenancy.keys import generate_api_key, hash_api_key, redact_key_for_log, verify_api_key

    plain, prefix, digest = generate_api_key()
    assert plain.startswith("ao_")
    assert prefix == plain[:10]
    assert verify_api_key(plain, digest)
    assert not verify_api_key(plain + "x", digest)
    assert hash_api_key(plain) == digest
    red = redact_key_for_log(plain)
    assert plain not in red
    assert "…" in red or "***" in red


@pytest.mark.asyncio
async def test_org_api_keys_and_audit_isolation():
    pool = MemoryPool()
    store = TenancyStore(pool)
    org_a = await store.create_organization(name="A", slug="keys-a1")
    org_b = await store.create_organization(name="B", slug="keys-b1")
    user_a = await store.create_user(email="owner-a@test.example")
    user_b = await store.create_user(email="owner-b@test.example")
    await store.add_membership(user_id=user_a.id, org_id=org_a.id, role="owner")
    await store.add_membership(user_id=user_b.id, org_id=org_b.id, role="owner")
    ctx_a = await store.tenant_context(user_a.id, org_a.id)
    ctx_b = await store.tenant_context(user_b.id, org_b.id)

    meta, plaintext = await store.create_org_api_key(
        org_id=org_a.id, actor=ctx_a, name="ci", scopes=["mission.read", "mission.run"]
    )
    assert meta.org_id == org_a.id
    assert meta.key_prefix
    assert "key_hash" not in meta.to_dict()
    assert plaintext.startswith("ao_")

    # auth works
    got = await store.authenticate_org_api_key(plaintext)
    assert got is not None
    assert got[0].id == meta.id
    assert got[1] == org_a.id

    # cross-org list blocked
    with pytest.raises(TenantNotFound):
        await store.list_org_api_keys(org_a.id, actor=ctx_b)

    keys_a = await store.list_org_api_keys(org_a.id, actor=ctx_a)
    assert len(keys_a) == 1
    assert keys_a[0].id == meta.id

    # audit only for org A
    events_a = await store.list_audit_events(org_a.id, actor=ctx_a)
    assert any(e.event_type == "api_key.created" for e in events_a)
    for e in events_a:
        assert e.org_id == org_a.id
        assert "key_hash" not in (e.detail or {})
        assert plaintext not in str(e.detail)

    with pytest.raises(TenantNotFound):
        await store.list_audit_events(org_a.id, actor=ctx_b)

    # revoke + auth fails
    revoked = await store.revoke_org_api_key(org_a.id, meta.id, actor=ctx_a)
    assert revoked.status == "revoked"
    assert await store.authenticate_org_api_key(plaintext) is None

    events_a2 = await store.list_audit_events(org_a.id, actor=ctx_a)
    assert any(e.event_type == "api_key.revoked" for e in events_a2)

    # org B has empty audit
    events_b = await store.list_audit_events(org_b.id, actor=ctx_b)
    assert events_b == []
