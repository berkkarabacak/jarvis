from __future__ import annotations

from __future__ import annotations

from typing import TYPE_CHECKING

from app.llm.base import LlmProvider
from app.llm.openrouter import OPENROUTER_AUTO_MODEL, OpenRouterLlmProvider
from app.llm.xai import XaiLlmProvider

if TYPE_CHECKING:
    from app.auth.provider import TokenProvider
    from app.config import Settings


def build_llm_provider(settings: "Settings", token_provider: "TokenProvider") -> LlmProvider:
    provider = (settings.llm_provider or "openrouter").strip().lower()
    mode = (settings.llm_model_mode or "auto").strip().lower()
    if mode not in ("auto", "fixed"):
        mode = "auto"
    timeout = float(settings.llm_timeout_seconds or settings.grok_timeout_seconds or 600)

    if provider in ("xai", "grok"):
        return XaiLlmProvider(
            token_provider,
            timeout_seconds=timeout,
            default_model=settings.default_model,
            mode="fixed",
        )

    # Default: OpenRouter
    default_model = settings.default_model
    if mode == "auto":
        default_model = OPENROUTER_AUTO_MODEL
    return OpenRouterLlmProvider(
        settings.openrouter_api_key,
        timeout_seconds=timeout,
        default_model=default_model,
        mode=mode,
        site_url="https://aicontrolroom.nl/",
        app_title="Jarvis",
    )


def resolve_model(
    *,
    settings: "Settings",
    job_model: str | None,
    job_model_mode: str | None = None,
) -> tuple[str, str]:
    """Return (requested_model, mode) for a job run.

    Resolution: job override > global settings.
    mode: auto | fixed
    """
    global_mode = (settings.llm_model_mode or "auto").strip().lower()
    if global_mode not in ("auto", "fixed"):
        global_mode = "auto"

    mode = (job_model_mode or "inherit").strip().lower()
    if mode in ("", "inherit"):
        mode = global_mode
    if mode not in ("auto", "fixed"):
        mode = global_mode

    provider = (settings.llm_provider or "openrouter").strip().lower()

    if mode == "auto" and provider in ("openrouter", "or"):
        return OPENROUTER_AUTO_MODEL, "auto"

    # fixed
    model = (job_model or "").strip() or (settings.default_model or "").strip()
    if not model:
        if provider in ("openrouter", "or"):
            model = OPENROUTER_AUTO_MODEL
        else:
            model = "grok-4.5"
    return model, mode
