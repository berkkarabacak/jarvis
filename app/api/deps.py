from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from app.auth.provider import TokenProvider
from app.auth.store import AuthTokenStore
from app.config import Settings
from app.llm.base import LlmProvider
from app.runner.runner import JobRunner
from app.store.jobs import JobStore


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_auth_store(request: Request) -> AuthTokenStore:
    return request.app.state.auth_store


def get_token_provider(request: Request) -> TokenProvider:
    return request.app.state.token_provider


def get_llm(request: Request) -> LlmProvider:
    return request.app.state.llm


def get_job_store(request: Request) -> JobStore:
    return request.app.state.job_store


def get_runner(request: Request) -> JobRunner:
    return request.app.state.runner


def get_executive_registry(request: Request):
    return request.app.state.executive_registry


def get_executive_runtime(request: Request):
    return request.app.state.executive_runtime


def get_handoff_store(request: Request):
    return request.app.state.handoff_store


def get_db_provider(request: Request):
    return request.app.state.db_provider


def get_notify_diag(request: Request):
    return request.app.state.notify_diag


async def require_api_secret(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    settings: Settings = request.app.state.settings
    expected = (settings.api_secret or "").strip()
    if not expected or expected == "dev-secret-change-me":
        # A missing or publicly-known secret must never authenticate anyone.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API_SECRET is unset or a well-known default; set a long random string",
        )
    provided = x_api_key
    if not provided and authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided = parts[1].strip()
        else:
            provided = authorization.strip()
    if not provided or not hmac.compare_digest(provided.strip(), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API secret",
        )
