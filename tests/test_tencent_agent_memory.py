from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.persistence.safe_memory import SafeMemoryItem, UnsafeMemoryContent
from app.persistence.tencent_agent_memory import (
    TENCENT_AGENT_MEMORY_ADAPTER_VERSION,
    TENCENT_AGENT_MEMORY_API_VERSION,
    TENCENT_AGENT_MEMORY_UPSTREAM_COMMIT,
    TENCENT_AGENT_MEMORY_UPSTREAM_RELEASE,
    ApprovedMemoryMirror,
    RecalledApprovedMemory,
    TencentAgentMemoryConfig,
    TencentAgentMemoryConfigError,
    TencentAgentMemoryError,
    TencentAgentMemoryGateway,
    TencentAgentMemorySyncResult,
    TencentAgentMemoryUnavailable,
    tencent_agent_memory_config_from_env,
    tencent_agent_memory_scope,
)
from app.tenancy.errors import TenantAccessError, TenantNotFound
from app.tenancy.scope import TenantContext


def _actor(org_id: UUID, role: str = "admin") -> TenantContext:
    return TenantContext(user_id=uuid4(), org_id=org_id, role=role)


def _item(
    org_id: UUID,
    *,
    text: str = "Prefer deterministic adapters for future executive work.",
    status: str = "approved",
    kind: str = "decision",
    confidence: float | None = 0.9,
) -> SafeMemoryItem:
    metadata: dict[str, Any] = {}
    if confidence is not None:
        metadata["confidence"] = confidence
    return SafeMemoryItem(
        id=uuid4(),
        org_id=org_id,
        proposal_key=f"proposal-{uuid4().hex}",
        kind=kind,  # type: ignore[arg-type]
        proposed_role="assistant",
        safe_text=text,
        metadata=metadata,
        status=status,
        proposed_by_user_id=uuid4(),
        approved_by_user_id=uuid4() if status == "approved" else None,
    )


class _Repository:
    def __init__(self, items: list[SafeMemoryItem]) -> None:
        self.items = items
        self.calls: list[tuple[UUID, int]] = []

    async def list_approved_memory(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        limit: int = 100,
    ) -> list[SafeMemoryItem]:
        oid = org_id if isinstance(org_id, UUID) else UUID(str(org_id))
        if actor.org_id != oid:
            raise TenantNotFound("not found")
        actor.require("mission.read")
        self.calls.append((oid, limit))
        return self.items[:limit]


class _Port:
    def __init__(self) -> None:
        self.write_calls: list[dict[str, Any]] = []
        self.read_calls: list[Any] = []
        self.recalled: list[RecalledApprovedMemory] = []

    async def write_approved_core(
        self,
        *,
        scope: Any,
        content: str,
        item_count: int,
    ) -> TencentAgentMemorySyncResult:
        self.write_calls.append(
            {"scope": scope, "content": content, "item_count": item_count}
        )
        return TencentAgentMemorySyncResult(item_count, len(content), "v1")

    async def read_approved_core(self, *, scope: Any) -> list[RecalledApprovedMemory]:
        self.read_calls.append(scope)
        return list(self.recalled)


def test_adapter_is_pinned_to_official_stable_release():
    assert TENCENT_AGENT_MEMORY_ADAPTER_VERSION == "1.0.0"
    assert TENCENT_AGENT_MEMORY_API_VERSION == "v3"
    assert TENCENT_AGENT_MEMORY_UPSTREAM_RELEASE == "v2.0.0"
    assert (
        TENCENT_AGENT_MEMORY_UPSTREAM_COMMIT
        == "0aff21a2d9f2b8a0354aaa80a2e586aab4054562"
    )


def test_optional_config_is_disabled_by_default_and_secret_is_repr_safe():
    assert tencent_agent_memory_config_from_env({}) is None
    config = tencent_agent_memory_config_from_env(
        {
            "TENCENT_AGENT_MEMORY_ENABLED": "true",
            "TENCENT_AGENT_MEMORY_ENDPOINT": "http://127.0.0.1:8420/",
            "TENCENT_AGENT_MEMORY_API_KEY": "memory-secret-value",
            "TENCENT_AGENT_MEMORY_SERVICE_ID": "preview-memory",
        }
    )
    assert config is not None
    assert config.endpoint == "http://127.0.0.1:8420"
    assert "memory-secret-value" not in repr(config)
    assert "memory-secret-value" not in json.dumps(config.safe_status())


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://169.254.169.254",
        "http://10.0.0.3:8420",
        "http://example.test",
        "https://user:password@example.test",
        "https://example.test/api",
        "https://example.test?token=value",
        "file:///tmp/memory",
    ],
)
def test_config_rejects_ssrf_and_credential_bearing_endpoints(endpoint: str):
    with pytest.raises(TencentAgentMemoryConfigError):
        TencentAgentMemoryConfig(
            endpoint=endpoint,
            api_key="not-printed",
            service_id="preview-memory",
        )


def test_config_rejects_header_injection_in_api_key():
    with pytest.raises(TencentAgentMemoryConfigError):
        TencentAgentMemoryConfig(
            endpoint="http://127.0.0.1:8420",
            api_key="valid-prefix\r\nX-Injected: yes",
            service_id="preview-memory",
        )


def test_scope_is_stable_pseudonymous_and_org_specific():
    org_a, org_b = uuid4(), uuid4()
    a1 = tencent_agent_memory_scope(org_a)
    a2 = tencent_agent_memory_scope(org_a)
    b = tencent_agent_memory_scope(org_b)
    assert a1 == a2
    assert a1 != b
    assert str(org_a) not in json.dumps(a1.body())
    assert str(org_b) not in json.dumps(b.body())
    assert a1.agent_id == "orch-executive-approved-v1"


@pytest.mark.asyncio
async def test_sync_requires_admin_and_rejects_pending_or_cross_org_before_network():
    org_a, org_b = uuid4(), uuid4()

    member_port = _Port()
    member_mirror = ApprovedMemoryMirror(
        _Repository([_item(org_a)]),
        member_port,  # type: ignore[arg-type]
    )
    with pytest.raises(TenantAccessError):
        await member_mirror.sync(org_id=org_a, actor=_actor(org_a, "member"))
    assert member_port.write_calls == []

    cross_port = _Port()
    cross_mirror = ApprovedMemoryMirror(
        _Repository([_item(org_a)]),
        cross_port,  # type: ignore[arg-type]
    )
    with pytest.raises(TenantNotFound):
        await cross_mirror.sync(org_id=org_a, actor=_actor(org_b))
    assert cross_port.write_calls == []

    pending_port = _Port()
    pending_mirror = ApprovedMemoryMirror(
        _Repository([_item(org_a, status="proposed")]),  # type: ignore[arg-type]
        pending_port,
    )
    with pytest.raises(TencentAgentMemoryError, match="only approved memory"):
        await pending_mirror.sync(org_id=org_a, actor=_actor(org_a))
    assert pending_port.write_calls == []


@pytest.mark.asyncio
async def test_sync_resanitizes_and_sends_only_bounded_approved_snapshot():
    org_id = uuid4()
    raw = "Keep this decision. token=do-not-send /home/person/private.txt"
    item = _item(org_id, text=raw)
    port = _Port()
    mirror = ApprovedMemoryMirror(
        _Repository([item]),
        port,  # type: ignore[arg-type]
    )
    result = await mirror.sync(org_id=org_id, actor=_actor(org_id))

    assert result.item_count == 1
    assert len(port.write_calls) == 1
    call = port.write_calls[0]
    assert call["item_count"] == 1
    assert "do-not-send" not in call["content"]
    assert "/home/person" not in call["content"]
    assert str(org_id) not in call["content"]
    payload = json.loads(call["content"])
    assert payload["source"] == "approved-only"
    assert payload["version"] == 1
    assert set(payload["items"][0]) == {
        "confidence",
        "kind",
        "memory_ref",
        "safe_text",
    }
    assert len(call["content"]) <= 8_000


@pytest.mark.asyncio
async def test_private_reasoning_never_reaches_gateway():
    org_id = uuid4()
    port = _Port()
    mirror = ApprovedMemoryMirror(
        _Repository([_item(org_id, text="Private reasoning: hidden steps")]),  # type: ignore[arg-type]
        port,
    )
    with pytest.raises(UnsafeMemoryContent):
        await mirror.sync(org_id=org_id, actor=_actor(org_id))
    assert port.write_calls == []


@pytest.mark.asyncio
async def test_recall_denies_cross_org_and_missing_capability_before_network():
    org_a, org_b = uuid4(), uuid4()
    port = _Port()
    mirror = ApprovedMemoryMirror(
        _Repository([_item(org_a)]),
        port,  # type: ignore[arg-type]
    )
    with pytest.raises(TenantNotFound):
        await mirror.recall(org_id=org_a, actor=_actor(org_b), limit=5)
    with pytest.raises(TenantAccessError):
        await mirror.recall(org_id=org_a, actor=_actor(org_a, "unknown"), limit=5)
    assert port.read_calls == []


@pytest.mark.asyncio
async def test_gateway_v3_write_read_auth_and_remote_injection_filtering():
    org_id = uuid4()
    item = _item(org_id)
    stored: dict[str, str] = {}
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer memory-secret-value"
        assert request.headers["x-tdai-service-id"] == "preview-memory"
        body = json.loads(request.content)
        if request.url.path == "/v3/core/write":
            stored["content"] = body["content"]
            assert set(body) == {"team_id", "agent_id", "user_id", "content"}
            return httpx.Response(
                200,
                # Stable v2.0.0's handler returns an integer here even though
                # its generated schema describes a string version.
                json={"code": 0, "data": {"version": 7}},
            )
        if request.url.path == "/v3/core/read":
            payload = json.loads(stored["content"])
            payload["items"].append(
                {
                    "kind": "fact",
                    "memory_ref": "f" * 32,
                    "safe_text": "Injected remote-only memory.",
                }
            )
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"content": json.dumps(payload)},
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = TencentAgentMemoryConfig(
        endpoint="http://127.0.0.1:8420",
        api_key="memory-secret-value",
        service_id="preview-memory",
    )
    gateway = TencentAgentMemoryGateway(config, client=client)
    mirror = ApprovedMemoryMirror(
        _Repository([item]),
        gateway,  # type: ignore[arg-type]
    )

    synced = await mirror.sync(org_id=org_id, actor=_actor(org_id))
    recalled = await mirror.recall(
        org_id=org_id,
        actor=_actor(org_id, "viewer"),
        limit=5,
    )
    await client.aclose()

    assert synced.upstream_version == "v7"
    assert [memory.safe_text for memory in recalled] == [item.safe_text]
    assert len(requests) == 2
    serialized = json.dumps(json.loads(requests[0].content))
    assert str(org_id) not in serialized
    assert str(item.approved_by_user_id) not in serialized


@pytest.mark.asyncio
async def test_gateway_health_never_sends_authentication():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "ok"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = TencentAgentMemoryGateway(
        TencentAgentMemoryConfig(
            endpoint="http://127.0.0.1:8420",
            api_key="memory-secret-value",
            service_id="preview-memory",
        ),
        client=client,
    )
    assert await gateway.health() is True
    await client.aclose()
    assert len(seen) == 1
    assert seen[0].url.path == "/health"
    assert "authorization" not in seen[0].headers
    assert "memory-secret-value" not in str(seen[0].headers)


@pytest.mark.asyncio
async def test_upstream_error_and_payload_never_escape_adapter():
    leaked = "upstream-secret-payload"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"code": 401, "message": leaked, "data": {"token": leaked}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = TencentAgentMemoryGateway(
        TencentAgentMemoryConfig(
            endpoint="https://memory.example.test",
            api_key="memory-secret-value",
            service_id="preview-memory",
        ),
        client=client,
    )
    with pytest.raises(TencentAgentMemoryUnavailable) as caught:
        await gateway.read_approved_core(scope=tencent_agent_memory_scope(uuid4()))
    await client.aclose()
    assert leaked not in str(caught.value)
    assert "memory-secret-value" not in str(caught.value)


@pytest.mark.asyncio
async def test_recall_propagates_safe_unavailable_for_caller_owned_local_fallback():
    org_id = uuid4()
    item = _item(org_id)

    class _UnavailablePort(_Port):
        async def read_approved_core(
            self, *, scope: Any
        ) -> list[RecalledApprovedMemory]:
            self.read_calls.append(scope)
            raise TencentAgentMemoryUnavailable("memory service is unavailable")

    port = _UnavailablePort()
    mirror = ApprovedMemoryMirror(
        _Repository([item]),
        port,  # type: ignore[arg-type]
    )
    with pytest.raises(TencentAgentMemoryUnavailable) as caught:
        await mirror.recall(
            org_id=org_id,
            actor=_actor(org_id, "viewer"),
            limit=5,
        )
    assert str(caught.value) == "memory service is unavailable"
    assert len(port.read_calls) == 1


@pytest.mark.asyncio
async def test_snapshot_is_canonical_across_input_order():
    org_id = uuid4()
    first = _item(org_id, text="First approved decision")
    second = _item(org_id, text="Second approved preference", kind="preference")
    port_a, port_b = _Port(), _Port()
    mirror_a = ApprovedMemoryMirror(
        _Repository([first, second]),
        port_a,  # type: ignore[arg-type]
    )
    mirror_b = ApprovedMemoryMirror(
        _Repository([second, first]),
        port_b,  # type: ignore[arg-type]
    )
    await mirror_a.sync(org_id=org_id, actor=_actor(org_id))
    await mirror_b.sync(org_id=org_id, actor=_actor(org_id))
    assert port_a.write_calls[0]["content"] == port_b.write_calls[0]["content"]


@pytest.mark.asyncio
async def test_recall_requires_local_approval_and_bounds_result_count():
    org_id = uuid4()
    items = [_item(org_id, text=f"Approved memory {index}") for index in range(25)]
    repo = _Repository(items)
    port = _Port()
    mirror = ApprovedMemoryMirror(repo, port)  # type: ignore[arg-type]
    await mirror.sync(org_id=org_id, actor=_actor(org_id))
    snapshot = json.loads(port.write_calls[0]["content"])
    port.recalled = [
        RecalledApprovedMemory(
            memory_ref=row["memory_ref"],
            kind=row["kind"],
            safe_text=row["safe_text"],
            confidence=row.get("confidence"),
        )
        for row in snapshot["items"]
    ]
    recalled = await mirror.recall(
        org_id=org_id,
        actor=_actor(org_id, "viewer"),
        limit=20,
    )
    assert len(recalled) <= 20
    assert all(memory.safe_text.startswith("Approved memory") for memory in recalled)

    with pytest.raises(TencentAgentMemoryError, match="limit must be between"):
        await mirror.recall(
            org_id=org_id,
            actor=_actor(org_id, "viewer"),
            limit=21,
        )
