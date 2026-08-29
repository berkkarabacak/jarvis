"""ORCH-371: see_screen runs vision now and never claims it is deferred."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

# 1x1 PNG
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_DESC = "Chrome is focused. Slack and File Explorer are open. The taskbar shows 14:02."
_FORBIDDEN = (
    "not_implemented_v1",
    "deferred",
    "no click/type automation yet",
)


def _assert_clean(blob: str) -> None:
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"forbidden {phrase!r} in {blob[:400]}"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "Jarvis"
    root.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(root))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8787")
    monkeypatch.delenv("PUBLIC_GUEST_PROFILE", raising=False)
    monkeypatch.delenv("JARVIS_PUBLIC_CLOUD", raising=False)
    return root


def _shot_dict(root: Path, *, include_b64: bool = True) -> dict:
    path = root / "Exports" / "screenshots" / "screen_test.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_PNG)
    rel = "Exports/screenshots/screen_test.png"
    out = {"ok": True, "path": rel, "bytes": len(_PNG)}
    if include_b64:
        out["png_base64_full"] = base64.b64encode(_PNG).decode("ascii")
    return out


@pytest.mark.asyncio
async def test_run_see_screen_fake_http_post(ws):
    from app.jarvis.screen_loop import run_see_screen

    async def fake_post():
        return {"choices": [{"message": {"content": _DESC}}]}

    result = await run_see_screen(
        _shot_dict(ws),
        workspace_root=ws,
        user_goal="",
        http_post=fake_post,
    )
    assert result.get("ok") is True
    assert result.get("vision_description") == _DESC
    assert result.get("vision_error") in (None, "")
    assert "proposal" not in result
    _assert_clean(json.dumps(result))


@pytest.mark.asyncio
async def test_run_see_screen_restores_png_from_file(ws):
    from app.jarvis.screen_loop import run_see_screen

    seen = {"bytes": 0}

    async def fake_post():
        return {"choices": [{"message": {"content": _DESC}}]}

    # no b64 on the result — vision must read the saved PNG
    shot = _shot_dict(ws, include_b64=False)
    assert "png_base64_full" not in shot

    # wrap vision to prove bytes were restored
    import app.jarvis.screen_loop as sl

    orig = sl.vision_describe_png

    async def wrapped(png_bytes, *, user_goal="", http_post=None):
        seen["bytes"] = len(png_bytes or b"")
        return await orig(png_bytes, user_goal=user_goal, http_post=http_post)

    sl.vision_describe_png = wrapped
    try:
        result = await run_see_screen(
            shot, workspace_root=ws, user_goal="", http_post=fake_post
        )
    finally:
        sl.vision_describe_png = orig

    assert seen["bytes"] == len(_PNG)
    assert result.get("vision_description") == _DESC
    _assert_clean(json.dumps(result))


@pytest.mark.asyncio
async def test_run_see_screen_vision_error_not_fake_success(ws):
    from app.jarvis.screen_loop import run_see_screen

    async def boom():
        raise TimeoutError("vision timed out")

    result = await run_see_screen(
        _shot_dict(ws),
        workspace_root=ws,
        user_goal="",
        http_post=boom,
    )
    assert result.get("ok") is False
    assert result.get("vision_error")
    assert "timed out" in result["vision_error"]
    assert not result.get("vision_description")
    _assert_clean(json.dumps(result))


def test_see_screen_tool_returns_vision_description(ws, monkeypatch):
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace
    import app.jarvis.tools as tools_mod
    import app.jarvis.screen_loop as sl

    def fake_shot(ctx, args):
        return _shot_dict(ctx.ws.root)

    async def fake_vision(png_bytes, *, user_goal="", http_post=None):
        assert png_bytes, "vision must receive png bytes"
        return _DESC

    monkeypatch.setattr(tools_mod, "_screenshot", fake_shot)
    monkeypatch.setattr(sl, "vision_describe_png", fake_vision)

    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    raw = run_tool(ctx, "see_screen", {})
    data = json.loads(raw)
    assert data.get("ok") is True, data
    assert data.get("vision_description") == _DESC
    assert data.get("vision_error") in (None, "")
    _assert_clean(raw)


@pytest.mark.asyncio
async def test_see_screen_runs_vision_inside_running_loop(ws, monkeypatch):
    """Live bug: loop.is_running() used to stub vision as 'deferred'."""
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace
    import app.jarvis.tools as tools_mod
    import app.jarvis.screen_loop as sl

    def fake_shot(ctx, args):
        return _shot_dict(ctx.ws.root)

    async def fake_vision(png_bytes, *, user_goal="", http_post=None):
        assert png_bytes
        return _DESC

    monkeypatch.setattr(tools_mod, "_screenshot", fake_shot)
    monkeypatch.setattr(sl, "vision_describe_png", fake_vision)

    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    raw = run_tool(ctx, "see_screen", {"goal": ""})
    data = json.loads(raw)
    assert data.get("ok") is True, data
    assert data.get("vision_description") == _DESC
    assert "deferred" not in raw.lower()
    _assert_clean(raw)


def test_proposal_to_dict_has_no_v1_unimplemented():
    from app.jarvis.screen_loop import ScreenProposal, build_proposal_from_vision

    p = build_proposal_from_vision(description=_DESC, user_goal="")
    blob = json.dumps(p.to_dict())
    _assert_clean(blob)
    assert p.to_dict()["description"] == _DESC
    assert p.to_dict()["needs_confirm"] is False

    p2 = ScreenProposal(
        proposal_id="prop_test",
        description=_DESC,
        proposed_action="click Start",
        needs_confirm=True,
    )
    _assert_clean(json.dumps(p2.to_dict()))


@pytest.mark.asyncio
async def test_run_see_screen_look_goal_has_no_confirm_proposal(ws):
    from app.jarvis.screen_loop import run_see_screen

    async def fake_post():
        return {"choices": [{"message": {"content": _DESC}}]}

    for goal in ("what do you see on the screen", "close the tab", "Switzerland news"):
        result = await run_see_screen(
            _shot_dict(ws),
            workspace_root=ws,
            user_goal=goal,
            http_post=fake_post,
        )
        assert result.get("ok") is True, goal
        assert result.get("needs_confirm") in (None, False), goal
        assert "proposal" not in result, goal
        blob = json.dumps(result).lower()
        assert "say confirm" not in blob, goal


def test_prompts_forbid_deferred_and_option_picking():
    from app.jarvis.agent import SYSTEM_PROMPT
    from app.jarvis.realtime import JARVIS_REALTIME_INSTRUCTIONS

    for text in (SYSTEM_PROMPT, JARVIS_REALTIME_INSTRUCTIONS):
        low = text.lower()
        assert "vision_description" in text
        assert "deferred" in low
        assert "never say vision is deferred" in low
        assert "wait / open / retry" in low or "wait/open/retry" in low
