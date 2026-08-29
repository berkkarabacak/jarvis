from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.public_access.dependencies import (
    get_public_access_store,
    require_account_principal,
)
from app.public_access.errors import (
    AccountResourceNotFound,
    BrowserMutationRejected,
    UsageQuotaExceeded,
)
from app.public_access.executive_routes import public_executive_router
from app.public_access.models import AccountPrincipalV1
from app.public_access.security import (
    GUEST_BOOTSTRAP_DAILY_LIMIT,
    GUEST_BOOTSTRAP_HOURLY_LIMIT,
    PUBLIC_SESSION_TTL_SECONDS,
    derive_bootstrap_subject_key,
    public_session_cookie_name,
    public_session_cookie_secure,
    read_public_session_token,
    require_browser_mutation,
)
from app.public_access.store import PublicAccessStore

public_router = APIRouter(prefix="/api/public", tags=["public-account"])
public_router.include_router(public_executive_router)


class GuestSessionBootstrapBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RenameAccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=80)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Cookie"


def _browser_mutation(request: Request) -> None:
    try:
        require_browser_mutation(request)
    except BrowserMutationRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Browser mutation rejected",
        ) from exc


def _set_session_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        key=public_session_cookie_name(request),
        value=token,
        max_age=PUBLIC_SESSION_TTL_SECONDS,
        path="/",
        secure=public_session_cookie_secure(request),
        httponly=True,
        samesite="lax",
    )


@public_router.post("/session")
async def bootstrap_public_session(
    request: Request,
    response: Response,
    _body: GuestSessionBootstrapBody | None = None,
    store: PublicAccessStore = Depends(get_public_access_store),
) -> dict[str, Any]:
    """Create or resume one isolated zero-friction guest account."""

    _browser_mutation(request)
    _no_store(response)
    existing = await store.resolve_session(read_public_session_token(request))
    if existing is not None:
        return existing.to_dict()

    settings: Settings = request.app.state.settings
    subject_key = derive_bootstrap_subject_key(request, settings.api_secret)
    try:
        await store.consume_quota(
            subject_key=subject_key,
            quota_name="guest_session_bootstrap",
            hourly_limit=GUEST_BOOTSTRAP_HOURLY_LIMIT,
            daily_limit=GUEST_BOOTSTRAP_DAILY_LIMIT,
        )
    except UsageQuotaExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Guest session limit reached",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    issued = await store.create_guest_session()
    _set_session_cookie(response, issued.session_token, request)
    return issued.principal.to_dict()


@public_router.get("/session")
async def get_public_session(
    response: Response,
    principal: AccountPrincipalV1 = Depends(require_account_principal),
) -> dict[str, Any]:
    _no_store(response)
    return principal.to_dict()


@public_router.patch("/session")
async def rename_public_account(
    body: RenameAccountBody,
    request: Request,
    response: Response,
    principal: AccountPrincipalV1 = Depends(require_account_principal),
    store: PublicAccessStore = Depends(get_public_access_store),
) -> dict[str, Any]:
    _browser_mutation(request)
    _no_store(response)
    try:
        renamed = await store.rename_account(principal, body.display_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except AccountResourceNotFound as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    return renamed.to_dict()


@public_router.delete("/session")
async def revoke_public_session(
    request: Request,
    response: Response,
    store: PublicAccessStore = Depends(get_public_access_store),
) -> dict[str, Any]:
    _browser_mutation(request)
    _no_store(response)
    token = read_public_session_token(request)
    principal = await store.resolve_session(token)
    await store.revoke_session(token)
    gateway = getattr(request.app.state, "public_executive_gateway", None)
    if principal is not None and gateway is not None:
        await gateway.revoke_principal(principal)
    response.delete_cookie(
        key=public_session_cookie_name(request),
        path="/",
        secure=public_session_cookie_secure(request),
        httponly=True,
        samesite="lax",
    )
    return {"schema_version": 1, "revoked": True}
