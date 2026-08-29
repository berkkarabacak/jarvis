"""External runtime adapters for ORCH-71 (Prime Agent, model routing)."""

from app.executive.adapters.prime import (
    NullPrimeAgent,
    PrimeAgentRuntime,
    PrimeMessageResult,
    PrimeRuntimeError,
    PrimeSessionInfo,
    PrimeUnavailableError,
)
from app.executive.adapters.prime_rpc import (
    OPENROUTER_AUTOROUTER_MODEL,
    PRIME_AGENT_COMMIT,
    PRIME_AGENT_VERSION,
    PrimeJsonlRpcAgent,
    PrimeRpcClient,
    PrimeRpcTransport,
    SubprocessPrimeRpcTransport,
    build_prime_agent_from_environment,
    build_prime_environment,
)
from app.executive.adapters.routing import (
    HeuristicModelRouter,
    ModelRouteDecision,
    ModelRouter,
    NullModelRouter,
)

__all__ = [
    "OPENROUTER_AUTOROUTER_MODEL",
    "PRIME_AGENT_COMMIT",
    "PRIME_AGENT_VERSION",
    "HeuristicModelRouter",
    "ModelRouteDecision",
    "ModelRouter",
    "NullModelRouter",
    "NullPrimeAgent",
    "PrimeAgentRuntime",
    "PrimeJsonlRpcAgent",
    "PrimeMessageResult",
    "PrimeRpcClient",
    "PrimeRpcTransport",
    "PrimeRuntimeError",
    "PrimeSessionInfo",
    "PrimeUnavailableError",
    "SubprocessPrimeRpcTransport",
    "build_prime_agent_from_environment",
    "build_prime_environment",
]
