from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ModelRouteDecision:
    """Evidence-aware model choice — no provider call is made here."""

    model: str
    provider: str
    reason: str
    estimated_cost_usd: float | None = None
    quality_mode: str = "balanced"
    escalate: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "reason": self.reason,
            "estimated_cost_usd": self.estimated_cost_usd,
            "quality_mode": self.quality_mode,
            "escalate": self.escalate,
            "metadata": dict(self.metadata),
        }


@runtime_checkable
class ModelRouter(Protocol):
    """Port for OpenRouter (or other) adaptive routing.

    Must remain callable without live API keys — return a plan only.
    """

    name: str

    async def route(
        self,
        *,
        task_summary: str,
        quality_mode: str = "balanced",
        remaining_budget_usd: float | None = None,
        prior_failures: int = 0,
        requires_tools: bool = False,
    ) -> ModelRouteDecision: ...

    async def health(self) -> dict[str, Any]: ...


class NullModelRouter:
    """No provider credentials — deterministic placeholder decision."""

    name = "null"

    def __init__(self, *, default_model: str = "openrouter/auto") -> None:
        self.default_model = default_model
        self._last_error: str | None = None

    async def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "available": False,
            "availability": "unavailable",
            "adapter": self.name,
            "live_provider": False,
            "live": False,
            "credentials_configured": False,
            "last_error": self._last_error,
            "detail": "NullModelRouter — OpenRouter unavailable; plan-only, no network",
        }

    async def route(
        self,
        *,
        task_summary: str,
        quality_mode: str = "balanced",
        remaining_budget_usd: float | None = None,
        prior_failures: int = 0,
        requires_tools: bool = False,
    ) -> ModelRouteDecision:
        return ModelRouteDecision(
            model=self.default_model,
            provider="none",
            reason="null router; wire OpenRouter adapter when credentials exist",
            estimated_cost_usd=None,
            quality_mode=quality_mode,
            escalate=False,
            metadata={"task_chars": len(task_summary or "")},
        )


class HeuristicModelRouter:
    """Credential-free heuristic plan for cheapest-capable selection.

    Does not call OpenRouter. Produces a routing *decision* the control plane
    or a future live adapter can execute.
    """

    name = "heuristic"

    # Ordered cheapest → premium (illustrative; live table comes from CP later)
    _LADDER = (
        ("openrouter/auto", 0.002, "auto"),
        ("openai/gpt-4.1-mini", 0.01, "cheap"),
        ("anthropic/claude-sonnet-4", 0.05, "balanced"),
        ("openai/gpt-4.1", 0.12, "premium"),
    )

    async def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "available": True,
            "availability": "plan_only",
            "adapter": self.name,
            "live_provider": False,
            "live": False,
            "credentials_configured": False,
            "last_error": None,
            "ladder": [m[0] for m in self._LADDER],
            "detail": (
                "Heuristic plan-only router — no OpenRouter credentials used or logged; "
                "live execution deferred"
            ),
        }

    async def route(
        self,
        *,
        task_summary: str,
        quality_mode: str = "balanced",
        remaining_budget_usd: float | None = None,
        prior_failures: int = 0,
        requires_tools: bool = False,
    ) -> ModelRouteDecision:
        text = (task_summary or "").lower()
        mode = (quality_mode or "balanced").lower()
        # Start index by quality preference
        idx = 0
        if mode in ("premium", "max", "high"):
            idx = 3
        elif mode in ("balanced", "default"):
            idx = 2 if requires_tools or len(text) > 400 else 1
        elif mode in ("cheap", "economy", "low"):
            idx = 0
        # Escalate on prior failures
        idx = min(len(self._LADDER) - 1, idx + max(0, int(prior_failures)))
        # Budget ceiling: step down until estimate fits
        while idx > 0 and remaining_budget_usd is not None:
            if self._LADDER[idx][1] <= float(remaining_budget_usd):
                break
            idx -= 1
        model, est, tier = self._LADDER[idx]
        escalate = prior_failures > 0 or tier in ("balanced", "premium")
        reason = (
            f"heuristic tier={tier} mode={mode} failures={prior_failures} "
            f"tools={requires_tools}"
        )
        return ModelRouteDecision(
            model=model,
            provider="openrouter-plan",
            reason=reason,
            estimated_cost_usd=est,
            quality_mode=mode,
            escalate=escalate,
            metadata={
                "tier": tier,
                "live_call": False,
                "task_chars": len(task_summary or ""),
            },
        )
