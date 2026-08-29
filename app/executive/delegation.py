from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.executive.safety import (
    ExecutiveSafetyError,
    sanitize_private_input,
    sanitize_public_text,
)

MAX_DELEGATIONS = 2
MAX_PLAN_CHARS = 900
MAX_PLAN_REPLY_CHARS = 400
MAX_DELEGATION_TASK_CHARS = 160
ALLOWED_DELEGATION_ROLES = frozenset(
    {
        "analyst",
        "engineer",
        "planner",
        "researcher",
        "reviewer",
        "tester",
        "writer",
    }
)

_UNSAFE_PLAN_REPLY = "Executive response could not be safely processed"


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = child
    return value


@dataclass(frozen=True)
class DelegationRequest:
    role: str
    task: str = field(repr=False)


@dataclass(frozen=True)
class ParsedExecutiveReply:
    reply: str
    delegations: tuple[DelegationRequest, ...] = ()
    plan_rejected: bool = False


def _safe_reply(value: object) -> str:
    reply, _ = sanitize_public_text(
        value,
        maximum=MAX_PLAN_REPLY_CHARS,
        withheld_text=_UNSAFE_PLAN_REPLY,
    )
    return reply


def parse_executive_reply(value: object) -> ParsedExecutiveReply:
    """Parse a strict host delegation plan or preserve a normal plain reply.

    Any JSON-looking but nonconforming response fails closed to its safe `reply`
    field (when present) or a generic message. Delegation tasks never appear in
    the returned public reply and are kept out of repr/log-friendly structures.
    """

    if not isinstance(value, str):
        return ParsedExecutiveReply(reply=_UNSAFE_PLAN_REPLY, plan_rejected=True)
    text = value.replace("\x00", "").strip()
    if not text:
        return ParsedExecutiveReply(reply=_UNSAFE_PLAN_REPLY, plan_rejected=True)
    if not text.startswith("{"):
        if text.startswith(("[", "```")):
            return ParsedExecutiveReply(reply=_UNSAFE_PLAN_REPLY, plan_rejected=True)
        return ParsedExecutiveReply(reply=_safe_reply(text))
    # Stay below the adapter's existing 1,000-character public-result boundary,
    # so every accepted plan is parsed in full rather than after truncation.
    if len(text) > MAX_PLAN_CHARS:
        return ParsedExecutiveReply(reply=_UNSAFE_PLAN_REPLY, plan_rejected=True)
    try:
        raw = json.loads(text, object_pairs_hook=_strict_object)
    except (json.JSONDecodeError, ValueError):
        return ParsedExecutiveReply(reply=_UNSAFE_PLAN_REPLY, plan_rejected=True)
    if not isinstance(raw, dict):
        return ParsedExecutiveReply(reply=_UNSAFE_PLAN_REPLY, plan_rejected=True)

    raw_reply = raw.get("reply")
    fallback = _safe_reply(raw_reply)
    if set(raw) != {"reply", "delegations"}:
        return ParsedExecutiveReply(reply=fallback, plan_rejected=True)
    if not isinstance(raw_reply, str) or not raw_reply.strip():
        return ParsedExecutiveReply(reply=fallback, plan_rejected=True)
    _, reply_filtered = sanitize_public_text(
        raw_reply,
        maximum=MAX_PLAN_REPLY_CHARS,
        withheld_text=_UNSAFE_PLAN_REPLY,
    )
    if reply_filtered:
        return ParsedExecutiveReply(reply=fallback, plan_rejected=True)
    delegations = raw.get("delegations")
    if not isinstance(delegations, list) or len(delegations) > MAX_DELEGATIONS:
        return ParsedExecutiveReply(reply=fallback, plan_rejected=True)

    parsed: list[DelegationRequest] = []
    try:
        for item in delegations:
            if not isinstance(item, dict) or set(item) != {"role", "task"}:
                raise ExecutiveSafetyError("Delegation shape is invalid")
            role = item.get("role")
            if not isinstance(role, str) or role not in ALLOWED_DELEGATION_ROLES:
                raise ExecutiveSafetyError("Delegation role is invalid")
            task = sanitize_private_input(
                item.get("task"), maximum=MAX_DELEGATION_TASK_CHARS
            )
            parsed.append(DelegationRequest(role=role, task=task))
    except ExecutiveSafetyError:
        return ParsedExecutiveReply(reply=fallback, plan_rejected=True)

    return ParsedExecutiveReply(reply=fallback, delegations=tuple(parsed))


def final_public_reply(value: object) -> str:
    """Strip any second-round delegation plan and return only its safe reply."""

    return parse_executive_reply(value).reply
