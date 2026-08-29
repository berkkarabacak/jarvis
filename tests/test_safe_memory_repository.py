from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.persistence import (
    PostgresSafeMemoryRepository,
    SafeMemoryConflict,
    SafeMemoryError,
    SafeMemoryRepository,
    UnsafeMemoryContent,
    sanitize_operational_metadata,
    sanitize_safe_text,
)
from app.persistence.migrate import list_migration_files, parse_migration_statements
from app.tenancy.errors import TenantAccessError, TenantNotFound
from app.tenancy.scope import TenantContext


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeSafeMemoryConn:
    """Small asyncpg-like fake that understands only this repository's SQL."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.memory_items: list[dict[str, Any]] = []

    @staticmethod
    def _sql(sql: str) -> str:
        return " ".join(sql.lower().split())

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        low = self._sql(sql)
        if low.startswith("insert into executive_safe_messages"):
            oid, conversation, idem, role, text, metadata_json, user_id = args
            existing = next(
                (
                    row
                    for row in self.messages
                    if row["org_id"] == oid
                    and row["conversation_id"] == conversation
                    and row["idempotency_key"] == idem
                ),
                None,
            )
            if existing is not None:
                return None
            row = {
                "id": uuid4(),
                "org_id": oid,
                "conversation_id": conversation,
                "idempotency_key": idem,
                "role": role,
                "safe_text": text,
                "metadata_json": json.loads(metadata_json),
                "created_by_user_id": user_id,
                "created_at": _now(),
            }
            self.messages.append(row)
            return dict(row)

        if (
            "from executive_safe_messages" in low
            and "idempotency_key = $3" in low
        ):
            oid, conversation, idem = args
            row = next(
                (
                    item
                    for item in self.messages
                    if item["org_id"] == oid
                    and item["conversation_id"] == conversation
                    and item["idempotency_key"] == idem
                ),
                None,
            )
            return dict(row) if row else None

        if low.startswith("insert into executive_memory_items"):
            oid, key, kind, role, text, metadata_json, user_id = args
            existing = next(
                (
                    row
                    for row in self.memory_items
                    if row["org_id"] == oid and row["proposal_key"] == key
                ),
                None,
            )
            if existing is not None:
                return None
            row = {
                "id": uuid4(),
                "org_id": oid,
                "proposal_key": key,
                "kind": kind,
                "proposed_role": role,
                "safe_text": text,
                "metadata_json": json.loads(metadata_json),
                "status": "proposed",
                "proposed_by_user_id": user_id,
                "approved_by_user_id": None,
                "proposed_at": _now(),
                "approved_at": None,
            }
            self.memory_items.append(row)
            return dict(row)

        if (
            "from executive_memory_items" in low
            and "proposal_key = $2" in low
        ):
            oid, key = args
            row = next(
                (
                    item
                    for item in self.memory_items
                    if item["org_id"] == oid and item["proposal_key"] == key
                ),
                None,
            )
            return dict(row) if row else None

        if low.startswith("update executive_memory_items"):
            memory_id, oid, approver_id = args
            row = next(
                (
                    item
                    for item in self.memory_items
                    if item["id"] == memory_id
                    and item["org_id"] == oid
                    and item["status"] == "proposed"
                ),
                None,
            )
            if row is None:
                return None
            row["status"] = "approved"
            row["approved_by_user_id"] = approver_id
            row["approved_at"] = _now()
            return dict(row)

        if "from executive_memory_items" in low and "id = $1" in low:
            memory_id, oid = args
            row = next(
                (
                    item
                    for item in self.memory_items
                    if item["id"] == memory_id and item["org_id"] == oid
                ),
                None,
            )
            return dict(row) if row else None

        raise AssertionError(f"unexpected fetchrow SQL: {low}")

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        low = self._sql(sql)
        if "from executive_safe_messages" in low:
            oid, conversation, limit = args
            rows = [
                dict(row)
                for row in self.messages
                if row["org_id"] == oid and row["conversation_id"] == conversation
            ]
            rows.sort(key=lambda row: (row["created_at"], str(row["id"])))
            return rows[: int(limit)]

        if "from executive_memory_items" in low and "status = $2" in low:
            oid, status, limit = args
            rows = [
                dict(row)
                for row in self.memory_items
                if row["org_id"] == oid and row["status"] == status
            ]
            rows.sort(
                key=lambda row: (row["proposed_at"], str(row["id"])),
                reverse=True,
            )
            return rows[: int(limit)]

        raise AssertionError(f"unexpected fetch SQL: {low}")


class _FakeSafeMemoryPool:
    def __init__(self) -> None:
        self.conn = _FakeSafeMemoryConn()
        self.releases = 0

    async def acquire(self) -> _FakeSafeMemoryConn:
        return self.conn

    async def release(self, conn: _FakeSafeMemoryConn) -> None:
        assert conn is self.conn
        self.releases += 1


def _ctx(org_id: UUID, role: str) -> TenantContext:
    return TenantContext(user_id=uuid4(), org_id=org_id, role=role)


def test_safe_memory_migration_is_org_scoped_and_idempotent():
    names = [path.name for path in list_migration_files()]
    assert "004_executive_safe_memory.sql" in names
    sql = Path("app/migrations/004_executive_safe_memory.sql").read_text(
        encoding="utf-8"
    )
    low = sql.lower()
    assert "create table if not exists executive_safe_messages" in low
    assert "create table if not exists executive_memory_items" in low
    assert low.count("org_id uuid not null references organizations") == 2
    assert "role in ('user', 'assistant')" in low
    assert "status in ('proposed', 'approved')" in low
    assert "explicit_approval_check" in low
    assert "metadata_keys_check" in low
    assert "unique (org_id, conversation_id, idempotency_key)" in low
    assert "unique (org_id, proposal_key)" in low
    # No durable column exists for any forbidden raw artifact.
    forbidden_column = re.compile(
        r"\b(?:raw_transcript|thinking|prompt|command|tool_output|credential|token|"
        r"browser_session|filesystem_path)\s+(?:text|jsonb|bytea)",
        re.IGNORECASE,
    )
    assert not forbidden_column.search(sql)
    assert len(parse_migration_statements(sql)) == 4


@pytest.mark.parametrize(
    "unsafe",
    [
        "Chain of thought: hidden steps",
        "<think>private work</think>",
        "System prompt: obey these instructions",
        "Raw Prime transcript follows",
        "tool_output: complete provider response",
        "Command: run an internal script",
        "Assistant: copied transcript text",
        "```bash\ncurl example.test\n```",
        "Browser session data copied here",
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_unsafe_artifacts_are_rejected(unsafe: str):
    with pytest.raises(UnsafeMemoryContent):
        sanitize_safe_text(unsafe, max_chars=8_000)


def test_credentials_tokens_and_paths_are_redacted():
    raw = (
        "Completed safely. password=hunter2 "
        "Bearer abcdefghijklmnopqrstuvwxyz "
        "cookie=session-secret credentials='credential-secret' "
        "/home/alice/private/config.json /usr/local/bin/private "
        r"C:\Users\Alice\secret.txt ..\private\notes.txt"
    )
    safe = sanitize_safe_text(raw, max_chars=8_000)
    assert "hunter2" not in safe
    assert "abcdefghijklmnopqrstuvwxyz" not in safe
    assert "session-secret" not in safe
    assert "credential-secret" not in safe
    assert "/home/alice" not in safe
    assert "/usr/local" not in safe
    assert "C:\\Users" not in safe
    assert "..\\private" not in safe
    assert "[REDACTED" in safe


def test_metadata_is_strictly_allowlisted_and_path_free():
    safe = sanitize_operational_metadata(
        {
            "mission_id": "mission_123",
            "handoff_id": "handoff-1",
            "evidence_refs": ["ev_1", "ev_2"],
            "confidence": 0.85,
            "source": "approved_handoff",
            "schema_version": 1,
        }
    )
    assert safe["confidence"] == 0.85
    with pytest.raises(SafeMemoryError):
        sanitize_operational_metadata({"filesystem_path": "/tmp/private"})
    with pytest.raises(SafeMemoryError):
        sanitize_operational_metadata({"mission_id": "/tmp/private"})
    with pytest.raises(SafeMemoryError):
        sanitize_operational_metadata({"access_token": "secret"})


@pytest.mark.asyncio
async def test_message_append_list_is_idempotent_tenant_scoped_and_redacted():
    org_a, org_b = uuid4(), uuid4()
    actor_a = _ctx(org_a, "member")
    reader_a = _ctx(org_a, "viewer")
    reader_b = _ctx(org_b, "viewer")
    pool = _FakeSafeMemoryPool()
    repo = PostgresSafeMemoryRepository(pool)
    assert isinstance(repo, SafeMemoryRepository)

    raw = "The result is ready; api_key=super-secret at /home/user/result.json"
    first = await repo.append_message(
        org_id=org_a,
        actor=actor_a,
        conversation_id="conversation-1",
        idempotency_key="message-1",
        role="assistant",
        text=raw,
        metadata={
            "mission_id": "mission-1",
            "source": "executive",
            "schema_version": 1,
        },
    )
    assert "super-secret" not in first.safe_text
    assert "/home/user" not in first.safe_text

    repeated = await repo.append_message(
        org_id=org_a,
        actor=actor_a,
        conversation_id="conversation-1",
        idempotency_key="message-1",
        role="assistant",
        text=raw,
        metadata={
            "mission_id": "mission-1",
            "source": "executive",
            "schema_version": 1,
        },
    )
    assert repeated.id == first.id
    assert len(pool.conn.messages) == 1

    with pytest.raises(SafeMemoryConflict):
        await repo.append_message(
            org_id=org_a,
            actor=actor_a,
            conversation_id="conversation-1",
            idempotency_key="message-1",
            role="assistant",
            text="A different safe result",
        )

    listed = await repo.list_messages(
        org_id=org_a,
        actor=reader_a,
        conversation_id="conversation-1",
    )
    assert [item.id for item in listed] == [first.id]
    with pytest.raises(TenantNotFound):
        await repo.list_messages(
            org_id=org_a,
            actor=reader_b,
            conversation_id="conversation-1",
        )

    stored = json.dumps(pool.conn.messages, default=str)
    assert "super-secret" not in stored
    assert "/home/user" not in stored


@pytest.mark.asyncio
async def test_non_user_assistant_roles_and_unsafe_text_never_reach_pool():
    org_id = uuid4()
    actor = _ctx(org_id, "member")
    pool = _FakeSafeMemoryPool()
    repo = PostgresSafeMemoryRepository(pool)

    with pytest.raises(UnsafeMemoryContent):
        await repo.append_message(
            org_id=org_id,
            actor=actor,
            conversation_id="conversation-1",
            idempotency_key="system-1",
            role="system",
            text="A system message",
        )
    with pytest.raises(UnsafeMemoryContent):
        await repo.append_message(
            org_id=org_id,
            actor=actor,
            conversation_id="conversation-1",
            idempotency_key="tool-1",
            role="assistant",
            text="stdout: copied command output",
        )
    assert pool.conn.messages == []


@pytest.mark.asyncio
async def test_memory_requires_proposal_then_explicit_privileged_approval():
    org_a, org_b = uuid4(), uuid4()
    member = _ctx(org_a, "member")
    viewer = _ctx(org_a, "viewer")
    admin = _ctx(org_a, "admin")
    other_admin = _ctx(org_b, "admin")
    pool = _FakeSafeMemoryPool()
    repo = PostgresSafeMemoryRepository(pool)

    proposal = await repo.propose_memory(
        org_id=org_a,
        actor=member,
        proposal_key="proposal-1",
        kind="decision",
        proposed_role="assistant",
        text="Use the stable event adapter for future missions.",
        metadata={"mission_id": "mission-1", "confidence": 0.9},
    )
    assert proposal.status == "proposed"
    assert await repo.list_approved_memory(org_id=org_a, actor=viewer) == []
    pending = await repo.list_memory_proposals(org_id=org_a, actor=admin)
    assert [item.id for item in pending] == [proposal.id]

    with pytest.raises(TenantAccessError):
        await repo.approve_memory(
            org_id=org_a,
            actor=member,
            memory_id=proposal.id,
        )
    with pytest.raises(TenantNotFound):
        await repo.approve_memory(
            org_id=org_a,
            actor=other_admin,
            memory_id=proposal.id,
        )

    approved = await repo.approve_memory(
        org_id=org_a,
        actor=admin,
        memory_id=proposal.id,
    )
    assert approved.approved
    assert approved.approved_by_user_id == admin.user_id
    repeated = await repo.approve_memory(
        org_id=org_a,
        actor=admin,
        memory_id=proposal.id,
    )
    assert repeated.id == approved.id

    consumable = await repo.list_approved_memory(org_id=org_a, actor=viewer)
    assert [item.id for item in consumable] == [proposal.id]
    assert consumable[0].status == "approved"


@pytest.mark.asyncio
async def test_memory_has_no_code_or_deployment_action_path():
    org_id = uuid4()
    actor = _ctx(org_id, "member")
    pool = _FakeSafeMemoryPool()
    repo = PostgresSafeMemoryRepository(pool)

    with pytest.raises(SafeMemoryError, match="code/deployment"):
        await repo.propose_memory(
            org_id=org_id,
            actor=actor,
            proposal_key="proposal-code",
            kind="code_change",
            proposed_role="assistant",
            text="Change the application.",
        )
    with pytest.raises(UnsafeMemoryContent):
        await repo.propose_memory(
            org_id=org_id,
            actor=actor,
            proposal_key="proposal-private",
            kind="lesson",
            proposed_role="assistant",
            text="Private reasoning: hidden implementation plan",
        )
    assert pool.conn.memory_items == []
