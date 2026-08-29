"""ORCH-374: do not infer home_list on a screen-control job."""

from __future__ import annotations

from app.jarvis.bridge_routes import _infer_tool_from_goal

# Live failure shape: adjective "desktop job" + "see_screen shows" must not infer.
NTV_DESKTOP_JOB = (
    "Hard multi-step desktop job. Open https://www.ntv.com.tr. "
    "focus_app chrome. see_screen shows this chat. Name the headlines."
)


def test_screen_control_desktop_job_does_not_infer():
    assert _infer_tool_from_goal(NTV_DESKTOP_JOB) is None


def test_list_desktop_still_infers_home_list():
    inferred = _infer_tool_from_goal("list desktop")
    assert inferred == ("home_list", {"root": "Desktop", "path": "."})


def test_show_my_downloads_still_infers_home_list():
    inferred = _infer_tool_from_goal("show my downloads")
    assert inferred == ("home_list", {"root": "Downloads", "path": "."})


def test_desktop_job_alone_does_not_infer():
    """Adjective 'desktop job' is not a list-folder ask even without screen markers."""
    assert _infer_tool_from_goal("Hard multi-step desktop job") is None
