from app.config import Settings
from app.llm.factory import resolve_model
from app.llm.openrouter import OPENROUTER_AUTO_MODEL


def test_resolve_model_auto_openrouter():
    s = Settings(
        LLM_PROVIDER="openrouter",
        LLM_MODEL_MODE="auto",
        DEFAULT_MODEL="openai/gpt-4.1-mini",
    )
    model, mode = resolve_model(settings=s, job_model="x", job_model_mode="inherit")
    assert mode == "auto"
    assert model == OPENROUTER_AUTO_MODEL


def test_resolve_model_job_fixed_override():
    s = Settings(
        LLM_PROVIDER="openrouter",
        LLM_MODEL_MODE="auto",
        DEFAULT_MODEL="openrouter/auto",
    )
    model, mode = resolve_model(
        settings=s,
        job_model="anthropic/claude-sonnet-4",
        job_model_mode="fixed",
    )
    assert mode == "fixed"
    assert model == "anthropic/claude-sonnet-4"


def test_resolve_model_fixed_online_marker_is_preserved_for_adapter():
    s = Settings(
        LLM_PROVIDER="openrouter",
        LLM_MODEL_MODE="auto",
        DEFAULT_MODEL="openrouter/auto",
    )
    model, mode = resolve_model(
        settings=s,
        job_model="openrouter/auto:online",
        job_model_mode="fixed",
    )
    assert mode == "fixed"
    assert model == "openrouter/auto:online"


def test_resolve_model_inherit_fixed():
    s = Settings(
        LLM_PROVIDER="openrouter",
        LLM_MODEL_MODE="fixed",
        DEFAULT_MODEL="openai/gpt-4.1-mini",
    )
    model, mode = resolve_model(settings=s, job_model="", job_model_mode="inherit")
    assert mode == "fixed"
    assert model == "openai/gpt-4.1-mini"
