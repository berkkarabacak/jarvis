from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from app.memory.sanitize import sanitize_text

HANDOFF_SCHEMA_VERSION = 1

_ROLE_MAX = 120
_TEXT_MAX = 8000
_LIST_MAX = 40
_REF_MAX = 200


class HandoffValidationError(ValueError):
    pass


@dataclass
class MemoryUpdate:
    scope: str
    body: str
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"scope": self.scope, "title": self.title, "body": self.body}


@dataclass
class HandoffPacket:
    """Structured, auditable agent-to-agent handoff (ORCH-71 / ORCH-58)."""

    from_role: str
    to_role: str
    objective: str
    attempted_work: str
    outcome: str
    confidence: float
    evidence_refs: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    costs: dict[str, Any] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    recommendation: str = ""
    memory_updates: list[MemoryUpdate] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    schema_version: int = HANDOFF_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["memory_updates"] = [m.to_dict() for m in self.memory_updates]
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def _s(value: Any, *, field_name: str, required: bool = True, max_chars: int = _TEXT_MAX) -> str:
    if value is None:
        if required:
            raise HandoffValidationError(f"missing required field: {field_name}")
        return ""
    if not isinstance(value, str):
        value = str(value)
    text = sanitize_text(value.strip(), max_chars=max_chars)
    if required and not text:
        raise HandoffValidationError(f"empty required field: {field_name}")
    return text


def _role(value: Any, *, field_name: str) -> str:
    text = _s(value, field_name=field_name, max_chars=_ROLE_MAX)
    # Free-text roles (ORCH-66): length + safe charset only — no allowlist.
    if not all(ch.isalnum() or ch in ("-", "_", " ", ".", "/") for ch in text):
        raise HandoffValidationError(f"{field_name} has unsafe characters")
    return text


def _str_list(value: Any, *, field_name: str, max_item: int = _REF_MAX) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HandoffValidationError(f"{field_name} must be a list")
    if len(value) > _LIST_MAX:
        raise HandoffValidationError(f"{field_name} exceeds {_LIST_MAX} items")
    out: list[str] = []
    for i, item in enumerate(value):
        out.append(_s(item, field_name=f"{field_name}[{i}]", required=True, max_chars=max_item))
    return out


def _confidence(value: Any) -> float:
    if value is None:
        raise HandoffValidationError("missing required field: confidence")
    try:
        c = float(value)
    except (TypeError, ValueError) as exc:
        raise HandoffValidationError("confidence must be a number") from exc
    if c < 0.0 or c > 1.0:
        raise HandoffValidationError("confidence must be between 0 and 1 inclusive")
    return c


def _costs(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HandoffValidationError("costs must be an object")
    # Keep only JSON-scalar values; sanitize string leaves.
    out: dict[str, Any] = {}
    for k, v in list(value.items())[:20]:
        key = sanitize_text(str(k), max_chars=64)
        if isinstance(v, (int, float, bool)) or v is None:
            out[key] = v
        else:
            out[key] = sanitize_text(str(v), max_chars=200)
    return out


def _memory_updates(value: Any) -> list[MemoryUpdate]:
    from app.executive.scopes import normalize_memory_scope

    if value is None:
        return []
    if not isinstance(value, list):
        raise HandoffValidationError("memory_updates must be a list")
    if len(value) > _LIST_MAX:
        raise HandoffValidationError(f"memory_updates exceeds {_LIST_MAX} items")
    out: list[MemoryUpdate] = []
    for i, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise HandoffValidationError(f"memory_updates[{i}] must be an object")
        try:
            scope = normalize_memory_scope(raw.get("scope"))
        except ValueError as exc:
            raise HandoffValidationError(str(exc)) from exc
        body = _s(raw.get("body"), field_name=f"memory_updates[{i}].body", max_chars=_TEXT_MAX)
        title = _s(
            raw.get("title"),
            field_name=f"memory_updates[{i}].title",
            required=False,
            max_chars=200,
        )
        out.append(MemoryUpdate(scope=scope, body=body, title=title))
    return out


def parse_handoff(data: Any) -> HandoffPacket:
    """Parse and validate a handoff dict or JSON string. Rejects freeform prose."""
    if isinstance(data, str):
        text = data.strip()
        if not text:
            raise HandoffValidationError("empty handoff payload")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HandoffValidationError("handoff must be a JSON object") from exc
    if not isinstance(data, dict):
        raise HandoffValidationError("handoff must be a JSON object")

    version = data.get("schema_version", HANDOFF_SCHEMA_VERSION)
    try:
        version_i = int(version)
    except (TypeError, ValueError) as exc:
        raise HandoffValidationError("schema_version must be an integer") from exc
    if version_i != HANDOFF_SCHEMA_VERSION:
        raise HandoffValidationError(
            f"unsupported handoff schema_version {version_i}; want {HANDOFF_SCHEMA_VERSION}"
        )

    return HandoffPacket(
        from_role=_role(data.get("from_role"), field_name="from_role"),
        to_role=_role(data.get("to_role"), field_name="to_role"),
        objective=_s(data.get("objective"), field_name="objective"),
        attempted_work=_s(data.get("attempted_work"), field_name="attempted_work"),
        outcome=_s(data.get("outcome"), field_name="outcome"),
        confidence=_confidence(data.get("confidence")),
        evidence_refs=_str_list(data.get("evidence_refs"), field_name="evidence_refs"),
        changes=_str_list(data.get("changes"), field_name="changes", max_item=500),
        costs=_costs(data.get("costs")),
        risks=_str_list(data.get("risks"), field_name="risks", max_item=500),
        recommendation=_s(
            data.get("recommendation"),
            field_name="recommendation",
            required=False,
            max_chars=_TEXT_MAX,
        ),
        memory_updates=_memory_updates(data.get("memory_updates")),
        open_questions=_str_list(
            data.get("open_questions"), field_name="open_questions", max_item=500
        ),
        schema_version=version_i,
    )
