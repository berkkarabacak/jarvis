from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.executive.delegation import ALLOWED_DELEGATION_ROLES
from app.executive.safety import (
    ExecutiveSafetyError,
    require_public_identifier,
    sanitize_private_input,
    sanitize_public_text,
)

ExecutionProfile = Literal["standard", "bounded_test_v1", "public_guest_v1"]

BOUNDED_TEST_PROFILE = "bounded_test_v1"
PUBLIC_GUEST_PROFILE = "public_guest_v1"
STANDARD_EXECUTION_PROFILE = "standard"


class GenerationTelemetryError(RuntimeError):
    """Safe failure at the provider usage-metadata boundary."""


def _bounded_nonnegative_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise GenerationTelemetryError(f"{field_name} is unavailable")
    if value < 0 or value > 100_000_000:
        raise GenerationTelemetryError(f"{field_name} is unavailable")
    return value


def _bounded_decimal(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise GenerationTelemetryError(f"{field_name} is unavailable")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise GenerationTelemetryError(f"{field_name} is unavailable") from exc
    if not parsed.is_finite() or parsed < 0 or parsed > Decimal(1000):
        raise GenerationTelemetryError(f"{field_name} is unavailable")
    return parsed


def _safe_model(value: Any) -> str:
    if not isinstance(value, str):
        raise GenerationTelemetryError("selected model is unavailable")
    model, filtered = sanitize_public_text(value, maximum=200, withheld_text="")
    if (
        filtered
        or not model
        or any(not (ch.isalnum() or ch in "._:/-") for ch in model)
    ):
        raise GenerationTelemetryError("selected model is unavailable")
    return model


@dataclass(frozen=True)
class ApprovedMemoryReference:
    reference_id: str
    label: str

    @classmethod
    def build(cls, reference_id: Any, label: Any) -> ApprovedMemoryReference:
        public_id = require_public_identifier(reference_id)
        public_label, filtered = sanitize_public_text(
            label,
            maximum=160,
            withheld_text="",
        )
        if filtered or not public_label:
            raise ExecutiveSafetyError("Approved memory reference is not publishable")
        return cls(reference_id=public_id, label=public_label)

    def to_dict(self) -> dict[str, str]:
        return {"reference_id": self.reference_id, "label": self.label}


@dataclass(frozen=True)
class ApprovedMemorySnapshot:
    references: tuple[ApprovedMemoryReference, ...] = ()
    context: str = field(default="", repr=False)
    context_sha256: str = ""

    @classmethod
    def empty(cls) -> ApprovedMemorySnapshot:
        return cls()

    @classmethod
    def build(
        cls,
        *,
        context: Any,
        references: Any = (),
    ) -> ApprovedMemorySnapshot:
        raw_context = str(context or "").strip()
        if not raw_context:
            return cls.empty()
        safe_context, _ = sanitize_public_text(
            raw_context,
            maximum=400,
            withheld_text="",
        )
        if not safe_context:
            return cls.empty()
        digest = hashlib.sha256(safe_context.encode("utf-8")).hexdigest()
        safe_references: list[ApprovedMemoryReference] = []
        raw_references = references if isinstance(references, (list, tuple)) else ()
        for raw in raw_references[:8]:
            try:
                if isinstance(raw, ApprovedMemoryReference):
                    reference = raw
                elif isinstance(raw, dict):
                    reference = ApprovedMemoryReference.build(
                        raw.get("reference_id") or raw.get("id"),
                        raw.get("label") or raw.get("title") or "Approved memory",
                    )
                else:
                    reference = ApprovedMemoryReference.build(
                        getattr(raw, "reference_id", None) or getattr(raw, "id", None),
                        getattr(raw, "label", None)
                        or getattr(raw, "title", None)
                        or "Approved memory",
                    )
            except ExecutiveSafetyError:
                continue
            if all(
                item.reference_id != reference.reference_id for item in safe_references
            ):
                safe_references.append(reference)
        if not safe_references:
            safe_references.append(
                ApprovedMemoryReference(
                    reference_id=f"approved-memory-{digest[:20]}",
                    label="Approved persistent memory context",
                )
            )
        return cls(
            references=tuple(safe_references),
            context=safe_context,
            context_sha256=digest,
        )

    def prompt_block(self) -> str:
        references = "\n".join(
            f"- {item.reference_id}: {item.label}" for item in self.references
        )
        return (
            "Approved memory references (host-approved background only):\n"
            f"{references or '- none'}\n"
            "Approved memory context:\n"
            f"{self.context or '(none approved)'}"
        )


@dataclass(frozen=True)
class GenerationTelemetry:
    generation_id: str
    selected_model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    actual_cost_usd: Decimal
    source: Literal["openrouter_generation", "openrouter_stream"] = (
        "openrouter_generation"
    )

    @classmethod
    def build(
        cls,
        *,
        generation_id: Any,
        selected_model: Any,
        input_tokens: Any,
        output_tokens: Any,
        total_tokens: Any,
        actual_cost_usd: Any,
        source: Literal["openrouter_generation", "openrouter_stream"] = (
            "openrouter_generation"
        ),
    ) -> GenerationTelemetry:
        if source not in {"openrouter_generation", "openrouter_stream"}:
            raise GenerationTelemetryError("generation telemetry source is unavailable")
        public_generation_id = require_public_identifier(generation_id)
        tokens_in = _bounded_nonnegative_int(
            input_tokens, field_name="input token count"
        )
        tokens_out = _bounded_nonnegative_int(
            output_tokens, field_name="output token count"
        )
        tokens_total = _bounded_nonnegative_int(
            total_tokens, field_name="total token count"
        )
        if tokens_total != tokens_in + tokens_out:
            raise GenerationTelemetryError("total token count is inconsistent")
        return cls(
            generation_id=public_generation_id,
            selected_model=_safe_model(selected_model),
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            total_tokens=tokens_total,
            actual_cost_usd=_bounded_decimal(
                actual_cost_usd, field_name="actual provider cost"
            ),
            source=source,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation_id": self.generation_id,
            "selected_model": self.selected_model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "actual_cost_usd": format(self.actual_cost_usd, "f"),
            "source": self.source,
        }


@dataclass(frozen=True)
class TimedGeneration:
    phase: Literal["root_plan", "worker", "root_synthesis"]
    role: str
    started_at: str
    ended_at: str
    started_monotonic: float = field(repr=False)
    ended_monotonic: float = field(repr=False)
    telemetry: GenerationTelemetry | None = None
    status: Literal["completed", "failed", "timed_out"] = "completed"

    def __post_init__(self) -> None:
        valid_role = self.role == "executive" or self.role in ALLOWED_DELEGATION_ROLES
        if (
            not valid_role
            or not isinstance(self.started_at, str)
            or not isinstance(self.ended_at, str)
            or not self.started_at
            or not self.ended_at
            or not math.isfinite(self.started_monotonic)
            or not math.isfinite(self.ended_monotonic)
            or self.ended_monotonic < self.started_monotonic
        ):
            raise ValueError("generation timing is invalid")
        try:
            datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            datetime.fromisoformat(self.ended_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("generation timing is invalid") from exc

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "phase": self.phase,
            "role": self.role,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": round(
                (self.ended_monotonic - self.started_monotonic) * 1_000
            ),
            "status": self.status,
        }
        if self.telemetry is not None:
            payload.update(self.telemetry.to_dict())
        else:
            payload["telemetry"] = "unavailable"
        return payload


@dataclass(frozen=True)
class BoundedTestPolicyV1:
    target_cost_usd: Decimal = Decimal("0.03")
    hard_cost_usd: Decimal = Decimal("0.10")
    max_total_tokens: int = 12_000
    worker_limit: int = 2
    max_user_prompt_utf8_bytes: int = 1_800
    max_bounded_workdir_utf8_bytes: int = 256
    prime_fixed_prompt_utf8_bytes: int = 189
    chat_framing_token_reserve: int = 128
    max_output_tokens_per_generation: int = 600
    reserved_tokens_per_generation: int = 3_000
    reserved_cost_per_generation_usd: Decimal = Decimal("0.0054")
    max_prompt_price_usd_per_million: Decimal = Decimal(1)
    max_completion_price_usd_per_million: Decimal = Decimal(5)
    max_request_price_usd: Decimal = Decimal(0)
    max_image_price_usd: Decimal = Decimal(0)
    max_audio_price_usd: Decimal = Decimal(0)
    memory_recall_timeout_seconds: float = 5.0
    root_timeout_seconds: float = 40.0
    worker_start_timeout_seconds: float = 10.0
    worker_timeout_seconds: float = 40.0
    synthesis_timeout_seconds: float = 40.0
    cleanup_timeout_seconds: float = 5.0
    handoff_timeout_seconds: float = 3.0
    total_turn_timeout_seconds: float = 195.0
    contract_version: str = "1.0"

    def __post_init__(self) -> None:
        # Prime 0.7.1 appends its pinned custom system prompt, current-date line,
        # and cwd label. A UTF-8 byte is a conservative upper bound for one text
        # token; the explicit framing reserve covers provider chat-template tokens.
        prospective_total = (
            self.max_user_prompt_utf8_bytes
            + self.max_bounded_workdir_utf8_bytes
            + self.prime_fixed_prompt_utf8_bytes
            + self.chat_framing_token_reserve
            + self.max_output_tokens_per_generation
        )
        if prospective_total > self.reserved_tokens_per_generation:
            raise ValueError("bounded generation reservation is not prospective")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "profile": BOUNDED_TEST_PROFILE,
            "contract_version": self.contract_version,
            "target_cost_usd": float(self.target_cost_usd),
            "hard_cost_usd": float(self.hard_cost_usd),
            "max_total_tokens": self.max_total_tokens,
            "worker_limit": self.worker_limit,
            "max_user_prompt_utf8_bytes": self.max_user_prompt_utf8_bytes,
            "max_bounded_workdir_utf8_bytes": self.max_bounded_workdir_utf8_bytes,
            "prime_fixed_prompt_utf8_bytes": self.prime_fixed_prompt_utf8_bytes,
            "chat_framing_token_reserve": self.chat_framing_token_reserve,
            "prospective_total_tokens_per_generation": (
                self.max_user_prompt_utf8_bytes
                + self.max_bounded_workdir_utf8_bytes
                + self.prime_fixed_prompt_utf8_bytes
                + self.chat_framing_token_reserve
                + self.max_output_tokens_per_generation
            ),
            "max_output_tokens_per_generation": (self.max_output_tokens_per_generation),
            "model_selector": "openrouter/auto",
            "timeouts_seconds": {
                "memory_recall": self.memory_recall_timeout_seconds,
                "root_plan": self.root_timeout_seconds,
                "worker_start": self.worker_start_timeout_seconds,
                "worker_prompt": self.worker_timeout_seconds,
                "root_synthesis": self.synthesis_timeout_seconds,
                "cleanup": self.cleanup_timeout_seconds,
                "handoff_append": self.handoff_timeout_seconds,
                "whole_turn": self.total_turn_timeout_seconds,
            },
            "provider_max_price": {
                "prompt": str(self.max_prompt_price_usd_per_million),
                "completion": str(self.max_completion_price_usd_per_million),
                "request": str(self.max_request_price_usd),
                "image": str(self.max_image_price_usd),
                "audio": str(self.max_audio_price_usd),
            },
            "text_only": True,
            "requires_account_default_paid_plugins_disabled": True,
        }


DEFAULT_BOUNDED_TEST_POLICY = BoundedTestPolicyV1()


@dataclass
class BoundedRunLedger:
    policy: BoundedTestPolicyV1 = DEFAULT_BOUNDED_TEST_POLICY
    entries: list[TimedGeneration] = field(default_factory=list)
    _generation_ids: set[str] = field(default_factory=set, repr=False)
    _reserved_calls: int = field(default=0, repr=False)
    failure_reason: str | None = None
    synthesis_skipped_reason: str | None = None
    peak_active_workers: int = 0

    @property
    def actual_cost_usd(self) -> Decimal:
        return sum(
            (
                entry.telemetry.actual_cost_usd
                for entry in self.entries
                if entry.telemetry is not None
            ),
            Decimal(0),
        )

    @property
    def total_tokens(self) -> int:
        return sum(
            entry.telemetry.total_tokens
            for entry in self.entries
            if entry.telemetry is not None
        )

    @property
    def telemetry_complete(self) -> bool:
        return bool(self.entries) and all(
            entry.telemetry is not None for entry in self.entries
        )

    def reserve(self, count: int = 1) -> bool:
        count = int(count)
        if count < 1:
            return False
        projected_tokens = self.total_tokens + (
            (self._reserved_calls + count) * self.policy.reserved_tokens_per_generation
        )
        projected_cost = self.actual_cost_usd + (
            Decimal(self._reserved_calls + count)
            * self.policy.reserved_cost_per_generation_usd
        )
        if projected_tokens > self.policy.max_total_tokens:
            self.failure_reason = "token_reservation_exceeded"
            return False
        if projected_cost > self.policy.hard_cost_usd:
            self.failure_reason = "cost_reservation_exceeded"
            return False
        self._reserved_calls += count
        return True

    def release_reservation(self, count: int = 1) -> None:
        self._reserved_calls = max(0, self._reserved_calls - max(0, int(count)))

    def record(self, entry: TimedGeneration) -> None:
        telemetry = entry.telemetry
        if telemetry is not None and telemetry.generation_id in self._generation_ids:
            # The duplicate identity fails the gate, but the authoritative
            # receipt still represents provider spend and must be settled.
            self.entries.append(entry)
            self.failure_reason = self.failure_reason or "duplicate_generation_id"
            return
        self.entries.append(entry)
        if telemetry is None:
            self.failure_reason = self.failure_reason or "telemetry_unavailable"
            return
        self._generation_ids.add(telemetry.generation_id)
        if telemetry.total_tokens > self.policy.reserved_tokens_per_generation:
            self.failure_reason = "per_generation_token_limit_exceeded"
        if telemetry.output_tokens > self.policy.max_output_tokens_per_generation:
            self.failure_reason = "generation_output_limit_exceeded"
        if self.actual_cost_usd > self.policy.hard_cost_usd:
            self.failure_reason = "hard_cost_exceeded"
        if self.total_tokens > self.policy.max_total_tokens:
            self.failure_reason = "token_limit_exceeded"

    @property
    def hard_limits_passed(self) -> bool:
        return (
            self.failure_reason is None
            and self.telemetry_complete
            and self.actual_cost_usd <= self.policy.hard_cost_usd
            and self.total_tokens <= self.policy.max_total_tokens
        )

    @property
    def target_met(self) -> bool:
        return self.actual_cost_usd <= self.policy.target_cost_usd

    def can_run_optional_synthesis(self) -> bool:
        if not self.hard_limits_passed or not self.target_met:
            return False
        return (
            self.total_tokens + self.policy.reserved_tokens_per_generation
            <= self.policy.max_total_tokens
            and self.actual_cost_usd + self.policy.reserved_cost_per_generation_usd
            <= self.policy.target_cost_usd
            and self.actual_cost_usd + self.policy.reserved_cost_per_generation_usd
            <= self.policy.hard_cost_usd
        )

    def fail(self, reason: str) -> None:
        self.failure_reason = self.failure_reason or require_public_identifier(reason)

    def to_dict(self) -> dict[str, Any]:
        workers = [entry for entry in self.entries if entry.phase == "worker"]
        overlap: dict[str, Any] = {
            "worker_start_delta_ms": None,
            "worker_overlap_ms": 0,
            "worker_overlap_ratio": 0.0,
        }
        if len(workers) == 2:
            first, second = workers
            overlap_ms = max(
                0,
                round(
                    (
                        min(first.ended_monotonic, second.ended_monotonic)
                        - max(first.started_monotonic, second.started_monotonic)
                    )
                    * 1_000
                ),
            )
            shorter_ms = max(
                1,
                min(
                    round((first.ended_monotonic - first.started_monotonic) * 1_000),
                    round((second.ended_monotonic - second.started_monotonic) * 1_000),
                ),
            )
            overlap = {
                "worker_start_delta_ms": round(
                    abs(first.started_monotonic - second.started_monotonic) * 1_000
                ),
                "worker_overlap_ms": overlap_ms,
                "worker_overlap_ratio": round(overlap_ms / shorter_ms, 4),
            }
        completed_workers = [
            entry
            for entry in workers
            if entry.status == "completed" and entry.telemetry is not None
        ]
        worker_limit_respected = (
            0 < self.peak_active_workers <= self.policy.worker_limit
        )
        parallelism_passed = (
            len(completed_workers) == self.policy.worker_limit
            and self.peak_active_workers == self.policy.worker_limit
            and overlap["worker_start_delta_ms"] is not None
            and overlap["worker_start_delta_ms"] <= 2_000
            and overlap["worker_overlap_ms"] > 0
            and overlap["worker_overlap_ratio"] >= 0.5
            and worker_limit_respected
        )
        completed_root_plans = [
            entry
            for entry in self.entries
            if entry.phase == "root_plan"
            and entry.status == "completed"
            and entry.telemetry is not None
        ]
        completed_syntheses = [
            entry
            for entry in self.entries
            if entry.phase == "root_synthesis"
            and entry.status == "completed"
            and entry.telemetry is not None
        ]
        synthesis_passed = len(completed_syntheses) == 1
        execution_shape_passed = (
            len(completed_root_plans) == 1
            and synthesis_passed
            and len(self._generation_ids) == 4
        )
        return {
            "contract": "orch.executive.bounded-test",
            "contract_version": self.policy.contract_version,
            "policy": self.policy.to_public_dict(),
            "actual_cost_usd": format(self.actual_cost_usd, "f"),
            "total_tokens": self.total_tokens,
            "generation_count": len(self._generation_ids),
            "telemetry_complete": self.telemetry_complete,
            "target_met": self.target_met,
            "hard_limits_passed": self.hard_limits_passed,
            "passed": (
                self.hard_limits_passed
                and self.target_met
                and parallelism_passed
                and execution_shape_passed
            ),
            "failure_reason": self.failure_reason,
            "synthesis_skipped_reason": self.synthesis_skipped_reason,
            "entries": [entry.to_dict() for entry in self.entries],
            "synthesis_passed": synthesis_passed,
            "execution_shape_passed": execution_shape_passed,
            "parallelism": {
                **overlap,
                "peak_active_workers": self.peak_active_workers,
                "worker_limit_respected": worker_limit_respected,
                "parallelism_passed": parallelism_passed,
            },
        }


def mission_text_sha256(message: str) -> str:
    safe_message = sanitize_private_input(message, maximum=16_000)
    return hashlib.sha256(safe_message.encode("utf-8")).hexdigest()


def bounded_run_spec_sha256(
    *,
    mission_text_sha: str,
    workers: tuple[tuple[str, str], ...],
    memory: ApprovedMemorySnapshot,
    policy: BoundedTestPolicyV1 = DEFAULT_BOUNDED_TEST_POLICY,
) -> str:
    """One safe digest proving which immutable bounded spec a run used."""

    policy_values: dict[str, Any] = {}
    for item in fields(policy):
        value = getattr(policy, item.name)
        policy_values[item.name] = (
            format(value, "f") if isinstance(value, Decimal) else value
        )
    canonical = {
        "contract": "orch.executive.bounded-test-spec",
        "contract_version": policy.contract_version,
        "mission_text_sha256": require_public_identifier(mission_text_sha),
        "worker_specs": [
            {
                "role": role,
                "task_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
            }
            for role, task in workers
        ],
        "approved_memory": {
            "context_sha256": memory.context_sha256,
            "references_sha256": hashlib.sha256(
                json.dumps(
                    [item.to_dict() for item in memory.references],
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
        },
        "model_selector": "openrouter/auto",
        "policy": policy_values,
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
