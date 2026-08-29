from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.public_access.models import AccountPrincipalV1
from app.public_access.security import read_public_session_token
from app.public_access.store import PublicAccessStore


def get_public_access_store(request: Request) -> PublicAccessStore:
    store = getattr(request.app.state, "public_access_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Public account service unavailable",
        )
    return store


async def require_account_principal(
    request: Request,
    store: PublicAccessStore = Depends(get_public_access_store),
) -> AccountPrincipalV1:
    principal = await store.resolve_session(read_public_session_token(request))
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account session required",
        )
    return principal
