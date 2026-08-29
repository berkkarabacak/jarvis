from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.ceo.presence import AVATAR_STATES
from app.control_plane.events import CONTRACT_NAME, CONTRACT_VERSION, EventAccess
from app.control_plane.models import TERMINAL_MISSION_STATUSES
from app.control_plane.service import ControlPlaneService
from app.executive.adapters.prime import (
    PrimeRuntimeError,
    PrimeUnavailableError,
)
from app.executive.memory_policy import ExecutiveMemoryPolicy
from app.executive.runtime import ExecutiveRuntime
from app.executive.safety import (
    ExecutiveSafetyError,
    require_public_identifier,
    sanitize_private_input,
    sanitize_public_text,
)
from app.executive.session import ExecutiveSessionError
from app.executive.telemetry import PUBLIC_GUEST_PROFILE
from app.integrations.executive_control_plane import (
    ExecutiveControlPlaneAdapter,
    ExecutiveControlPlaneIntegrationError,
)
from app.public_access.dependencies import require_account_principal
from app.public_access.errors import (
    AccountAccessDenied,
    AccountResourceNotFound,
    BrowserMutationRejected,
    UsageQuotaExceeded,
)
from app.public_access.models import AccountPrincipalV1, ResourceBinding
from app.public_access.security import (
    derive_account_subject_key,
    require_browser_mutation,
)
from app.public_access.store import PublicAccessStore

PUBLIC_GUEST_EXECUTION_PROFILE = PUBLIC_GUEST_PROFILE
PUBLIC_ACCOUNT_TURN_HOURLY_LIMIT = 8
PUBLIC_ACCOUNT_TURN_DAILY_LIMIT = 24
PUBLIC_GLOBAL_TURN_HOURLY_LIMIT = 60
PUBLIC_GLOBAL_TURN_DAILY_LIMIT = 240
PUBLIC_ACCOUNT_OPEN_HOURLY_LIMIT = 12
PUBLIC_ACCOUNT_OPEN_DAILY_LIMIT = 48
PUBLIC_GLOBAL_OPEN_HOURLY_LIMIT = 120
PUBLIC_GLOBAL_OPEN_DAILY_LIMIT = 480
PUBLIC_ACTIVE_SESSIONS_PER_ACCOUNT = 1
PUBLIC_ACTIVE_SESSIONS_GLOBAL = 8
PUBLIC_CONCURRENT_OPERATIONS = 2
PUBLIC_SESSION_IDLE_SECONDS = 15 * 60
PUBLIC_TURN_TIMEOUT_SECONDS = 90.0
PUBLIC_CLEANUP_TIMEOUT_SECONDS = 5.0
PUBLIC_SWEEP_INTERVAL_SECONDS = 15.0

_GLOBAL_QUOTA_SUBJECT = "public-executive-global-v1"
_SESSION_RESOURCE = "executive_session"
_MISSION_RESOURCE = "control_plane_mission"
_ACTIVE_STATUSES = frozenset({"active", "paused"})
_UNSAFE_SERVER_SECRETS = frozenset(
    {"", "dev-secret-change-me", "change-me", "test-secret"}
)

log = logging.getLogger("agent_orchestrator.public_executive")

public_executive_router = APIRouter(tags=["public-executive"])


class PublicMissionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: str = Field(min_length=1, max_length=1_200)


class PublicMessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1_200)


class PublicStopBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="stopped", pattern=r"^stopped$")
    reason: str = Field(default="ceo_stopped", min_length=1, max_length=80)


class PublicExecutiveCapacityError(RuntimeError):
    def __init__(self, detail: str, *, retry_after_seconds: int = 15) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retry_after_seconds = max(1, int(retry_after_seconds))


PUBLIC_GATE_CODE_HEADER = "X-AI-Control-Room-Gate-Code"
_PUBLIC_GATE_CODES = frozenset(
    {
        "hard_limit",
        "metering_contract",
        "metering_receipt",
        "publication_contract",
        "response_contract",
        "runtime_cleanup",
        "runtime_orchestration",
        "snapshot_identity",
        "target_exceeded",
        "telemetry_incomplete",
        "unavailable",
    }
)


class PublicExecutiveTurnError(RuntimeError):
    def __init__(
        self,
        detail: str,
        *,
        status_code: int = 503,
        gate_code: str = "unavailable",
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.gate_code = gate_code if gate_code in _PUBLIC_GATE_CODES else "unavailable"


async def _shielded(awaitable: Awaitable[Any]) -> Any:
    """Finish one cleanup task before propagating caller cancellation."""

    task = asyncio.create_task(awaitable)
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
            if task.done():
                result = task.result()
                break
    if cancellation is not None:
        raise cancellation
    return result


@dataclass
class _PublicMissionRecord:
    principal: AccountPrincipalV1
    adapter: ExecutiveControlPlaneAdapter
    mission_id: str
    session_id: str
    created_at: float
    last_used_monotonic: float
    busy: bool = False
    closing: bool = False
    final_snapshot: dict[str, Any] | None = None
    cleanup_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def account_key(self) -> tuple[str, str]:
        return (str(self.principal.org_id), str(self.principal.user_id))


@dataclass
class PublicExecutiveGateway:
    """Cookie-principal adapter for public CEO turns.

    The gateway owns only safe account/resource identifiers. Browser cookies,
    provider credentials, prompts, and model reasoning never enter its state.
    """

    runtime: ExecutiveRuntime
    control_plane: ControlPlaneService
    store: PublicAccessStore
    server_secret: str = field(repr=False)
    idle_seconds: float = PUBLIC_SESSION_IDLE_SECONDS
    sweep_interval_seconds: float = PUBLIC_SWEEP_INTERVAL_SECONDS
    turn_timeout_seconds: float = PUBLIC_TURN_TIMEOUT_SECONDS
    cleanup_timeout_seconds: float = PUBLIC_CLEANUP_TIMEOUT_SECONDS
    _records: dict[str, _PublicMissionRecord] = field(
        default_factory=dict, init=False, repr=False
    )
    _opening_accounts: set[tuple[str, str]] = field(
        default_factory=set, init=False, repr=False
    )
    _state_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _operations: int = field(default=0, init=False, repr=False)
    _sweeper: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _ready: bool = field(default=False, init=False, repr=False)

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("public executive gateway is closed")
        if (
            len(self.server_secret.encode("utf-8")) < 32
            or self.server_secret.strip().lower() in _UNSAFE_SERVER_SECRETS
        ):
            # API_SECRET is also the HMAC key that pseudonymises guest IPs for
            # the quota subject, so a weak value is refused here. Say so loudly:
            # the symptom is the whole public chat answering 503 forever, which
            # is otherwise indistinguishable from a provider outage.
            log.error(
                "public executive gateway DISABLED: API_SECRET must be at least "
                "32 bytes and not a known placeholder. Public AI chat will return "
                "503 until it is replaced. Generate one with: "
                "python3 -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
            self._ready = False
            return
        try:
            await self.reconcile_stale_missions()
        except Exception:
            self._ready = False
        else:
            self._ready = True
        if self._sweeper is None:
            self._sweeper = asyncio.create_task(
                self._sweep_loop(),
                name="public-executive-session-sweeper",
            )

    async def close(self) -> None:
        self._closed = True
        sweeper = self._sweeper
        self._sweeper = None
        if sweeper is not None:
            sweeper.cancel()
            try:
                await sweeper
            except asyncio.CancelledError:
                pass
        for record in list(self._records.values()):
            await _shielded(self._cleanup_record(record, reason="application_shutdown"))

    @asynccontextmanager
    async def _operation_slot(self):
        async with self._state_lock:
            if self._operations >= PUBLIC_CONCURRENT_OPERATIONS:
                raise PublicExecutiveCapacityError(
                    "The public executive is at capacity. Try again shortly."
                )
            self._operations += 1
        try:
            yield
        finally:
            async with self._state_lock:
                self._operations = max(0, self._operations - 1)

    async def _reserve_open(self, principal: AccountPrincipalV1) -> None:
        key = (str(principal.org_id), str(principal.user_id))
        async with self._state_lock:
            active_for_account = sum(
                1 for item in self._records.values() if item.account_key == key
            )
            if key in self._opening_accounts or (
                active_for_account >= PUBLIC_ACTIVE_SESSIONS_PER_ACCOUNT
            ):
                raise PublicExecutiveCapacityError(
                    "This account already has an active executive mission."
                )
            if len(self._records) + len(self._opening_accounts) >= (
                PUBLIC_ACTIVE_SESSIONS_GLOBAL
            ):
                raise PublicExecutiveCapacityError(
                    "The public executive is at capacity. Try again shortly."
                )
            self._opening_accounts.add(key)

    async def _release_open(self, principal: AccountPrincipalV1) -> None:
        key = (str(principal.org_id), str(principal.user_id))
        async with self._state_lock:
            self._opening_accounts.discard(key)

    async def open_mission(
        self,
        principal: AccountPrincipalV1,
        *,
        brief: str,
    ) -> dict[str, Any]:
        if not self._ready:
            raise PublicExecutiveTurnError("Public executive is unavailable.")
        principal.require("mission.run")
        safe_brief = sanitize_private_input(brief, maximum=1_200)
        await self.sweep_once()
        await self._reserve_open(principal)
        adapter = ExecutiveControlPlaneAdapter.for_tenant(
            self.control_plane,
            principal.tenant_context(),
        )
        mission_id = ""
        session_id = ""
        mission_binding: ResourceBinding | None = None
        record: _PublicMissionRecord | None = None
        try:
            async with self._operation_slot():
                await self._charge_open(principal)
                mission = await adapter.start_mission()
                mission_id = mission.id
                mission_binding = await self.store.bind_resource(
                    resource_type=_MISSION_RESOURCE,
                    resource_id=mission_id,
                    principal=principal,
                )
                session = await asyncio.wait_for(
                    self.runtime.open_mission(
                        mission_id=mission_id,
                        brief=safe_brief,
                        memory_policy=ExecutiveMemoryPolicy.disabled(),
                        execution_profile=PUBLIC_GUEST_EXECUTION_PROFILE,  # type: ignore[arg-type]
                    ),
                    timeout=20.0,
                )
                session_id = session.session_id
                await self.store.bind_resource(
                    resource_type=_SESSION_RESOURCE,
                    resource_id=session_id,
                    principal=principal,
                )
                now = time.monotonic()
                record = _PublicMissionRecord(
                    principal=principal,
                    adapter=adapter,
                    mission_id=mission_id,
                    session_id=session_id,
                    created_at=time.time(),
                    last_used_monotonic=now,
                )
                async with self._state_lock:
                    self._records[session_id] = record
                return _safe_snapshot(self.runtime.snapshot(session_id))
        except asyncio.CancelledError:
            if session_id:
                recovery = record or _PublicMissionRecord(
                    principal=principal,
                    adapter=adapter,
                    mission_id=mission_id,
                    session_id=session_id,
                    created_at=time.time(),
                    last_used_monotonic=time.monotonic(),
                    closing=True,
                )
                async with self._state_lock:
                    self._records.setdefault(session_id, recovery)
                await _shielded(
                    self._cleanup_record(recovery, reason="public_open_cancelled")
                )
            elif mission_id:
                await _shielded(
                    self._rollback_unopened_mission(
                        adapter,
                        mission_id,
                        mission_binding,
                    )
                )
            raise
        except Exception:
            if session_id:
                recovery = record or _PublicMissionRecord(
                    principal=principal,
                    adapter=adapter,
                    mission_id=mission_id,
                    session_id=session_id,
                    created_at=time.time(),
                    last_used_monotonic=time.monotonic(),
                    closing=True,
                )
                async with self._state_lock:
                    self._records.setdefault(session_id, recovery)
                await _shielded(
                    self._cleanup_record(recovery, reason="public_open_failed")
                )
            else:
                await _shielded(
                    self._rollback_unopened_mission(
                        adapter,
                        mission_id,
                        mission_binding,
                    )
                )
            raise
        finally:
            await self._release_open(principal)

    async def _charge_open(self, principal: AccountPrincipalV1) -> None:
        await self.store.consume_quota(
            subject_key=derive_account_subject_key(
                principal.user_id,
                principal.org_id,
                self.server_secret,
            ),
            quota_name="public_executive_open",
            hourly_limit=PUBLIC_ACCOUNT_OPEN_HOURLY_LIMIT,
            daily_limit=PUBLIC_ACCOUNT_OPEN_DAILY_LIMIT,
        )
        await self.store.consume_quota(
            subject_key=_GLOBAL_QUOTA_SUBJECT,
            quota_name="public_executive_global_open",
            hourly_limit=PUBLIC_GLOBAL_OPEN_HOURLY_LIMIT,
            daily_limit=PUBLIC_GLOBAL_OPEN_DAILY_LIMIT,
        )

    async def _rollback_unopened_mission(
        self,
        adapter: ExecutiveControlPlaneAdapter,
        mission_id: str,
        binding: ResourceBinding | None,
    ) -> None:
        await adapter.rollback_created_mission(
            mission_id,
            created=bool(mission_id),
        )
        if binding is None:
            return
        try:
            await self.store.release_resource_binding(binding)
        except Exception:
            # A retained binding is deliberate: startup reconciliation will
            # close and release it before the public gateway becomes ready.
            pass

    async def _owned_record(
        self,
        principal: AccountPrincipalV1,
        session_id: str,
    ) -> _PublicMissionRecord:
        try:
            public_session_id = require_public_identifier(session_id)
        except ExecutiveSafetyError as exc:
            raise AccountResourceNotFound() from exc
        await self.store.require_owned_resource(
            resource_type=_SESSION_RESOURCE,
            resource_id=public_session_id,
            principal=principal,
        )
        async with self._state_lock:
            record = self._records.get(public_session_id)
        if record is None or record.account_key != (
            str(principal.org_id),
            str(principal.user_id),
        ):
            raise AccountResourceNotFound()
        await self.store.require_owned_resource(
            resource_type=_MISSION_RESOURCE,
            resource_id=record.mission_id,
            principal=principal,
        )
        return record

    async def _charge_turn(self, principal: AccountPrincipalV1) -> dict[str, Any]:
        account = await self.store.consume_quota(
            subject_key=derive_account_subject_key(
                principal.user_id,
                principal.org_id,
                self.server_secret,
            ),
            quota_name="public_executive_turn",
            hourly_limit=PUBLIC_ACCOUNT_TURN_HOURLY_LIMIT,
            daily_limit=PUBLIC_ACCOUNT_TURN_DAILY_LIMIT,
        )
        global_usage = await self.store.consume_quota(
            subject_key=_GLOBAL_QUOTA_SUBJECT,
            quota_name="public_executive_global_turn",
            hourly_limit=PUBLIC_GLOBAL_TURN_HOURLY_LIMIT,
            daily_limit=PUBLIC_GLOBAL_TURN_DAILY_LIMIT,
        )
        return {
            "account": account.to_dict(),
            "service": global_usage.to_dict(),
        }

    async def send_message(
        self,
        principal: AccountPrincipalV1,
        session_id: str,
        *,
        message: str,
    ) -> dict[str, Any]:
        principal.require("mission.run")
        record = await self._owned_record(principal, session_id)
        safe_message = sanitize_private_input(message, maximum=1_200)
        async with self._state_lock:
            if record.closing or record.busy:
                raise PublicExecutiveCapacityError(
                    "This executive mission is already processing a request."
                )
            record.busy = True
        try:
            async with self._operation_slot():
                quota = await self._charge_turn(principal)
                try:
                    turn = await asyncio.wait_for(
                        self.runtime.send_message(
                            record.session_id,
                            message=safe_message,
                        ),
                        timeout=self.turn_timeout_seconds,
                    )
                except asyncio.TimeoutError as exc:
                    raise PublicExecutiveTurnError(
                        "The executive turn timed out safely.",
                        status_code=504,
                    ) from exc

                response = _validated_safe_turn(
                    turn,
                    expected_mission_id=record.mission_id,
                    expected_session_id=record.session_id,
                )
                publication = await record.adapter.publish_turn(
                    turn.get("event_batch"),
                    expected_mission_id=record.mission_id,
                    expected_message_id=response["message"]["message_id"],
                    expected_final_text=response["message"]["text"],
                )
                _attach_safe_publication(
                    response,
                    publication,
                    expected_mission_id=record.mission_id,
                )
                response["quota"] = quota["account"]
                async with self._state_lock:
                    if self._records.get(record.session_id) is record:
                        record.last_used_monotonic = time.monotonic()
                return response
        except (ExecutiveSafetyError, UsageQuotaExceeded):
            raise
        except PublicExecutiveTurnError:
            await _shielded(
                self._cleanup_record(record, reason="public_turn_gate_failed")
            )
            raise
        except asyncio.CancelledError:
            await _shielded(
                self._cleanup_record(record, reason="public_turn_cancelled")
            )
            raise
        except Exception as exc:
            await _shielded(self._cleanup_record(record, reason="public_turn_failed"))
            if isinstance(exc, PrimeUnavailableError):
                raise PublicExecutiveTurnError(
                    "The executive service is temporarily unavailable."
                ) from exc
            if isinstance(exc, (PrimeRuntimeError, ExecutiveSessionError)):
                raise PublicExecutiveTurnError(
                    "The executive turn failed safely.", status_code=502
                ) from exc
            if isinstance(exc, ExecutiveControlPlaneIntegrationError):
                raise PublicExecutiveTurnError(
                    "Executive evidence persistence failed safely."
                ) from exc
            raise PublicExecutiveTurnError(
                "The executive request failed safely."
            ) from exc
        finally:
            async with self._state_lock:
                if self._records.get(record.session_id) is record:
                    record.busy = False

    async def stop_mission(
        self,
        principal: AccountPrincipalV1,
        session_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        principal.require("mission.run")
        record = await self._owned_record(principal, session_id)
        await _shielded(
            self._cleanup_record(
                record,
                reason=sanitize_private_input(reason, maximum=80),
            )
        )
        async with self._state_lock:
            still_active = self._records.get(record.session_id) is record
        if still_active:
            raise PublicExecutiveTurnError("Executive cleanup is still in progress.")
        if record.final_snapshot is None:
            raise PublicExecutiveTurnError("Executive cleanup state is unavailable.")
        return record.final_snapshot

    async def revoke_principal(self, principal: AccountPrincipalV1) -> None:
        key = (str(principal.org_id), str(principal.user_id))
        async with self._state_lock:
            records = [
                item for item in self._records.values() if item.account_key == key
            ]
        for record in records:
            await _shielded(
                self._cleanup_record(record, reason="account_session_revoked")
            )

    async def presence(
        self,
        principal: AccountPrincipalV1,
        *,
        display_mode: str,
        subtitles: bool,
        subtitle_language: str,
        subtitle_size: str,
        only_while_speaking: bool,
    ) -> dict[str, Any]:
        principal.require("mission.read")
        await self.sweep_once()
        key = (str(principal.org_id), str(principal.user_id))
        async with self._state_lock:
            record = next(
                (
                    item
                    for item in self._records.values()
                    if item.account_key == key and not item.closing
                ),
                None,
            )
        snapshot = None
        if record is not None:
            try:
                snapshot = _safe_snapshot(self.runtime.snapshot(record.session_id))
            except ExecutiveSessionError:
                snapshot = None
        return _presence_payload(
            snapshot,
            display_mode=display_mode,
            subtitles=subtitles,
            subtitle_language=subtitle_language,
            subtitle_size=subtitle_size,
            only_while_speaking=only_while_speaking,
        )

    async def sweep_once(self) -> None:
        now_wall = time.time()
        now_mono = time.monotonic()
        async with self._state_lock:
            expired = [
                item
                for item in self._records.values()
                if not item.busy
                and (
                    item.closing
                    or item.principal.expires_at <= now_wall
                    or now_mono - item.last_used_monotonic >= self.idle_seconds
                )
            ]
        for record in expired:
            reason = (
                "account_session_expired"
                if record.principal.expires_at <= now_wall
                else "public_session_idle"
            )
            await _shielded(self._cleanup_record(record, reason=reason))

    async def reconcile_stale_missions(self) -> None:
        """End public missions left running by an abrupt prior process exit."""

        try:
            bindings = await self.store.list_resource_bindings(
                resource_type=_MISSION_RESOURCE,
            )
            stale_sessions = await self.store.list_resource_bindings(
                resource_type=_SESSION_RESOURCE,
            )
        except Exception as exc:
            raise RuntimeError("public mission reconciliation is unavailable") from exc
        for binding in bindings:
            org_id = str(binding.org_id)
            adapter = ExecutiveControlPlaneAdapter(
                control_plane=self.control_plane,
                org_id=org_id,
                access=EventAccess.owner(org_id),
                actor="public_executive_reconciler",
            )
            try:
                await asyncio.wait_for(
                    adapter.end_mission(
                        binding.resource_id,
                        status="stopped",
                        reason="public_runtime_restarted",
                    ),
                    timeout=self.cleanup_timeout_seconds,
                )
            except Exception as exc:
                raise RuntimeError("public mission reconciliation failed") from exc
            await self.store.release_resource_binding(binding)
        for binding in stale_sessions:
            await self.store.release_resource_binding(binding)

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(max(1.0, self.sweep_interval_seconds))
            if not self._ready:
                try:
                    await self.reconcile_stale_missions()
                except Exception:
                    continue
                self._ready = True
            await self.sweep_once()

    async def _cleanup_record(
        self,
        record: _PublicMissionRecord,
        *,
        reason: str,
    ) -> None:
        async with record.cleanup_lock:
            async with self._state_lock:
                record.closing = True
            session = self.runtime.registry.get(record.session_id)
            target_ids = (
                {item.instance_id for item in session.specialists.values()}
                if session is not None
                else set()
            )
            runtime_stopped = False
            try:
                await asyncio.wait_for(
                    self.runtime.stop_mission(
                        record.session_id,
                        reason=reason,
                        status="stopped",
                    ),
                    timeout=self.cleanup_timeout_seconds,
                )
                runtime_stopped = True
            except (ExecutiveSessionError, asyncio.TimeoutError):
                runtime_stopped = session is None
            except Exception:
                runtime_stopped = False

            try:
                live_rows = await asyncio.wait_for(
                    self.runtime.prime.list_sessions(),
                    timeout=self.cleanup_timeout_seconds,
                )
                live = {item.session_id for item in live_rows}
            except Exception:
                live = set(target_ids)
            for instance_id in sorted(target_ids & live):
                try:
                    await asyncio.wait_for(
                        self.runtime.prime.stop_session(
                            instance_id,
                            reason=reason,
                        ),
                        timeout=self.cleanup_timeout_seconds,
                    )
                except Exception:
                    runtime_stopped = False
            try:
                remaining_rows = await asyncio.wait_for(
                    self.runtime.prime.list_sessions(),
                    timeout=self.cleanup_timeout_seconds,
                )
                # Prime RPC removes a successfully closed process. The null/test
                # port may retain terminal history rows, while a ``failed`` row
                # can still own a process after cleanup trouble and must remain
                # blocking. Retry all rows above, then accept only explicit
                # non-live history states here.
                remaining = {
                    item.session_id
                    for item in remaining_rows
                    if item.status in {"active", "stopping", "failed"}
                }
                runtime_stopped = runtime_stopped and not (target_ids & remaining)
            except Exception:
                runtime_stopped = False

            control_plane_stopped = False
            try:
                mission = await asyncio.wait_for(
                    record.adapter.end_mission(
                        record.mission_id,
                        status="stopped",
                        reason=reason,
                    ),
                    timeout=self.cleanup_timeout_seconds,
                )
                control_plane_stopped = (
                    mission is None or mission.status in TERMINAL_MISSION_STATUSES
                )
            except Exception:
                control_plane_stopped = False

            if runtime_stopped and control_plane_stopped:
                try:
                    record.final_snapshot = _safe_snapshot(
                        self.runtime.snapshot(record.session_id)
                    )
                except (ExecutiveSessionError, PublicExecutiveTurnError):
                    record.final_snapshot = {
                        "contract": "orch.public-executive.session",
                        "contract_version": "1.0",
                        "mission_id": record.mission_id,
                        "session_id": record.session_id,
                        "status": "stopped",
                        "confidence": {"score": 0},
                        "evidence_count": 0,
                        "specialists": [],
                        "execution_profile": PUBLIC_GUEST_EXECUTION_PROFILE,
                    }
                self.runtime.registry.drop(record.session_id)
                bindings_released = True
                for resource_type, resource_id in (
                    (_MISSION_RESOURCE, record.mission_id),
                    (_SESSION_RESOURCE, record.session_id),
                ):
                    try:
                        binding = await self.store.require_owned_resource(
                            resource_type=resource_type,
                            resource_id=resource_id,
                            principal=record.principal,
                        )
                        await self.store.release_resource_binding(binding)
                    except AccountResourceNotFound:
                        continue
                    except Exception:
                        bindings_released = False
                async with self._state_lock:
                    if (
                        bindings_released
                        and self._records.get(record.session_id) is record
                    ):
                        self._records.pop(record.session_id, None)

    async def safe_state(self) -> dict[str, int]:
        async with self._state_lock:
            return {
                "active_sessions": len(self._records),
                "opening_sessions": len(self._opening_accounts),
                "operations": self._operations,
            }


def _safe_snapshot(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PublicExecutiveTurnError("Executive session state is unavailable.")
    mission_id = require_public_identifier(raw.get("mission_id"))
    session_id = require_public_identifier(raw.get("session_id"))
    state = str(raw.get("status") or "active")
    if state not in {"active", "paused", "completed", "failed", "stopped"}:
        state = "failed"
    confidence = (
        raw.get("confidence") if isinstance(raw.get("confidence"), dict) else {}
    )
    score = confidence.get("score")
    score = (
        int(score)
        if isinstance(score, (int, float)) and not isinstance(score, bool)
        else 0
    )
    score = min(100, max(0, score))
    specialists: list[dict[str, str]] = []
    for item in raw.get("specialists") or []:
        if not isinstance(item, dict):
            continue
        role, role_filtered = sanitize_public_text(item.get("role_name"), maximum=32)
        specialist_status, status_filtered = sanitize_public_text(
            item.get("status"), maximum=20
        )
        if role and not role_filtered and specialist_status and not status_filtered:
            specialists.append({"role": role, "status": specialist_status})
    return {
        "contract": "orch.public-executive.session",
        "contract_version": "1.0",
        "mission_id": mission_id,
        "session_id": session_id,
        "status": state,
        "confidence": {"score": score},
        "evidence_count": max(0, int(raw.get("evidence_count") or 0)),
        "specialists": specialists[:8],
        "execution_profile": PUBLIC_GUEST_EXECUTION_PROFILE,
    }


_PUBLIC_RUNTIME_CLEANUP_FAILURES = frozenset(
    {
        "root_rotation_cleanup_failed",
        "session_cleanup_failed",
        "worker_cleanup_failed",
        "worker_finalization_cancelled",
    }
)
_PUBLIC_RUNTIME_TELEMETRY_FAILURES = frozenset(
    {
        "authoritative_telemetry_unavailable",
        "duplicate_generation_id",
        "telemetry_unavailable",
    }
)


def _runtime_gate_code(metering: dict[str, Any]) -> str:
    """Map private runtime failure state to one fixed, non-sensitive code."""

    if metering.get("telemetry_complete") is not True:
        return "telemetry_incomplete"
    if metering.get("hard_limits_passed") is not True:
        return "hard_limit"
    if metering.get("target_met") is not True:
        return "target_exceeded"
    reason = metering.get("failure_reason")
    if reason in _PUBLIC_RUNTIME_CLEANUP_FAILURES:
        return "runtime_cleanup"
    if reason in _PUBLIC_RUNTIME_TELEMETRY_FAILURES:
        return "metering_receipt"
    return "runtime_orchestration"


def _validated_safe_turn(
    raw: Any,
    *,
    expected_mission_id: str,
    expected_session_id: str,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PublicExecutiveTurnError(
            "Executive response is unavailable.", gate_code="response_contract"
        )
    message = raw.get("message")
    if not isinstance(message, dict):
        raise PublicExecutiveTurnError(
            "Executive response is unavailable.", gate_code="response_contract"
        )
    message_id = require_public_identifier(message.get("message_id"))
    text, filtered = sanitize_public_text(message.get("text"), maximum=600)
    if not text:
        raise PublicExecutiveTurnError(
            "Executive response is unavailable.", gate_code="response_contract"
        )
    metering = raw.get("public_guest")
    if not isinstance(metering, dict):
        raise PublicExecutiveTurnError(
            "Executive cost telemetry is unavailable.",
            gate_code="metering_receipt",
        )
    safe_metering = _public_metering(metering)
    if (
        metering.get("passed") is not True
        or metering.get("failure_reason") is not None
        or metering.get("requires_fresh_mission") is not False
        or not safe_metering["telemetry_complete"]
        or not safe_metering["target_met"]
        or not safe_metering["hard_limits_passed"]
    ):
        raise PublicExecutiveTurnError(
            "Executive cost gate rejected the turn.",
            gate_code=_runtime_gate_code(metering),
        )
    snapshot = _safe_snapshot(raw.get("snapshot"))
    if snapshot["mission_id"] != require_public_identifier(
        expected_mission_id
    ) or snapshot["session_id"] != require_public_identifier(expected_session_id):
        raise PublicExecutiveTurnError(
            "Executive response identity is unavailable.",
            gate_code="snapshot_identity",
        )
    delegations: list[dict[str, str]] = []
    for item in raw.get("delegations") or []:
        if not isinstance(item, dict):
            continue
        role, role_filtered = sanitize_public_text(item.get("role"), maximum=32)
        outcome, outcome_filtered = sanitize_public_text(item.get("status"), maximum=20)
        if role and not role_filtered and outcome and not outcome_filtered:
            delegations.append({"role": role, "status": outcome})
    return {
        "contract": "orch.public-executive.turn",
        "contract_version": "1.0",
        "message": {
            "message_id": message_id,
            "text": text,
            "safety_filtered": bool(message.get("safety_filtered") or filtered),
        },
        "delegations": delegations[:2],
        "snapshot": snapshot,
        "metering": safe_metering,
    }


def _attach_safe_publication(
    response: dict[str, Any],
    publication: Any,
    *,
    expected_mission_id: str,
) -> None:
    persisted = isinstance(publication, dict) and publication.get("persisted") is True
    if not persisted:
        raise PublicExecutiveTurnError(
            "Executive evidence persistence is unavailable.",
            gate_code="publication_contract",
        )
    mission_id = require_public_identifier(publication.get("mission_id"))
    if (
        publication.get("contract") != CONTRACT_NAME
        or publication.get("contract_version") != CONTRACT_VERSION
        or mission_id != require_public_identifier(expected_mission_id)
    ):
        raise PublicExecutiveTurnError(
            "Executive evidence persistence is unavailable.",
            gate_code="publication_contract",
        )
    response["event_publication"] = {
        "contract": CONTRACT_NAME,
        "contract_version": CONTRACT_VERSION,
        "persisted": True,
    }


def _presence_payload(
    snapshot: dict[str, Any] | None,
    *,
    display_mode: str,
    subtitles: bool,
    subtitle_language: str,
    subtitle_size: str,
    only_while_speaking: bool,
) -> dict[str, Any]:
    mode = (
        display_mode
        if display_mode in {"calm", "subtitles", "cards", "ops"}
        else "calm"
    )
    language = (
        subtitle_language
        if subtitle_language in {"en", "nl", "tr", "de", "fr", "es"}
        else "en"
    )
    size = subtitle_size if subtitle_size in {"sm", "md", "lg"} else "md"
    active = snapshot is not None and snapshot.get("status") in _ACTIVE_STATUSES
    status_line = (
        "Executive session is ready" if active else "Listening for your first mission"
    )
    return {
        "schema_version": 2,
        "source": "public-executive",
        "live": True,
        "mocked": False,
        "backend_dependency": "executive_runtime",
        "avatar_state": "working" if active else "listening",
        "avatar_states": list(AVATAR_STATES),
        "status_line": status_line,
        "subtitle": "Tell the executive what you want to accomplish"
        if subtitles
        else "",
        "subtitles_enabled": bool(subtitles),
        "subtitle_prefs": {
            "enabled": bool(subtitles),
            "language": language,
            "size": size,
            "only_while_speaking": bool(only_while_speaking),
        },
        "display_mode": mode,
        "display_modes": ["calm", "subtitles", "cards", "ops"],
        "progress": {
            "objective": "Active executive mission"
            if active
            else "Stand by for your first mission",
            "latest_verified_result": "Safe public runtime connected",
            "next_action": "Continue the conversation"
            if active
            else "Tell the executive what you need",
            "stage": snapshot.get("status") if snapshot else "idle",
        },
        "progress_drawer": {
            "confidence": snapshot.get("confidence", {}).get("score")
            if snapshot
            else None,
            "budget": {"consumed_usd": None, "cap_usd": 0.10, "currency": "USD"},
            "teams_active": len(snapshot.get("specialists", [])) if snapshot else 0,
            "work": {"completed": 0, "active": 1 if active else 0, "blocked": 0},
            "events": [],
        },
        "preview": None,
        "controls": {
            "can_start": not active,
            "can_pause": False,
            "can_resume": False,
            "can_stop": active,
            "can_preview": False,
            "mock": False,
        },
        "teams_active": len(snapshot.get("specialists", [])) if snapshot else 0,
        "mission_id": snapshot.get("mission_id") if snapshot else None,
        "mission_status": snapshot.get("status") if snapshot else "idle",
        "safe_copy": True,
        "notes": "Free public session. Provider credentials and private reasoning are never sent to the browser.",
        "session_id": snapshot.get("session_id") if snapshot else None,
    }


def _public_metering(raw: dict[str, Any]) -> dict[str, Any]:
    turn_number = raw.get("turn_number")
    worker_limit = raw.get("worker_limit")
    peak_workers = raw.get("peak_active_workers")
    if (
        raw.get("contract") != "orch.executive.public-guest-turn"
        or raw.get("contract_version") != "1.0"
        or raw.get("profile") != PUBLIC_GUEST_EXECUTION_PROFILE
        or raw.get("target_cost_usd") != "0.03"
        or raw.get("hard_cost_usd") != "0.10"
        or raw.get("max_total_tokens") != 12_000
        or raw.get("max_context_tokens_per_generation") != 3_000
        or raw.get("max_output_tokens_per_generation") != 600
        or raw.get("model_selector") != "openrouter/auto"
        or raw.get("provider_max_price")
        != {
            "prompt": "1",
            "completion": "5",
            "request": "0",
            "image": "0",
            "audio": "0",
        }
        or raw.get("fresh_process_context") is not True
        or raw.get("auto_compaction") != "disabled"
        or worker_limit != 2
        or not isinstance(turn_number, int)
        or isinstance(turn_number, bool)
        or turn_number < 1
        or not isinstance(peak_workers, int)
        or isinstance(peak_workers, bool)
        or not 0 <= peak_workers <= worker_limit
    ):
        raise PublicExecutiveTurnError(
            "Executive cost contract is unavailable.",
            gate_code="metering_contract",
        )
    cost_value = raw.get("actual_cost_usd")
    if not isinstance(cost_value, str):
        raise PublicExecutiveTurnError(
            "Executive cost telemetry is unavailable.",
            gate_code="metering_receipt",
        )
    try:
        cost = Decimal(cost_value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PublicExecutiveTurnError(
            "Executive cost telemetry is unavailable.",
            gate_code="metering_receipt",
        ) from exc
    tokens = raw.get("total_tokens")
    generations = raw.get("generation_count")
    if (
        isinstance(generations, int)
        and not isinstance(generations, bool)
        and generations == 0
    ):
        gate_code = (
            "telemetry_incomplete"
            if raw.get("telemetry_complete") is not True
            else "metering_receipt"
        )
        raise PublicExecutiveTurnError(
            "Executive cost telemetry is unavailable.", gate_code=gate_code
        )
    if (
        not cost.is_finite()
        or cost < 0
        or cost > Decimal("0.10")
        or not isinstance(tokens, int)
        or isinstance(tokens, bool)
        or not 0 <= tokens <= 12_000
        or not isinstance(generations, int)
        or isinstance(generations, bool)
        or not 1 <= generations <= 4
    ):
        raise PublicExecutiveTurnError(
            "Executive cost gate rejected the turn.", gate_code="hard_limit"
        )
    telemetry_complete = raw.get("telemetry_complete") is True
    hard_limits_passed = raw.get("hard_limits_passed") is True
    target_met = raw.get("target_met") is True
    if target_met != (cost <= Decimal("0.03")):
        raise PublicExecutiveTurnError(
            "Executive cost telemetry is inconsistent.",
            gate_code="metering_receipt",
        )
    return {
        "actual_cost_usd": format(cost, "f"),
        "total_tokens": tokens,
        "generation_count": generations,
        "telemetry_complete": telemetry_complete,
        "target_met": target_met,
        "hard_limits_passed": hard_limits_passed,
        "limits": {
            "target_cost_usd": "0.03",
            "hard_cost_usd": "0.10",
            "max_total_tokens": 12_000,
        },
    }


def _gateway(request: Request) -> PublicExecutiveGateway:
    gateway = getattr(request.app.state, "public_executive_gateway", None)
    if not isinstance(gateway, PublicExecutiveGateway) or not gateway._ready:
        raise HTTPException(status_code=503, detail="Public executive is unavailable")
    return gateway


def _browser_mutation(request: Request) -> None:
    try:
        require_browser_mutation(request)
    except BrowserMutationRejected as exc:
        raise HTTPException(
            status_code=403, detail="Browser mutation rejected"
        ) from exc


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Cookie"


def _quota_http(exc: UsageQuotaExceeded) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Free executive usage limit reached",
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


def _capacity_http(exc: PublicExecutiveCapacityError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=exc.detail,
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


@public_executive_router.get("/presence")
async def public_presence(
    request: Request,
    response: Response,
    display_mode: str = Query(default="calm"),
    subtitles: bool = Query(default=True),
    subtitle_language: str = Query(default="en"),
    subtitle_size: str = Query(default="md"),
    only_while_speaking: bool = Query(default=False),
    principal: AccountPrincipalV1 = Depends(require_account_principal),
) -> dict[str, Any]:
    _no_store(response)
    return await _gateway(request).presence(
        principal,
        display_mode=display_mode,
        subtitles=subtitles,
        subtitle_language=subtitle_language,
        subtitle_size=subtitle_size,
        only_while_speaking=only_while_speaking,
    )


@public_executive_router.post("/executive/missions")
async def public_open_mission(
    body: PublicMissionBody,
    request: Request,
    response: Response,
    principal: AccountPrincipalV1 = Depends(require_account_principal),
) -> dict[str, Any]:
    _no_store(response)
    _browser_mutation(request)
    try:
        return await _gateway(request).open_mission(principal, brief=body.brief)
    except PublicExecutiveCapacityError as exc:
        raise _capacity_http(exc) from exc
    except UsageQuotaExceeded as exc:
        raise _quota_http(exc) from exc
    except AccountAccessDenied as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    except (PrimeUnavailableError, PrimeRuntimeError) as exc:
        raise HTTPException(
            status_code=503, detail="Public executive is unavailable"
        ) from exc
    except (ExecutiveSafetyError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="Invalid public mission request"
        ) from exc
    except PublicExecutiveTurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Public executive is unavailable"
        ) from exc


@public_executive_router.post("/executive/sessions/{session_id}/messages")
async def public_message(
    session_id: str,
    body: PublicMessageBody,
    request: Request,
    response: Response,
    principal: AccountPrincipalV1 = Depends(require_account_principal),
) -> dict[str, Any]:
    _no_store(response)
    _browser_mutation(request)
    try:
        return await _gateway(request).send_message(
            principal,
            session_id,
            message=body.message,
        )
    except AccountResourceNotFound as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    except AccountAccessDenied as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    except UsageQuotaExceeded as exc:
        raise _quota_http(exc) from exc
    except PublicExecutiveCapacityError as exc:
        raise _capacity_http(exc) from exc
    except PublicExecutiveTurnError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
            headers={
                "X-AI-Control-Room-Session-State": "closed",
                PUBLIC_GATE_CODE_HEADER: exc.gate_code,
            },
        ) from exc
    except ExecutiveSafetyError as exc:
        raise HTTPException(status_code=400, detail="Invalid public message") from exc


@public_executive_router.post("/executive/sessions/{session_id}/stop")
async def public_stop(
    session_id: str,
    body: PublicStopBody,
    request: Request,
    response: Response,
    principal: AccountPrincipalV1 = Depends(require_account_principal),
) -> dict[str, Any]:
    _no_store(response)
    _browser_mutation(request)
    try:
        return await _gateway(request).stop_mission(
            principal,
            session_id,
            reason=body.reason,
        )
    except AccountResourceNotFound as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    except AccountAccessDenied as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    except PublicExecutiveTurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def get_public_executive_gateway(request: Request) -> PublicExecutiveGateway:
    return _gateway(request)
