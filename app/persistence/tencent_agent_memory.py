from __future__ import annotations

"""Approved-only TencentDB Agent Memory adapter for ORCH-69.

The local ``SafeMemoryRepository`` remains the source of truth. This module
mirrors a bounded snapshot of already-approved executive memory into a
dedicated TencentDB Agent Memory L3 core and verifies every recalled item
against the local approved set before a caller can consume it.

It intentionally has no raw transcript, prompt, tool, credential, session,
code-change, or deployment input.
"""

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx

from app.persistence.safe_memory import (
    MAX_MEMORY_CHARS,
    MEMORY_KINDS,
    SafeMemoryError,
    SafeMemoryItem,
    SafeMemoryRepository,
    sanitize_safe_text,
)
from app.tenancy.models import require_org_id
from app.tenancy.scope import TenantContext, hide_cross_tenant

TENCENT_AGENT_MEMORY_ADAPTER_VERSION = "1.0.0"
TENCENT_AGENT_MEMORY_UPSTREAM_REPOSITORY = (
    "https://github.com/TencentCloud/TencentDB-Agent-Memory"
)
TENCENT_AGENT_MEMORY_UPSTREAM_RELEASE = "v2.0.0"
TENCENT_AGENT_MEMORY_UPSTREAM_COMMIT = "0aff21a2d9f2b8a0354aaa80a2e586aab4054562"
TENCENT_AGENT_MEMORY_API_VERSION = "v3"

_SNAPSHOT_CONTRACT = "orch69.tencentdb-agent-memory.approved-core"
_SNAPSHOT_VERSION = 1
_MAX_CORE_CHARS = 8_000
_MAX_SYNC_ITEMS = 50
_MAX_RECALL_ITEMS = 20
_OPAQUE_CONFIG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class TencentAgentMemoryError(SafeMemoryError):
    """Base adapter error whose message never contains upstream payloads."""


class TencentAgentMemoryConfigError(TencentAgentMemoryError):
    """The host-controlled adapter configuration is incomplete or unsafe."""


class TencentAgentMemoryUnavailable(TencentAgentMemoryError):
    """The memory service failed without exposing its response or endpoint."""


@dataclass(frozen=True)
class TencentAgentMemoryConfig:
    """Host-controlled connection settings; the API key is never repr-visible."""

    endpoint: str
    api_key: str = field(repr=False)
    service_id: str
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint", _validated_endpoint(self.endpoint))
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise TencentAgentMemoryConfigError("api_key must be configured")
        normalized_api_key = self.api_key.strip()
        if len(normalized_api_key) > 4_096:
            raise TencentAgentMemoryConfigError("api_key exceeds the safe bound")
        if any(
            char.isspace() or ord(char) < 32 or ord(char) == 127
            for char in normalized_api_key
        ):
            raise TencentAgentMemoryConfigError("api_key contains invalid characters")
        normalized_service_id = str(self.service_id or "").strip()
        if not _OPAQUE_CONFIG_RE.fullmatch(normalized_service_id):
            raise TencentAgentMemoryConfigError(
                "service_id must be a bounded opaque identifier"
            )
        object.__setattr__(self, "api_key", normalized_api_key)
        object.__setattr__(self, "service_id", normalized_service_id)
        timeout = self.timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0.1 <= float(timeout) <= 30.0
        ):
            raise TencentAgentMemoryConfigError(
                "timeout_seconds must be between 0.1 and 30"
            )
        object.__setattr__(self, "timeout_seconds", float(timeout))

    def safe_status(self) -> dict[str, Any]:
        """Return only non-secret compatibility metadata."""

        return {
            "enabled": True,
            "adapter_version": TENCENT_AGENT_MEMORY_ADAPTER_VERSION,
            "api_version": TENCENT_AGENT_MEMORY_API_VERSION,
            "upstream_release": TENCENT_AGENT_MEMORY_UPSTREAM_RELEASE,
            "upstream_commit": TENCENT_AGENT_MEMORY_UPSTREAM_COMMIT,
        }


def tencent_agent_memory_config_from_env(
    env: Mapping[str, str] | None = None,
) -> TencentAgentMemoryConfig | None:
    """Load the optional adapter without changing the shared Settings model.

    Disabled is the safe default. When explicitly enabled, every required
    value must be supplied by the host environment.
    """

    values = os.environ if env is None else env
    enabled = str(values.get("TENCENT_AGENT_MEMORY_ENABLED", "")).strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return None

    required = {
        "endpoint": str(values.get("TENCENT_AGENT_MEMORY_ENDPOINT", "")).strip(),
        "api_key": str(values.get("TENCENT_AGENT_MEMORY_API_KEY", "")).strip(),
        "service_id": str(values.get("TENCENT_AGENT_MEMORY_SERVICE_ID", "")).strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise TencentAgentMemoryConfigError(
            "enabled adapter is missing required fields: " + ", ".join(missing)
        )
    raw_timeout = str(values.get("TENCENT_AGENT_MEMORY_TIMEOUT_SECONDS", "5")).strip()
    try:
        timeout = float(raw_timeout)
    except ValueError as exc:
        raise TencentAgentMemoryConfigError("timeout_seconds must be numeric") from exc
    return TencentAgentMemoryConfig(
        endpoint=required["endpoint"],
        api_key=required["api_key"],
        service_id=required["service_id"],
        timeout_seconds=timeout,
    )


def _validated_endpoint(value: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        raise TencentAgentMemoryConfigError(
            "endpoint must be a valid HTTP(S) URL"
        ) from None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise TencentAgentMemoryConfigError("endpoint must be a valid HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise TencentAgentMemoryConfigError(
            "endpoint cannot contain credentials, query, or fragment"
        )
    if parsed.path not in {"", "/"}:
        raise TencentAgentMemoryConfigError("endpoint cannot contain a path")
    host = parsed.hostname.lower()
    if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS:
        raise TencentAgentMemoryConfigError(
            "plain HTTP is allowed only for a loopback endpoint"
        )
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, "", "", ""))


@dataclass(frozen=True)
class TencentAgentMemoryScope:
    """Pseudonymous, stable isolation identifiers for one organization."""

    team_id: str
    agent_id: str
    user_id: str
    scope_ref: str

    def body(self) -> dict[str, str]:
        return {
            "team_id": self.team_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
        }


def tencent_agent_memory_scope(org_id: UUID | str) -> TencentAgentMemoryScope:
    oid = require_org_id(org_id)
    digest = hashlib.sha256(f"orch69:memory-scope:v1:{oid}".encode()).hexdigest()
    ref = digest[:32]
    return TencentAgentMemoryScope(
        team_id=f"orch-team-{ref}",
        agent_id="orch-executive-approved-v1",
        user_id=f"orch-org-shared-{ref}",
        scope_ref=ref,
    )


@dataclass(frozen=True)
class RecalledApprovedMemory:
    memory_ref: str
    kind: str
    safe_text: str
    confidence: float | None = None


@dataclass(frozen=True)
class TencentAgentMemorySyncResult:
    item_count: int
    content_chars: int
    upstream_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_count": self.item_count,
            "content_chars": self.content_chars,
            "upstream_version": self.upstream_version,
            "adapter_version": TENCENT_AGENT_MEMORY_ADAPTER_VERSION,
        }


@runtime_checkable
class TencentAgentMemoryPort(Protocol):
    async def write_approved_core(
        self,
        *,
        scope: TencentAgentMemoryScope,
        content: str,
        item_count: int,
    ) -> TencentAgentMemorySyncResult: ...

    async def read_approved_core(
        self, *, scope: TencentAgentMemoryScope
    ) -> list[RecalledApprovedMemory]: ...


class TencentAgentMemoryGateway:
    """Minimal strict-v3 HTTP adapter pinned to upstream release v2.0.0."""

    def __init__(
        self,
        config: TencentAgentMemoryConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=config.timeout_seconds,
            verify=True,
            trust_env=False,
            follow_redirects=False,
        )

    async def health(self) -> bool:
        """Probe the public health route without attaching credentials."""

        try:
            response = await self._client.get(
                f"{self._config.endpoint}/health",
                headers={"Accept": "application/json"},
                timeout=self._config.timeout_seconds,
                follow_redirects=False,
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def write_approved_core(
        self,
        *,
        scope: TencentAgentMemoryScope,
        content: str,
        item_count: int,
    ) -> TencentAgentMemorySyncResult:
        data = await self._post(
            "/v3/core/write",
            {**scope.body(), "content": content},
        )
        raw_version = data.get("version")
        if (
            isinstance(raw_version, int)
            and not isinstance(raw_version, bool)
            and 0 <= raw_version <= 2_147_483_647
        ):
            version = f"v{raw_version}"
        elif isinstance(raw_version, str) and _OPAQUE_CONFIG_RE.fullmatch(raw_version):
            version = raw_version
        else:
            raise TencentAgentMemoryUnavailable(
                "memory service returned an invalid write acknowledgement"
            )
        return TencentAgentMemorySyncResult(
            item_count=item_count,
            content_chars=len(content),
            upstream_version=version,
        )

    async def read_approved_core(
        self, *, scope: TencentAgentMemoryScope
    ) -> list[RecalledApprovedMemory]:
        data = await self._post("/v3/core/read", scope.body())
        content = data.get("content")
        if content is None:
            return []
        if not isinstance(content, str) or len(content) > _MAX_CORE_CHARS:
            raise TencentAgentMemoryUnavailable(
                "memory service returned an invalid approved snapshot"
            )
        return _parse_snapshot(content, scope=scope)

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "x-tdai-service-id": self._config.service_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            response = await self._client.post(
                f"{self._config.endpoint}{path}",
                json=body,
                headers=headers,
                timeout=self._config.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise TencentAgentMemoryUnavailable(
                "memory service is unavailable"
            ) from None

        try:
            envelope = response.json()
        except ValueError:
            raise TencentAgentMemoryUnavailable(
                "memory service returned an invalid response"
            ) from None
        if not isinstance(envelope, dict):
            raise TencentAgentMemoryUnavailable(
                "memory service returned an invalid response"
            )
        code = envelope.get("code")
        if (
            not 200 <= response.status_code < 300
            or not isinstance(code, int)
            or isinstance(code, bool)
            or code != 0
        ):
            raise TencentAgentMemoryUnavailable("memory service rejected the request")
        data = envelope.get("data")
        if data is None:
            data = {}
        elif not isinstance(data, dict):
            raise TencentAgentMemoryUnavailable(
                "memory service returned an invalid response"
            )
        return data

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class ApprovedMemoryMirror:
    """Authorization-aware bridge from local approval to TencentDB memory."""

    def __init__(
        self,
        repository: SafeMemoryRepository,
        gateway: TencentAgentMemoryPort,
    ) -> None:
        self._repository = repository
        self._gateway = gateway

    async def sync(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
    ) -> TencentAgentMemorySyncResult:
        oid = require_org_id(org_id)
        if actor.org_id != oid:
            raise hide_cross_tenant()
        actor.require("org.manage")
        approved = await self._repository.list_approved_memory(
            org_id=oid,
            actor=actor,
            limit=_MAX_SYNC_ITEMS,
        )
        scope = tencent_agent_memory_scope(oid)
        content, mirrored = _render_snapshot(approved, org_id=oid, scope=scope)
        return await self._gateway.write_approved_core(
            scope=scope,
            content=content,
            item_count=len(mirrored),
        )

    async def recall(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        limit: int = 10,
    ) -> list[RecalledApprovedMemory]:
        if isinstance(limit, bool) or not 1 <= int(limit) <= _MAX_RECALL_ITEMS:
            raise TencentAgentMemoryError(
                f"limit must be between 1 and {_MAX_RECALL_ITEMS}"
            )
        oid = require_org_id(org_id)
        approved = await self._repository.list_approved_memory(
            org_id=oid,
            actor=actor,
            limit=_MAX_SYNC_ITEMS,
        )
        scope = tencent_agent_memory_scope(oid)
        _, local_items = _render_snapshot(approved, org_id=oid, scope=scope)
        allowed = {item.memory_ref: item for item in local_items}
        recalled = await self._gateway.read_approved_core(scope=scope)
        verified: list[RecalledApprovedMemory] = []
        for item in recalled:
            if allowed.get(item.memory_ref) == item:
                verified.append(item)
            if len(verified) >= int(limit):
                break
        return verified


def _memory_ref(org_id: UUID, memory_id: UUID) -> str:
    digest = hashlib.sha256(
        f"orch69:approved-memory:v1:{org_id}:{memory_id}".encode()
    ).hexdigest()
    return digest[:32]


def _safe_item(item: SafeMemoryItem, *, org_id: UUID) -> RecalledApprovedMemory:
    if item.org_id != org_id:
        raise TencentAgentMemoryError("approved snapshot cannot cross organizations")
    if not item.approved:
        raise TencentAgentMemoryError("only approved memory can be mirrored")
    if item.kind not in MEMORY_KINDS:
        raise TencentAgentMemoryError("approved memory kind is not supported")
    safe_text = sanitize_safe_text(item.safe_text, max_chars=MAX_MEMORY_CHARS)
    confidence_value = item.metadata.get("confidence")
    confidence: float | None = None
    if confidence_value is not None:
        if (
            isinstance(confidence_value, bool)
            or not isinstance(confidence_value, (int, float))
            or not 0.0 <= float(confidence_value) <= 1.0
        ):
            raise TencentAgentMemoryError("approved memory confidence is invalid")
        confidence = float(confidence_value)
    return RecalledApprovedMemory(
        memory_ref=_memory_ref(org_id, item.id),
        kind=item.kind,
        safe_text=safe_text,
        confidence=confidence,
    )


def _snapshot_payload(
    items: Sequence[RecalledApprovedMemory], *, scope: TencentAgentMemoryScope
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in items:
        row: dict[str, Any] = {
            "kind": item.kind,
            "memory_ref": item.memory_ref,
            "safe_text": item.safe_text,
        }
        if item.confidence is not None:
            row["confidence"] = item.confidence
        rows.append(row)
    return {
        "contract": _SNAPSHOT_CONTRACT,
        "items": rows,
        "scope_ref": scope.scope_ref,
        "source": "approved-only",
        "version": _SNAPSHOT_VERSION,
    }


def _encode_snapshot(
    items: Sequence[RecalledApprovedMemory], *, scope: TencentAgentMemoryScope
) -> str:
    return json.dumps(
        _snapshot_payload(items, scope=scope),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _render_snapshot(
    items: Sequence[SafeMemoryItem],
    *,
    org_id: UUID,
    scope: TencentAgentMemoryScope,
) -> tuple[str, list[RecalledApprovedMemory]]:
    if len(items) > _MAX_SYNC_ITEMS:
        raise TencentAgentMemoryError(
            f"approved snapshot exceeds {_MAX_SYNC_ITEMS} items"
        )
    safe_items = [_safe_item(item, org_id=org_id) for item in items]
    safe_items.sort(key=lambda item: item.memory_ref)
    selected: list[RecalledApprovedMemory] = []
    for item in safe_items:
        candidate = [*selected, item]
        if len(_encode_snapshot(candidate, scope=scope)) > _MAX_CORE_CHARS:
            continue
        selected = candidate
    encoded = _encode_snapshot(selected, scope=scope)
    if len(encoded) > _MAX_CORE_CHARS:
        raise TencentAgentMemoryError("approved snapshot exceeds the safe bound")
    return encoded, selected


def _parse_snapshot(
    content: str, *, scope: TencentAgentMemoryScope
) -> list[RecalledApprovedMemory]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        raise TencentAgentMemoryUnavailable(
            "memory service returned an invalid approved snapshot"
        ) from None
    if not isinstance(payload, dict):
        raise TencentAgentMemoryUnavailable(
            "memory service returned an invalid approved snapshot"
        )
    if (
        payload.get("contract") != _SNAPSHOT_CONTRACT
        or payload.get("version") != _SNAPSHOT_VERSION
        or payload.get("source") != "approved-only"
        or payload.get("scope_ref") != scope.scope_ref
        or set(payload) != {"contract", "items", "scope_ref", "source", "version"}
    ):
        raise TencentAgentMemoryUnavailable(
            "memory service returned an incompatible approved snapshot"
        )
    rows = payload.get("items")
    if not isinstance(rows, list) or len(rows) > _MAX_SYNC_ITEMS:
        raise TencentAgentMemoryUnavailable(
            "memory service returned an invalid approved snapshot"
        )
    parsed: list[RecalledApprovedMemory] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not set(row).issubset(
            {"memory_ref", "kind", "safe_text", "confidence"}
        ):
            raise TencentAgentMemoryUnavailable(
                "memory service returned an invalid approved snapshot"
            )
        if not {"memory_ref", "kind", "safe_text"}.issubset(row):
            raise TencentAgentMemoryUnavailable(
                "memory service returned an invalid approved snapshot"
            )
        ref = row.get("memory_ref")
        kind = row.get("kind")
        if (
            not isinstance(ref, str)
            or not re.fullmatch(r"[0-9a-f]{32}", ref)
            or ref in seen
            or kind not in MEMORY_KINDS
        ):
            raise TencentAgentMemoryUnavailable(
                "memory service returned an invalid approved snapshot"
            )
        try:
            safe_text = sanitize_safe_text(
                row.get("safe_text"), max_chars=MAX_MEMORY_CHARS
            )
        except SafeMemoryError:
            raise TencentAgentMemoryUnavailable(
                "memory service returned unsafe approved memory"
            ) from None
        raw_confidence = row.get("confidence")
        confidence: float | None = None
        if raw_confidence is not None:
            if (
                isinstance(raw_confidence, bool)
                or not isinstance(raw_confidence, (int, float))
                or not 0.0 <= float(raw_confidence) <= 1.0
            ):
                raise TencentAgentMemoryUnavailable(
                    "memory service returned an invalid approved snapshot"
                )
            confidence = float(raw_confidence)
        seen.add(ref)
        parsed.append(
            RecalledApprovedMemory(
                memory_ref=ref,
                kind=str(kind),
                safe_text=safe_text,
                confidence=confidence,
            )
        )
    return parsed
