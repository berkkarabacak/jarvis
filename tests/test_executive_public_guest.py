from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

import pytest

from app.executive.adapters.prime import PrimeMessageResult, PrimeSessionInfo
from app.executive.adapters.routing import HeuristicModelRouter
from app.executive.memory_policy import ExecutiveMemoryPolicy
from app.executive.registry import ExecutiveSessionRegistry
from app.executive.runtime import ExecutiveRuntime
from app.executive.telemetry import (
    PUBLIC_GUEST_PROFILE,
    GenerationTelemetry,
)


class PublicGuestPrime:
    name = "public-guest-prime"

    def __init__(
        self,
        *,
        plans: Iterable[str],
        syntheses: Iterable[str] = (),
        telemetry: Iterable[GenerationTelemetry | None] = (),
        worker_delay: float = 0.01,
        hang_workers: bool = False,
        stop_failures: int = 0,
        block_stops: bool = False,
    ) -> None:
        self.plans = list(plans)
        self.syntheses = list(syntheses)
        self.telemetry = list(telemetry)
        self.worker_delay = worker_delay
        self.hang_workers = hang_workers
        self.stop_failures = stop_failures
        self.block_stops = block_stops
        self.worker_started = asyncio.Event()
        self.stop_started = asyncio.Event()
        self.release_stops = asyncio.Event()
        self.sessions: dict[str, PrimeSessionInfo] = {}
        self.starts: list[dict[str, Any]] = []
        self.stops: list[str] = []
        self.prompts: list[tuple[str, str, str]] = []
        self.active_workers = 0
        self.peak_active_workers = 0
        self._session_counter = 0
        self._message_counter = 0

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
        assert metadata is not None
        assert metadata.get("execution_profile") == PUBLIC_GUEST_PROFILE
        self._session_counter += 1
        session = PrimeSessionInfo(
            session_id=f"public-prime-{self._session_counter}",
            role_name=role_name,
            parent_session_id=parent_session_id,
            model="openrouter/auto",
        )
        self.sessions[session.session_id] = session
        self.starts.append(
            {
                "session_id": session.session_id,
                "role": role_name,
                "parent": parent_session_id,
                "metadata": dict(metadata),
            }
        )
        return session

    async def stop_session(self, session_id: str, *, reason: str = "stopped") -> None:
        del reason
        self.stops.append(session_id)
        self.stop_started.set()
        if self.block_stops:
            await self.release_stops.wait()
        if self.stop_failures:
            self.stop_failures -= 1
            raise RuntimeError("SYNTHETIC_PRIVATE_STOP_FAILURE")
        session = self.sessions.pop(session_id, None)
        if session is not None:
            session.status = "stopped"

    async def list_sessions(self) -> list[PrimeSessionInfo]:
        return list(self.sessions.values())

    async def send_message(
        self,
        session_id: str,
        *,
        message: str,
    ) -> PrimeMessageResult:
        session = self.sessions[session_id]
        self.prompts.append((session_id, session.role_name, message))
        if session.role_name != "executive":
            self.worker_started.set()
            self.active_workers += 1
            self.peak_active_workers = max(
                self.peak_active_workers,
                self.active_workers,
            )
            try:
                if self.hang_workers:
                    await asyncio.Event().wait()
                await asyncio.sleep(self.worker_delay)
            finally:
                self.active_workers -= 1
            text = f"Safe {session.role_name} report."
        elif message.startswith("Produce the final public executive reply."):
            text = self.syntheses.pop(0)
        else:
            text = self.plans.pop(0)
        self._message_counter += 1
        generation = self.telemetry.pop(0) if self.telemetry else None
        return PrimeMessageResult(
            message_id=f"public-message-{self._message_counter}",
            session_id=session_id,
            text=text,
            generation=generation,
        )

    async def close(self) -> None:
        self.sessions.clear()


def receipt(
    number: int,
    *,
    generation_id: str | None = None,
    cost: str = "0.001",
    tokens: tuple[int, int, int] = (100, 50, 150),
    source: str = "openrouter_stream",
) -> GenerationTelemetry:
    input_tokens, output_tokens, total_tokens = tokens
    return GenerationTelemetry.build(
        generation_id=generation_id or f"gen-public-{number}",
        selected_model="openai/gpt-5-nano",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        actual_cost_usd=Decimal(cost),
        source=source,  # type: ignore[arg-type]
    )


def runtime(prime: PublicGuestPrime) -> ExecutiveRuntime:
    return ExecutiveRuntime(
        registry=ExecutiveSessionRegistry(),
        prime=prime,
        router=HeuristicModelRouter(),
    )


async def open_public(runtime: ExecutiveRuntime, mission_id: str = "public-mission"):
    return await runtime.open_mission(
        mission_id=mission_id,
        brief="Public CEO conversation",
        memory_policy=ExecutiveMemoryPolicy.disabled(),
        execution_profile=PUBLIC_GUEST_PROFILE,
    )


@pytest.mark.asyncio
async def test_public_guest_repeats_turns_with_fresh_roots_and_parallel_workers():
    plan = json.dumps(
        {
            "reply": "I will consult two specialists.",
            "delegations": [
                {"role": "analyst", "task": "Assess the low-cost approach."},
                {"role": "reviewer", "task": "Challenge the safety evidence."},
            ],
        },
        separators=(",", ":"),
    )
    prime = PublicGuestPrime(
        plans=[plan, "The prior recommendation remains valid."],
        syntheses=["Use the safe low-cost approach."],
        telemetry=[receipt(index) for index in range(1, 6)],
        worker_delay=0.03,
    )
    app = runtime(prime)
    session = await open_public(app)

    first = await app.send_message(
        session.session_id,
        message="Compare options API_KEY=SYNTHETIC_INPUT_SECRET",
    )
    assert first["public_guest"]["passed"] is True
    assert first["public_guest"]["generation_count"] == 4
    assert first["public_guest"]["actual_cost_usd"] == "0.004"
    assert first["public_guest"]["max_context_tokens_per_generation"] == 3_000
    assert first["public_guest"]["max_output_tokens_per_generation"] == 600
    assert first["public_guest"]["model_selector"] == "openrouter/auto"
    assert first["public_guest"]["provider_max_price"] == {
        "prompt": "1",
        "completion": "5",
        "request": "0",
        "image": "0",
        "audio": "0",
    }
    assert first["public_guest"]["peak_active_workers"] == 2
    assert len(first["public_guest"]["handoff_ids"]) == 2
    assert [item["phase"] for item in first["public_guest"]["generations"]] == [
        "root_plan",
        "worker",
        "worker",
        "root_synthesis",
    ]
    assert {item["generation_id"] for item in first["public_guest"]["generations"]} == {
        f"gen-public-{index}" for index in range(1, 5)
    }
    assert {
        item["selected_model"] for item in first["public_guest"]["generations"]
    } == {"openai/gpt-5-nano"}
    assert prime.sessions == {}

    second = await app.send_message(
        session.session_id,
        message="Can you restate that recommendation?",
    )
    assert second["public_guest"]["passed"] is True
    assert second["public_guest"]["turn_number"] == 2
    assert second["public_guest"]["generation_count"] == 1
    assert second["snapshot"]["status"] == "active"
    assert second["snapshot"]["public_guest_turns_completed"] == 2
    assert prime.sessions == {}
    assert all(
        item["metadata"]["execution_profile"] == PUBLIC_GUEST_PROFILE
        for item in prime.starts
    )
    root_ids = [
        item["session_id"] for item in prime.starts if item["role"] == "executive"
    ]
    assert len(root_ids) == 3
    assert len(set(root_ids)) == 3
    second_plan_prompt = [
        prompt
        for _, role, prompt in prime.prompts
        if role == "executive" and not prompt.startswith("Produce the final")
    ][1]
    assert "Use the safe low-cost approach." in second_plan_prompt
    assert "SYNTHETIC_INPUT_SECRET" not in second_plan_prompt
    assert len(second_plan_prompt.encode("utf-8")) <= 1_800
    assert all(len(prompt.encode("utf-8")) <= 1_800 for _, _, prompt in prime.prompts)
    serialized = json.dumps([first, second])
    assert "SYNTHETIC_INPUT_SECRET" not in serialized
    assert "private reasoning" not in serialized.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("telemetry", "expected_reason"),
    [
        ([None], "telemetry_unavailable"),
        (
            [receipt(1, source="openrouter_generation")],
            "authoritative_telemetry_unavailable",
        ),
        ([receipt(1, cost="0.031")], "target_cost_exceeded"),
        ([receipt(1, cost="0.11")], "hard_cost_exceeded"),
        (
            [receipt(1, tokens=(2_401, 600, 3_001))],
            "per_generation_token_limit_exceeded",
        ),
        ([receipt(1, tokens=(100, 601, 701))], "generation_output_limit_exceeded"),
    ],
)
async def test_public_guest_fails_closed_on_receipt_and_budget_boundaries(
    telemetry,
    expected_reason,
):
    prime = PublicGuestPrime(plans=["Safe provider reply"], telemetry=telemetry)
    app = runtime(prime)
    session = await open_public(app, mission_id=f"public-{expected_reason}")

    turn = await app.send_message(session.session_id, message="Run the safe task")

    gate = turn["public_guest"]
    assert gate["passed"] is False
    assert gate["requires_fresh_mission"] is True
    assert gate["failure_reason"] == expected_reason
    assert turn["message"]["text"].startswith("This turn could not be completed")
    assert turn["snapshot"]["status"] == "failed"
    assert prime.sessions == {}


@pytest.mark.asyncio
async def test_public_guest_rejects_oversized_context_before_provider_and_cleans_root():
    prime = PublicGuestPrime(plans=["must not run"], telemetry=[receipt(1)])
    app = runtime(prime)
    session = await open_public(app, mission_id="public-context-limit")

    with pytest.raises(Exception, match="safe context limit"):
        await app.send_message(session.session_id, message="x" * 2_000)

    assert prime.prompts == []
    assert prime.sessions == {}
    assert session.status == "failed"


@pytest.mark.asyncio
async def test_public_guest_rejects_duplicate_generation_receipts_and_skips_synthesis():
    plan = json.dumps(
        {
            "reply": "A reviewer is checking.",
            "delegations": [{"role": "reviewer", "task": "Review this safely."}],
        },
        separators=(",", ":"),
    )
    prime = PublicGuestPrime(
        plans=[plan],
        syntheses=["Must not run"],
        telemetry=[
            receipt(1, generation_id="gen-public-duplicate"),
            receipt(2, generation_id="gen-public-duplicate"),
        ],
    )
    app = runtime(prime)
    session = await open_public(app, mission_id="public-duplicate")

    turn = await app.send_message(session.session_id, message="Delegate once")

    assert turn["public_guest"]["failure_reason"] == "duplicate_generation_id"
    assert turn["public_guest"]["generation_count"] == 2
    assert turn["public_guest"]["actual_cost_usd"] == "0.002"
    assert not any(
        prompt.startswith("Produce the final") for _, _, prompt in prime.prompts
    )
    assert prime.sessions == {}


@pytest.mark.asyncio
async def test_public_guest_cancellation_closes_root_and_parallel_workers():
    plan = json.dumps(
        {
            "reply": "Two specialists are checking.",
            "delegations": [
                {"role": "analyst", "task": "Assess."},
                {"role": "reviewer", "task": "Review."},
            ],
        },
        separators=(",", ":"),
    )
    prime = PublicGuestPrime(
        plans=[plan],
        telemetry=[receipt(1), receipt(2), receipt(3)],
        hang_workers=True,
        stop_failures=4,
    )
    app = runtime(prime)
    session = await open_public(app, mission_id="public-cancel")
    task = asyncio.create_task(
        app.send_message(session.session_id, message="Start specialists")
    )
    await asyncio.wait_for(prime.worker_started.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await prime.list_sessions() == []
    assert session.status == "failed"
    assert prime.active_workers == 0


@pytest.mark.asyncio
async def test_public_guest_cancellation_during_normal_cleanup_waits_for_zero_handles():
    prime = PublicGuestPrime(
        plans=["Safe reply after metered generation."],
        telemetry=[receipt(1)],
        block_stops=True,
    )
    app = runtime(prime)
    session = await open_public(app, mission_id="public-cleanup-cancel")
    task = asyncio.create_task(
        app.send_message(session.session_id, message="Run one safe turn")
    )
    await asyncio.wait_for(prime.stop_started.wait(), timeout=1)

    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    prime.release_stops.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await prime.list_sessions() == []
    assert session.status == "failed"


@pytest.mark.asyncio
async def test_public_guest_retries_transient_cleanup_without_orphan_handles():
    prime = PublicGuestPrime(
        plans=["Safe reply after metered generation."],
        telemetry=[receipt(1)],
        stop_failures=1,
    )
    app = runtime(prime)
    session = await open_public(app, mission_id="public-cleanup-retry")

    turn = await app.send_message(session.session_id, message="Run one safe turn")

    assert turn["public_guest"]["passed"] is True
    assert turn["snapshot"]["status"] == "active"
    assert await prime.list_sessions() == []
    assert len(prime.stops) == 2


@pytest.mark.asyncio
async def test_public_guest_retries_workers_already_marked_failed_without_orphans():
    plan = json.dumps(
        {
            "reply": "A specialist is checking.",
            "delegations": [{"role": "reviewer", "task": "Review safely."}],
        },
        separators=(",", ":"),
    )
    prime = PublicGuestPrime(
        plans=[plan],
        telemetry=[receipt(1), receipt(2)],
        stop_failures=2,
    )
    app = runtime(prime)
    session = await open_public(app, mission_id="public-failed-worker-cleanup")

    turn = await app.send_message(session.session_id, message="Delegate once")

    assert turn["public_guest"]["passed"] is False
    assert turn["public_guest"]["failure_reason"] == "worker_cleanup_failed"
    assert session.status == "failed"
    assert await prime.list_sessions() == []


@pytest.mark.asyncio
async def test_public_guest_tracks_unregistered_worker_candidate_through_cleanup():
    plan = json.dumps(
        {
            "reply": "A specialist is checking.",
            "delegations": [{"role": "reviewer", "task": "Review safely."}],
        },
        separators=(",", ":"),
    )
    prime = PublicGuestPrime(
        plans=[plan],
        telemetry=[receipt(1)],
        stop_failures=2,
    )
    app = runtime(prime)
    session = await open_public(app, mission_id="public-unregistered-worker")
    original_spawn = session.spawn_specialist

    def reject_worker(role_name: str, **kwargs: Any):
        if role_name != "executive":
            raise RuntimeError("SYNTHETIC_PRIVATE_REGISTRATION_FAILURE")
        return original_spawn(role_name, **kwargs)

    session.spawn_specialist = reject_worker  # type: ignore[method-assign]

    turn = await app.send_message(session.session_id, message="Delegate once")

    assert turn["public_guest"]["passed"] is False
    assert turn["public_guest"]["failure_reason"] == "worker_start_failed"
    assert await prime.list_sessions() == []


@pytest.mark.asyncio
async def test_public_guest_persistent_cleanup_failure_remains_retryable_and_verified():
    prime = PublicGuestPrime(
        plans=["Safe reply after metered generation."],
        telemetry=[receipt(1)],
        stop_failures=10,
    )
    app = runtime(prime)
    session = await open_public(app, mission_id="public-persistent-cleanup")

    turn = await app.send_message(session.session_id, message="Run one safe turn")

    assert turn["public_guest"]["passed"] is False
    assert turn["public_guest"]["failure_reason"] == "session_cleanup_failed"
    assert await prime.list_sessions()

    prime.stop_failures = 0
    assert await app._close_public_guest_sessions(
        session,
        reason="public_guest_cleanup_retry",
    )
    assert await prime.list_sessions() == []
    assert session.session_id not in app._public_guest_instance_ids


@pytest.mark.asyncio
async def test_public_guest_stop_retains_unregistered_handle_until_verified_cleanup():
    plan = json.dumps(
        {
            "reply": "A specialist is checking.",
            "delegations": [{"role": "reviewer", "task": "Review safely."}],
        },
        separators=(",", ":"),
    )
    prime = PublicGuestPrime(
        plans=[plan],
        telemetry=[receipt(1)],
        stop_failures=20,
    )
    app = runtime(prime)
    session = await open_public(app, mission_id="public-stop-unregistered-worker")
    original_spawn = session.spawn_specialist

    def reject_worker(role_name: str, **kwargs: Any):
        if role_name != "executive":
            raise RuntimeError("SYNTHETIC_PRIVATE_REGISTRATION_FAILURE")
        return original_spawn(role_name, **kwargs)

    session.spawn_specialist = reject_worker  # type: ignore[method-assign]
    turn = await app.send_message(session.session_id, message="Delegate once")

    assert turn["public_guest"]["passed"] is False
    assert await prime.list_sessions()
    with pytest.raises(Exception, match="cleanup is still in progress"):
        await app.stop_mission(session.session_id, reason="first_cleanup_attempt")
    assert session.session_id in app._public_guest_instance_ids
    assert app.execution_profile_for(session.session_id) == PUBLIC_GUEST_PROFILE

    prime.stop_failures = 0
    await app.stop_mission(session.session_id, reason="verified_cleanup_retry")

    assert await prime.list_sessions() == []
    assert session.session_id not in app._public_guest_instance_ids


@pytest.mark.asyncio
async def test_public_guest_requires_host_disabled_memory_policy_before_prime_start():
    prime = PublicGuestPrime(plans=["unused"])
    app = runtime(prime)

    with pytest.raises(Exception, match="Persistent memory must be disabled"):
        await app.open_mission(
            mission_id="public-memory-rejected",
            execution_profile=PUBLIC_GUEST_PROFILE,
        )

    assert prime.starts == []


@pytest.mark.asyncio
async def test_public_guest_never_forwards_explicit_memory_commands():
    prime = PublicGuestPrime(plans=["must not run"], telemetry=[receipt(1)])
    app = runtime(prime)
    session = await open_public(app, mission_id="public-no-memory-command")

    with pytest.raises(Exception, match="Persistent memory is disabled"):
        await app.send_message(session.session_id, message="/remember private note")

    assert prime.prompts == []
    assert prime.sessions == {}
    assert session.status == "failed"
