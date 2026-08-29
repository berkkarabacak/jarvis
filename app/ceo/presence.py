from __future__ import annotations

from typing import Any, Literal

from app.ceo.mission_mock import MockMission, MockMissionStore, get_mock_mission_store
from app.ceo.subtitles import SubtitlePrefs, normalize_subtitle_prefs

AvatarState = Literal[
    "listening",
    "thinking",
    "speaking",
    "working",
    "blocked",
    "awaiting_ceo",
    "completed",
]

AVATAR_STATES: tuple[str, ...] = (
    "listening",
    "thinking",
    "speaking",
    "working",
    "blocked",
    "awaiting_ceo",
    "completed",
)

DisplayMode = Literal["calm", "subtitles", "cards", "ops"]

# Safe operational copy only — never model chain-of-thought.
_MOCK_NARRATIVE = {
    "objective": "Stand by for your first mission",
    "latest_verified_result": "Control room shell is online",
    "next_action": "Tell the executive what you want built",
    "stage": "idle",
    "blockers": [],
    "ceo_input_needed": True,
    "confidence": None,
    "budget": {"consumed_usd": None, "cap_usd": None, "currency": "USD"},
}


def build_presence_snapshot(
    *,
    avatar_state: str | None = None,
    display_mode: str = "calm",
    subtitles_enabled: bool = True,
    subtitle_language: str = "en",
    subtitle_size: str = "md",
    only_while_speaking: bool = False,
    mock: bool = True,
    store: MockMissionStore | None = None,
) -> dict[str, Any]:
    """CEO presence DTO for the calm home shell.

    Live missions will replace mock fields via the control-plane event stream
    (ORCH-69/70/71). This shape is stable so the UI can ship first.
    """
    mission_store = store or get_mock_mission_store()
    mission = mission_store.active()
    narrative, state, mission_id, teams = _narrative_from_mission(
        mission, avatar_state_override=avatar_state
    )
    mode = display_mode if display_mode in ("calm", "subtitles", "cards", "ops") else "calm"
    prefs = normalize_subtitle_prefs(
        enabled=subtitles_enabled,
        language=subtitle_language,
        size=subtitle_size,
        only_while_speaking=only_while_speaking,
    )
    status_line = _status_line(state, narrative)
    show_sub = prefs.enabled
    if prefs.only_while_speaking and state not in ("speaking", "listening"):
        show_sub = False
    subtitle = _subtitle_for(state, narrative, prefs) if show_sub else ""

    drawer = mission_store.progress_drawer(mission_id)
    preview = mission_store.preview(mission_id)

    return {
        "schema_version": 2,
        "source": "mock" if mock else "live",
        "live": False if mock else True,
        "mocked": bool(mock),
        "backend_dependency": "none" if mock else "control_plane",
        "avatar_state": state,
        "avatar_states": list(AVATAR_STATES),
        "status_line": status_line,
        "subtitle": subtitle,
        "subtitles_enabled": prefs.enabled,
        "subtitle_prefs": prefs.to_dict(),
        "display_mode": mode,
        "display_modes": ["calm", "subtitles", "cards", "ops"],
        "progress": narrative,
        "progress_drawer": drawer,
        "preview": preview,
        "controls": {
            "can_start": True,
            "can_pause": bool(mission and mission.status == "active"),
            "can_resume": bool(mission and mission.status == "paused"),
            "can_stop": bool(mission and mission.status in ("active", "paused")),
            "can_preview": True,
            "mock": True,
        },
        "teams_active": teams,
        "mission_id": mission_id,
        "mission_status": mission.status if mission else "idle",
        "safe_copy": True,
        "notes": (
            "Mock CEO presence for ORCH-72. "
            "Mission input/pause/stop/preview are local mocks — no live agent execution. "
            "Does not expose model chain-of-thought."
        ),
    }


def _narrative_from_mission(
    mission: MockMission | None,
    *,
    avatar_state_override: str | None,
) -> tuple[dict[str, Any], str, str | None, int]:
    if mission is None:
        state = (
            avatar_state_override
            if avatar_state_override in AVATAR_STATES
            else "listening"
        )
        return dict(_MOCK_NARRATIVE), state, None, 0

    state = (
        avatar_state_override
        if avatar_state_override in AVATAR_STATES
        else mission.avatar_state
    )
    if state not in AVATAR_STATES:
        state = mission.avatar_state
    blockers = ["Paused — resume when ready"] if mission.status == "paused" else []
    narrative = {
        "objective": mission.brief,
        "latest_verified_result": (
            mission.events[-1]["message"] if mission.events else "Mission accepted"
        ),
        "next_action": (
            "Resume or stop the mission"
            if mission.status == "paused"
            else "Watch progress or open preview"
        ),
        "stage": mission.status,
        "blockers": blockers,
        "ceo_input_needed": mission.status == "paused",
        "confidence": mission.confidence,
        "budget": {
            "consumed_usd": mission.budget_consumed_usd,
            "cap_usd": mission.budget_cap_usd,
            "currency": "USD",
        },
    }
    teams = 1 if mission.status == "active" else 0
    return narrative, state, mission.mission_id, teams


def _status_line(state: str, narrative: dict[str, Any]) -> str:
    objective = str(narrative.get("objective") or "Ready")
    if state == "listening":
        return f"Listening · {objective}"
    if state == "thinking":
        return f"Thinking · {objective}"
    if state == "speaking":
        return f"Speaking · {objective}"
    if state == "working":
        stage = narrative.get("stage") or "in progress"
        return f"Working · {stage}"
    if state == "blocked":
        blockers = narrative.get("blockers") or []
        detail = blockers[0] if blockers else "needs attention"
        return f"Blocked · {detail}"
    if state == "awaiting_ceo":
        return "Awaiting your decision"
    if state == "completed":
        return f"Completed · {narrative.get('latest_verified_result') or 'done'}"
    return objective


def _subtitle_for(
    state: str,
    narrative: dict[str, Any],
    prefs: SubtitlePrefs | None = None,
) -> str:
    # Language preference reserved for future i18n catalogs; English copy for now.
    _ = prefs
    if state == "speaking" or state == "listening":
        return str(narrative.get("next_action") or "")
    if state == "working":
        return str(narrative.get("latest_verified_result") or "")
    if state == "blocked" or state == "awaiting_ceo":
        return "Your input will unblock the company"
    if state == "completed":
        return str(narrative.get("latest_verified_result") or "Mission complete")
    if state == "thinking":
        return "Reviewing options…"
    return ""
