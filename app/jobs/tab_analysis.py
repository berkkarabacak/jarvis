"""Look+keys combined tab analysis as a first-class scheduled job (ORCH-393).

Uses the existing job clock only: job cron + POST /api/jobs/{id}/run.
The job definition carries the goal — a human does not POST the analysis text.
Live two-tab PASS on XPS13 is ORCH-394; this module is the scheduler path.
"""

from __future__ import annotations

import os
from typing import Any

from app.jarvis.agent import (
    LOOK_JOB_STOP_PROMPT,
    is_desktop_look_job,
    resolve_tool_rounds,
)

TAB_ANALYSIS_JOB_NAME = "tab-analysis"

# Sample sites are fine (ORCH-390). Words must come from pages actually seen.
TAB_ANALYSIS_GOAL = (
    "Open https://example.com with run_app. focus_app chrome. "
    "see_screen. keys ctrl+tab. see_screen. "
    "Return one combined analysis of the pages you actually saw. "
    "Do not invent headlines. Words must come from those pages."
)

# None = one-shot (fire via POST /run). Cron still uses the same /run clock.
ONESHOT_SCHEDULE: str | None = None
SHORT_DELAY_CRON = "* * * * *"

_COMBINED_NEEDLES = (
    "combined",
    "both pages",
    "both page",
    "all pages",
    "summarize both",
    "one combined",
    "pages you actually saw",
    "pages it actually saw",
)


def is_look_keys_combined_analysis(goal: str) -> bool:
    """True when the goal is a look+keys combined page-analysis task."""
    g = (goal or "").strip()
    if not is_desktop_look_job(g):
        return False
    low = g.lower()
    has_keys = "keys" in low or "ctrl+tab" in low or "ctrl+" in low
    has_combine = any(needle in low for needle in _COMBINED_NEEDLES)
    return has_keys and has_combine


def tab_analysis_job_payload(
    *,
    schedule: str | None = ONESHOT_SCHEDULE,
    name: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """POST /api/jobs body. Goal lives on the job — same runner as other jobs."""
    body: dict[str, Any] = {
        "name": name or TAB_ANALYSIS_JOB_NAME,
        "prompt_template": TAB_ANALYSIS_GOAL,
        "enabled": enabled,
        "runner": "llm",
        "slack_on_success": False,
        "slack_on_failure": True,
    }
    if schedule:
        body["schedule"] = schedule
    return body


async def invoke_desktop_look_goal(
    goal: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """Run a look+keys goal through Jarvis (same work as a live desktop turn).

    Tests replace this. Production needs JARVIS_ENABLED on the laptop host.
    Does not start a second scheduler.
    """
    from app.jarvis.agent import build_jarvis_agent
    from app.jarvis.guardrails import jarvis_tools_allowed

    text = (goal or "").strip()
    if not text:
        raise RuntimeError("Desktop look job goal is empty")
    if not is_desktop_look_job(text):
        raise RuntimeError("Goal is not a look+keys desktop job")
    if not jarvis_tools_allowed():
        raise RuntimeError(
            "Jarvis desktop tools are not enabled on this host (JARVIS_ENABLED). "
            "Tab analysis uses the existing job clock on the laptop, not a second scheduler."
        )

    key = (api_key or os.environ.get("OPENROUTER_API_KEY") or "").strip()
    agent = build_jarvis_agent(
        api_key=key,
        model=model,
        tool_source="job-scheduler",
        timeout_seconds=timeout_seconds,
        max_tool_rounds=resolve_tool_rounds(text),
        goal=text,
    )
    if agent is None:
        raise RuntimeError("Jarvis agent unavailable for desktop look job")

    bridged = text + "\n\n[Look policy] " + LOOK_JOB_STOP_PROMPT
    sess = await agent.start_session(role_name="job-scheduler")
    try:
        msg = await agent.send_message(sess.session_id, message=bridged)
    finally:
        await agent.stop_session(sess.session_id, reason="job_complete")

    result_text = (getattr(msg, "text", None) or "").strip()
    tools = list(getattr(agent, "_tools_called", []) or [])
    return {
        "text": result_text,
        "tools_called": tools,
        "model": getattr(agent, "_model", model),
    }
