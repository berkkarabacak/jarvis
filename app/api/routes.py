from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import (
    get_auth_store,
    get_executive_registry,
    get_executive_runtime,
    get_handoff_store,
    get_job_store,
    get_llm,
    get_notify_diag,
    get_runner,
    get_settings,
    get_token_provider,
    require_api_secret,
)
from app.auth.constants import DEFAULT_XAI_MODELS, XAI_OAUTH_TOKEN_URL_FALLBACK
from app.auth.oauth import (
    build_authorize_url,
    create_oauth_nonce,
    create_oauth_state,
    discover_xai_oauth,
    exchange_code_for_tokens,
    generate_pkce,
)
from app.auth.provider import TokenProvider
from app.auth.store import AuthTokenStore
from app.config import Settings
from app.control_plane.event_routes import router as control_plane_event_router
from app.executive.adapters.prime import PrimeRuntimeError, PrimeUnavailableError
from app.executive.confidence import EvidenceItem
from app.executive.handoff import HandoffValidationError
from app.executive.registry import ExecutiveSessionRegistry
from app.executive.runtime import ExecutiveRuntime
from app.executive.safety import ExecutiveSafetyError, sanitize_private_input
from app.executive.session import ExecutiveSessionError
from app.integrations.executive_control_plane import (
    ExecutiveControlPlaneIntegrationError,
)
from app.llm.base import LlmProvider
from app.llm.openrouter import DEFAULT_OPENROUTER_MODELS, OPENROUTER_AUTO_MODEL
from app.persistence.factory import database_health
from app.public_access.routes import public_router
from app.runner.runner import JobRunner
from app.store.jobs import JobStore

log = logging.getLogger("agent_orchestrator.api")

router = APIRouter()
api_router = APIRouter(dependencies=[Depends(require_api_secret)])

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
DASHBOARD_HTML = STATIC_DIR / "dashboard.html"
HISTORY_HTML = STATIC_DIR / "history.html"
CEO_HTML = STATIC_DIR / "ceo.html"
LOGO_SVG = STATIC_DIR / "logo.svg"
FAVICON_SVG = STATIC_DIR / "favicon.svg"


class ImportTokensBody(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: float
    token_endpoint: str | None = None
    redirect_uri: str | None = None
    token_type: str = "Bearer"


class CreateJobBody(BaseModel):
    name: str
    prompt_template: str
    model: str | None = None
    model_mode: str | None = "inherit"
    schedule: str | None = None
    memory_doc: str = ""
    enabled: bool = True
    notify_email: str = ""
    slack_on_success: bool = False
    slack_on_failure: bool = True
    runner: str | None = "llm"  # llm | herdr
    herdr_agent_kind: str | None = None
    herdr_agent_name: str | None = None
    herdr_cwd: str | None = None
    herdr_workspace_label: str | None = None
    herdr_extra_args: list[str] | None = None


class UpdateJobBody(BaseModel):
    name: str | None = None
    prompt_template: str | None = None
    model: str | None = None
    model_mode: str | None = None
    schedule: str | None = Field(default=None)
    enabled: bool | None = None
    notify_email: str | None = None
    slack_on_success: bool | None = None
    slack_on_failure: bool | None = None
    clear_schedule: bool = False
    runner: str | None = None
    herdr_agent_kind: str | None = None
    herdr_agent_name: str | None = None
    herdr_cwd: str | None = None
    herdr_workspace_label: str | None = None
    herdr_extra_args: list[str] | None = None


class LlmSettingsBody(BaseModel):
    provider: str | None = None  # openrouter | xai
    model_mode: str | None = None  # auto | fixed
    default_model: str | None = None
    openrouter_api_key: str | None = None  # write-only; empty string clears


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-orchestrator"}


# GET / is public Talk (app.jarvis.public_routes). Old CEO stays at /ceo.


@router.get("/logo.svg")
async def logo_svg() -> FileResponse:
    if not LOGO_SVG.is_file():
        raise HTTPException(status_code=404, detail="Logo not found")
    return FileResponse(LOGO_SVG, media_type="image/svg+xml")


@router.get("/favicon.svg")
async def favicon_svg() -> FileResponse:
    if not FAVICON_SVG.is_file():
        raise HTTPException(status_code=404, detail="Favicon not found")
    return FileResponse(FAVICON_SVG, media_type="image/svg+xml")


@router.get("/favicon.ico")
async def favicon_ico() -> RedirectResponse:
    return RedirectResponse(url="favicon.svg", status_code=307)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page() -> FileResponse:
    """One-screen home UI. Data requires X-Api-Key via API calls; no secrets embedded."""
    if not DASHBOARD_HTML.is_file():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return FileResponse(DASHBOARD_HTML, media_type="text/html; charset=utf-8")


@router.get("/history", response_class=HTMLResponse)
async def history_page() -> FileResponse:
    """Past runs page (separate from the one-screen home UI)."""
    if not HISTORY_HTML.is_file():
        raise HTTPException(status_code=404, detail="History page not found")
    return FileResponse(HISTORY_HTML, media_type="text/html; charset=utf-8")


@router.get("/ceo", response_class=HTMLResponse)
async def ceo_home_page() -> FileResponse:
    """ORCH-72 calm CEO home shell. Additive; does not replace /dashboard."""
    if not CEO_HTML.is_file():
        raise HTTPException(status_code=404, detail="CEO home not found")
    return FileResponse(CEO_HTML, media_type="text/html; charset=utf-8")


@router.post("/oauth/start", dependencies=[Depends(require_api_secret)])
async def oauth_start(
    request: Request,
    auth_store: AuthTokenStore = Depends(get_auth_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Start PKCE login. Prefer local CLI; this helps local loopback mode."""
    pkce = generate_pkce()
    state = create_oauth_state()
    nonce = create_oauth_nonce()
    redirect_uri = settings.oauth_redirect_uri
    await auth_store.save_pending(
        state=state,
        code_verifier=pkce.verifier,
        code_challenge=pkce.challenge,
        redirect_uri=redirect_uri,
        nonce=nonce,
    )
    url = build_authorize_url(
        redirect_uri=redirect_uri,
        code_challenge=pkce.challenge,
        state=state,
        nonce=nonce,
    )
    return {
        "authorize_url": url,
        "state": state,
        "redirect_uri": redirect_uri,
        "note": "Borrowed client only allows localhost callback. Use scripts/login_local.py on a machine with a browser, then POST /oauth/import.",
    }


@router.get("/oauth/callback")
async def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    auth_store: AuthTokenStore = Depends(get_auth_store),
) -> dict[str, Any]:
    if error:
        raise HTTPException(status_code=400, detail=error_description or error)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    pending = await auth_store.pop_pending(state)
    if pending is None:
        raise HTTPException(status_code=400, detail="Unknown or expired OAuth state")

    discovery = await discover_xai_oauth()
    tokens = await exchange_code_for_tokens(
        token_endpoint=discovery.token_endpoint,
        code=code,
        redirect_uri=pending["redirect_uri"],
        code_verifier=pending["code_verifier"],
        code_challenge=pending["code_challenge"],
    )
    await auth_store.save(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_at=tokens.expires_at,
        token_endpoint=discovery.token_endpoint,
        redirect_uri=pending["redirect_uri"],
        token_type=tokens.token_type,
        needs_reauth=False,
        provider_type="oauth",
        last_error=None,
    )
    return {
        "ok": True,
        "expires_at": tokens.expires_at,
        "message": "Tokens stored. You can close this window.",
    }


@api_router.post("/oauth/import")
async def oauth_import(
    body: ImportTokensBody,
    auth_store: AuthTokenStore = Depends(get_auth_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    await auth_store.save(
        access_token=body.access_token,
        refresh_token=body.refresh_token,
        expires_at=body.expires_at,
        token_endpoint=body.token_endpoint or XAI_OAUTH_TOKEN_URL_FALLBACK,
        redirect_uri=body.redirect_uri or settings.oauth_redirect_uri,
        token_type=body.token_type,
        needs_reauth=False,
        provider_type="oauth",
        last_error=None,
    )
    return {"ok": True, "needs_reauth": False}


async def _model_catalog(settings: Settings, llm: LlmProvider) -> list[str]:
    provider = (settings.llm_provider or "openrouter").lower()
    try:
        models = await llm.list_models()
        if models:
            return models
    except Exception:
        pass
    if provider in ("xai", "grok"):
        return list(DEFAULT_XAI_MODELS)
    return list(DEFAULT_OPENROUTER_MODELS)


def _mask_secret(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= 8:
        return "••••••••"
    return v[:4] + "…" + v[-4:]


@api_router.get("/api/status")
async def api_status(
    request: Request,
    token_provider: TokenProvider = Depends(get_token_provider),
    llm: LlmProvider = Depends(get_llm),
    jobs: JobStore = Depends(get_job_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    from app.schedule.compat import list_scheduled_work, summarize_schedule_views

    auth = await token_provider.status()
    llm_status = await llm.status()
    db = request.app.state.db_provider
    db_status = await database_health(db)
    last = await jobs.last_run_any()
    models = await _model_catalog(settings, llm)
    mem_counts = await _memory_counts(request, jobs)
    herdr_summary = await _herdr_summary(settings)
    items = await jobs.list_jobs()
    last_runs: dict[str, Any] = {}
    for j in items:
        lr = await jobs.last_run_for_job(j.id)
        if lr is not None:
            last_runs[j.id] = lr
    provider = (settings.llm_provider or "openrouter").strip().lower()
    schedule_views = list_scheduled_work(
        items,
        llm_provider=provider,
        tz_name=settings.tz or "UTC",
        last_runs=last_runs,
    )
    return {
        "service": "agent-orchestrator",
        "auth": auth.to_dict(),
        "llm": llm_status.to_dict(),
        "database": db_status.to_dict(),
        "memory": mem_counts,
        "herdr": herdr_summary,
        "schedules": summarize_schedule_views(schedule_views),
        "last_run": last.to_dict() if last else None,
        "models": models,
        "scheduler_note": (
            "Next Cloud Scheduler fire is managed in GCP, not in this process. "
            "Job.schedule is informational for the dashboard. "
            "ORCH-73 compatibility: GET /api/schedules."
        ),
    }


async def _herdr_summary(settings: Settings) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "enabled": bool(settings.herdr_enabled),
        "bin": settings.herdr_bin,
        "default_kind": settings.herdr_default_kind,
        "available": False,
    }
    try:
        from app.integrations.herdr import HerdrClient, HerdrConfig

        st = await HerdrClient(HerdrConfig.from_settings(settings)).status()
        summary["available"] = bool(st.get("available"))
        if st.get("error"):
            summary["error"] = st["error"]
        if st.get("version"):
            summary["version"] = st["version"]
    except Exception as exc:
        summary["error"] = str(exc)[:200]
    return summary


async def _memory_counts(request: Request, jobs: JobStore) -> dict[str, Any]:
    """Lightweight memory stats from job store + shared/private bank."""
    try:
        cur = await jobs.db.conn.execute(
            "SELECT COUNT(*) AS c, COALESCE(SUM(LENGTH(memory_doc)),0) AS chars FROM jobs"
        )
        row = await cur.fetchone()
        cur2 = await jobs.db.conn.execute("SELECT COUNT(*) AS c FROM memory_log")
        row2 = await cur2.fetchone()
        shared = private = 0
        mem_store = getattr(request.app.state, "memory_store", None)
        if mem_store is not None:
            counts = await mem_store.counts()
            shared = int(counts.get("shared") or 0)
            private = int(counts.get("private") or 0)
        return {
            "jobs_with_memory": int(row["c"] or 0) if row else 0,
            "short_memory_chars": int(row["chars"] or 0) if row else 0,
            "log_entries": int(row2["c"] or 0) if row2 else 0,
            "shared": shared,
            "private": private,
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}


@api_router.get("/api/settings/llm")
async def get_llm_settings(
    settings: Settings = Depends(get_settings),
    llm: LlmProvider = Depends(get_llm),
) -> dict[str, Any]:
    status = await llm.status()
    return {
        "provider": (settings.llm_provider or "openrouter").lower(),
        "model_mode": (settings.llm_model_mode or "auto").lower(),
        "default_model": settings.default_model,
        "openrouter_api_key_set": bool((settings.openrouter_api_key or "").strip()),
        "openrouter_api_key_masked": _mask_secret(settings.openrouter_api_key),
        "auto_model_id": OPENROUTER_AUTO_MODEL,
        "status": status.to_dict(),
        "note": (
            "Runtime settings are loaded from environment / .env. "
            "PUT updates process memory until restart; persist via .env on the server."
        ),
    }


@api_router.put("/api/settings/llm")
async def put_llm_settings(
    body: LlmSettingsBody,
    request: Request,
    settings: Settings = Depends(get_settings),
    token_provider: TokenProvider = Depends(get_token_provider),
) -> dict[str, Any]:
    """Update in-process LLM settings (survives until process restart).

    For durable config, set env vars on the host (.env / systemd).
    """
    if body.provider is not None:
        p = body.provider.strip().lower()
        if p not in ("openrouter", "xai", "grok"):
            raise HTTPException(status_code=400, detail="provider must be openrouter or xai")
        settings.llm_provider = "xai" if p in ("xai", "grok") else "openrouter"
    if body.model_mode is not None:
        m = body.model_mode.strip().lower()
        if m not in ("auto", "fixed"):
            raise HTTPException(status_code=400, detail="model_mode must be auto or fixed")
        settings.llm_model_mode = m
    if body.default_model is not None:
        settings.default_model = body.default_model.strip() or settings.default_model
    if body.openrouter_api_key is not None:
        settings.openrouter_api_key = body.openrouter_api_key.strip()

    from app.llm.factory import build_llm_provider

    llm = build_llm_provider(settings, token_provider)
    request.app.state.llm = llm
    request.app.state.runner.llm = llm
    request.app.state.settings = settings

    # The executive adapter captures the OpenRouter credential when it is built,
    # so rebuilding only the scheduler LLM would leave public chat running on the
    # previous key — including after an operator deliberately cleared it. Swap the
    # adapter too and close the old one, which drops any session still holding the
    # retired credential.
    executive_rebuilt = False
    runtime = getattr(request.app.state, "executive_runtime", None)
    if runtime is not None:
        from app.executive.adapters.factory import build_executive_prime_agent

        previous = getattr(runtime, "prime", None)
        replacement = build_executive_prime_agent(settings)
        runtime.prime = replacement
        executive_rebuilt = True
        if previous is not None and previous is not replacement:
            try:
                await previous.close()
            except Exception as exc:  # noqa: BLE001 - retirement is best effort
                log.warning(
                    "retiring previous executive adapter failed: %s", type(exc).__name__
                )

    status = await llm.status()
    return {
        "ok": True,
        "provider": settings.llm_provider,
        "model_mode": settings.llm_model_mode,
        "default_model": settings.default_model,
        "openrouter_api_key_set": bool(settings.openrouter_api_key),
        "executive_adapter_rebuilt": executive_rebuilt,
        "status": status.to_dict(),
    }


@api_router.post("/api/settings/llm/test")
async def test_llm_settings(
    llm: LlmProvider = Depends(get_llm),
    model: str | None = Query(default=None),
) -> dict[str, Any]:
    result = await llm.test_connection(model=model)
    return result.to_dict()


async def _build_schedule_context(
    jobs: JobStore,
    settings: Settings,
    *,
    run_history_limit: int = 8,
) -> tuple[list[Any], list[Any], str, str]:
    """Shared loader for schedule compatibility endpoints."""
    from app.schedule.compat import list_normalized_runs, list_scheduled_work

    items = await jobs.list_jobs()
    last_runs: dict[str, Any] = {}
    runs_by_job: dict[str, list[Any]] = {}
    for j in items:
        hist = await jobs.list_runs(j.id, limit=run_history_limit)
        if hist:
            runs_by_job[j.id] = hist
            last_runs[j.id] = hist[0]
    tz_name = settings.tz or "UTC"
    provider = (settings.llm_provider or "openrouter").strip().lower()
    views = list_scheduled_work(
        items,
        llm_provider=provider,
        tz_name=tz_name,
        last_runs=last_runs,
        runs_by_job=runs_by_job,
    )
    names = {j.id: j.name for j in items}
    recent_raw = await jobs.recent_runs(limit=40)
    recent_norm = list_normalized_runs(
        recent_raw, job_names=names, default_provider=provider
    )
    return views, recent_norm, tz_name, provider


@api_router.get("/api/schedules")
async def list_schedules(
    jobs: JobStore = Depends(get_job_store),
    settings: Settings = Depends(get_settings),
    run_history_limit: int = Query(default=8, ge=1, le=50),
    health: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    due_state: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    paused: bool | None = Query(default=None),
    runner: str | None = Query(default=None),
    include_upcoming: bool = Query(default=True),
    upcoming_days: float = Query(default=7.0, ge=0.0, le=60.0),
) -> dict[str, Any]:
    """ORCH-73: Control Room view of legacy scheduled jobs (compatibility adapter)."""
    from app.schedule.compat import (
        build_upcoming_fires,
        filter_run_views,
        filter_schedule_views,
        summarize_schedule_views,
    )

    views, recent_norm, tz_name, llm_provider = await _build_schedule_context(
        jobs, settings, run_history_limit=run_history_limit
    )
    filtered = filter_schedule_views(
        views,
        health=health,
        provider=provider,
        due_state=due_state,
        enabled=enabled,
        paused=paused,
        runner=runner,
    )
    runs = filter_run_views(recent_norm, provider=provider) if provider else recent_norm
    payload: dict[str, Any] = {
        "adapter": "legacy_job_v1",
        "timezone": tz_name,
        "llm_provider": llm_provider,
        "filters": {
            "health": health,
            "provider": provider,
            "due_state": due_state,
            "enabled": enabled,
            "paused": paused,
            "runner": runner,
        },
        "summary": summarize_schedule_views(filtered),
        "summary_unfiltered": summarize_schedule_views(views),
        "filtered_count": len(filtered),
        "schedules": [v.to_dict() for v in filtered],
        "recent_runs": [r.to_dict() for r in runs],
        "note": (
            "Legacy jobs/runs exposed as scheduled work for AI Control Room. "
            "compatibility_mode=compatibility until native schedule model lands. "
            "Read-only adapter — does not change job execution or credentials. "
            "Grok/xAI model ids stay labeled provider=xai even when default LLM is OpenRouter."
        ),
    }
    if include_upcoming:
        payload["upcoming"] = build_upcoming_fires(
            filtered, days=upcoming_days, limit=50
        )
    return payload


@api_router.get("/api/schedules/upcoming")
async def list_schedule_upcoming(
    jobs: JobStore = Depends(get_job_store),
    settings: Settings = Depends(get_settings),
    days: float = Query(default=7.0, ge=0.0, le=60.0),
    limit: int = Query(default=50, ge=1, le=200),
    provider: str | None = Query(default=None),
    health: str | None = Query(default=None),
) -> dict[str, Any]:
    """ORCH-73: read-only upcoming fire calendar from legacy cron schedules."""
    from app.schedule.compat import (
        build_upcoming_fires,
        filter_schedule_views,
    )

    views, _, tz_name, _llm = await _build_schedule_context(
        jobs, settings, run_history_limit=1
    )
    views = filter_schedule_views(views, provider=provider, health=health)
    upcoming = build_upcoming_fires(views, days=days, limit=limit)
    return {
        "adapter": "legacy_job_v1",
        "timezone": tz_name,
        "days": days,
        "read_only": True,
        "upcoming": upcoming,
        "count": len(upcoming),
        "note": "Projected fires only — does not dispatch jobs.",
    }


@api_router.get("/api/schedules/runs")
async def list_schedule_runs(
    jobs: JobStore = Depends(get_job_store),
    settings: Settings = Depends(get_settings),
    limit: int = Query(default=50, ge=1, le=200),
    job_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    provider: str | None = Query(default=None),
) -> dict[str, Any]:
    """ORCH-73: normalized scheduled-run history (read-only)."""
    from app.schedule.compat import filter_run_views, list_normalized_runs

    llm_provider = (settings.llm_provider or "openrouter").strip().lower()
    names = await jobs.list_job_names()
    if job_id:
        job = await jobs.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Schedule/job not found")
        raw = await jobs.list_runs(job_id, limit=limit)
    else:
        raw = await jobs.recent_runs(limit=limit)
    normalized = list_normalized_runs(raw, job_names=names, default_provider=llm_provider)
    filtered = filter_run_views(
        normalized, status=status, provider=provider, schedule_id=job_id
    )
    return {
        "adapter": "legacy_job_v1",
        "llm_provider": llm_provider,
        "count": len(filtered),
        "runs": [r.to_dict() for r in filtered],
    }


@api_router.get("/api/schedules/{schedule_id}")
async def get_schedule_detail(
    schedule_id: str,
    jobs: JobStore = Depends(get_job_store),
    settings: Settings = Depends(get_settings),
    run_history_limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """ORCH-73: single schedule compatibility descriptor + recent normalized runs."""
    from app.schedule.compat import compatibility_for_job, list_normalized_runs

    job = await jobs.get_job(schedule_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule/job not found")
    hist = await jobs.list_runs(schedule_id, limit=run_history_limit)
    lr = hist[0] if hist else None
    provider = (settings.llm_provider or "openrouter").strip().lower()
    tz_name = settings.tz or "UTC"
    view = compatibility_for_job(
        job,
        llm_provider=provider,
        tz_name=tz_name,
        last_run=lr,
        recent_runs=hist,
    )
    names = {schedule_id: job.name}
    runs = list_normalized_runs(hist, job_names=names, default_provider=provider)
    return {
        "adapter": "legacy_job_v1",
        "timezone": tz_name,
        "llm_provider": provider,
        "schedule": view.to_dict(),
        "runs": [r.to_dict() for r in runs],
    }
@api_router.get("/api/ceo/presence")
async def ceo_presence(
    avatar_state: str | None = Query(default=None),
    display_mode: str | None = Query(default=None),
    subtitles: str | None = Query(default=None),
    subtitle_language: str | None = Query(default=None),
    subtitle_size: str | None = Query(default=None),
    only_while_speaking: str | None = Query(default=None),
) -> dict[str, Any]:
    """ORCH-72 CEO presence snapshot (mock mission-aware)."""
    from app.ceo.presence import build_presence_snapshot

    subs = True
    if subtitles is not None:
        subs = str(subtitles).strip().lower() in {"1", "true", "yes", "on"}
    ows = False
    if only_while_speaking is not None:
        ows = str(only_while_speaking).strip().lower() in {"1", "true", "yes", "on"}
    return build_presence_snapshot(
        avatar_state=avatar_state,
        display_mode=display_mode or "calm",
        subtitles_enabled=subs,
        subtitle_language=subtitle_language or "en",
        subtitle_size=subtitle_size or "md",
        only_while_speaking=ows,
        mock=True,
    )


class CeoMissionStartBody(BaseModel):
    brief: str
    mission_id: str | None = None


class CeoMissionActionBody(BaseModel):
    mission_id: str | None = None
    reason: str | None = None


class CeoSubtitlePrefsBody(BaseModel):
    enabled: bool | None = None
    language: str | None = None
    size: str | None = None
    only_while_speaking: bool | None = None


@api_router.post("/api/ceo/missions")
async def ceo_start_mission(body: CeoMissionStartBody) -> dict[str, Any]:
    """Start a mock mission (no live agent execution)."""
    from app.ceo.mission_mock import get_mock_mission_store
    from app.ceo.presence import build_presence_snapshot

    store = get_mock_mission_store()
    try:
        m = store.start(body.brief, mission_id=body.mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "mission_id": m.mission_id,
        "status": m.status,
        "brief": m.brief,
        "presence": build_presence_snapshot(store=store, mock=True),
    }


@api_router.post("/api/ceo/missions/pause")
async def ceo_pause_mission(body: CeoMissionActionBody | None = None) -> dict[str, Any]:
    from app.ceo.mission_mock import get_mock_mission_store
    from app.ceo.presence import build_presence_snapshot

    store = get_mock_mission_store()
    mid = body.mission_id if body else None
    try:
        m = store.pause(mid)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"mission_id": m.mission_id, "status": m.status, "presence": build_presence_snapshot(store=store)}


@api_router.post("/api/ceo/missions/resume")
async def ceo_resume_mission(body: CeoMissionActionBody | None = None) -> dict[str, Any]:
    from app.ceo.mission_mock import get_mock_mission_store
    from app.ceo.presence import build_presence_snapshot

    store = get_mock_mission_store()
    mid = body.mission_id if body else None
    try:
        m = store.resume(mid)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"mission_id": m.mission_id, "status": m.status, "presence": build_presence_snapshot(store=store)}


@api_router.post("/api/ceo/missions/stop")
async def ceo_stop_mission(body: CeoMissionActionBody | None = None) -> dict[str, Any]:
    from app.ceo.mission_mock import get_mock_mission_store
    from app.ceo.presence import build_presence_snapshot

    store = get_mock_mission_store()
    mid = body.mission_id if body else None
    reason = (body.reason if body else None) or "ceo_stopped"
    try:
        m = store.stop(mid, reason=reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"mission_id": m.mission_id, "status": m.status, "presence": build_presence_snapshot(store=store)}


@api_router.get("/api/ceo/progress")
async def ceo_progress_drawer(
    mission_id: str | None = Query(default=None),
) -> dict[str, Any]:
    from app.ceo.mission_mock import get_mock_mission_store

    return get_mock_mission_store().progress_drawer(mission_id)


@api_router.get("/api/ceo/preview")
async def ceo_preview(mission_id: str | None = Query(default=None)) -> dict[str, Any]:
    from app.ceo.mission_mock import get_mock_mission_store

    return get_mock_mission_store().preview(mission_id)


@api_router.get("/api/ceo/subtitles")
async def ceo_get_subtitle_defaults() -> dict[str, Any]:
    from app.ceo.subtitles import SubtitlePrefs

    return SubtitlePrefs().to_dict()


@api_router.post("/api/ceo/subtitles")
async def ceo_validate_subtitle_prefs(body: CeoSubtitlePrefsBody) -> dict[str, Any]:
    """Normalize/validate subtitle prefs (client persists; server is source of allowlists)."""
    from app.ceo.subtitles import normalize_subtitle_prefs

    prefs = normalize_subtitle_prefs(
        enabled=body.enabled,
        language=body.language,
        size=body.size,
        only_while_speaking=body.only_while_speaking,
    )
    return prefs.to_dict()


@api_router.get("/api/dashboard/overview")
async def dashboard_overview(
    request: Request,
    token_provider: TokenProvider = Depends(get_token_provider),
    llm: LlmProvider = Depends(get_llm),
    jobs: JobStore = Depends(get_job_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    from app.schedule.compat import (
        build_upcoming_fires,
        compatibility_for_job,
        list_normalized_runs,
        list_scheduled_work,
    )
    from app.schedule_util import schedule_info

    auth = await token_provider.status()
    llm_status = await llm.status()
    db = request.app.state.db_provider
    db_status = await database_health(db)
    mem_counts = await _memory_counts(request, jobs)
    herdr_summary = await _herdr_summary(settings)
    last = await jobs.last_run_any()
    items = await jobs.list_jobs()
    names = await jobs.list_job_names()
    models = await _model_catalog(settings, llm)
    tz_name = settings.tz or "UTC"
    llm_provider = (settings.llm_provider or "openrouter").strip().lower()
    last_runs: dict[str, Any] = {}
    runs_by_job: dict[str, list[Any]] = {}
    job_rows: list[dict[str, Any]] = []
    for j in items:
        row = j.to_dict(include_memory=False)
        hist = await jobs.list_runs(j.id, limit=8)
        lr = hist[0] if hist else None
        if lr is not None:
            last_runs[j.id] = lr
            runs_by_job[j.id] = hist
        row["last_run"] = lr.to_dict() if lr else None
        sched = schedule_info(j.schedule, tz_name=tz_name)
        row["schedule_human"] = sched["human"]
        row["schedule_cron"] = sched["cron"]
        row["timezone"] = sched["timezone"]
        row["next_run_at"] = sched["next_run_at"]
        row["next_run_ts"] = sched["next_run_ts"]
        if not j.enabled:
            row["next_run_at"] = None
            row["next_run_ts"] = None
            row["schedule_human"] = f"Paused · {sched['human']}" if j.schedule else "Paused"
        sw = compatibility_for_job(
            j,
            llm_provider=llm_provider,
            tz_name=tz_name,
            last_run=lr,
            recent_runs=hist,
        )
        row["scheduled_work"] = sw.to_dict()
        job_rows.append(row)
    schedule_views = list_scheduled_work(
        items,
        llm_provider=llm_provider,
        tz_name=tz_name,
        last_runs=last_runs,
        runs_by_job=runs_by_job,
    )
    recent = await jobs.recent_runs(limit=100)
    recent_rows = []
    for r in recent:
        d = r.to_dict()
        d["job_name"] = names.get(r.job_id) or r.job_id[:8]
        recent_rows.append(d)
    recent_norm = list_normalized_runs(
        recent[:40], job_names=names, default_provider=llm_provider
    )
    return {
        "service_ok": True,
        "timezone": tz_name,
        "status": {
            "auth": auth.to_dict(),
            "llm": llm_status.to_dict(),
            "database": db_status.to_dict(),
            "memory": mem_counts,
            "herdr": herdr_summary,
            "last_run": last.to_dict() if last else None,
            "models": models,
            "scheduler_note": (
                "Next run is estimated from the task cron in the app timezone. "
                "Cloud Scheduler must match that cron for unattended runs. "
                "See GET /api/schedules for Control Room compatibility descriptors (ORCH-73)."
            ),
        },
        "jobs": job_rows,
        "schedules": [v.to_dict() for v in schedule_views],
        "schedule_runs": [r.to_dict() for r in recent_norm],
        "schedule_upcoming": build_upcoming_fires(schedule_views, days=7.0, limit=40),
        "recent_runs": recent_rows,
        "job_names": names,
    }

class DatabaseSettingsBody(BaseModel):
    provider: str | None = None  # sqlite | postgres | tencentdb (mysql legacy)
    tencentdb_host: str | None = None
    tencentdb_port: int | None = None
    tencentdb_user: str | None = None
    tencentdb_password: str | None = None
    tencentdb_database: str | None = None
    tencentdb_ssl_mode: str | None = None
    postgres_host: str | None = None
    postgres_port: int | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_database: str | None = None
    postgres_ssl_mode: str | None = None


class MemoryCreateBody(BaseModel):
    scope: str  # shared | private
    body: str
    title: str = ""
    project_id: str = "default"
    owner_agent_id: str | None = None
    actor_agent_id: str = "scheduler-worker"


class MemoryUpdateBody(BaseModel):
    body: str | None = None
    title: str | None = None
    actor_agent_id: str = "scheduler-worker"


class MemoryAclBody(BaseModel):
    target_agent_id: str
    can_read: bool = True
    can_write: bool = False
    actor_agent_id: str = "scheduler-worker"


class AgentCreateBody(BaseModel):
    name: str
    agent_type: str = "scheduler_worker"
    project_id: str = "default"


@api_router.get("/api/settings/database")
async def get_database_settings(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    from app.persistence.config_validation import validate_database_settings
    from app.persistence.contract import PERSISTENCE_CONTRACT
    from app.persistence.migrate import migration_plan

    db = request.app.state.db_provider
    health = await database_health(db)
    validation = validate_database_settings(settings)
    return {
        "provider": (settings.database_provider or "sqlite").lower(),
        "strict": bool(settings.database_strict),
        "sqlite_path": str(settings.database_path_resolved),
        "postgres": {
            "host": settings.postgres_host or "",
            "port": settings.postgres_port,
            "user": settings.postgres_user or "",
            "database": settings.postgres_database or "",
            "ssl_mode": settings.postgres_ssl_mode or "",
            "password_set": bool((settings.postgres_password or "").strip()),
            "pgvector_required": bool(settings.postgres_pgvector_required),
            "migrate_on_startup": bool(settings.postgres_migrate_on_startup),
        },
        "tencentdb": {
            "host": settings.tencentdb_host or "",
            "port": settings.tencentdb_port,
            "user": settings.tencentdb_user or "",
            "database": settings.tencentdb_database or "",
            "ssl_mode": settings.tencentdb_ssl_mode or "",
            "password_set": bool((settings.tencentdb_password or "").strip()),
            "legacy": True,
        },
        "validation": validation.to_dict(),
        "platform_dialect": getattr(request.app.state, "platform_dialect", None),
        "app_data_dialect": getattr(request.app.state, "app_data_dialect", None),
        "migration_summary": getattr(request.app.state, "migration_summary", None),
        "migration_plan": migration_plan(),
        "contract": PERSISTENCE_CONTRACT.to_dict(),
        "status": health.to_dict(),
        "note": (
            "Default app data remains SQLite. Control Room durable store target is "
            "PostgreSQL + pgvector (ORCH-69 / D-007). MySQL/TencentDB-MySQL is legacy-frozen."
        ),
    }


@api_router.get("/api/persistence/contract")
async def get_persistence_contract(request: Request) -> dict[str, Any]:
    """Stable contract other Control Room agents should build against (ORCH-69)."""
    from app.persistence.contract import PERSISTENCE_CONTRACT

    return {
        "contract": PERSISTENCE_CONTRACT.to_dict(),
        "platform_dialect": getattr(request.app.state, "platform_dialect", None),
        "app_data_dialect": getattr(request.app.state, "app_data_dialect", None),
        "migration_summary": getattr(request.app.state, "migration_summary", None),
    }


@api_router.get("/api/tenancy/status")
async def tenancy_status(request: Request) -> dict[str, Any]:
    """Tenancy readiness: bootstrap org when platform Postgres + migrations applied."""
    from app.persistence.contract import PERSISTENCE_CONTRACT
    from app.tenancy.errors import TenantNotFound

    store = getattr(request.app.state, "tenancy_store", None)
    payload: dict[str, Any] = {
        "enabled": store is not None,
        "platform_dialect": getattr(request.app.state, "platform_dialect", None),
        "contract_version": PERSISTENCE_CONTRACT.version,
        "roles": list(PERSISTENCE_CONTRACT.member_roles),
        "bootstrap_org": None,
        "note": (
            "TenancyStore attaches when DATABASE_PROVIDER=postgres after connect. "
            "Apply migration 002_tenancy_organizations.sql on the platform DB."
        ),
    }
    if store is None:
        return payload
    try:
        org = await store.get_bootstrap_org()
        payload["bootstrap_org"] = org.to_dict()
    except TenantNotFound as exc:
        payload["error"] = str(exc)
    except Exception as exc:
        payload["error"] = str(exc)[:300]
    return payload


@api_router.put("/api/settings/database")
async def put_database_settings(
    body: DatabaseSettingsBody,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if body.provider is not None:
        p = body.provider.strip().lower()
        allowed = {
            "sqlite",
            "postgres",
            "postgresql",
            "pg",
            "tencentdb-postgres",
            "tencentdb",
            "mysql",
            "tencentdb-mysql",
        }
        if p not in allowed:
            raise HTTPException(
                status_code=400,
                detail="provider must be sqlite, postgres, or tencentdb (mysql legacy)",
            )
        if p in ("postgres", "postgresql", "pg", "tencentdb-postgres"):
            updates["database_provider"] = "postgres"
        elif p in ("tencentdb", "mysql", "tencentdb-mysql"):
            updates["database_provider"] = "tencentdb"
        else:
            updates["database_provider"] = "sqlite"
    if body.tencentdb_host is not None:
        updates["tencentdb_host"] = body.tencentdb_host.strip()
    if body.tencentdb_port is not None:
        updates["tencentdb_port"] = int(body.tencentdb_port)
    if body.tencentdb_user is not None:
        updates["tencentdb_user"] = body.tencentdb_user.strip()
    if body.tencentdb_password is not None:
        updates["tencentdb_password"] = body.tencentdb_password
    if body.tencentdb_database is not None:
        updates["tencentdb_database"] = body.tencentdb_database.strip()
    if body.tencentdb_ssl_mode is not None:
        updates["tencentdb_ssl_mode"] = body.tencentdb_ssl_mode.strip()
    if body.postgres_host is not None:
        updates["postgres_host"] = body.postgres_host.strip()
    if body.postgres_port is not None:
        updates["postgres_port"] = int(body.postgres_port)
    if body.postgres_user is not None:
        updates["postgres_user"] = body.postgres_user.strip()
    if body.postgres_password is not None:
        updates["postgres_password"] = body.postgres_password
    if body.postgres_database is not None:
        updates["postgres_database"] = body.postgres_database.strip()
    if body.postgres_ssl_mode is not None:
        updates["postgres_ssl_mode"] = body.postgres_ssl_mode.strip()
    try:
        settings.apply_updates(updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.app.state.settings = settings
    return await get_database_settings(request, settings)


@api_router.post("/api/settings/database/test")
async def test_database_settings(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    provider = (settings.database_provider or "sqlite").lower()
    if provider in ("postgres", "postgresql", "pg", "tencentdb-postgres") and (
        settings.postgres_host or ""
    ).strip():
        from app.persistence.postgres_provider import (
            PostgresConfig,
            test_postgres_connection,
        )

        return (
            await test_postgres_connection(
                PostgresConfig(
                    host=settings.postgres_host,
                    port=int(settings.postgres_port or 5432),
                    user=settings.postgres_user or "",
                    password=settings.postgres_password or "",
                    database=settings.postgres_database or "",
                    ssl_mode=settings.postgres_ssl_mode or "require",
                )
            )
        ).to_dict()
    if provider in ("tencentdb", "mysql", "tencentdb-mysql") and (settings.tencentdb_host or "").strip():
        from app.persistence.mysql_provider import (
            MysqlConfig,
            test_tencentdb_connection,
        )

        return (
            await test_tencentdb_connection(
                MysqlConfig(
                    host=settings.tencentdb_host,
                    port=int(settings.tencentdb_port or 3306),
                    user=settings.tencentdb_user or "",
                    password=settings.tencentdb_password or "",
                    database=settings.tencentdb_database or "",
                    ssl_mode=settings.tencentdb_ssl_mode or "PREFERRED",
                )
            )
        ).to_dict()
    db = request.app.state.db_provider
    health = await database_health(db)
    return health.to_dict()


@api_router.get("/api/agents")
async def list_agents(request: Request) -> dict[str, Any]:
    reg = request.app.state.agent_registry
    agents = await reg.list_agents()
    return {"agents": [a.to_dict() for a in agents], "types": reg.list_types()}


@api_router.post("/api/agents")
async def create_agent(body: AgentCreateBody, request: Request) -> dict[str, Any]:
    reg = request.app.state.agent_registry
    try:
        agent = await reg.create_agent(
            name=body.name,
            agent_type=body.agent_type,
            project_id=body.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"agent": agent.to_dict()}


@api_router.get("/api/memories")
async def list_memories(
    request: Request,
    actor_agent_id: str = Query(default="scheduler-worker"),
    scope: str | None = Query(default=None),
    project_id: str = Query(default="default"),
) -> dict[str, Any]:
    store = request.app.state.memory_store
    items = await store.list_for_agent(
        actor_agent_id=actor_agent_id, project_id=project_id, scope=scope
    )
    return {"memories": [m.to_dict() for m in items]}


@api_router.post("/api/memories")
async def create_memory(body: MemoryCreateBody, request: Request) -> dict[str, Any]:
    store = request.app.state.memory_store
    try:
        mem = await store.create(
            scope=body.scope,
            body=body.body,
            title=body.title,
            project_id=body.project_id,
            owner_agent_id=body.owner_agent_id,
            actor_agent_id=body.actor_agent_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"memory": mem.to_dict()}


@api_router.patch("/api/memories/{memory_id}")
async def patch_memory(
    memory_id: str, body: MemoryUpdateBody, request: Request
) -> dict[str, Any]:
    store = request.app.state.memory_store
    try:
        mem = await store.update(
            memory_id,
            actor_agent_id=body.actor_agent_id,
            body=body.body,
            title=body.title,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Memory not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"memory": mem.to_dict()}


@api_router.put("/api/memories/{memory_id}/acl")
async def put_memory_acl(
    memory_id: str, body: MemoryAclBody, request: Request
) -> dict[str, Any]:
    store = request.app.state.memory_store
    try:
        await store.set_acl(
            memory_id,
            actor_agent_id=body.actor_agent_id,
            target_agent_id=body.target_agent_id,
            can_read=body.can_read,
            can_write=body.can_write,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Memory not found") from None
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@api_router.get("/api/runs/{run_id}/messages")
async def list_run_messages(run_id: str, request: Request) -> dict[str, Any]:
    jobs: JobStore = request.app.state.job_store
    run = await jobs.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    store = request.app.state.message_store
    msgs = await store.list_for_run(run_id)
    return {"messages": [m.to_dict() for m in msgs]}


@api_router.get("/api/settings/notifications")
async def notification_settings(
    settings: Settings = Depends(get_settings),
    diag=Depends(get_notify_diag),
) -> dict[str, Any]:
    """Public status only — never returns webhook URL or secrets."""
    snap = await diag.snapshot(
        slack_configured=settings.slack_configured,
        email_configured=settings.email_configured,
    )
    snap["slack_mode"] = settings.slack_mode
    snap["slack_channel"] = (settings.slack_channel or "").strip() or None
    snap["slack_workspace"] = (settings.slack_workspace or "").strip() or None
    return {
        "notifications": snap,
        "defaults": {
            "slack_on_success": False,
            "slack_on_failure": True,
        },
        "help": {
            "slack": (
                "Preferred: SLACK_BOT_TOKEN (xoxb-...) + SLACK_CHANNEL (#all-ai-berk). "
                "Optional fallback: SLACK_WEBHOOK_URL. Secrets never shown in the dashboard."
            ),
        },
    }


@api_router.post("/api/settings/slack/test")
async def slack_test_notification(
    settings: Settings = Depends(get_settings),
    diag=Depends(get_notify_diag),
) -> dict[str, Any]:
    """Send a safe test message. Available only when Slack bot or webhook is configured."""
    from app.notify.slack import (
        build_run_slack_payload,
        redact_secret,
        redact_webhook_url,
        send_slack_payload,
    )

    if not settings.slack_configured:
        raise HTTPException(
            status_code=400,
            detail=(
                "Slack is not configured. Add SLACK_BOT_TOKEN + SLACK_CHANNEL "
                "(or SLACK_WEBHOOK_URL) on the server first."
            ),
        )
    payload = build_run_slack_payload(
        job_name="Slack test",
        status="succeeded",
        run_id="test-notification",
        started_at=__import__("time").time(),
        result="Test notification from Agent Orchestrator. If you see this, Slack is working.",
        error=None,
        history_url=(settings.public_base_url or "").rstrip("/") + "/history"
        if settings.public_base_url
        else None,
    )
    result = await send_slack_payload(settings, payload)
    await diag.record_slack(
        configured=True,
        ok=result.ok,
        diagnostic=result.diagnostic,
    )
    ref = (
        f"bot:{redact_secret(settings.slack_bot_token, kind='bot')}→{settings.slack_channel}"
        if result.mode == "bot"
        else redact_webhook_url(settings.slack_webhook_url)
    )
    return {
        "ok": result.ok,
        "diagnostic": result.diagnostic,
        "mode": result.mode,
        "target_ref": ref,
    }


@api_router.get("/api/runs")
async def list_all_runs(
    jobs: JobStore = Depends(get_job_store),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    names = await jobs.list_job_names()
    runs = await jobs.recent_runs(limit=limit)
    out = []
    for r in runs:
        d = r.to_dict()
        d["job_name"] = names.get(r.job_id) or r.job_id[:8]
        out.append(d)
    return {"runs": out}


@api_router.get("/api/runs/{run_id}")
async def get_run_detail(
    run_id: str,
    jobs: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    run = await jobs.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    names = await jobs.list_job_names()
    d = run.to_dict()
    d["job_name"] = names.get(run.job_id) or run.job_id[:8]
    return {"run": d}


@api_router.get("/api/jobs")
async def list_jobs(jobs: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    items = await jobs.list_jobs()
    return {"jobs": [j.to_dict(include_memory=False) for j in items]}


@api_router.post("/api/jobs")
async def create_job(
    body: CreateJobBody,
    jobs: JobStore = Depends(get_job_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    model = body.model or settings.default_model
    runner = (body.runner or "llm").strip().lower()
    if runner not in ("llm", "herdr"):
        raise HTTPException(status_code=400, detail="runner must be llm or herdr")
    job = await jobs.create_job(
        name=body.name,
        prompt_template=body.prompt_template,
        model=model,
        model_mode=body.model_mode or "inherit",
        schedule=body.schedule,
        memory_doc=body.memory_doc,
        enabled=body.enabled,
        notify_email=body.notify_email,
        slack_on_success=body.slack_on_success,
        slack_on_failure=body.slack_on_failure,
        runner=runner,
        herdr_agent_kind=body.herdr_agent_kind or settings.herdr_default_kind,
        herdr_agent_name=body.herdr_agent_name or "",
        herdr_cwd=body.herdr_cwd or "",
        herdr_workspace_label=body.herdr_workspace_label or "",
        herdr_extra_args=body.herdr_extra_args,
    )
    return {"job": job.to_dict()}


@api_router.get("/api/jobs/{job_id}")
async def get_job(job_id: str, jobs: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    job = await jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": job.to_dict(include_memory=True)}


@api_router.patch("/api/jobs/{job_id}")
async def patch_job(
    job_id: str,
    body: UpdateJobBody,
    jobs: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    if body.runner is not None and body.runner.strip().lower() not in ("llm", "herdr"):
        raise HTTPException(status_code=400, detail="runner must be llm or herdr")
    try:
        job = await jobs.update_job(
            job_id,
            name=body.name,
            prompt_template=body.prompt_template,
            model=body.model,
            model_mode=body.model_mode,
            schedule=body.schedule,
            enabled=body.enabled,
            notify_email=body.notify_email,
            slack_on_success=body.slack_on_success,
            slack_on_failure=body.slack_on_failure,
            clear_schedule=body.clear_schedule,
            runner=body.runner,
            herdr_agent_kind=body.herdr_agent_kind,
            herdr_agent_name=body.herdr_agent_name,
            herdr_cwd=body.herdr_cwd,
            herdr_workspace_label=body.herdr_workspace_label,
            herdr_extra_args=body.herdr_extra_args,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found") from None
    return {"job": job.to_dict(include_memory=False)}


@api_router.get("/api/settings/herdr")
async def get_herdr_settings(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    from app.integrations.herdr import HerdrClient, HerdrConfig

    cfg = HerdrConfig.from_settings(settings)
    client = HerdrClient(cfg)
    st = await client.status()
    return {
        "enabled": cfg.enabled,
        "bin": cfg.bin,
        "session": cfg.session or None,
        "timeout_ms": cfg.timeout_ms,
        "default_kind": cfg.default_kind,
        "status": st,
    }


@api_router.post("/api/settings/herdr/test")
async def test_herdr_settings(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    from app.integrations.herdr import HerdrClient, HerdrConfig

    cfg = HerdrConfig.from_settings(settings)
    client = HerdrClient(cfg)
    st = await client.status()
    return {"ok": bool(st.get("available")), **st}


@api_router.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str, jobs: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    ok = await jobs.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "deleted": job_id}


@api_router.post("/api/jobs/{job_id}/run")
async def run_job(
    job_id: str,
    request: Request,
    runner: JobRunner = Depends(get_runner),
    idempotency_key: str | None = Query(default=None, alias="idempotency_key"),
) -> dict[str, Any]:
    header_key = request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
    key = idempotency_key or header_key
    try:
        run = await runner.run_job(job_id, idempotency_key=key)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found") from None
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"run": run.to_dict()}


@api_router.get("/api/jobs/{job_id}/runs")
async def list_runs(
    job_id: str,
    jobs: JobStore = Depends(get_job_store),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    job = await jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    runs = await jobs.list_runs(job_id, limit=limit)
    return {"runs": [r.to_dict() for r in runs]}


# --- ORCH-70: deterministic control plane (missions / budget / audit / workers) ---


class CreateMissionBody(BaseModel):
    title: str
    brief: str = ""
    org_id: str = "default"
    budget_limit_cents: int = Field(default=0, ge=0)
    deadline_at: float | None = None


class BudgetAmountBody(BaseModel):
    amount_cents: int = Field(ge=0)
    note: str = ""


class MissionEndBody(BaseModel):
    reason: str = ""
    commit_cents: int = Field(default=0, ge=0)
    note: str = ""


def _get_control_plane(request: Request):
    cp = getattr(request.app.state, "control_plane", None)
    if cp is None:
        raise HTTPException(status_code=503, detail="Control plane not initialized")
    return cp


def _get_executive_control_plane(request: Request):
    adapter = getattr(request.app.state, "executive_control_plane", None)
    if adapter is None:
        raise HTTPException(
            status_code=503,
            detail="Executive control-plane adapter not initialized",
        )
    return adapter


def _cp_http(exc: Exception) -> HTTPException:
    from app.control_plane.models import BudgetError, ControlPlaneError, TransitionError

    if isinstance(exc, BudgetError):
        return HTTPException(status_code=409, detail=exc.to_dict())
    if isinstance(exc, TransitionError):
        return HTTPException(status_code=409, detail=exc.to_dict())
    if isinstance(exc, ControlPlaneError):
        code = 404 if exc.code == "not_found" else 400
        return HTTPException(status_code=code, detail=exc.to_dict())
    return HTTPException(status_code=400, detail=str(exc))


@api_router.get("/api/control-plane/status")
async def control_plane_status(request: Request) -> dict[str, Any]:
    cp = _get_control_plane(request)
    await cp.ensure_ready()
    missions = await cp.list_missions(limit=200)
    by_status: dict[str, int] = {}
    for m in missions:
        by_status[m.status] = by_status.get(m.status, 0) + 1
    return {
        "ok": True,
        "service": "control_plane",
        "epic": "ORCH-70",
        "mission_count": len(missions),
        "by_status": by_status,
        "capabilities": {
            "mission_lifecycle": True,
            "hard_budget_checks": True,
            "audit_events": True,
            "public_event_contract_v1": True,
            "event_history": True,
            "event_stream": True,
            "worker_boundaries": True,
            "real_container_isolation": False,
            "secret_broker": False,
        },
        "note": (
            "Deterministic control plane slice. Does not execute legacy jobs or "
            "hold provider credentials. Worker isolation is logical-boundary only."
        ),
    }


@api_router.post("/api/control-plane/missions")
async def cp_create_mission(
    body: CreateMissionBody,
    request: Request,
) -> dict[str, Any]:
    cp = _get_control_plane(request)
    try:
        mission = await cp.create_mission(
            title=body.title,
            brief=body.brief,
            org_id=body.org_id,
            budget_limit_cents=body.budget_limit_cents,
            deadline_at=body.deadline_at,
            actor="api",
        )
    except Exception as exc:
        raise _cp_http(exc) from exc
    return {"mission": mission.to_dict()}


@api_router.get("/api/control-plane/missions")
async def cp_list_missions(
    request: Request,
    org_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    cp = _get_control_plane(request)
    items = await cp.list_missions(org_id=org_id, limit=limit)
    return {"missions": [m.to_dict() for m in items]}


@api_router.get("/api/control-plane/missions/{mission_id}")
async def cp_get_mission(mission_id: str, request: Request) -> dict[str, Any]:
    cp = _get_control_plane(request)
    detail = await cp.mission_detail(mission_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    return detail


@api_router.post("/api/control-plane/missions/{mission_id}/queue")
async def cp_queue_mission(mission_id: str, request: Request) -> dict[str, Any]:
    cp = _get_control_plane(request)
    try:
        mission = await cp.queue_mission(mission_id, actor="api")
    except Exception as exc:
        raise _cp_http(exc) from exc
    return {"mission": mission.to_dict()}


@api_router.post("/api/control-plane/missions/{mission_id}/start")
async def cp_start_mission(mission_id: str, request: Request) -> dict[str, Any]:
    cp = _get_control_plane(request)
    try:
        mission = await cp.start_mission(mission_id, actor="api")
    except Exception as exc:
        raise _cp_http(exc) from exc
    detail = await cp.mission_detail(mission_id)
    return detail or {"mission": mission.to_dict()}


@api_router.post("/api/control-plane/missions/{mission_id}/complete")
async def cp_complete_mission(
    mission_id: str,
    request: Request,
    body: MissionEndBody | None = None,
) -> dict[str, Any]:
    cp = _get_control_plane(request)
    body = body or MissionEndBody()
    try:
        mission = await cp.complete_mission(
            mission_id,
            actor="api",
            commit_cents=body.commit_cents,
            note=body.note,
        )
    except Exception as exc:
        raise _cp_http(exc) from exc
    return {"mission": mission.to_dict()}


@api_router.post("/api/control-plane/missions/{mission_id}/fail")
async def cp_fail_mission(
    mission_id: str,
    request: Request,
    body: MissionEndBody | None = None,
) -> dict[str, Any]:
    cp = _get_control_plane(request)
    body = body or MissionEndBody()
    try:
        mission = await cp.fail_mission(
            mission_id, actor="api", reason=body.reason or "failed"
        )
    except Exception as exc:
        raise _cp_http(exc) from exc
    return {"mission": mission.to_dict()}


@api_router.post("/api/control-plane/missions/{mission_id}/kill")
async def cp_kill_mission(
    mission_id: str,
    request: Request,
    body: MissionEndBody | None = None,
) -> dict[str, Any]:
    cp = _get_control_plane(request)
    body = body or MissionEndBody()
    try:
        mission = await cp.kill_mission(
            mission_id, actor="api", reason=body.reason or "killed"
        )
    except Exception as exc:
        raise _cp_http(exc) from exc
    return {"mission": mission.to_dict()}


@api_router.post("/api/control-plane/missions/{mission_id}/budget/reserve")
async def cp_reserve_budget(
    mission_id: str,
    body: BudgetAmountBody,
    request: Request,
) -> dict[str, Any]:
    cp = _get_control_plane(request)
    try:
        mission = await cp.reserve_budget(
            mission_id,
            amount_cents=body.amount_cents,
            actor="api",
            note=body.note,
        )
    except Exception as exc:
        raise _cp_http(exc) from exc
    return {"mission": mission.to_dict()}


@api_router.post("/api/control-plane/missions/{mission_id}/budget/commit")
async def cp_commit_budget(
    mission_id: str,
    body: BudgetAmountBody,
    request: Request,
) -> dict[str, Any]:
    cp = _get_control_plane(request)
    try:
        mission = await cp.commit_budget(
            mission_id,
            amount_cents=body.amount_cents,
            actor="api",
            note=body.note,
        )
    except Exception as exc:
        raise _cp_http(exc) from exc
    return {"mission": mission.to_dict()}


@api_router.post("/api/control-plane/missions/{mission_id}/budget/release")
async def cp_release_budget(
    mission_id: str,
    request: Request,
    body: BudgetAmountBody | None = None,
) -> dict[str, Any]:
    cp = _get_control_plane(request)
    amount = body.amount_cents if body else None
    note = body.note if body else ""
    try:
        mission = await cp.release_budget(
            mission_id, amount_cents=amount, actor="api", note=note
        )
    except Exception as exc:
        raise _cp_http(exc) from exc
    return {"mission": mission.to_dict()}


@api_router.get("/api/control-plane/missions/{mission_id}/audit")
async def cp_mission_audit(
    mission_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    cp = _get_control_plane(request)
    if await cp.get_mission(mission_id) is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    return {"audit": await cp.list_audit(mission_id=mission_id, limit=limit)}


@api_router.get("/api/control-plane/audit")
async def cp_global_audit(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    cp = _get_control_plane(request)
    return {"audit": await cp.list_audit(limit=limit)}


api_router.include_router(control_plane_event_router)


# --- ORCH-71 executive session API (no Prime / no provider keys) ---


class OpenExecutiveSessionBody(BaseModel):
    mission_id: str
    brief: str = ""
    confidence_target: int = 80
    session_id: str | None = None


class ExecutiveHandoffBody(BaseModel):
    packet: dict[str, Any]
    memory_scope: str = "team"


class ExecutiveEvidenceBody(BaseModel):
    kind: str = "artifact"
    weight: float = 1.0
    passed: bool | None = None
    summary: str = ""
    artifact_id: str | None = None


class ExecutiveSpecialistBody(BaseModel):
    role_name: str
    parent_instance_id: str | None = None


class ExecutiveTransitionBody(BaseModel):
    status: str
    reason: str | None = None


@api_router.post("/api/executive/sessions")
async def open_executive_session(
    body: OpenExecutiveSessionBody,
    registry: ExecutiveSessionRegistry = Depends(get_executive_registry),
) -> dict[str, Any]:
    try:
        session = registry.open_session(
            mission_id=body.mission_id,
            brief=body.brief,
            confidence_target=body.confidence_target,
            session_id=body.session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.snapshot()


@api_router.get("/api/executive/sessions")
async def list_executive_sessions(
    mission_id: str | None = Query(default=None),
    registry: ExecutiveSessionRegistry = Depends(get_executive_registry),
) -> dict[str, Any]:
    return {"sessions": registry.snapshot_all(mission_id=mission_id)}


@api_router.get("/api/executive/sessions/{session_id}")
async def get_executive_session(
    session_id: str,
    registry: ExecutiveSessionRegistry = Depends(get_executive_registry),
) -> dict[str, Any]:
    try:
        session = registry.require(session_id)
    except ExecutiveSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return session.snapshot()


@api_router.get("/api/executive/sessions/{session_id}/confidence")
async def get_executive_confidence(
    session_id: str,
    registry: ExecutiveSessionRegistry = Depends(get_executive_registry),
) -> dict[str, Any]:
    try:
        session = registry.require(session_id)
    except ExecutiveSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return session.confidence().to_dict()


@api_router.post("/api/executive/sessions/{session_id}/handoffs")
async def post_executive_handoff(
    session_id: str,
    body: ExecutiveHandoffBody,
    registry: ExecutiveSessionRegistry = Depends(get_executive_registry),
) -> dict[str, Any]:
    try:
        session = registry.require(session_id)
        row = await session.record_handoff(body.packet, memory_scope=body.memory_scope)
    except ExecutiveSessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (HandoffValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "handoff": row.to_dict(),
        "confidence": session.confidence().to_dict(),
        "snapshot": session.snapshot(),
    }


@api_router.get("/api/executive/sessions/{session_id}/handoffs")
async def list_executive_handoffs(
    session_id: str,
    memory_scope: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    registry: ExecutiveSessionRegistry = Depends(get_executive_registry),
) -> dict[str, Any]:
    try:
        session = registry.require(session_id)
        rows = await session.handoffs(memory_scope=memory_scope, limit=limit)
    except ExecutiveSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"handoffs": [r.to_dict() for r in rows]}


@api_router.post("/api/executive/sessions/{session_id}/evidence")
async def post_executive_evidence(
    session_id: str,
    body: ExecutiveEvidenceBody,
    registry: ExecutiveSessionRegistry = Depends(get_executive_registry),
) -> dict[str, Any]:
    try:
        session = registry.require(session_id)
        item = session.record_evidence(
            EvidenceItem(
                kind=body.kind,
                weight=body.weight,
                passed=body.passed,
                summary=body.summary,
                artifact_id=body.artifact_id,
            )
        )
    except ExecutiveSessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"evidence": item.to_dict(), "confidence": session.confidence().to_dict()}


@api_router.post("/api/executive/sessions/{session_id}/specialists")
async def post_executive_specialist(
    session_id: str,
    body: ExecutiveSpecialistBody,
    registry: ExecutiveSessionRegistry = Depends(get_executive_registry),
) -> dict[str, Any]:
    try:
        session = registry.require(session_id)
        ref = session.spawn_specialist(
            body.role_name, parent_instance_id=body.parent_instance_id
        )
    except ExecutiveSessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"specialist": ref.to_dict()}


@api_router.post("/api/executive/sessions/{session_id}/transition")
async def post_executive_transition(
    session_id: str,
    body: ExecutiveTransitionBody,
    registry: ExecutiveSessionRegistry = Depends(get_executive_registry),
) -> dict[str, Any]:
    try:
        session = registry.require(session_id)
        session.transition(body.status, reason=body.reason)  # type: ignore[arg-type]
    except ExecutiveSessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return session.snapshot()


@api_router.get("/api/executive/sessions/{session_id}/memory")
async def get_executive_scoped_memory(
    session_id: str,
    scope: str = Query(..., description="Memory scope e.g. team, company, run"),
    registry: ExecutiveSessionRegistry = Depends(get_executive_registry),
) -> dict[str, Any]:
    try:
        session = registry.require(session_id)
        items = session.memory_for_scope(scope)
    except ExecutiveSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"scope": scope, "items": items}


@api_router.get("/api/executive/missions/{mission_id}/handoffs")
async def list_mission_handoffs(
    mission_id: str,
    memory_scope: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    store=Depends(get_handoff_store),
) -> dict[str, Any]:
    try:
        rows = await store.list_for_mission(
            mission_id, memory_scope=memory_scope, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"mission_id": mission_id, "handoffs": [r.to_dict() for r in rows]}


class RuntimeOpenMissionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: str = ""
    confidence_target: int = 80
    execution_profile: Literal["standard", "bounded_test_v1"] = "standard"


class RuntimeSpawnBody(BaseModel):
    role_name: str
    parent_instance_id: str | None = None
    quality_mode: str = "balanced"
    remaining_budget_usd: float | None = None
    prior_failures: int = 0
    requires_tools: bool = False


class RuntimeRouteBody(BaseModel):
    task_summary: str
    quality_mode: str = "balanced"
    remaining_budget_usd: float | None = None
    prior_failures: int = 0
    requires_tools: bool = False


class RuntimeMessageBody(BaseModel):
    message: str = Field(min_length=1, max_length=16_000)


@api_router.get("/api/executive/runtime/health")
async def executive_runtime_health(
    runtime: ExecutiveRuntime = Depends(get_executive_runtime),
) -> dict[str, Any]:
    """Adapter health — Prime/OpenRouter stay non-live by default."""
    return await runtime.adapter_health()


@api_router.post("/api/executive/runtime/missions")
async def executive_runtime_open_mission(
    body: RuntimeOpenMissionBody,
    request: Request,
    runtime: ExecutiveRuntime = Depends(get_executive_runtime),
) -> dict[str, Any]:
    adapter = _get_executive_control_plane(request)
    mission_id = ""
    created = False
    try:
        cp_mission = await adapter.start_mission()
        mission_id = cp_mission.id
        created = True
        safe_brief = sanitize_private_input(body.brief) if body.brief.strip() else ""
        session = await runtime.open_mission(
            mission_id=mission_id,
            brief=safe_brief,
            confidence_target=body.confidence_target,
            execution_profile=body.execution_profile,
        )
    except PrimeUnavailableError as exc:
        await adapter.rollback_created_mission(mission_id, created=created)
        raise HTTPException(status_code=503, detail="Prime RPC is unavailable") from exc
    except PrimeRuntimeError as exc:
        await adapter.rollback_created_mission(mission_id, created=created)
        raise HTTPException(status_code=502, detail="Prime RPC session failed") from exc
    except ExecutiveControlPlaneIntegrationError as exc:
        await adapter.rollback_created_mission(mission_id, created=created)
        raise HTTPException(
            status_code=409,
            detail="Control-plane mission is not available",
        ) from exc
    except ExecutiveSafetyError as exc:
        await adapter.rollback_created_mission(mission_id, created=created)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        await adapter.rollback_created_mission(mission_id, created=created)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        await adapter.rollback_created_mission(mission_id, created=created)
        raise HTTPException(
            status_code=503,
            detail="Control-plane integration is unavailable",
        ) from exc
    snapshot = runtime.snapshot(session.session_id)
    snapshot["control_plane"] = {
        "mission_id": cp_mission.id,
        "status": cp_mission.status,
        "event_contract": "orch.control-plane.event",
        "event_contract_version": "1.0",
    }
    return snapshot


@api_router.post("/api/executive/runtime/sessions/{session_id}/specialists")
async def executive_runtime_spawn(
    session_id: str,
    body: RuntimeSpawnBody,
    runtime: ExecutiveRuntime = Depends(get_executive_runtime),
) -> dict[str, Any]:
    try:
        ref, prime_sess, decision = await runtime.spawn_specialist(
            session_id,
            role_name=body.role_name,
            parent_instance_id=body.parent_instance_id,
            quality_mode=body.quality_mode,
            remaining_budget_usd=body.remaining_budget_usd,
            prior_failures=body.prior_failures,
            requires_tools=body.requires_tools,
        )
    except ExecutiveSessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PrimeUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Prime RPC is unavailable") from exc
    except PrimeRuntimeError as exc:
        raise HTTPException(
            status_code=409, detail="Prime specialist dispatch is not enabled"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "specialist": ref.to_dict(),
        "prime_session": prime_sess.to_dict(),
        "route": decision.to_dict(),
        "snapshot": runtime.snapshot(session_id),
    }


@api_router.post("/api/executive/runtime/route")
async def executive_runtime_route(
    body: RuntimeRouteBody,
    runtime: ExecutiveRuntime = Depends(get_executive_runtime),
) -> dict[str, Any]:
    decision = await runtime.router.route(
        task_summary=body.task_summary,
        quality_mode=body.quality_mode,
        remaining_budget_usd=body.remaining_budget_usd,
        prior_failures=body.prior_failures,
        requires_tools=body.requires_tools,
    )
    return {"route": decision.to_dict(), "live_call": False}


@api_router.post("/api/executive/runtime/sessions/{session_id}/messages")
async def executive_runtime_message(
    session_id: str,
    body: RuntimeMessageBody,
    request: Request,
    runtime: ExecutiveRuntime = Depends(get_executive_runtime),
) -> dict[str, Any]:
    """One authenticated Prime executive turn; output is public-safe only."""

    try:
        turn = await runtime.send_message(session_id, message=body.message)
    except PrimeUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Prime RPC is unavailable") from exc
    except PrimeRuntimeError as exc:
        raise HTTPException(status_code=502, detail="Prime RPC turn failed") from exc
    except ExecutiveSessionError as exc:
        raise HTTPException(status_code=404, detail="Executive session not found") from exc
    except ExecutiveSafetyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    adapter = _get_executive_control_plane(request)
    mission_id = turn.get("snapshot", {}).get("mission_id")
    try:
        turn["event_publication"] = await adapter.publish_turn(
            turn.get("event_batch"),
            expected_mission_id=mission_id,
            expected_message_id=turn.get("message", {}).get("message_id"),
            expected_final_text=turn.get("message", {}).get("text"),
        )
    except ExecutiveControlPlaneIntegrationError as exc:
        raise HTTPException(
            status_code=502,
            detail="Executive event contract rejected",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Executive event persistence unavailable",
        ) from exc
    return turn


@api_router.post("/api/executive/runtime/sessions/{session_id}/stop")
async def executive_runtime_stop(
    session_id: str,
    request: Request,
    body: ExecutiveTransitionBody | None = None,
    runtime: ExecutiveRuntime = Depends(get_executive_runtime),
) -> dict[str, Any]:
    reason = (body.reason if body else None) or "ceo_stopped"
    status = (body.status if body else None) or "stopped"
    try:
        await runtime.stop_mission(session_id, reason=reason, status=status)
    except ExecutiveSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    snapshot = runtime.snapshot(session_id)
    adapter = _get_executive_control_plane(request)
    try:
        cp_mission = await adapter.end_mission(
            snapshot["mission_id"],
            status=status,
            reason=reason,
        )
        snapshot["control_plane"] = {
            "mission_id": snapshot["mission_id"],
            "status": cp_mission.status if cp_mission else "not_found",
            "synchronized": cp_mission is not None,
        }
    except Exception:  # noqa: BLE001 - Prime is stopped even if status sync fails
        snapshot["control_plane"] = {
            "mission_id": snapshot["mission_id"],
            "synchronized": False,
        }
    return snapshot


def build_router() -> APIRouter:
    root = APIRouter()
    root.include_router(router)
    root.include_router(public_router)
    root.include_router(api_router)
    try:
        from app.jarvis.public_routes import router as jarvis_public_router

        root.include_router(jarvis_public_router)
    except Exception:  # pragma: no cover - optional local module
        pass
    try:
        from app.jarvis.realtime_routes import router as jarvis_router

        root.include_router(jarvis_router)
        # Alias under /jarvis/api/jarvis/* so old bookmarks and the
        # berkkarabacak.com/jarvis path still reach the same handlers.
        root.include_router(jarvis_router, prefix="/jarvis")
    except Exception:  # pragma: no cover - optional local module
        pass
    try:
        from app.jarvis.settings_routes import router as jarvis_settings_router

        root.include_router(jarvis_settings_router)
        # Public Talk on / still posts to /api/jarvis/settings. Keep the
        # /jarvis prefix so the alias host can keep serving Talk there.
        root.include_router(jarvis_settings_router, prefix="/jarvis")
    except Exception:  # pragma: no cover - optional local module
        pass
    try:
        from app.jarvis.bridge_routes import router as bridge_router

        root.include_router(bridge_router)
    except Exception:  # pragma: no cover
        pass
    try:
        from app.jarvis.screen_routes import router as jarvis_screen_router

        root.include_router(jarvis_screen_router)
    except Exception:  # pragma: no cover
        pass
    return root
