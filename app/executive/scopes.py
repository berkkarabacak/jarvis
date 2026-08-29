from __future__ import annotations

# Control Room memory scopes (ORCH-71). Extends legacy shared/private (ORCH-38).
CONTROL_ROOM_SCOPES = frozenset(
    {
        "run",  # ephemeral current-run only
        "specialist",  # private to one agent instance / role
        "team",  # shared among specialists on one mission team
        "company",  # org-durable, executive-reviewed
        "shared",  # legacy project shared (ORCH-38)
        "private",  # legacy agent private (ORCH-38)
    }
)

_ALIASES = {
    "agent": "specialist",
    "role": "specialist",
    "mission": "team",
    "org": "company",
    "organization": "company",
    "global": "company",
}


def normalize_memory_scope(scope: str | None) -> str:
    """Return a canonical scope or raise ValueError."""
    raw = (scope or "").strip().lower()
    if not raw:
        raise ValueError("memory scope is required")
    raw = _ALIASES.get(raw, raw)
    if raw not in CONTROL_ROOM_SCOPES:
        allowed = ", ".join(sorted(CONTROL_ROOM_SCOPES))
        raise ValueError(f"unknown memory scope {scope!r}; allowed: {allowed}")
    return raw
