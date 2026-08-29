from __future__ import annotations

import base64
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.control_plane.models import TERMINAL_MISSION_STATUSES, AuditEvent, Mission
from app.control_plane.store import ControlPlaneStore

CONTRACT_VERSION = "1.0"
CONTRACT_NAME = "orch.control-plane.event"
EVENT_VISIBILITY = "executive_safe"

MISSION_STATUS = "mission_status"
BUDGET_AUDIT_DECISION = "budget_audit_decision"
EXECUTIVE_MESSAGE = "executive_message"
HANDOFF = "handoff"
EVIDENCE = "evidence"
CONFIDENCE = "confidence"

PUBLIC_EVENT_TYPES = frozenset(
    {
        MISSION_STATUS,
        BUDGET_AUDIT_DECISION,
        EXECUTIVE_MESSAGE,
        HANDOFF,
        EVIDENCE,
        CONFIDENCE,
    }
)
PUBLISHABLE_EVENT_TYPES = frozenset(
    {EXECUTIVE_MESSAGE, HANDOFF, EVIDENCE, CONFIDENCE}
)

MISSION_AUDIT_TO_STATUS = {
    "mission.created": "draft",
    "mission.queued": "queued",
    "mission.started": "running",
    "mission.succeeded": "succeeded",
    "mission.failed": "failed",
    "mission.killed": "killed",
    "mission.deadline_blocked": "failed",
}
BUDGET_AUDIT_TO_ACTION = {
    "budget.denied": ("reserve_or_commit", "denied"),
    "budget.reserved": ("reserve", "approved"),
    "budget.committed": ("commit", "approved"),
    "budget.released": ("release", "approved"),
}
SAFE_AUDIT_EVENT_TYPES = frozenset(
    set(MISSION_AUDIT_TO_STATUS)
    | set(BUDGET_AUDIT_TO_ACTION)
    | {f"public.{event_type}" for event_type in PUBLISHABLE_EVENT_TYPES}
)

MISSION_READ = "mission.read"
AUDIT_READ = "audit.read"
EVENT_PUBLISH = "event.publish"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REASONING_MARKERS = re.compile(
    r"(?i)(chain[ _-]?of[ _-]?thought|private[ _-]?reasoning|scratchpad|<thinking>|"
    r"browser[ _-]?session|session[ _-]?cookie|document\.cookie|"
    r"localstorage|sessionstorage|begin[ _-]?private[ _-]?key)"
)
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}"),
    re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=]{8,}"),
    re.compile(
        r"(?i)\b[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|COOKIE|SESSION)"
        r"\s*=\s*[^\s,;]+"
    ),
    re.compile(
        r"(?i)\b(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
        r"password|secret|cookie|session)\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"\b(?:sk-|xai-|ghp_|github_pat_)[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+)?"),
    re.compile(r"(?i)https?://[^\s/@:]+:[^\s/@]+@[^\s]+"),
    re.compile(r"(?i)https?://[^\s?#]+[?#][^\s]+"),
)
_FORBIDDEN_KEY_PARTS = (
    "reasoning",
    "chainofthought",
    "scratchpad",
    "credential",
    "token",
    "apikey",
    "password",
    "secret",
    "authorization",
    "cookie",
    "session",
    "browser",
    "rawresponse",
    "prompt",
    "privatememory",
)


class EventContractError(Exception):
    code = "event_contract_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EventValidationError(EventContractError):
    code = "event_validation_error"


class EventAuthorizationError(EventContractError):
    code = "event_forbidden"


class EventNotFoundError(EventContractError):
    code = "event_subject_not_found"


@dataclass(frozen=True)
class EventAccess:
    """Authorization port; ORCH-69 can replace the current API-key adapter."""

    org_id: str | None
    capabilities: frozenset[str]
    global_owner: bool = False

    @classmethod
    def owner(cls, org_id: str) -> EventAccess:
        return cls(
            org_id=org_id,
            capabilities=frozenset({MISSION_READ, AUDIT_READ, EVENT_PUBLISH}),
        )

    @classmethod
    def legacy_global_owner(cls) -> EventAccess:
        """Transitional access for the existing operator-wide API secret."""

        return cls(
            org_id=None,
            capabilities=frozenset({MISSION_READ, AUDIT_READ, EVENT_PUBLISH}),
            global_owner=True,
        )


@dataclass(frozen=True)
class PublicEvent:
    id: str
    cursor: str
    type: str
    occurred_at: str
    org_id: str
    mission_id: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": CONTRACT_NAME,
            "contract_version": CONTRACT_VERSION,
            "id": self.id,
            "cursor": self.cursor,
            "type": self.type,
            "occurred_at": self.occurred_at,
            "source": "control_plane",
            "org_id": self.org_id,
            "mission_id": self.mission_id,
            "visibility": EVENT_VISIBILITY,
            "data": dict(self.data),
        }


def encode_cursor(sequence: int) -> str:
    if sequence < 0:
        raise EventValidationError("Invalid event cursor")
    raw = int(sequence).to_bytes(8, "big", signed=False)
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"v1.{encoded}"


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        prefix, encoded = cursor.split(".", 1)
        if prefix != "v1" or not encoded:
            raise ValueError
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if len(raw) != 8:
            raise ValueError
        return int.from_bytes(raw, "big", signed=False)
    except (TypeError, ValueError, base64.binascii.Error) as exc:
        raise EventValidationError("Invalid event cursor") from exc


def _iso_time(timestamp: float) -> str:
    return (
        datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _normalized_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _reject_forbidden_structure(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_key(key)
            if any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
                raise EventValidationError("Event contains a forbidden field")
            _reject_forbidden_structure(child)
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden_structure(child)


def _safe_text(value: Any, *, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise EventValidationError("Event field must be text")
    text = value.strip()
    if required and not text:
        raise EventValidationError("Event field is required")
    if len(text) > maximum:
        raise EventValidationError("Event field exceeds its size limit")
    if _REASONING_MARKERS.search(text):
        raise EventValidationError("Event contains non-public reasoning")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text


def _safe_identifier(value: Any) -> str:
    text = _safe_text(value, maximum=128)
    if "[redacted]" in text or not _IDENTIFIER.fullmatch(text):
        raise EventValidationError("Event identifier is invalid")
    return text


def _safe_identifiers(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise EventValidationError("Event references are invalid")
    return [_safe_identifier(item) for item in value]


def _strict_fields(
    data: dict[str, Any], *, required: Iterable[str], optional: Iterable[str] = ()
) -> None:
    required_set = set(required)
    allowed = required_set | set(optional)
    if set(data) - allowed or required_set - set(data):
        raise EventValidationError("Event fields do not match the contract")


def sanitize_publish_data(event_type: str, data: Any) -> dict[str, Any]:
    if event_type not in PUBLISHABLE_EVENT_TYPES:
        raise EventValidationError("Only safe integration events may be published")
    if not isinstance(data, dict):
        raise EventValidationError("Event data must be an object")
    _reject_forbidden_structure(data)

    if event_type == EXECUTIVE_MESSAGE:
        _strict_fields(data, required={"summary"}, optional={"severity", "action_required"})
        severity = data.get("severity", "info")
        if severity not in {"info", "warning", "action_required"}:
            raise EventValidationError("Executive message severity is invalid")
        action_required = data.get("action_required", severity == "action_required")
        if not isinstance(action_required, bool):
            raise EventValidationError("action_required must be boolean")
        return {
            "severity": severity,
            "summary": _safe_text(data["summary"], maximum=1000),
            "action_required": action_required,
        }

    if event_type == HANDOFF:
        _strict_fields(
            data,
            required={"handoff_id", "from_role", "to_role", "status", "summary"},
            optional={"evidence_ids"},
        )
        status = data["status"]
        if status not in {"offered", "accepted", "completed", "blocked"}:
            raise EventValidationError("Handoff status is invalid")
        return {
            "handoff_id": _safe_identifier(data["handoff_id"]),
            "from_role": _safe_identifier(data["from_role"]),
            "to_role": _safe_identifier(data["to_role"]),
            "status": status,
            "summary": _safe_text(data["summary"], maximum=1000),
            "evidence_ids": _safe_identifiers(data.get("evidence_ids")),
        }

    if event_type == EVIDENCE:
        _strict_fields(
            data,
            required={"evidence_id", "kind", "reference_id", "label", "verification_status"},
        )
        kind = data["kind"]
        if kind not in {
            "artifact",
            "test",
            "automated_test",
            "ui_test",
            "visual_review",
            "independent_review",
            "screenshot",
            "trace",
            "document",
            "metric",
        }:
            raise EventValidationError("Evidence kind is invalid")
        verification = data["verification_status"]
        if verification not in {"pending", "verified", "failed"}:
            raise EventValidationError("Evidence verification status is invalid")
        return {
            "evidence_id": _safe_identifier(data["evidence_id"]),
            "kind": kind,
            "reference_id": _safe_identifier(data["reference_id"]),
            "label": _safe_text(data["label"], maximum=240),
            "verification_status": verification,
        }

    _strict_fields(
        data,
        required={"subject_type", "subject_id", "score", "basis"},
    )
    subject_type = data["subject_type"]
    if subject_type not in {"mission", "handoff", "evidence"}:
        raise EventValidationError("Confidence subject type is invalid")
    score = data["score"]
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise EventValidationError("Confidence score must be an integer from 0 to 100")
    basis = data["basis"]
    allowed_basis = {"status", "budget", "tests", "evidence", "handoffs"}
    if (
        not isinstance(basis, list)
        or not 1 <= len(basis) <= 5
        or any(item not in allowed_basis for item in basis)
    ):
        raise EventValidationError("Confidence basis is invalid")
    return {
        "subject_type": subject_type,
        "subject_id": _safe_identifier(data["subject_id"]),
        "score": score,
        "basis": list(dict.fromkeys(basis)),
    }


def _safe_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _project_audit(
    sequence: int, audit: AuditEvent, *, org_id: str
) -> PublicEvent | None:
    event_type: str
    data: dict[str, Any]

    if audit.event_type in MISSION_AUDIT_TO_STATUS:
        status = MISSION_AUDIT_TO_STATUS[audit.event_type]
        previous = audit.detail.get("from")
        if previous not in {
            "draft",
            "queued",
            "running",
            "blocked",
            "succeeded",
            "failed",
            "killed",
        }:
            previous = None
        data = {
            "status": status,
            "previous_status": previous,
            "terminal": status in TERMINAL_MISSION_STATUSES,
        }
        if audit.event_type == "mission.deadline_blocked":
            data["reason_code"] = "deadline_exceeded"
        event_type = MISSION_STATUS
    elif audit.event_type in BUDGET_AUDIT_TO_ACTION:
        action, outcome = BUDGET_AUDIT_TO_ACTION[audit.event_type]
        data = {"domain": "budget", "action": action, "outcome": outcome}
        if outcome == "denied":
            reason = audit.detail.get("reason")
            data["reason_code"] = (
                reason
                if reason in {"insufficient_budget", "insufficient_budget_on_commit"}
                else "policy_denied"
            )
        for key in (
            "requested_cents",
            "amount_cents",
            "available_cents",
            "limit_cents",
            "spend_cents",
            "reserved_cents",
        ):
            number = _safe_nonnegative_int(audit.detail.get(key))
            if number is not None:
                data[key] = number
        event_type = BUDGET_AUDIT_DECISION
    elif audit.event_type.startswith("public."):
        event_type = audit.event_type.removeprefix("public.")
        if event_type not in PUBLISHABLE_EVENT_TYPES:
            return None
        try:
            data = sanitize_publish_data(event_type, audit.detail)
        except EventValidationError:
            return None
        if event_type == CONFIDENCE:
            score = data["score"]
            data["band"] = "high" if score >= 80 else "medium" if score >= 50 else "low"
    else:
        return None

    if audit.mission_id is None:
        return None
    return PublicEvent(
        id=audit.id,
        cursor=encode_cursor(sequence),
        type=event_type,
        occurred_at=_iso_time(audit.created_at),
        org_id=org_id,
        mission_id=audit.mission_id,
        data=data,
    )


class ControlPlaneEvents:
    def __init__(self, store: ControlPlaneStore) -> None:
        self.store = store

    @staticmethod
    def _authorize(
        access: EventAccess, mission: Mission | None, capability: str
    ) -> Mission:
        if mission is None or (
            not access.global_owner and mission.org_id != access.org_id
        ):
            raise EventNotFoundError("Mission not found")
        if capability not in access.capabilities:
            raise EventAuthorizationError("Event access denied")
        return mission

    async def history(
        self,
        *,
        access: EventAccess,
        mission_id: str,
        after: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        mission = self._authorize(
            access, await self.store.get_mission(mission_id), MISSION_READ
        )
        sequence = decode_cursor(after)
        bounded_limit = max(1, min(int(limit), 200))
        allowed_types = set(MISSION_AUDIT_TO_STATUS)
        allowed_types.update(f"public.{item}" for item in PUBLISHABLE_EVENT_TYPES)
        if AUDIT_READ in access.capabilities:
            allowed_types.update(BUDGET_AUDIT_TO_ACTION)
        rows = await self.store.list_audit_after(
            mission_id=mission.id,
            after_sequence=sequence,
            event_types=allowed_types,
            limit=bounded_limit + 1,
        )
        has_more = len(rows) > bounded_limit
        rows = rows[:bounded_limit]
        events = [
            projected.to_dict()
            for row_sequence, audit in rows
            if (projected := _project_audit(row_sequence, audit, org_id=mission.org_id))
            is not None
        ]
        next_cursor = encode_cursor(rows[-1][0]) if rows else after
        return {
            "contract": CONTRACT_NAME,
            "contract_version": CONTRACT_VERSION,
            "events": events,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    async def publish(
        self,
        *,
        access: EventAccess,
        mission_id: str,
        event_type: str,
        data: Any,
    ) -> dict[str, Any]:
        mission = self._authorize(
            access, await self.store.get_mission(mission_id), EVENT_PUBLISH
        )
        safe_data = sanitize_publish_data(event_type, data)
        audit = await self.store.append_audit(
            event_type=f"public.{event_type}",
            actor="event_contract",
            mission_id=mission.id,
            detail=safe_data,
        )
        sequence = await self.store.audit_sequence(audit.id)
        projected = _project_audit(sequence, audit, org_id=mission.org_id)
        if projected is None:  # pragma: no cover - defensive invariant
            raise EventContractError("Event projection failed")
        return projected.to_dict()
