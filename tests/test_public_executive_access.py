from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.control_plane.service import build_control_plane
from app.db import Database
from app.executive.memory_policy import ExecutiveMemoryPolicy
from app.public_access.errors import AccountResourceNotFound
from app.public_access.executive_routes import (
    PUBLIC_ACCOUNT_OPEN_DAILY_LIMIT,
    PUBLIC_ACCOUNT_OPEN_HOURLY_LIMIT,
    PUBLIC_ACCOUNT_TURN_DAILY_LIMIT,
    PUBLIC_ACCOUNT_TURN_HOURLY_LIMIT,
    PUBLIC_GATE_CODE_HEADER,
    PUBLIC_GUEST_EXECUTION_PROFILE,
    PublicExecutiveGateway,
    PublicExecutiveTurnError,
    _attach_safe_publication,
)
from app.public_access.routes import public_router
from app.public_access.security import (
    PUBLIC_MUTATION_HEADER,
    PUBLIC_MUTATION_HEADER_VALUE,
    PUBLIC_SESSION_COOKIE_NAME,
    derive_account_subject_key,
)
from app.public_access.store import SqlitePublicAccessStore

STRONG_SECRET = "public-test-secret-" + ("a" * 48)
MUTATION_HEADERS = {
    "Origin": "https://test",
    PUBLIC_MUTATION_HEADER: PUBLIC_MUTATION_HEADER_VALUE,
}


@dataclass
class _FakeSpecialist:
    instance_id: str
    role_name: str = "executive"
    status: str = "active"


@dataclass
class _FakeSession:
    session_id: str
    mission_id: str
    status: str
    specialists: dict[str, _FakeSpecialist]


class _FakeRegistry:
    def __init__(self) -> None:
        self.sessions: dict[str, _FakeSession] = {}

    def get(self, session_id: str) -> _FakeSession | None:
        return self.sessions.get(session_id)

    def drop(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)


class _FakePrime:
    def __init__(self) -> None:
        self.states: dict[str, str] = {}
        self.process_handles: set[str] = set()
        self.stop_reasons: list[str] = []

    async def list_sessions(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(session_id=session_id, status=status)
            for session_id, status in self.states.items()
        ]

    async def stop_session(self, session_id: str, *, reason: str) -> None:
        self.stop_reasons.append(reason)
        if session_id in self.states:
            self.states[session_id] = "stopped"
        self.process_handles.discard(session_id)

    @property
    def active_handles(self) -> set[str]:
        return set(self.process_handles)


class _FakeRuntime:
    def __init__(self) -> None:
        self.registry = _FakeRegistry()
        self.prime = _FakePrime()
        self.open_calls: list[dict[str, Any]] = []
        self.send_calls: list[tuple[str, str]] = []
        self.stop_calls: list[tuple[str, str]] = []
        self.invalid_public_gate = False
        self.metering_overrides: dict[str, Any] = {}
        self.snapshot_overrides: dict[str, Any] = {}
        self.block_send = False
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()
        self._sequence = 0

    async def open_mission(
        self,
        *,
        mission_id: str,
        brief: str,
        memory_policy: ExecutiveMemoryPolicy,
        execution_profile: str,
    ) -> _FakeSession:
        self._sequence += 1
        session_id = f"public-session-{self._sequence}"
        prime_id = f"prime-session-{self._sequence}"
        session = _FakeSession(
            session_id=session_id,
            mission_id=mission_id,
            status="active",
            specialists={prime_id: _FakeSpecialist(prime_id)},
        )
        self.registry.sessions[session_id] = session
        self.prime.states[prime_id] = "active"
        self.prime.process_handles.add(prime_id)
        self.open_calls.append(
            {
                "mission_id": mission_id,
                "brief": brief,
                "memory_policy": memory_policy,
                "execution_profile": execution_profile,
            }
        )
        return session

    def snapshot(self, session_id: str) -> dict[str, Any]:
        session = self.registry.sessions[session_id]
        snapshot = {
            "session_id": session.session_id,
            "mission_id": session.mission_id,
            "status": session.status,
            "confidence": {"score": 82},
            "evidence_count": 1,
            "specialists": [
                {"role_name": item.role_name, "status": item.status}
                for item in session.specialists.values()
            ],
            "private_runtime_state": "must-not-cross-public-boundary",
        }
        snapshot.update(self.snapshot_overrides)
        return snapshot

    async def send_message(self, session_id: str, *, message: str) -> dict[str, Any]:
        self.send_calls.append((session_id, message))
        self.send_started.set()
        if self.block_send:
            await self.release_send.wait()
        session = self.registry.sessions[session_id]
        message_id = f"message-{len(self.send_calls)}"
        text = "Final safe answer."
        metering = {
            "contract": "orch.executive.public-guest-turn",
            "contract_version": "1.0",
            "profile": PUBLIC_GUEST_EXECUTION_PROFILE,
            "target_cost_usd": "0.03",
            "hard_cost_usd": "0.10",
            "max_total_tokens": 12_000,
            "max_context_tokens_per_generation": 3_000,
            "max_output_tokens_per_generation": 600,
            "model_selector": "openrouter/auto",
            "provider_max_price": {
                "prompt": "1",
                "completion": "5",
                "request": "0",
                "image": "0",
                "audio": "0",
            },
            "fresh_process_context": True,
            "auto_compaction": "disabled",
            "worker_limit": 2,
            "turn_number": len(self.send_calls),
            "peak_active_workers": 2,
            "passed": not self.invalid_public_gate,
            "failure_reason": "telemetry_unavailable"
            if self.invalid_public_gate
            else None,
            "requires_fresh_mission": False,
            "actual_cost_usd": "0.0025",
            "total_tokens": 120,
            "generation_count": 3,
            "telemetry_complete": not self.invalid_public_gate,
            "target_met": True,
            "hard_limits_passed": not self.invalid_public_gate,
            "generation_id": "internal-generation-id",
            "selected_model": "internal/model-name",
        }
        metering.update(self.metering_overrides)
        return {
            "message": {
                "message_id": message_id,
                "text": text,
                "safety_filtered": False,
            },
            "snapshot": self.snapshot(session_id),
            "delegations": [
                {"role": "researcher", "status": "completed", "prompt": "private"}
            ],
            "public_guest": metering,
            "event_batch": _safe_event_batch(session.mission_id, message_id, text),
            "credential": "must-not-cross-public-boundary",
        }

    async def stop_mission(
        self,
        session_id: str,
        *,
        reason: str,
        status: str,
    ) -> _FakeSession:
        self.stop_calls.append((session_id, reason))
        session = self.registry.sessions[session_id]
        for specialist in session.specialists.values():
            await self.prime.stop_session(specialist.instance_id, reason=reason)
            specialist.status = "stopped"
        session.status = status
        return session


def _safe_event_batch(mission_id: str, message_id: str, text: str) -> dict[str, Any]:
    return {
        "target_contract": "orch.control-plane.event",
        "target_contract_version": "1.0",
        "mission_id": mission_id,
        "authorization": "required_at_orch70_publish_adapter",
        "events": [
            {
                "type": "executive_message",
                "data": {
                    "summary": text,
                    "severity": "info",
                    "action_required": False,
                },
            },
            {
                "type": "evidence",
                "data": {
                    "evidence_id": message_id,
                    "kind": "trace",
                    "reference_id": f"prime-turn:{message_id}",
                    "label": "Public executive turn completed",
                    "verification_status": "verified",
                },
            },
            {
                "type": "confidence",
                "data": {
                    "subject_type": "mission",
                    "subject_id": mission_id,
                    "score": 82,
                    "basis": ["status", "evidence"],
                },
            },
        ],
    }


@dataclass
class _Stack:
    app: FastAPI
    client: AsyncClient
    db: Database
    store: SqlitePublicAccessStore
    control_plane: Any
    runtime: _FakeRuntime
    gateway: PublicExecutiveGateway


@pytest.fixture
async def public_stack(tmp_path):
    db = Database(tmp_path / "public-executive.db")
    await db.connect()
    store = SqlitePublicAccessStore(db)
    control_plane = build_control_plane(db)
    await control_plane.ensure_ready()
    runtime = _FakeRuntime()
    gateway = PublicExecutiveGateway(
        runtime=runtime,  # type: ignore[arg-type]
        control_plane=control_plane,
        store=store,
        server_secret=STRONG_SECRET,
        idle_seconds=60.0,
        sweep_interval_seconds=3_600.0,
        turn_timeout_seconds=2.0,
        cleanup_timeout_seconds=1.0,
    )
    await gateway.start()
    app = FastAPI()
    from app.main import _public_no_store_middleware

    app.middleware("http")(_public_no_store_middleware)
    app.state.settings = SimpleNamespace(api_secret=STRONG_SECRET)
    app.state.public_access_store = store
    app.state.public_executive_gateway = gateway
    app.include_router(public_router)
    transport = ASGITransport(app=app, client=("127.0.0.1", 43120))
    client = AsyncClient(transport=transport, base_url="https://test")
    stack = _Stack(app, client, db, store, control_plane, runtime, gateway)
    try:
        yield stack
    finally:
        await client.aclose()
        await gateway.close()
        await db.close()


async def _bootstrap(client: AsyncClient) -> dict[str, Any]:
    response = await client.post("/api/public/session", headers=MUTATION_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


async def _principal(stack: _Stack, client: AsyncClient | None = None):
    source = client or stack.client
    token = source.cookies.get(PUBLIC_SESSION_COOKIE_NAME)
    principal = await stack.store.resolve_session(token)
    assert principal is not None
    return principal


async def _open(client: AsyncClient, brief: str = "Run a safe public mission"):
    response = await client.post(
        "/api/public/executive/missions",
        headers=MUTATION_HEADERS,
        json={"brief": brief},
    )
    assert response.status_code == 200, response.text
    return response


@pytest.mark.asyncio
async def test_cookie_public_lifecycle_is_tenant_bound_memory_disabled_and_safe(
    public_stack,
):
    stack = public_stack
    account = await _bootstrap(stack.client)
    opened = await _open(stack.client)
    snapshot = opened.json()
    session_id = snapshot["session_id"]
    mission_id = snapshot["mission_id"]

    assert opened.headers["cache-control"] == "no-store, private"
    assert stack.runtime.open_calls[0]["execution_profile"] == (
        PUBLIC_GUEST_EXECUTION_PROFILE
    )
    policy = stack.runtime.open_calls[0]["memory_policy"]
    assert isinstance(policy, ExecutiveMemoryPolicy)
    assert policy.approved_persistent_memory is False
    principal = await _principal(stack)
    mission = await stack.control_plane.get_mission(mission_id)
    assert mission is not None
    assert mission.org_id == str(principal.org_id) == account["organization"]["id"]

    presence = await stack.client.get("/api/public/presence")
    assert presence.status_code == 200
    assert presence.headers["cache-control"] == "no-store, private"
    assert presence.json()["session_id"] == session_id
    assert presence.json()["mission_id"] == mission_id
    assert presence.json()["mocked"] is False

    # A page reload recovers the same owned session without exposing credentials.
    reloaded = await stack.client.get("/api/public/presence")
    assert reloaded.json()["session_id"] == session_id

    turn = await stack.client.post(
        f"/api/public/executive/sessions/{session_id}/messages",
        headers=MUTATION_HEADERS,
        json={"message": "Continue safely"},
    )
    assert turn.status_code == 200, turn.text
    body = turn.json()
    assert body["message"]["text"] == "Final safe answer."
    assert body["event_publication"]["persisted"] is True
    assert body["metering"] == {
        "actual_cost_usd": "0.0025",
        "total_tokens": 120,
        "generation_count": 3,
        "telemetry_complete": True,
        "target_met": True,
        "hard_limits_passed": True,
        "limits": {
            "target_cost_usd": "0.03",
            "hard_cost_usd": "0.10",
            "max_total_tokens": 12_000,
        },
    }
    encoded = str(body).lower()
    for forbidden in (
        "credential",
        "private_runtime_state",
        "internal-generation-id",
        "internal/model-name",
        "prompt",
        "api_secret",
    ):
        assert forbidden not in encoded

    stopped = await stack.client.post(
        f"/api/public/executive/sessions/{session_id}/stop",
        headers=MUTATION_HEADERS,
        json={"status": "stopped", "reason": "ceo_stopped"},
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "stopped"
    assert stopped.headers["cache-control"] == "no-store, private"
    assert stack.runtime.prime.active_handles == set()
    assert stack.runtime.registry.get(session_id) is None
    assert (await stack.gateway.safe_state())["active_sessions"] == 0


@pytest.mark.asyncio
async def test_cross_cookie_malformed_ids_and_forged_tenant_fields_are_leak_safe(
    public_stack,
):
    stack = public_stack
    await _bootstrap(stack.client)
    opened = await _open(stack.client)
    session_id = opened.json()["session_id"]
    initial_opens = len(stack.runtime.open_calls)

    csrf_rejected = await stack.client.post(
        "/api/public/executive/missions",
        json={"brief": "missing the browser mutation proof"},
    )
    assert csrf_rejected.status_code == 403
    assert csrf_rejected.headers["cache-control"] == "no-store, private"
    assert len(stack.runtime.open_calls) == initial_opens

    forged = await stack.client.post(
        "/api/public/executive/missions",
        headers=MUTATION_HEADERS,
        json={
            "brief": "forged",
            "org_id": "00000000-0000-4000-8000-000000000999",
            "memory_policy": {"approved_persistent_memory": True},
        },
    )
    assert forged.status_code == 422
    assert forged.headers["cache-control"] == "no-store, private"
    assert len(stack.runtime.open_calls) == initial_opens

    other_transport = ASGITransport(app=stack.app, client=("127.0.0.1", 43121))
    async with AsyncClient(transport=other_transport, base_url="https://test") as other:
        await _bootstrap(other)
        for path in (
            f"/api/public/executive/sessions/{session_id}/messages",
            "/api/public/executive/sessions/not%20an%20id/messages",
        ):
            denied = await other.post(
                path,
                headers=MUTATION_HEADERS,
                json={"message": "try to cross tenants"},
            )
            assert denied.status_code == 404
            assert denied.json() == {"detail": "Not found"}
            assert denied.headers["cache-control"] == "no-store, private"
        denied_stop = await other.post(
            f"/api/public/executive/sessions/{session_id}/stop",
            headers=MUTATION_HEADERS,
            json={"status": "stopped", "reason": "cross_tenant"},
        )
        assert denied_stop.status_code == 404
        assert denied_stop.json() == {"detail": "Not found"}

    assert stack.runtime.prime.active_handles


@pytest.mark.asyncio
async def test_invalid_public_cost_gate_publishes_no_events_and_cleans_runtime(
    public_stack,
):
    stack = public_stack
    await _bootstrap(stack.client)
    opened = await _open(stack.client)
    session_id = opened.json()["session_id"]
    mission_id = opened.json()["mission_id"]
    stack.runtime.invalid_public_gate = True

    rejected = await stack.client.post(
        f"/api/public/executive/sessions/{session_id}/messages",
        headers=MUTATION_HEADERS,
        json={"message": "must fail closed"},
    )
    assert rejected.status_code == 503
    assert rejected.json() == {"detail": "Executive cost gate rejected the turn."}
    assert rejected.headers[PUBLIC_GATE_CODE_HEADER] == "telemetry_incomplete"
    audit = await stack.control_plane.list_audit(mission_id=mission_id, limit=100)
    assert not any(item["event_type"].startswith("public.") for item in audit)
    assert stack.runtime.prime.active_handles == set()
    assert stack.runtime.registry.get(session_id) is None
    assert (await stack.gateway.safe_state())["active_sessions"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metering_overrides", "expected_code"),
    (
        (
            {
                "generation_count": 0,
                "passed": False,
                "failure_reason": "telemetry_unavailable",
                "requires_fresh_mission": True,
                "telemetry_complete": False,
            },
            "telemetry_incomplete",
        ),
        (
            {
                "passed": False,
                "failure_reason": "session_cleanup_failed",
                "requires_fresh_mission": True,
            },
            "runtime_cleanup",
        ),
        (
            {
                "passed": False,
                "failure_reason": "telemetry_unavailable",
                "requires_fresh_mission": True,
            },
            "metering_receipt",
        ),
        (
            {
                "actual_cost_usd": "0.031",
                "passed": False,
                "failure_reason": "target_cost_exceeded",
                "requires_fresh_mission": True,
                "target_met": False,
            },
            "target_exceeded",
        ),
        (
            {
                "passed": False,
                "failure_reason": "secret=sk-must-not-cross",
                "requires_fresh_mission": True,
            },
            "runtime_orchestration",
        ),
    ),
)
async def test_public_gate_header_is_fixed_and_never_forwards_runtime_reason(
    public_stack,
    metering_overrides,
    expected_code,
):
    stack = public_stack
    await _bootstrap(stack.client)
    opened = await _open(stack.client)
    session_id = opened.json()["session_id"]
    stack.runtime.metering_overrides = metering_overrides

    rejected = await stack.client.post(
        f"/api/public/executive/sessions/{session_id}/messages",
        headers=MUTATION_HEADERS,
        json={"message": "diagnose with a fixed safe code"},
    )

    assert rejected.status_code == 503
    assert rejected.headers[PUBLIC_GATE_CODE_HEADER] == expected_code
    public_failure = f"{dict(rejected.headers)} {rejected.text}"
    assert "sk-must-not-cross" not in public_failure
    assert "failure_reason" not in public_failure
    assert stack.runtime.prime.active_handles == set()


@pytest.mark.asyncio
async def test_public_cost_contract_drift_fails_before_event_publication(public_stack):
    stack = public_stack
    await _bootstrap(stack.client)
    opened = await _open(stack.client)
    session_id = opened.json()["session_id"]
    mission_id = opened.json()["mission_id"]
    stack.runtime.metering_overrides = {"target_cost_usd": "0.04"}

    rejected = await stack.client.post(
        f"/api/public/executive/sessions/{session_id}/messages",
        headers=MUTATION_HEADERS,
        json={"message": "reject drifted cost contract"},
    )
    assert rejected.status_code == 503
    assert rejected.json() == {"detail": "Executive cost contract is unavailable."}
    assert rejected.headers[PUBLIC_GATE_CODE_HEADER] == "metering_contract"
    audit = await stack.control_plane.list_audit(mission_id=mission_id, limit=100)
    assert not any(item["event_type"].startswith("public.") for item in audit)
    assert stack.runtime.prime.active_handles == set()


@pytest.mark.asyncio
async def test_snapshot_identity_drift_fails_before_event_publication(public_stack):
    stack = public_stack
    await _bootstrap(stack.client)
    opened = await _open(stack.client)
    session_id = opened.json()["session_id"]
    mission_id = opened.json()["mission_id"]
    stack.runtime.snapshot_overrides = {"mission_id": "foreign-mission-id"}

    rejected = await stack.client.post(
        f"/api/public/executive/sessions/{session_id}/messages",
        headers=MUTATION_HEADERS,
        json={"message": "reject mismatched runtime identity"},
    )
    assert rejected.status_code == 503
    assert rejected.json() == {"detail": "Executive response identity is unavailable."}
    assert rejected.headers[PUBLIC_GATE_CODE_HEADER] == "snapshot_identity"
    audit = await stack.control_plane.list_audit(mission_id=mission_id, limit=100)
    assert not any(item["event_type"].startswith("public.") for item in audit)
    assert stack.runtime.prime.active_handles == set()


def test_publication_receipt_requires_exact_contract_version_and_mission():
    base = {
        "contract": "orch.control-plane.event",
        "contract_version": "1.0",
        "mission_id": "mission-owned-1",
        "persisted": True,
    }
    for override in (
        {"contract": "wrong.contract"},
        {"contract_version": "2.0"},
        {"mission_id": "mission-foreign-2"},
    ):
        with pytest.raises(
            PublicExecutiveTurnError,
            match="evidence persistence is unavailable",
        ) as error:
            _attach_safe_publication(
                {},
                {**base, **override},
                expected_mission_id="mission-owned-1",
            )
        assert error.value.gate_code == "publication_contract"


@pytest.mark.asyncio
async def test_cleanup_stops_target_even_when_prime_reports_failed_status(public_stack):
    stack = public_stack
    await _bootstrap(stack.client)
    opened = await _open(stack.client)
    session_id = opened.json()["session_id"]
    session = stack.runtime.registry.get(session_id)
    assert session is not None
    prime_id = next(iter(session.specialists))
    stack.runtime.prime.states[prime_id] = "failed"
    assert prime_id in stack.runtime.prime.active_handles

    stopped = await stack.client.post(
        f"/api/public/executive/sessions/{session_id}/stop",
        headers=MUTATION_HEADERS,
        json={"status": "stopped", "reason": "failed_handle_cleanup"},
    )
    assert stopped.status_code == 200, stopped.text
    assert prime_id not in stack.runtime.prime.active_handles
    assert "failed_handle_cleanup" in stack.runtime.prime.stop_reasons
    assert stack.runtime.registry.get(session_id) is None


@pytest.mark.asyncio
async def test_presence_and_quota_rejection_do_not_renew_idle_lease(public_stack):
    stack = public_stack
    await _bootstrap(stack.client)
    opened = await _open(stack.client)
    session_id = opened.json()["session_id"]
    principal = await _principal(stack)
    record = stack.gateway._records[session_id]
    record.last_used_monotonic = time.monotonic() - 10.0
    original_lease = record.last_used_monotonic

    for _ in range(PUBLIC_ACCOUNT_TURN_HOURLY_LIMIT):
        await stack.store.consume_quota(
            subject_key=derive_account_subject_key(
                principal.user_id,
                principal.org_id,
                STRONG_SECRET,
            ),
            quota_name="public_executive_turn",
            hourly_limit=PUBLIC_ACCOUNT_TURN_HOURLY_LIMIT,
            daily_limit=PUBLIC_ACCOUNT_TURN_DAILY_LIMIT,
        )
    rejected = await stack.client.post(
        f"/api/public/executive/sessions/{session_id}/messages",
        headers=MUTATION_HEADERS,
        json={"message": "over quota"},
    )
    assert rejected.status_code == 429
    assert record.last_used_monotonic == original_lease

    for _ in range(3):
        presence = await stack.client.get("/api/public/presence")
        assert presence.status_code == 200
    assert record.last_used_monotonic == original_lease

    stack.gateway.idle_seconds = 1.0
    reaped = await stack.client.get("/api/public/presence")
    assert reaped.status_code == 200
    assert reaped.json()["session_id"] is None
    assert stack.runtime.prime.active_handles == set()
    assert (await stack.gateway.safe_state())["active_sessions"] == 0


@pytest.mark.asyncio
async def test_open_quota_rejects_before_control_plane_or_prime_creation(public_stack):
    stack = public_stack
    await _bootstrap(stack.client)
    principal = await _principal(stack)
    for _ in range(PUBLIC_ACCOUNT_OPEN_HOURLY_LIMIT):
        await stack.store.consume_quota(
            subject_key=derive_account_subject_key(
                principal.user_id,
                principal.org_id,
                STRONG_SECRET,
            ),
            quota_name="public_executive_open",
            hourly_limit=PUBLIC_ACCOUNT_OPEN_HOURLY_LIMIT,
            daily_limit=PUBLIC_ACCOUNT_OPEN_DAILY_LIMIT,
        )

    rejected = await stack.client.post(
        "/api/public/executive/missions",
        headers=MUTATION_HEADERS,
        json={"brief": "must be rejected before process creation"},
    )
    assert rejected.status_code == 429
    assert rejected.headers["cache-control"] == "no-store, private"
    assert stack.runtime.open_calls == []
    assert stack.runtime.prime.active_handles == set()
    assert (await stack.gateway.safe_state())["active_sessions"] == 0


@pytest.mark.asyncio
async def test_account_revoke_cleans_prime_and_resource_ownership(public_stack):
    stack = public_stack
    await _bootstrap(stack.client)
    opened = await _open(stack.client)
    session_id = opened.json()["session_id"]
    mission_id = opened.json()["mission_id"]
    principal = await _principal(stack)

    revoked = await stack.client.delete(
        "/api/public/session",
        headers=MUTATION_HEADERS,
    )
    assert revoked.status_code == 200, revoked.text
    assert stack.runtime.prime.active_handles == set()
    assert stack.runtime.registry.get(session_id) is None
    assert (await stack.gateway.safe_state())["active_sessions"] == 0
    for resource_type, resource_id in (
        ("executive_session", session_id),
        ("control_plane_mission", mission_id),
    ):
        with pytest.raises(AccountResourceNotFound, match="not found"):
            await stack.store.require_owned_resource(
                resource_type=resource_type,
                resource_id=resource_id,
                principal=principal,
            )


@pytest.mark.asyncio
async def test_cancelled_turn_eventually_cleans_prime_record_and_mission(public_stack):
    stack = public_stack
    await _bootstrap(stack.client)
    opened = await _open(stack.client)
    session_id = opened.json()["session_id"]
    mission_id = opened.json()["mission_id"]
    principal = await _principal(stack)
    stack.runtime.block_send = True

    task = asyncio.create_task(
        stack.gateway.send_message(
            principal,
            session_id,
            message="cancel this public turn",
        )
    )
    await asyncio.wait_for(stack.runtime.send_started.wait(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)

    assert stack.runtime.prime.active_handles == set()
    assert stack.runtime.registry.get(session_id) is None
    assert (await stack.gateway.safe_state())["active_sessions"] == 0
    mission = await stack.control_plane.get_mission(mission_id)
    assert mission is not None
    assert mission.status in {"failed", "killed", "succeeded"}


@pytest.mark.asyncio
async def test_weak_secret_disables_public_gateway(public_stack):
    stack = public_stack
    await _bootstrap(stack.client)
    weak = PublicExecutiveGateway(
        runtime=stack.runtime,  # type: ignore[arg-type]
        control_plane=stack.control_plane,
        store=stack.store,
        server_secret="test-secret",
        sweep_interval_seconds=3_600.0,
    )
    await weak.start()
    original = stack.app.state.public_executive_gateway
    stack.app.state.public_executive_gateway = weak
    try:
        response = await stack.client.get("/api/public/presence")
        assert response.status_code == 503
        assert response.json() == {"detail": "Public executive is unavailable"}
    finally:
        stack.app.state.public_executive_gateway = original
        await weak.close()


@pytest.mark.asyncio
async def test_public_cookie_never_authorizes_admin_scheduler_or_oauth_start(
    tmp_path,
    monkeypatch,
):
    secret = "operator-secret-" + ("z" * 48)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "operator-isolation.db"))
    monkeypatch.setenv("API_SECRET", secret)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("PRIME_AGENT_ENABLED", "false")

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app, client=("127.0.0.1", 43122))
            async with AsyncClient(
                transport=transport, base_url="https://test"
            ) as client:
                await _bootstrap(client)
                for method, path in (
                    (client.get, "/api/status"),
                    (client.get, "/api/jobs"),
                    (client.post, "/oauth/start"),
                ):
                    denied = await method(path)
                    assert denied.status_code == 401, (path, denied.text)
                allowed = await client.post(
                    "/oauth/start",
                    headers={"X-Api-Key": secret},
                )
                assert allowed.status_code == 200, allowed.text
                assert "authorize_url" in allowed.json()
    finally:
        get_settings.cache_clear()
