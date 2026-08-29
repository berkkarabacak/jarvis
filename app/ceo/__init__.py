"""CEO experience surfaces (ORCH-72). UI-first; live runtime wires in later."""

from app.ceo.mission_mock import MockMissionStore, get_mock_mission_store
from app.ceo.presence import AVATAR_STATES, build_presence_snapshot
from app.ceo.subtitles import SubtitlePrefs, normalize_subtitle_prefs

__all__ = ["AVATAR_STATES", "build_presence_snapshot"]
