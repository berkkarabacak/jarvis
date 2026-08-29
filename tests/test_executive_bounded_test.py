from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.executive.adapters.prime import PrimeMessageResult, PrimeSessionInfo
from app.executive.adapters.routing import HeuristicModelRouter
from app.executive.registry import ExecutiveSessionRegistry
from app.executive.runtime import ExecutiveRuntime
from app.executive.session import ExecutiveSessionError
from app.executive.store import InMemoryHandoffStore
from app.executive.telemetry import (
    BOUNDED_TEST_PROFILE,
    DEFAULT_BOUNDED_TEST_POLICY,
    ApprovedMemorySnapshot,
    GenerationTelemetry,
    bounded_run_spec_sha256,
)


class ApprovedMemory:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.recall_calls = 0

    async def remember(self, text: str):
        del text
        raise AssertionError("bounded tests never capture memory")

    async def recall_context(self):
        self.recall_calls += 1
        if not self.available:
            raise RuntimeError("SYNTHETIC_PRIVATE_MEMORY_FAILURE")
        return SimpleNamespace(
            context="The CEO approved concise, cost-aware conclusions.",
            references=(
                {
                    "reference_id": "approved-ceo-preference-v1",
                    "label": "Approved CEO response preference",
                },
            ),
            status={"availability": "ready", "token": "SYNTHETIC_STATUS_SECRET"},
        )

    def safe_status(self) -> dict[str, Any]:
        return {"availability": "fallback", "approved_only": True}

    async def health(self) -> dict[str, Any]:
        return {"availability": "ready"}

    async def close(self) -> None:
        return None


class ConcurrentPrime:
    name = "concurrent-prime"

    def __init__(
        self,
        *,
        delegation_count: int = 2,
        costs: tuple[str, ...] = ("0.001", "0.001", "0.001", "0.001"),
        worker_delay: float = 0.05,
        hanging_role: str | None = None,
        telemetry_available: bool = True,
        token_counts: tuple[tuple[int, int, int], ...] = (),
    ) -> None:
        self.delegation_count = delegation_count
        self.costs = list(costs)
        self.worker_delay = worker_delay
        self.hanging_role = hanging_role
        self.telemetry_available = telemetry_available
        self.token_counts = list(token_counts)
        self.sessions: dict[str, PrimeSessionInfo] = {}
        self.prompts: list[tuple[str, str, str]] = []
        self._session_counter = 0
        self._generation_counter = 0
        self.active_workers = 0
        self.peak_active_workers = 0

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "available": True, "rpc": True, "live": True}

    async def start_session(
        self,
        *,
        role_name: str,
        parent_session_id: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PrimeSessionInfo:
        del model
        assert (
            metadata is None
            or metadata.get("execution_profile") == BOUNDED_TEST_PROFILE
        )
        self._session_counter += 1
        session = PrimeSessionInfo(
            session_id=f"prime-{self._session_counter}",
            role_name=role_name,
            parent_session_id=parent_session_id,
            model="openrouter/auto",
        )
        self.sessions[session.session_id] = session
        return session

    async def stop_session(self, session_id: str, *, reason: str = "stopped") -> None:
        del reason
        session = self.sessions.pop(session_id, None)
        if session is not None:
            session.status = "stopped"

    async def list_sessions(self) -> list[PrimeSessionInfo]:
        return list(self.sessions.values())

    def _telemetry(self) -> GenerationTelemetry | None:
        if not self.telemetry_available:
            return None
        self._generation_counter += 1
        cost = self.costs.pop(0) if self.costs else "0.001"
        input_tokens, output_tokens, total_tokens = (
            self.token_counts.pop(0) if self.token_counts else (100, 50, 150)
        )
        return GenerationTelemetry.build(
            generation_id=f"gen-{self._generation_counter}",
            selected_model="openai/gpt-5-nano",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            actual_cost_usd=cost,
        )

    async def send_message(
        self,
        session_id: str,
        *,
        message: str,
    ) -> PrimeMessageResult:
        session = self.sessions[session_id]
        self.prompts.append((session_id, session.role_name, message))
        if session.role_name != "executive":
            self.active_workers += 1
            self.peak_active_workers = max(
                self.peak_active_workers,
                self.active_workers,
            )
            try:
                if session.role_name == self.hanging_role:
                    await asyncio.Event().wait()
                await asyncio.sleep(self.worker_delay)
            finally:
                self.active_workers -= 1
            text = f"Safe {session.role_name} report using approved memory."
        elif message.startswith("Produce the final public executive reply."):
            text = "Final safe executive synthesis from both reports."
        else:
            delegations = [
                {"role": "analyst", "task": "Assess the delivery approach."},
                {"role": "reviewer", "task": "Review the evidence quality."},
            ][: self.delegation_count]
            text = json.dumps(
                {
                    "reply": "Two bounded specialists are checking this.",
                    "delegations": delegations,
                },
                separators=(",", ":"),
            )
        return PrimeMessageResult(
            message_id=f"message-{len(self.prompts)}",
            session_id=session_id,
            text=text,
            generation=self._telemetry(),
        )

    async def close(self) -> None:
        self.sessions.clear()


def build_runtime(
    *,
    prime: ConcurrentPrime,
    memory: ApprovedMemory,
    policy=DEFAULT_BOUNDED_TEST_POLICY,
    store: InMemoryHandoffStore | None = None,
) -> tuple[ExecutiveRuntime, InMemoryHandoffStore]:
    store = store or InMemoryHandoffStore()
    return (
        ExecutiveRuntime(
            registry=ExecutiveSessionRegistry(handoff_store=store),
            prime=prime,
            router=HeuristicModelRouter(),
            memory_bridge=memory,
            bounded_policy=policy,
        ),
        store,
    )


@pytest.mark.asyncio
async def test_bounded_test_runs_two_workers_in_parallel_and_replays_fresh_mission():
    prime = ConcurrentPrime()
    memory = ApprovedMemory()
    runtime, store = build_runtime(prime=prime, memory=memory)
    mission_text = "Demonstrate parallel specialists with persistent approved memory."
    turns: list[dict[str, Any]] = []

    for index in (1, 2):
        session = await runtime.open_mission(
            mission_id=f"bounded-replay-{index}",
            brief="Bounded orchestration verification",
            execution_profile=BOUNDED_TEST_PROFILE,
        )
        turn = await runtime.send_message(session.session_id, message=mission_text)
        turns.append(turn)

        gate = turn["bounded_test"]
        assert gate["passed"] is True
        assert gate["generation_count"] == 4
        assert gate["total_tokens"] == 600
        assert gate["actual_cost_usd"] == "0.004"
        assert gate["target_met"] is True
        assert gate["hard_limits_passed"] is True
        assert gate["synthesis_passed"] is True
        assert gate["parallelism"]["peak_active_workers"] == 2
        assert gate["parallelism"]["parallelism_passed"] is True
        assert gate["parallelism"]["worker_overlap_ms"] > 0
        assert gate["parallelism"]["worker_overlap_ratio"] >= 0.5
        assert [item["phase"] for item in gate["entries"]] == [
            "root_plan",
            "worker",
            "worker",
            "root_synthesis",
        ]
        assert all(
            item["selected_model"] == "openai/gpt-5-nano" for item in gate["entries"]
        )
        assert all(
            item["total_tokens"]
            <= DEFAULT_BOUNDED_TEST_POLICY.reserved_tokens_per_generation
            for item in gate["entries"]
        )
        assert len(gate["handoff_ids"]) == 2
        assert prime.sessions == {}

        handoffs = await store.list_for_mission(
            f"bounded-replay-{index}",
            memory_scope="run",
        )
        assert len(handoffs) == 2
        assert [row.packet.from_role for row in handoffs] == ["analyst", "reviewer"]
        for row in handoffs:
            assert row.packet.memory_updates == []
            assert row.packet.costs["actual_cost_usd"] == "0.001"
            assert any(
                ref == "approved-memory:approved-ceo-preference-v1"
                for ref in row.packet.evidence_refs
            )
            assert any(
                ref.startswith("openrouter-generation:gen-")
                for ref in row.packet.evidence_refs
            )

        with pytest.raises(ExecutiveSessionError, match="exactly one"):
            await runtime.send_message(session.session_id, message=mission_text)

    first_gate = turns[0]["bounded_test"]
    second_gate = turns[1]["bounded_test"]
    assert first_gate["mission_text_sha256"] == second_gate["mission_text_sha256"]
    assert first_gate["run_spec_sha256"] == second_gate["run_spec_sha256"]
    first_ids = {item["generation_id"] for item in first_gate["entries"]}
    second_ids = {item["generation_id"] for item in second_gate["entries"]}
    assert first_ids.isdisjoint(second_ids)
    assert memory.recall_calls == 2
    assert prime.peak_active_workers == 2

    worker_prompts = [
        message for _, role, message in prime.prompts if role != "executive"
    ]
    assert len(worker_prompts) == 4
    assert all("approved-ceo-preference-v1" in prompt for prompt in worker_prompts)
    assert all("cost-aware conclusions" in prompt for prompt in worker_prompts)
    executive_session_counts: dict[str, int] = {}
    for session_id, role, _ in prime.prompts:
        if role == "executive":
            executive_session_counts[session_id] = (
                executive_session_counts.get(session_id, 0) + 1
            )
    assert executive_session_counts
    assert set(executive_session_counts.values()) == {1}
    assert "SYNTHETIC_STATUS_SECRET" not in json.dumps(turns)
    await runtime.close()


@pytest.mark.asyncio
async def test_bounded_test_fails_before_provider_without_approved_memory():
    prime = ConcurrentPrime()
    runtime, _ = build_runtime(prime=prime, memory=ApprovedMemory(available=False))
    session = await runtime.open_mission(
        mission_id="bounded-no-memory",
        execution_profile=BOUNDED_TEST_PROFILE,
    )
    turn = await runtime.send_message(session.session_id, message="Run the test.")

    assert turn["bounded_test"]["failure_reason"] == "approved_memory_required"
    assert turn["bounded_test"]["generation_count"] == 0
    assert turn["bounded_test"]["passed"] is False
    assert prime.prompts == []
    assert prime.sessions == {}
    assert "SYNTHETIC_PRIVATE_MEMORY_FAILURE" not in json.dumps(turn)


@pytest.mark.asyncio
async def test_bounded_memory_recall_timeout_stops_before_generation():
    class SlowMemory(ApprovedMemory):
        async def recall_context(self):
            await asyncio.Event().wait()

    prime = ConcurrentPrime()
    policy = replace(
        DEFAULT_BOUNDED_TEST_POLICY,
        memory_recall_timeout_seconds=0.02,
        cleanup_timeout_seconds=0.05,
        total_turn_timeout_seconds=0.5,
    )
    runtime, _ = build_runtime(
        prime=prime,
        memory=SlowMemory(),
        policy=policy,
    )
    session = await runtime.open_mission(
        mission_id="bounded-memory-timeout",
        execution_profile=BOUNDED_TEST_PROFILE,
    )
    turn = await runtime.send_message(session.session_id, message="Run the test.")

    assert turn["bounded_test"]["failure_reason"] == "approved_memory_required"
    assert turn["bounded_test"]["generation_count"] == 0
    assert prime.prompts == []
    assert prime.sessions == {}


@pytest.mark.asyncio
async def test_bounded_test_requires_exactly_two_accepted_delegations():
    prime = ConcurrentPrime(delegation_count=1)
    runtime, store = build_runtime(prime=prime, memory=ApprovedMemory())
    session = await runtime.open_mission(
        mission_id="bounded-one-worker",
        execution_profile=BOUNDED_TEST_PROFILE,
    )
    turn = await runtime.send_message(session.session_id, message="Run the test.")

    gate = turn["bounded_test"]
    assert gate["failure_reason"] == "exactly_two_delegations_required"
    assert gate["generation_count"] == 1
    assert gate["passed"] is False
    assert len(prime.prompts) == 1
    assert await store.list_for_mission("bounded-one-worker") == []


@pytest.mark.asyncio
async def test_bounded_test_rejects_adversarial_large_prompt_before_generation():
    prime = ConcurrentPrime()
    runtime, _ = build_runtime(prime=prime, memory=ApprovedMemory())
    session = await runtime.open_mission(
        mission_id="bounded-large-prompt",
        execution_profile=BOUNDED_TEST_PROFILE,
    )
    turn = await runtime.send_message(session.session_id, message="!" * 3_000)

    gate = turn["bounded_test"]
    assert gate["failure_reason"] == "root_prompt_rejected"
    assert gate["generation_count"] == 0
    assert gate["passed"] is False
    assert prime.prompts == []
    assert prime.sessions == {}


@pytest.mark.asyncio
async def test_bounded_test_cost_reservation_stops_workers_and_persists_failures():
    prime = ConcurrentPrime(costs=("0.095",))
    runtime, store = build_runtime(prime=prime, memory=ApprovedMemory())
    session = await runtime.open_mission(
        mission_id="bounded-cost-stop",
        execution_profile=BOUNDED_TEST_PROFILE,
    )
    turn = await runtime.send_message(session.session_id, message="Run the test.")

    gate = turn["bounded_test"]
    assert gate["failure_reason"] == "cost_reservation_exceeded"
    assert gate["generation_count"] == 1
    assert gate["actual_cost_usd"] == "0.095"
    assert len(gate["handoff_ids"]) == 2
    assert len(prime.prompts) == 1
    handoffs = await store.list_for_mission("bounded-cost-stop", memory_scope="run")
    assert len(handoffs) == 2
    assert all(row.packet.confidence == 0.0 for row in handoffs)


@pytest.mark.asyncio
async def test_worker_timeout_cleans_sessions_and_persists_exactly_two_handoffs():
    prime = ConcurrentPrime(hanging_role="analyst", worker_delay=0.01)
    policy = replace(
        DEFAULT_BOUNDED_TEST_POLICY,
        worker_timeout_seconds=0.03,
        cleanup_timeout_seconds=0.05,
        handoff_timeout_seconds=0.1,
        total_turn_timeout_seconds=1.0,
    )
    runtime, store = build_runtime(
        prime=prime,
        memory=ApprovedMemory(),
        policy=policy,
    )
    session = await runtime.open_mission(
        mission_id="bounded-worker-timeout",
        execution_profile=BOUNDED_TEST_PROFILE,
    )
    turn = await runtime.send_message(session.session_id, message="Run the test.")

    gate = turn["bounded_test"]
    assert gate["failure_reason"] == "telemetry_unavailable"
    assert gate["passed"] is False
    assert gate["synthesis_passed"] is False
    assert len(gate["handoff_ids"]) == 2
    handoffs = await store.list_for_mission(
        "bounded-worker-timeout",
        memory_scope="run",
    )
    assert len(handoffs) == 2
    assert {row.packet.from_role for row in handoffs} == {"analyst", "reviewer"}
    assert prime.sessions == {}
    assert prime.active_workers == 0


@pytest.mark.asyncio
async def test_external_worker_cancellation_persists_two_safe_failure_handoffs():
    prime = ConcurrentPrime(worker_delay=10.0)
    policy = replace(
        DEFAULT_BOUNDED_TEST_POLICY,
        cleanup_timeout_seconds=0.05,
        handoff_timeout_seconds=0.1,
        total_turn_timeout_seconds=2.0,
    )
    runtime, store = build_runtime(
        prime=prime,
        memory=ApprovedMemory(),
        policy=policy,
    )
    session = await runtime.open_mission(
        mission_id="bounded-worker-cancelled",
        execution_profile=BOUNDED_TEST_PROFILE,
    )
    turn_task = asyncio.create_task(
        runtime.send_message(session.session_id, message="Run the test.")
    )
    for _ in range(200):
        if prime.active_workers == 2:
            break
        await asyncio.sleep(0.005)
    assert prime.active_workers == 2

    turn_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn_task

    handoffs = await store.list_for_mission(
        "bounded-worker-cancelled",
        memory_scope="run",
    )
    assert len(handoffs) == 2
    assert {row.packet.from_role for row in handoffs} == {"analyst", "reviewer"}
    assert all(row.packet.confidence == 0.0 for row in handoffs)
    assert all(row.packet.costs["status"] == "failed" for row in handoffs)
    assert prime.sessions == {}
    assert prime.active_workers == 0


@pytest.mark.asyncio
async def test_cancellation_during_handoff_append_finishes_without_duplicates():
    class DelayedHandoffStore(InMemoryHandoffStore):
        def __init__(self) -> None:
            super().__init__()
            self.first_append_started = asyncio.Event()
            self.append_calls = 0

        async def append(self, **kwargs):
            self.append_calls += 1
            row = await super().append(**kwargs)
            if self.append_calls == 1:
                self.first_append_started.set()
                await asyncio.sleep(0.05)
            return row

    prime = ConcurrentPrime(worker_delay=0.01)
    store = DelayedHandoffStore()
    policy = replace(
        DEFAULT_BOUNDED_TEST_POLICY,
        cleanup_timeout_seconds=0.05,
        handoff_timeout_seconds=0.2,
        total_turn_timeout_seconds=2.0,
    )
    runtime, _ = build_runtime(
        prime=prime,
        memory=ApprovedMemory(),
        policy=policy,
        store=store,
    )
    session = await runtime.open_mission(
        mission_id="bounded-handoff-cancelled",
        execution_profile=BOUNDED_TEST_PROFILE,
    )
    turn_task = asyncio.create_task(
        runtime.send_message(session.session_id, message="Run the test.")
    )
    await asyncio.wait_for(store.first_append_started.wait(), timeout=0.5)

    turn_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn_task

    handoffs = await store.list_for_mission(
        "bounded-handoff-cancelled",
        memory_scope="run",
    )
    assert len(handoffs) == 2
    assert store.append_calls == 2
    assert [row.packet.from_role for row in handoffs] == ["analyst", "reviewer"]
    assert prime.sessions == {}


@pytest.mark.asyncio
async def test_cancellation_during_worker_cleanup_still_finalizes_two_handoffs():
    class DelayedCleanupPrime(ConcurrentPrime):
        def __init__(self) -> None:
            super().__init__(worker_delay=0.01)
            self.worker_cleanup_started = asyncio.Event()
            self._cleanup_delayed = False

        async def stop_session(
            self,
            session_id: str,
            *,
            reason: str = "stopped",
        ) -> None:
            session = self.sessions.get(session_id)
            if (
                session is not None
                and session.role_name != "executive"
                and not self._cleanup_delayed
            ):
                self._cleanup_delayed = True
                self.worker_cleanup_started.set()
                await asyncio.sleep(0.05)
            await super().stop_session(session_id, reason=reason)

    prime = DelayedCleanupPrime()
    policy = replace(
        DEFAULT_BOUNDED_TEST_POLICY,
        cleanup_timeout_seconds=0.2,
        handoff_timeout_seconds=0.1,
        total_turn_timeout_seconds=2.0,
    )
    runtime, store = build_runtime(
        prime=prime,
        memory=ApprovedMemory(),
        policy=policy,
    )
    session = await runtime.open_mission(
        mission_id="bounded-cleanup-cancelled",
        execution_profile=BOUNDED_TEST_PROFILE,
    )
    turn_task = asyncio.create_task(
        runtime.send_message(session.session_id, message="Run the test.")
    )
    await asyncio.wait_for(prime.worker_cleanup_started.wait(), timeout=0.5)

    turn_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn_task

    handoffs = await store.list_for_mission(
        "bounded-cleanup-cancelled",
        memory_scope="run",
    )
    assert len(handoffs) == 2
    assert [row.packet.from_role for row in handoffs] == ["analyst", "reviewer"]
    assert prime.sessions == {}


@pytest.mark.asyncio
async def test_observed_per_generation_token_limit_fails_closed():
    prime = ConcurrentPrime(token_counts=((2_401, 600, 3_001),))
    runtime, _ = build_runtime(prime=prime, memory=ApprovedMemory())
    session = await runtime.open_mission(
        mission_id="bounded-generation-token-limit",
        execution_profile=BOUNDED_TEST_PROFILE,
    )
    turn = await runtime.send_message(session.session_id, message="Run the test.")

    gate = turn["bounded_test"]
    assert gate["failure_reason"] == "per_generation_token_limit_exceeded"
    assert gate["generation_count"] == 1
    assert gate["passed"] is False
    assert len(prime.prompts) == 1
    assert prime.sessions == {}


def test_bounded_policy_prospectively_reserves_full_prime_request():
    policy = DEFAULT_BOUNDED_TEST_POLICY
    prospective_total = (
        policy.max_user_prompt_utf8_bytes
        + policy.max_bounded_workdir_utf8_bytes
        + policy.prime_fixed_prompt_utf8_bytes
        + policy.chat_framing_token_reserve
        + policy.max_output_tokens_per_generation
    )
    assert prospective_total == 2_973
    assert prospective_total <= policy.reserved_tokens_per_generation
    with pytest.raises(ValueError, match="not prospective"):
        replace(policy, max_bounded_workdir_utf8_bytes=284)


def test_run_spec_hash_covers_approved_memory_reference_labels():
    first = ApprovedMemorySnapshot.build(
        context="Approved context",
        references=({"reference_id": "memory-v1", "label": "First label"},),
    )
    same = ApprovedMemorySnapshot.build(
        context="Approved context",
        references=({"reference_id": "memory-v1", "label": "First label"},),
    )
    changed_label = ApprovedMemorySnapshot.build(
        context="Approved context",
        references=({"reference_id": "memory-v1", "label": "Changed label"},),
    )
    kwargs = {
        "mission_text_sha": "a" * 64,
        "workers": (
            ("analyst", "Assess delivery."),
            ("reviewer", "Review evidence."),
        ),
    }

    first_hash = bounded_run_spec_sha256(memory=first, **kwargs)
    assert bounded_run_spec_sha256(memory=same, **kwargs) == first_hash
    assert bounded_run_spec_sha256(memory=changed_label, **kwargs) != first_hash


def test_generation_telemetry_rejects_float_tokens_and_preserves_decimal_cost():
    with pytest.raises(Exception, match="input token count is unavailable"):
        GenerationTelemetry.build(
            generation_id="gen-strict",
            selected_model="openai/gpt-5-nano",
            input_tokens=1.9,
            output_tokens=1,
            total_tokens=2,
            actual_cost_usd="0.001",
        )
    telemetry = GenerationTelemetry.build(
        generation_id="gen-decimal",
        selected_model="openai/gpt-5-nano",
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        actual_cost_usd=Decimal("0.000000123456789"),
    )
    assert telemetry.to_dict()["actual_cost_usd"] == "0.000000123456789"
