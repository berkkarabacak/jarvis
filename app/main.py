from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.agents.registry import AgentRegistry
from app.api.routes import build_router
from app.auth.provider import build_token_provider
from app.auth.store import AuthTokenStore
from app.config import get_settings, validate_secret_settings
from app.crypto import TokenCipher
from app.executive.adapters.factory import build_executive_prime_agent
from app.executive.adapters.routing import HeuristicModelRouter
from app.executive.memory_bridge import (
    build_executive_memory_bridge_from_environment,
)
from app.executive.registry import ExecutiveSessionRegistry
from app.executive.runtime import ExecutiveRuntime
from app.executive.store import SqliteHandoffStore
from app.integrations.executive_control_plane import ExecutiveControlPlaneAdapter
from app.llm.factory import build_llm_provider
from app.notify.diagnostics import NotifyDiagnostics
from app.persistence.contract import PERSISTENCE_CONTRACT, dialect_for_provider
from app.persistence.factory import (
    build_app_data_database,
    build_database,
    run_platform_migrations,
)
from app.public_access.executive_routes import PublicExecutiveGateway
from app.public_access.store import SqlitePublicAccessStore
from app.runner.runner import JobRunner
from app.store.jobs import JobStore
from app.store.memories import MemoryStore
from app.store.messages import MessageStore

log = logging.getLogger("agent_orchestrator")


async def _public_no_store_middleware(request: Request, call_next) -> Response:
    """Prevent account-scoped public API payloads from entering browser/proxy caches."""

    response = await call_next(request)
    path = request.scope.get("path", "")
    if path == "/api/public" or path.startswith("/api/public/"):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Vary"] = "Cookie"
    return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.enforce_secure_secrets:
        problems = validate_secret_settings(settings)
        if problems:
            raise RuntimeError(
                "refusing to start with insecure secrets "
                "(set ENFORCE_SECURE_SECRETS=false to allow): "
                + "; ".join(problems)
            )
    db_provider = build_database(settings)
    data_provider = build_app_data_database(settings, db_provider)

    await db_provider.connect()
    if data_provider is not db_provider:
        await data_provider.connect()

    migration_summary = None
    try:
        migration_summary = await run_platform_migrations(db_provider, settings)
        if migration_summary:
            log.info("platform migrations: %s", migration_summary)
    except Exception:
        log.exception("platform migrations failed")
        if bool(getattr(settings, "database_strict", False)):
            await data_provider.close()
            if data_provider is not db_provider:
                await db_provider.close()
            raise

    db = getattr(data_provider, "underlying", data_provider)
    cipher = TokenCipher(settings.token_encryption_key, settings.api_secret)
    auth_store = AuthTokenStore(db, cipher)
    token_provider = build_token_provider(settings, auth_store)
    llm = build_llm_provider(settings, token_provider)
    job_store = JobStore(db, memory_versions_keep=settings.memory_versions_keep)
    memory_store = MemoryStore(db)
    message_store = MessageStore(db)
    public_access_store = SqlitePublicAccessStore(db)
    agent_registry = AgentRegistry(db)
    await agent_registry.ensure_default()
    notify_diag = NotifyDiagnostics(db)
    await notify_diag.ensure_schema()
    handoff_store = SqliteHandoffStore(db)
    await handoff_store.ensure_schema()
    executive_registry = ExecutiveSessionRegistry(handoff_store=handoff_store)
    executive_memory = await build_executive_memory_bridge_from_environment(db)
    # Prime RPC is explicitly opt-in via PRIME_AGENT_ENABLED; it drives an
    # external `prime-agent` binary. When that is not enabled, fall back to the
    # in-process OpenRouter adapter so a host with only OPENROUTER_API_KEY set
    # still serves live executive turns. Null remains the last resort.
    # Neither adapter places the OpenRouter credential on argv or in health output.
    executive_runtime = ExecutiveRuntime(
        registry=executive_registry,
        prime=build_executive_prime_agent(settings),
        router=HeuristicModelRouter(),
        memory_bridge=executive_memory,
    )
    runner = JobRunner(
        jobs=job_store,
        llm=llm,
        settings=settings,
        notify_diag=notify_diag,
        memories=memory_store,
        messages=message_store,
    )
    from app.control_plane.service import build_control_plane

    control_plane = build_control_plane(db)
    await control_plane.ensure_ready()
    executive_control_plane = ExecutiveControlPlaneAdapter(control_plane)
    public_executive_gateway = PublicExecutiveGateway(
        runtime=executive_runtime,
        control_plane=control_plane,
        store=public_access_store,
        server_secret=settings.api_secret,
    )

    app.state.settings = settings
    app.state.db_provider = (
        db_provider  # platform (postgres target / health / migrations)
    )
    app.state.data_provider = data_provider  # app scheduler data (sqlite until cutover)
    app.state.db = db
    app.state.persistence_contract = PERSISTENCE_CONTRACT.to_dict()
    app.state.platform_dialect = dialect_for_provider(db_provider)
    app.state.app_data_dialect = dialect_for_provider(data_provider)
    app.state.migration_summary = migration_summary
    # Tenancy store only when platform is Postgres (migration 002).
    tenancy_store = None
    if dialect_for_provider(db_provider) == "postgres":
        from app.tenancy.store import TenancyStore

        tenancy_store = TenancyStore(db_provider.conn)
    app.state.tenancy_store = tenancy_store
    app.state.auth_store = auth_store
    app.state.token_provider = token_provider
    app.state.llm = llm
    app.state.job_store = job_store
    app.state.memory_store = memory_store
    app.state.message_store = message_store
    app.state.public_access_store = public_access_store
    app.state.agent_registry = agent_registry
    app.state.notify_diag = notify_diag
    app.state.handoff_store = handoff_store
    app.state.executive_registry = executive_registry
    app.state.executive_runtime = executive_runtime
    app.state.executive_control_plane = executive_control_plane
    app.state.public_executive_gateway = public_executive_gateway
    app.state.runner = runner
    app.state.control_plane = control_plane
    await public_executive_gateway.start()
    try:
        yield
    finally:
        try:
            await public_executive_gateway.close()
        finally:
            try:
                await executive_runtime.close()
            finally:
                await data_provider.close()
                if data_provider is not db_provider:
                    await db_provider.close()


def create_app() -> FastAPI:
    # D3: public cloud must never enable desktop tools / Prime / bridge
    try:
        from app.jarvis.guardrails import enforce_public_guardrails

        gr = enforce_public_guardrails()
        if gr.get("public_cloud"):
            log.warning("public cloud guardrails applied: %s", gr.get("applied"))
    except Exception:
        log.exception("guardrails init failed")

    app = FastAPI(
        title="Agent Orchestrator",
        version="0.3.0",
        description="Multi-provider scheduled agent runner (OpenRouter + optional xAI)",
        lifespan=lifespan,
    )
    app.middleware("http")(_public_no_store_middleware)
    app.include_router(build_router())
    return app


app = create_app()
