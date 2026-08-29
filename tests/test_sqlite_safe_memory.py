from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from app.db import Database
from app.persistence.safe_memory import (
    SafeMemoryConflict,
    SafeMemoryRepository,
    UnsafeMemoryContent,
)
from app.persistence.sqlite_safe_memory import SqliteSafeMemoryRepository
from app.tenancy.errors import TenantAccessError, TenantNotFound
from app.tenancy.scope import TenantContext

ORG_ID = UUID("00000000-0000-4000-8000-000000000001")


def _actor(role: str = "owner", *, org_id: UUID = ORG_ID) -> TenantContext:
    return TenantContext(user_id=uuid4(), org_id=org_id, role=role)


@pytest.mark.asyncio
async def test_sqlite_safe_memory_authorization_idempotency_and_restart(tmp_path):
    path = tmp_path / "approved-memory.db"
    db = Database(path)
    await db.connect()
    repo = SqliteSafeMemoryRepository(db)
    await repo.ensure_schema()
    owner = _actor()
    member = _actor("member")
    assert isinstance(repo, SafeMemoryRepository)

    proposal = await repo.propose_memory(
        org_id=ORG_ID,
        actor=member,
        proposal_key="preference-1",
        kind="preference",
        proposed_role="user",
        text="Prefer concise executive summaries.",
        metadata={"source": "user", "schema_version": 1},
    )
    duplicate = await repo.propose_memory(
        org_id=ORG_ID,
        actor=member,
        proposal_key="preference-1",
        kind="preference",
        proposed_role="user",
        text="Prefer concise executive summaries.",
        metadata={"source": "user", "schema_version": 1},
    )
    assert duplicate.id == proposal.id
    assert await repo.list_approved_memory(org_id=ORG_ID, actor=owner) == []
    assert [
        row.id for row in await repo.list_memory_proposals(org_id=ORG_ID, actor=owner)
    ] == [proposal.id]

    with pytest.raises(TenantAccessError):
        await repo.approve_memory(org_id=ORG_ID, actor=member, memory_id=proposal.id)
    with pytest.raises(TenantNotFound):
        await repo.approve_memory(
            org_id=ORG_ID,
            actor=_actor(org_id=uuid4()),
            memory_id=proposal.id,
        )
    with pytest.raises(SafeMemoryConflict):
        await repo.propose_memory(
            org_id=ORG_ID,
            actor=owner,
            proposal_key="preference-1",
            kind="fact",
            proposed_role="user",
            text="A different payload.",
        )

    approved = await repo.approve_memory(
        org_id=ORG_ID, actor=owner, memory_id=proposal.id
    )
    approved_again = await repo.approve_memory(
        org_id=ORG_ID, actor=owner, memory_id=proposal.id
    )
    assert approved_again.id == approved.id
    assert approved.approved is True
    assert approved.approved_by_user_id == owner.user_id
    assert approved.to_dict()["approved_at"] is not None

    first, second = await asyncio.gather(
        *(
            repo.propose_memory(
                org_id=ORG_ID,
                actor=owner,
                proposal_key="concurrent-idempotency",
                kind="fact",
                proposed_role="user",
                text="The company uses short status reports.",
            )
            for _ in range(2)
        )
    )
    assert first.id == second.id

    message = await repo.append_message(
        org_id=ORG_ID,
        actor=owner,
        conversation_id="conversation-1",
        idempotency_key="message-1",
        role="user",
        text="A safe bounded note.",
    )
    same_message = await repo.append_message(
        org_id=ORG_ID,
        actor=owner,
        conversation_id="conversation-1",
        idempotency_key="message-1",
        role="user",
        text="A safe bounded note.",
    )
    assert same_message.id == message.id
    with pytest.raises(SafeMemoryConflict):
        await repo.append_message(
            org_id=ORG_ID,
            actor=owner,
            conversation_id="conversation-1",
            idempotency_key="message-1",
            role="assistant",
            text="A different note.",
        )
    with pytest.raises(UnsafeMemoryContent):
        await repo.propose_memory(
            org_id=ORG_ID,
            actor=owner,
            proposal_key="unsafe-private-reasoning",
            kind="fact",
            proposed_role="user",
            text="Private reasoning: do not store this.",
        )

    await db.close()
    reopened = Database(path)
    await reopened.connect()
    reopened_repo = SqliteSafeMemoryRepository(reopened)
    await reopened_repo.ensure_schema()
    try:
        persisted = await reopened_repo.list_approved_memory(org_id=ORG_ID, actor=owner)
        assert [row.id for row in persisted] == [approved.id]
        messages = await reopened_repo.list_messages(
            org_id=ORG_ID,
            actor=owner,
            conversation_id="conversation-1",
        )
        assert [row.id for row in messages] == [message.id]
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_disabled_preview_does_not_create_memory_schema(tmp_path):
    from app.executive.memory_bridge import (
        build_executive_memory_bridge_from_environment,
    )

    db = Database(tmp_path / "disabled.db")
    await db.connect()
    try:
        assert await build_executive_memory_bridge_from_environment(db, {}) is None
        cursor = await db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name LIKE 'executive_%memory%'"
        )
        assert await cursor.fetchall() == []
    finally:
        await db.close()
