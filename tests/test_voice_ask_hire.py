"""Hire/create-many-files /ask: spawn_child first, then open. Not a screen fail."""

from __future__ import annotations

import sys

import pytest

from app.jarvis.virtual_pc import (
    goal_is_computer_job,
    goal_is_hire_job,
    goal_is_simple_talk,
    goal_is_virtual_pc_job,
    wants_screen_job,
)
from app.jarvis.voice_ask import (
    ASK_HIRE_MAX,
    ASK_TALK_MAX,
    HIRE_JOB_STOP_PROMPT,
    HIRE_WAVE_LINE,
    _HIRE_LOOKS,
    _SCREEN_FAIL,
    _child_file_goal,
    _ensure_hire_html_files,
    _hire_look,
    _sanitize_computer_agent_reply,
    _unique_game_html,
    _virtual_pc_ask_text,
    ask_text_max,
    empty_speech,
    ensure_spoken_reply,
    hire_fallback_reply,
    hire_start_line,
    recover_spawn_child_limit,
    run_voice_ask,
)

HIRE_TETRIS = (
    "Hire 10 OpenRouter children with spawn_child. "
    "Each writes a different pretty Tetris HTML and you open all 10 on this Linux PC."
)
CREATE_TEN_GAMES = "make 10 games and open them"
CREATE_FIVE_FILES = "create 5 html files"
CREATE_FIVE_TETRIS = (
    "Create five different Tetris games. Use sub-agents as much as you can."
)
WITH_HELPERS = "do this on the computer with helpers"


class _HireGateway:
    memory = None

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def clear_taint(self, *args, **kwargs):
        return None

    def run(self, name, args=None, *, source="ask", confirmed=False, max_auto=None):
        payload = dict(args or {})
        self.calls.append((name, payload))
        if name == "spawn_child":
            n = sum(1 for tool, _ in self.calls if tool == "spawn_child")
            return {"ok": True, "id": f"c_{n:08x}", "status": "running"}
        if name == "wait_child":
            cid = str((args or {}).get("id") or "c_1")
            try:
                n = int(cid.split("_")[-1], 16)
            except ValueError:
                n = 1
            return {
                "ok": True,
                "status": "done",
                "artifacts": [f"Exports/tetris_{n:02d}.html"],
            }
        return {"ok": True}


class _LimitOnceHireGateway(_HireGateway):
    """Third spawn_child is CHILD_LIMIT; later waves succeed."""

    def run(self, name, args=None, *, source="ask", confirmed=False, max_auto=None):
        payload = dict(args or {})
        self.calls.append((name, payload))
        if name == "spawn_child":
            n = sum(1 for tool, _ in self.calls if tool == "spawn_child")
            if n == 3:
                return {"ok": False, "error": "CHILD_LIMIT"}
            return {"ok": True, "id": f"c_{n:08x}", "status": "running"}
        if name == "wait_child":
            cid = str((args or {}).get("id") or "c_1")
            try:
                n = int(cid.split("_")[-1], 16)
            except ValueError:
                n = 1
            return {
                "ok": True,
                "status": "done",
                "artifacts": [f"Exports/tetris_{n:02d}.html"],
            }
        return {"ok": True}


def test_hire_tetris_is_a_hire_job_not_a_screen_look():
    assert goal_is_hire_job(HIRE_TETRIS) is True
    assert goal_is_simple_talk(HIRE_TETRIS) is False
    assert goal_is_computer_job(HIRE_TETRIS) is False
    assert goal_is_virtual_pc_job(HIRE_TETRIS) is False
    assert wants_screen_job(HIRE_TETRIS) is False


def test_create_n_goal_is_hire_without_saying_spawn_child():
    for goal in (CREATE_TEN_GAMES, CREATE_FIVE_FILES, WITH_HELPERS):
        assert "spawn_child" not in goal
        assert "hire" not in goal.lower()
        assert goal_is_hire_job(goal) is True, goal
        assert goal_is_simple_talk(goal) is False, goal
        assert goal_is_computer_job(goal) is False, goal
        assert wants_screen_job(goal) is False, goal
    assert ask_text_max(CREATE_TEN_GAMES) == ASK_HIRE_MAX
    assert ask_text_max("hello") == ASK_TALK_MAX


def test_hello_and_math_and_open_site_are_not_hire_jobs():
    assert goal_is_hire_job("hello") is False
    assert goal_is_hire_job("2+2") is False
    assert goal_is_hire_job("what is 5 plus 7") is False
    assert goal_is_simple_talk("hello") is True
    assert goal_is_hire_job("open cnn.com on this Linux PC") is False
    assert goal_is_hire_job("open the 2 files") is False
    assert goal_is_hire_job("what's on the screen") is False


def test_hire_ask_text_does_not_add_look_policy():
    from app.jarvis.agent import LOOK_JOB_STOP_PROMPT

    text = _virtual_pc_ask_text(HIRE_TETRIS)
    assert HIRE_JOB_STOP_PROMPT in text
    assert LOOK_JOB_STOP_PROMPT not in text
    assert "see_screen" in HIRE_JOB_STOP_PROMPT


def test_open_on_linux_pc_without_hire_is_still_a_computer_job():
    assert goal_is_computer_job("open cnn.com on this Linux PC") is True
    assert goal_is_hire_job("open cnn.com on this Linux PC") is False
    assert goal_is_computer_job("what's on the screen") is True


def test_ask_text_max_splits_hire_from_talk():
    assert ask_text_max("hello") == ASK_TALK_MAX
    assert ask_text_max(HIRE_TETRIS) == ASK_HIRE_MAX
    long_hire = HIRE_TETRIS + " " + ("blue neon theme. " * 40)
    assert len(long_hire) > ASK_TALK_MAX
    assert ask_text_max(long_hire) == ASK_HIRE_MAX


def test_ask_body_allows_long_hire_and_keeps_talk_at_400():
    from pydantic import ValidationError

    from app.jarvis.realtime_routes import AskBody

    long_hire = HIRE_TETRIS + " variant notes: " + ("red. " * 80)
    assert len(long_hire) > ASK_TALK_MAX
    assert AskBody(text=long_hire).text == long_hire
    with pytest.raises(ValidationError):
        AskBody(text=("hello there " * 50).strip())


@pytest.fixture
def hire_ws(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    (ws / "Exports").mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    return ws


def _patch_hire_desktop(monkeypatch, opened: list[dict]) -> None:
    from app.jarvis import computer as computer_mod

    monkeypatch.setattr(
        computer_mod,
        "linux_run_app",
        lambda plan: opened.append(plan) or {"ok": True, "started": "x"},
    )
    monkeypatch.setattr(
        computer_mod,
        "linux_close_chrome_windows",
        lambda app="chrome": {"ok": True},
    )
    monkeypatch.setattr(
        computer_mod,
        "stage_file_on_computer",
        lambda host, dest: {"ok": True, "dest": dest},
    )
    monkeypatch.setattr(
        "app.jarvis.voice_ask._look_now",
        lambda asked, **k: {
            "ok": True,
            "vision_description": "A Tetris board with a score and playfield",
        },
    )


@pytest.mark.asyncio
async def test_hire_ten_children_tetris_uses_spawn_child(hire_ws, monkeypatch):
    gw = _HireGateway()
    opened: list[dict] = []
    agent_calls: list[str] = []

    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: gw)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    _patch_hire_desktop(monkeypatch, opened)
    monkeypatch.setattr(
        "app.jarvis.agent.build_jarvis_agent",
        lambda **kwargs: agent_calls.append("agent") or None,
    )

    body = await run_voice_ask(HIRE_TETRIS)
    names = [n for n, _ in gw.calls]
    spawn_n = names.count("spawn_child")
    assert spawn_n == 10
    assert names.count("wait_child") == 10
    wave_ids = {payload.get("parent_job_id") for tool, payload in gw.calls if tool == "spawn_child"}
    assert len(wave_ids) >= 3
    assert "spawn_child" in body["tools_used"]
    assert body["tools_used"][0] == "spawn_child"
    assert body["ok"] is True
    assert body["reply"] != _SCREEN_FAIL
    assert "Could not do that on the screen." not in body["reply"]
    assert body["tools_used"].index("spawn_child") < body["tools_used"].index("run_app")
    assert agent_calls == []
    assert len(opened) == 10
    for plan in opened:
        url = str(plan.get("url") or "")
        argv = " ".join(str(x) for x in (plan.get("argv") or []))
        assert url.startswith("file:///"), plan
        assert "/home/jarvis/Exports/tetris_" in url
        assert url.endswith(".html")
        assert "file://exports/" not in url.lower()
        assert not url.lower().startswith("exports/")
        assert "thunar" not in argv.lower()


@pytest.mark.asyncio
async def test_hire_run_app_uses_file_url_not_exports_host(hire_ws, monkeypatch):
    from app.jarvis.computer import is_local_file_url, plan_linux_run_app

    gw = _HireGateway()
    opened: list[dict] = []
    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: gw)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    _patch_hire_desktop(monkeypatch, opened)

    body = await run_voice_ask(HIRE_TETRIS)
    assert body["ok"] is True
    assert opened
    for plan in opened:
        url = str(plan.get("url") or "")
        assert is_local_file_url(url), url
        assert plan_linux_run_app({"target": "chrome", "url": url})["ok"] is True
    host_shaped = plan_linux_run_app(
        {"target": "chrome", "url": "exports/tetris_03.html"}
    )
    assert host_shaped["ok"] is False
    bad_file = plan_linux_run_app(
        {"target": "chrome", "url": "file://exports/tetris_03.html"}
    )
    assert bad_file["ok"] is False


@pytest.mark.asyncio
async def test_hire_goal_does_not_refuse_screen_when_agent_is_empty(hire_ws, monkeypatch):
    """Even if a look-policy agent returns nothing, hire still spawns."""
    gw = _HireGateway()
    opened: list[dict] = []
    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: gw)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-real")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    _patch_hire_desktop(monkeypatch, opened)

    body = await run_voice_ask(HIRE_TETRIS)
    assert "spawn_child" in body["tools_used"]
    assert body["reply"] != _SCREEN_FAIL
    assert body["ok"] is True
    assert opened
    assert str(opened[0].get("url") or "").startswith("file:///")


@pytest.mark.asyncio
async def test_create_ten_games_uses_spawn_child_without_that_word(hire_ws, monkeypatch):
    gw = _HireGateway()
    opened: list[dict] = []
    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: gw)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    _patch_hire_desktop(monkeypatch, opened)

    body = await run_voice_ask(CREATE_TEN_GAMES)
    names = [n for n, _ in gw.calls]
    assert "spawn_child" not in CREATE_TEN_GAMES
    assert names.count("spawn_child") == 10
    assert names.count("wait_child") == 10
    wave_ids = {payload.get("parent_job_id") for tool, payload in gw.calls if tool == "spawn_child"}
    assert len(wave_ids) >= 3
    assert body["tools_used"][0] == "spawn_child"
    assert body["ok"] is True
    assert len(opened) == 10
    for plan in opened:
        url = str(plan.get("url") or "")
        assert url.startswith("file:///"), plan
        assert "/home/jarvis/Exports/game_" in url
        assert url.endswith(".html")
        assert "file://exports/" not in url.lower()


def test_tetris_child_briefs_demand_unique_looks():
    a = _child_file_goal(HIRE_TETRIS, 1, 10)
    b = _child_file_goal(HIRE_TETRIS, 2, 10)
    look_a = _hire_look(1)
    look_b = _hire_look(2)
    assert a != b
    assert "tetris_01.html" in a
    assert "tetris_02.html" in b
    assert "tetris_01.html" not in b
    assert "tetris_02.html" not in a
    for brief, look in ((a, look_a), (b, look_b)):
        low = brief.lower()
        assert "unique look required" in low
        assert "palette" in low
        assert "piece set" in low
        assert "hud" in low
        assert f"title {look['title']!r}" in brief
        assert look["palette"] in brief
        assert look["pieces"] in brief
        assert look["hud"] in brief
    assert look_a["title"] != look_b["title"]
    assert look_a["palette"] != look_b["palette"]
    assert look_a["pieces"] != look_b["pieces"]
    assert look_a["hud"] != look_b["hud"]
    assert look_a["title"] not in b
    assert look_b["title"] not in a
    assert look_a["palette"] not in b
    assert look_b["palette"] not in a
    titles = {_hire_look(i)["title"] for i in range(1, 11)}
    assert len(titles) == 10
    assert len(_HIRE_LOOKS) >= 10


def test_parent_overwrites_identical_hire_files(hire_ws):
    exp = hire_ws / "Exports"
    clone = _unique_game_html(1, "tetris")
    (exp / "tetris_01.html").write_text(clone, encoding="utf-8")
    (exp / "tetris_02.html").write_text(clone, encoding="utf-8")
    paths = _ensure_hire_html_files(HIRE_TETRIS, 2)
    texts = [p.read_text(encoding="utf-8") for p in paths]
    assert texts[0] != texts[1]
    assert "Neon Stack" in texts[0]
    assert "Sunset Quarry" in texts[1]
    assert 'data-variant="1"' in texts[0]
    assert 'data-variant="2"' in texts[1]
    assert texts[0].count("Neon Stack") >= 1
    keep = _unique_game_html(1, "tetris")
    other = _unique_game_html(2, "tetris")
    (exp / "tetris_01.html").write_text(keep, encoding="utf-8")
    (exp / "tetris_02.html").write_text(other, encoding="utf-8")
    again = _ensure_hire_html_files(HIRE_TETRIS, 2)
    assert again[0].read_text(encoding="utf-8") == keep
    assert again[1].read_text(encoding="utf-8") == other


@pytest.mark.asyncio
async def test_hello_does_not_spawn_children(hire_ws, monkeypatch):
    gw = _HireGateway()
    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: gw)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)

    body = await run_voice_ask("hello")
    names = [n for n, _ in gw.calls]
    assert "spawn_child" not in names
    assert "wait_child" not in names
    assert "spawn_child" not in body.get("tools_used", [])
    assert body["ok"] is True
    assert body["reply"]


@pytest.mark.asyncio
async def test_create_five_html_files_opens_file_url(hire_ws, monkeypatch):
    gw = _HireGateway()
    opened: list[dict] = []
    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: gw)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    _patch_hire_desktop(monkeypatch, opened)

    body = await run_voice_ask(CREATE_FIVE_FILES)
    assert "spawn_child" not in CREATE_FIVE_FILES
    assert "spawn_child" in body["tools_used"]
    assert body["ok"] is True
    assert opened
    for plan in opened:
        url = str(plan.get("url") or "")
        assert url.startswith("file:///"), plan
        assert "/home/jarvis/Exports/" in url
        assert url.endswith(".html")


def test_create_five_tetris_is_a_hire_job():
    from app.jarvis.virtual_pc import goal_is_hire_job, goal_is_simple_talk

    assert goal_is_hire_job(CREATE_FIVE_TETRIS) is True
    assert goal_is_simple_talk(CREATE_FIVE_TETRIS) is False
    assert "I'll make five different Tetris games." == hire_start_line(CREATE_FIVE_TETRIS)
    assert HIRE_WAVE_LINE == "Making the next ones."


def test_empty_braces_is_not_a_spoken_reply():
    assert empty_speech("{}") is True
    assert empty_speech("   {}  ") is True
    assert empty_speech("") is True
    assert empty_speech("I did that.") is False
    assert ensure_spoken_reply("{}", hire_fallback_reply(CREATE_FIVE_TETRIS)) != "{}"
    assert empty_speech(ensure_spoken_reply("{}", hire_fallback_reply(CREATE_FIVE_TETRIS))) is False
    assert "{" not in ensure_spoken_reply("", hire_start_line(CREATE_FIVE_TETRIS))


def test_recover_spawn_child_limit_waves_on_new_job():
    calls: list[dict] = []

    def run(args):
        calls.append(dict(args or {}))
        return {"ok": True, "id": "c_waved01", "status": "running"}

    out = recover_spawn_child_limit(
        "spawn_child",
        {"goal": "tetris 3", "budget_seconds": 90, "budget_usd": 0.15},
        {"ok": False, "error": "CHILD_LIMIT"},
        run,
    )
    assert out.get("ok") is True
    assert out.get("id") == "c_waved01"
    assert out.get("waved") is True
    assert out.get("summary") == HIRE_WAVE_LINE
    assert calls
    assert str(calls[0].get("parent_job_id") or "").startswith("ask-hire-wave-")
    assert recover_spawn_child_limit("wait_child", {}, {"ok": False, "error": "CHILD_LIMIT"}, run)[
        "error"
    ] == "CHILD_LIMIT"


def test_plain_summary_child_limit_is_wave_speech():
    from app.jarvis.tools import plain_summary

    spoken = plain_summary("spawn_child", {"ok": False, "error": "CHILD_LIMIT"})
    assert spoken == HIRE_WAVE_LINE
    assert "That did not work" not in spoken
    assert spoken != "{}"


def test_sanitize_keeps_speech_when_agent_returns_empty_after_spawn():
    body = _sanitize_computer_agent_reply(CREATE_FIVE_TETRIS, "{}", ["spawn_child"])
    assert body is not None
    assert body["ok"] is True
    assert empty_speech(body["reply"]) is False
    assert body["reply"] != "{}"
    assert "I'll make five" in body["reply"]


@pytest.mark.asyncio
async def test_create_five_after_child_limit_still_speaks(hire_ws, monkeypatch):
    gw = _LimitOnceHireGateway()
    opened: list[dict] = []
    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: gw)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    _patch_hire_desktop(monkeypatch, opened)

    body = await run_voice_ask(CREATE_FIVE_TETRIS)
    names = [n for n, _ in gw.calls]
    assert names.count("spawn_child") >= 6
    assert names.count("wait_child") >= 5
    assert body["ok"] is True
    reply = str(body.get("reply") or "")
    assert empty_speech(reply) is False
    assert reply.strip() != "{}"
    assert "{}" not in reply
    assert "I'll make five different Tetris games." in reply
    assert HIRE_WAVE_LINE in reply
    assert "Hired" in reply
    assert body["tools_used"][0] == "spawn_child"
    wave_ids = {
        payload.get("parent_job_id")
        for tool, payload in gw.calls
        if tool == "spawn_child"
    }
    assert len(wave_ids) >= 2
    assert len(opened) == 5
    urls = []
    for plan in opened:
        url = str(plan.get("url") or "")
        urls.append(url)
        assert url.startswith("file:///"), plan
        assert "/home/jarvis/Exports/tetris_" in url
        assert url.endswith(".html")
        assert "file://exports/" not in url.lower()
    assert len(set(urls)) == 5
    texts = [
        (hire_ws / "Exports" / f"tetris_{i:02d}.html").read_text(encoding="utf-8")
        for i in range(1, 6)
    ]
    assert len(set(texts)) == 5
    titles = {_hire_look(i)["title"] for i in range(1, 6)}
    assert len(titles) == 5
    for i, text in enumerate(texts, start=1):
        assert _hire_look(i)["title"] in text


@pytest.mark.asyncio
async def test_persist_ask_does_not_log_empty_braces_for_hire(hire_ws, tmp_path, monkeypatch):
    from app.jarvis.talk_log import last_conversation, persist_ask, reset_rate_limits

    monkeypatch.setenv("JARVIS_WORKSPACE", str(hire_ws))
    reset_rate_limits()
    persist_ask(
        CREATE_FIVE_TETRIS,
        {"ok": True, "reply": "{}", "tools_used": ["spawn_child"]},
        root=hire_ws,
    )
    convo = last_conversation(root=hire_ws)
    jarvis = [t for t in (convo.get("turns") or []) if t.get("role") == "jarvis"]
    assert jarvis
    text = str(jarvis[-1].get("text") or "")
    assert empty_speech(text) is False
    assert text.strip() != "{}"
    assert "I'll make five" in text
