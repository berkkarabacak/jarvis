"""Executive runtime adapter selection.

Lives outside ``app.main`` so request handlers can rebuild the adapter (for
example when the OpenRouter credential is rotated at runtime) without importing
the application module and creating an import cycle.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.executive.adapters.openrouter_prime import build_openrouter_prime_agent
from app.executive.adapters.prime import NullPrimeAgent, PrimeAgentRuntime
from app.executive.adapters.prime_rpc import build_prime_agent_from_environment

log = logging.getLogger("agent_orchestrator.executive_adapter")


def build_executive_prime_agent(settings: Any) -> PrimeAgentRuntime:
    """Pick the executive runtime adapter for this host.

    ``EXECUTIVE_PRIME_ADAPTER`` pins the choice explicitly (``rpc``,
    ``openrouter``, ``jarvis``, or ``null``). Unset means auto-select:

    1. ``jarvis`` / ``JARVIS_ENABLED`` — local computer-use colleague (tools).
    2. ``PRIME_AGENT_ENABLED`` — external ``prime-agent`` binary over JSONL RPC.
    3. ``OPENROUTER_API_KEY`` — in-process OpenRouter chat (no tools).
    4. :class:`NullPrimeAgent`.
    """

    pinned = str(os.environ.get("EXECUTIVE_PRIME_ADAPTER", "")).strip().lower()
    if pinned == "null":
        log.info("executive runtime adapter: null (pinned)")
        return NullPrimeAgent()

    # Jarvis local colleague (default on when JARVIS_ENABLED is not false)
    if pinned in {"jarvis", "local", ""}:
        try:
            from app.jarvis.agent import build_jarvis_agent

            jarvis = build_jarvis_agent(
                api_key=getattr(settings, "openrouter_api_key", "") or "",
                referer=getattr(settings, "public_base_url", "") or "",
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("jarvis adapter unavailable: %s", exc)
            jarvis = None
        if jarvis is not None and pinned == "jarvis":
            log.info("executive runtime adapter: jarvis-local (pinned)")
            return jarvis
        if jarvis is not None and pinned == "":
            log.info("executive runtime adapter: jarvis-local")
            return jarvis

    if pinned not in {"openrouter", "jarvis", "local"}:
        rpc_agent = build_prime_agent_from_environment()
        if getattr(rpc_agent, "name", "") != "null" or pinned == "rpc":
            log.info("executive runtime adapter: prime-rpc")
            return rpc_agent

    openrouter_agent = build_openrouter_prime_agent(
        api_key=getattr(settings, "openrouter_api_key", "") or "",
        referer=getattr(settings, "public_base_url", "") or "",
    )
    if openrouter_agent is not None:
        log.info("executive runtime adapter: openrouter (in-process)")
        return openrouter_agent

    log.warning(
        "executive runtime adapter: null — set OPENROUTER_API_KEY to enable live chat"
    )
    return NullPrimeAgent()
