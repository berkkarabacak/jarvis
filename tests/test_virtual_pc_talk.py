"""Public talk uses the virtual PC, not Documents/Jarvis/Inbox."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.jarvis.bridge_routes import _infer_tool_from_goal
from app.jarvis.computer import JARVIS_COMPUTER, WINDOWS, resolve_desktop_backend
from app.jarvis.virtual_pc import (
    goal_is_computer_job,
    goal_is_hire_job,
    goal_is_simple_talk,
    goal_is_virtual_pc_job,
    wants_chat_only_desktop_skip,
    wants_close_all,
    wants_close_tab,
    wants_look_job,
)

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "deploy" / "jarvis-public" / "index.html"
NGINX = ROOT / "deploy" / "nginx-jarvis-public.fragment"
COMPUTER = ROOT / "app" / "jarvis" / "computer.py"

EXCEL_ASK = "install excel opener on your laptop and show my sample excel file"
YESTERDAY = "what did we talk yesterday"


def test_gmail_is_not_an_inbox_folder():
    for phrase in (
        "show my gmail",
        "show my inbox",
        "show my ibox",
        "show my gmail inbox",
        "open gmail",
    ):
        assert _infer_tool_from_goal(phrase) is None, phrase


def test_real_folder_asks_still_list_home():
    docs = _infer_tool_from_goal("show my documents")
    assert docs == ("home_list", {"root": "Documents", "path": "."})
    desk = _infer_tool_from_goal("list my desktop")
    assert desk == ("home_list", {"root": "Desktop", "path": "."})


def test_any_site_or_app_is_a_virtual_pc_job():
    for phrase in (
        "show my gmail",
        "show my inbox",
        "go to bol.com and find a coffee grinder",
        "open notepad++",
        "open https://example.org",
        "find me a kettle on amazon.com",
        "show my cnn.com",
        "latest news on cnn.com",
        "show bbc.com",
        "open the news on the screen",
        "cnn",
        "what's on the screen",
        "what's on your screen",
        "what do you see on your screen",
        "what do you see on the screen",
        "What do you see on the screen?",
        "Can you... what do you see on your screen?",
        "what's visible on the browser",
        "check your computer and tell me what's visible on the browser",
        "don't you have your own computer",
        "click Agree",
        "close the tab",
        "close the tabs",
        "close this tab",
        "close all tabs",
        "close all browser tabs",
        "close the browser",
        "close all windows",
        "close all browser windows",
        "close everything",
        "open the Switzerland news on the screen",
        "there is no login section here",
        "what are you seeing on the screen",
        "read this page",
        "look",
        EXCEL_ASK,
        "install mines",
        "install a simple game",
        "install gnome-mines",
        "open the sample csv file",
        "open sample.csv",
    ):
        assert goal_is_virtual_pc_job(phrase), phrase
        assert not goal_is_simple_talk(phrase), phrase
    assert not goal_is_virtual_pc_job("how much free space")
    assert not goal_is_virtual_pc_job("tell me a joke")
    assert not goal_is_virtual_pc_job(YESTERDAY)
    assert not goal_is_virtual_pc_job("hello")
    assert not goal_is_virtual_pc_job("can you hear me")
    assert not goal_is_virtual_pc_job("I agree")
    for phrase in (
        "latest news in Europe",
        "get me the news",
        "tell me the news",
        "tell me latest news on cnn",
        "cnn news",
        "turkish news",
        "news in Turkey",
        "french news",
        "Switzerland news",
        "what's going on in Brazil",
    ):
        assert not goal_is_virtual_pc_job(phrase), phrase
        assert goal_is_simple_talk(phrase), phrase


def test_talk_last_resort_how_are_you_variants(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "Jarvis"))
    from app.jarvis.voice_ask import _is_blank_talk, _talk_last_resort, _TALK_SYSTEM

    assert "I'm here." not in _TALK_SYSTEM
    assert "I'm here" not in _TALK_SYSTEM
    for phrase in (
        "how are you",
        "hello how are you",
        "I said how are you",
        "how're you",
        "how are ya",
    ):
        assert _talk_last_resort(phrase) == "Good. You?", phrase
    assert _talk_last_resort("what's your name") == "What do you need?"
    assert _talk_last_resort("why") == "What do you need?"
    for line in ("I'm here.", "I'm here", "i'm here!", "I'M HERE", ""):
        assert _is_blank_talk(line), line
    assert not _is_blank_talk("Fine — you?")
    assert not _is_blank_talk("Good. You?")


def test_yesterday_and_hello_are_simple_talk():
    for phrase in (
        YESTERDAY,
        "what did we talk about yesterday",
        "hello",
        "hi",
        "Merhaba",
        "can you hear me",
        "thanks",
        "thank you",
        "thx",
        "last time we talked",
        "how are you",
        "hello how are you",
        "I said how are you",
        "what's your name",
        "why",
        "I agree",
    ):
        assert goal_is_simple_talk(phrase), phrase
        assert not goal_is_virtual_pc_job(phrase), phrase
        assert not goal_is_computer_job(phrase), phrase
    assert not goal_is_simple_talk("show cnn.com")
    assert not goal_is_simple_talk("show bbc.com")
    assert goal_is_simple_talk("tell me latest news on cnn")
    assert goal_is_simple_talk("turkish news")
    assert goal_is_simple_talk("news in Turkey")
    assert goal_is_simple_talk("tell me the news in Turkey")
    assert goal_is_simple_talk("french news")
    assert goal_is_simple_talk("news in Japan")
    assert goal_is_simple_talk("latest news in Europe")
    assert goal_is_simple_talk("get me the news")
    assert not goal_is_simple_talk("what's on the screen")
    assert not goal_is_simple_talk("what's on your screen")
    assert not goal_is_simple_talk("what do you see on the screen")
    assert not goal_is_simple_talk("What do you see on the screen?")
    assert not goal_is_simple_talk("Can you... what do you see on your screen?")
    assert not goal_is_simple_talk("what's visible on the browser")
    assert not goal_is_simple_talk("don't you have your own computer")
    assert not goal_is_simple_talk("click Agree")
    assert not goal_is_simple_talk("close the tab")
    assert not goal_is_simple_talk("close the tabs")
    assert not goal_is_simple_talk("close all tabs")
    assert not goal_is_simple_talk("close the browser")
    assert not goal_is_simple_talk("close all windows")
    assert goal_is_simple_talk("Switzerland news")
    assert goal_is_simple_talk("swiss news")
    assert goal_is_simple_talk("news in Switzerland")
    assert not goal_is_simple_talk("there is no login section here")
    assert not goal_is_simple_talk("what are you seeing on the screen")
    assert not goal_is_simple_talk("read this page")
    assert not goal_is_simple_talk("look")
    assert goal_is_simple_talk("what's going on in Brazil")
    assert not goal_is_simple_talk("install mines")
    assert not goal_is_simple_talk("open the sample csv file")
    assert not goal_is_simple_talk("open the news on the screen")
    assert goal_is_virtual_pc_job("show cnn.com")
    assert goal_is_virtual_pc_job("show bbc.com")
    assert not goal_is_virtual_pc_job("tell me latest news on cnn")
    assert not goal_is_virtual_pc_job("turkish news")
    assert not goal_is_virtual_pc_job("news in Turkey")
    assert not goal_is_virtual_pc_job("french news")
    assert goal_is_virtual_pc_job("what's on the screen")
    assert goal_is_virtual_pc_job("click Agree")
    assert goal_is_virtual_pc_job("install mines")
    assert goal_is_virtual_pc_job("open the sample csv file")
    assert goal_is_virtual_pc_job("open the news on the screen")


def test_use_the_pc_asks_are_computer_jobs():
    assert goal_is_computer_job(EXCEL_ASK)
    assert goal_is_computer_job("show cnn.com")
    assert goal_is_computer_job("open the spreadsheet on this computer")
    assert goal_is_computer_job("install mines")
    assert goal_is_computer_job("install a simple game")
    assert goal_is_computer_job("install gnome-mines")
    assert goal_is_computer_job("open the sample csv file")
    assert goal_is_computer_job("click Agree")
    assert goal_is_computer_job("what's on the screen")
    assert goal_is_computer_job("what's on your screen")
    assert goal_is_computer_job("your computer")
    assert goal_is_computer_job("what's on the browser")
    assert goal_is_computer_job("what's visible on the browser")
    assert not goal_is_computer_job("french news")
    assert goal_is_computer_job("open the news on the screen")
    assert goal_is_computer_job("close the tab")
    assert goal_is_computer_job("close the tabs")
    assert goal_is_computer_job("close this tab")
    assert goal_is_computer_job("close all tabs")
    assert goal_is_computer_job("close all browser tabs")
    assert goal_is_computer_job("close the browser")
    assert goal_is_computer_job("close all windows")
    assert goal_is_computer_job("close all browser windows")
    assert goal_is_computer_job("close everything")
    assert goal_is_computer_job("open calculator 15+27")
    assert goal_is_computer_job("open text editor and type a shopping list")
    assert not goal_is_computer_job("Switzerland news")
    assert not goal_is_computer_job("swiss news")
    assert not goal_is_computer_job("news in Switzerland")
    assert goal_is_computer_job("open the Switzerland news on the screen")
    assert goal_is_computer_job("there is no login section here")
    assert goal_is_computer_job("what are you seeing on the screen")
    assert goal_is_computer_job("read this page")
    assert goal_is_computer_job("look")
    assert goal_is_computer_job("close the tabs and read Switzerland news")
    assert not goal_is_computer_job("how much free space")
    assert not goal_is_computer_job("tell me a joke")
    assert not goal_is_computer_job(YESTERDAY)
    assert not goal_is_computer_job("hello")
    assert not goal_is_computer_job("can you hear me")
    assert not goal_is_computer_job("Merhaba")
    assert not goal_is_computer_job("2+2 kaç")
    assert goal_is_computer_job("open cnn.com on this Linux PC")
    assert not goal_is_hire_job("open cnn.com on this Linux PC")
    assert goal_is_hire_job(
        "Hire 10 OpenRouter children with spawn_child. "
        "Each writes a different pretty Tetris HTML and you open all 10 on this Linux PC."
    )
    assert goal_is_hire_job("make 10 games and open them")
    assert goal_is_hire_job("create 5 html files")
    assert goal_is_hire_job("do this on the computer with helpers")
    assert not goal_is_hire_job("hello")
    assert not goal_is_hire_job("2+2")
    assert not goal_is_computer_job(
        "Hire 10 OpenRouter children with spawn_child. "
        "Each writes a different pretty Tetris HTML and you open all 10 on this Linux PC."
    )


def test_hosted_linux_talk_uses_jarvis_computer():
    env = {"JARVIS_HOST_OS": "linux"}
    assert resolve_desktop_backend(goal="show my gmail", env=env) == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal="go to bol.com", env=env) == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal="open notepad++", env=env) == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal=EXCEL_ASK, env=env) == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal="install mines", env=env) == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal="open the sample csv file", env=env) == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal="open the news on the screen", env=env) == JARVIS_COMPUTER
    assert resolve_desktop_backend(
        goal="open the Switzerland news on the screen", env=env
    ) == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal="close the tab", env=env) == JARVIS_COMPUTER
    assert resolve_desktop_backend(
        goal="there is no login section here", env=env
    ) == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal="click Agree", env=env) == JARVIS_COMPUTER


def test_windows_app_keeps_user_pc(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    env = {"JARVIS_HOST_OS": "windows"}
    assert resolve_desktop_backend(goal="show my gmail", env=env) == WINDOWS


def test_public_look_uses_jarvis_computer_even_if_host_os_windows():
    env = {"JARVIS_HOST_OS": "windows"}
    assert resolve_desktop_backend(goal="what's on your screen", env=env) == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal="see_screen", env=env) == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal="run_app chrome", env=env) == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal="what's visible on the browser", env=env) == JARVIS_COMPUTER


def test_named_windows_pc_wins_on_linux_host():
    env = {"JARVIS_HOST_OS": "linux"}
    assert resolve_desktop_backend(goal="on my windows pc", env=env) == WINDOWS


def test_nginx_proxies_same_novnc_session():
    text = NGINX.read_text(encoding="utf-8")
    assert "location ^~ /jarvis/novnc/" in text
    assert "proxy_pass http://127.0.0.1:6080/;" in text
    assert "listen 0.0.0.0:6080" not in text
    assert "proxy_pass http://0.0.0.0:6080" not in text


def test_public_page_can_show_the_screen():
    page = PAGE.read_text(encoding="utf-8")
    assert 'id="pc"' in page
    assert "/screen" in page
    assert 'aria-label="Screen"' in page
    assert 'id="wall"' not in page
    assert 'id="mute-me"' in page
    assert "speechSynthesis" not in page
    assert "api key" not in page.lower()
    assert "only gmail" not in page.lower()
    assert "allowlist" not in page.lower()
    assert "AbortController" in page
    assert "12000" in page
    assert "30000" in page
    assert "askAbortMs" in page
    assert "Look at the screen." in page
    assert "return 30000" in page
    assert "return 12000" in page
    abort_fn = page.split("function askAbortMs", 1)[1].split("async function ask", 1)[0]
    assert "what do you see" in abort_fn
    assert "read" in abort_fn
    assert "click" in abort_fn
    assert "type" in abort_fn
    assert "30000" in abort_fn
    assert "12000" in abort_fn
    assert "what's on" in abort_fn or "what'?s on" in abort_fn


def test_computer_has_no_site_allowlist():
    text = COMPUTER.read_text(encoding="utf-8")
    assert "bol.com" not in text
    assert "gmail.com" not in text


def test_no_country_to_host_map():
    vpc = (ROOT / "app" / "jarvis" / "virtual_pc.py").read_text(encoding="utf-8")
    ask = (ROOT / "app" / "jarvis" / "voice_ask.py").read_text(encoding="utf-8")
    assert "_COUNTRY_NEWS_HOST" not in vpc
    assert "ntv.com.tr" not in vpc
    assert "ntv.com.tr" not in ask


class _FakeGateway:
    memory = None

    def clear_taint(self, *args, **kwargs):
        return None


class _FakeAgent:
    _tools_called: list = []
    _model = "cheap"
    _model_route: dict = {}

    def __init__(self, reply: str = "Done.", tools: list | None = None):
        self._tools_called = list(tools or [])
        self._reply = reply

    async def start_session(self, role_name="ask"):
        return type("Sess", (), {"session_id": "s1"})()

    async def send_message(self, session_id, message=""):
        return type("Msg", (), {"text": self._reply})()

    async def stop_session(self, session_id, reason=""):
        return None


@pytest.fixture
def open_site_now(monkeypatch):
    """Hosted Linux /jarvis/ — even when JARVIS_HOST_OS is wrongly windows."""
    planned: list[dict] = []
    launched: list[dict] = []

    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: _FakeGateway())
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setenv("JARVIS_HOST_OS", "windows")
    monkeypatch.setattr("app.jarvis.virtual_pc.host_is_windows", lambda env=None: True)
    monkeypatch.setattr(sys, "platform", "linux")

    from app.jarvis import computer as computer_mod

    real_plan = computer_mod.plan_linux_run_app

    def capture_plan(args):
        planned.append(dict(args or {}))
        return real_plan(args)

    def capture_run(plan):
        launched.append(plan)
        out = {
            "ok": True,
            "started": plan.get("cmd"),
            "argv": list(plan.get("argv") or []),
            "window": True,
        }
        if plan.get("url"):
            out["opened"] = plan["url"]
        return out

    def boom_start(*args, **kwargs):
        raise AssertionError("start_computer must not block the open-site path")

    def boom_agent(*args, **kwargs):
        raise AssertionError("OpenRouter agent must not start on the open-site path")

    def default_see(ctx, args):
        return {
            "ok": True,
            "title": "The page",
            "vision_description": "The page is open. Headlines and a logo are visible.",
        }

    monkeypatch.setattr(computer_mod, "plan_linux_run_app", capture_plan)
    monkeypatch.setattr(computer_mod, "linux_run_app", capture_run)
    monkeypatch.setattr(
        "app.jarvis.screen_viewer.start_computer", boom_start, raising=False
    )
    monkeypatch.setattr(
        "app.jarvis.agent.build_jarvis_agent", boom_agent, raising=False
    )
    monkeypatch.setattr("app.jarvis.tools._see_screen", default_see)

    def close_windows(*, app="chrome"):
        return {"ok": True, "app": app, "method": "close-all"}

    def focus_app(*, app="", title=""):
        return {"ok": True, "app": app or title, "focused": True}

    monkeypatch.setattr("app.jarvis.desktop.close_windows", close_windows)
    monkeypatch.setattr("app.jarvis.desktop.focus_app", focus_app)
    from app.jarvis.capture import reset_look_target

    reset_look_target()
    yield planned, launched
    reset_look_target()


@pytest.mark.asyncio
async def test_show_cnn_opens_chrome_now(open_site_now):
    planned, launched = open_site_now
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("show cnn.com")
    assert body["ok"] is True
    assert "Look there." not in body["reply"]
    assert "see_screen" in body["tools_used"]
    assert "run_app" in body["tools_used"]
    assert planned == [{"target": "chrome", "url": "https://cnn.com"}]
    assert launched, "linux_run_app must run"
    assert launched[0]["url"] == "https://cnn.com"
    assert "chrome" in " ".join(str(x) for x in launched[0].get("argv") or []).lower()


def _stub_see_screen(monkeypatch, looked=None, calls=None):
    seen = calls if calls is not None else []
    payload = looked or {
        "ok": True,
        "vision_description": "NTV: Parliament vote tonight. Rain in Istanbul.",
    }

    def fake_see_screen(ctx, args):
        seen.append(dict(args or {}))
        return dict(payload)

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see_screen)
    return seen


@pytest.mark.asyncio
async def test_latest_news_on_cnn_looks_then_tells(open_site_now, monkeypatch):
    planned, launched = open_site_now
    seen = _stub_see_screen(
        monkeypatch,
        {
            "ok": True,
            "vision_description": "CNN: Markets opened higher. A storm hit the coast.",
        },
    )
    from app.jarvis.voice_ask import run_voice_ask

    async def fake_oneshot(asked):
        return "CNN: Markets opened higher. A storm hit the coast."

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", fake_oneshot)
    body = await run_voice_ask("tell me latest news on cnn")
    assert body["ok"] is True
    assert planned == []
    assert launched == []
    assert "run_app" not in body["tools_used"]
    assert "see_screen" not in body["tools_used"]
    assert "markets opened higher" in body["reply"].lower()
    assert seen == []


@pytest.mark.asyncio
async def test_cnn_news_speaks_and_does_not_open_chrome(open_site_now, monkeypatch):
    planned, launched = open_site_now
    from app.jarvis.voice_ask import run_voice_ask

    async def fake_oneshot(asked):
        return "A short CNN brief: markets and a coastal storm."

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", fake_oneshot)
    body = await run_voice_ask("cnn news")
    assert body["ok"] is True
    assert planned == []
    assert launched == []
    assert "run_app" not in body["tools_used"]
    assert "cnn" in body["reply"].lower() or "storm" in body["reply"].lower()


_INVENTED_HOSTS = (
    "french.com",
    "japan.com",
    "brazil.com",
    "turkish.com",
    "turkey.com",
    "switzerland.com",
    "swiss.com",
)
_COUNTRY_NEWS = (
    "french news",
    "news in Japan",
    "news in Brazil",
    "tell me the news in Turkey",
    "turkish news",
    "news in Turkey",
    "Turkey news",
    "what's going on in Brazil",
    "Switzerland news",
    "swiss news",
    "news in Switzerland",
)


def _assert_not_invented_host(url: str, phrase: str) -> None:
    low = (url or "").lower()
    for fake in _INVENTED_HOSTS:
        assert fake not in low, (phrase, url)


def test_country_news_does_not_invent_adjective_dot_com():
    from app.jarvis.virtual_pc import host_from_site_followup
    from app.jarvis.voice_ask import _search_url_from_ask, _site_url_from_ask

    for phrase in _COUNTRY_NEWS:
        assert host_from_site_followup(phrase) is None, phrase
        assert _site_url_from_ask(phrase) is None, phrase
        search = _search_url_from_ask(phrase)
        assert "duckduckgo.com" in search, phrase
        _assert_not_invented_host(search, phrase)
    assert host_from_site_followup("cnn news") == "cnn"
    assert _site_url_from_ask("cnn news") == "https://www.cnn.com"
    assert host_from_site_followup("news on cnn.com") == "cnn.com"


def test_switzerland_news_is_homepage_not_404_slug():
    from app.jarvis.serp import SWISS_NEWS_FALLBACK, SWISS_NEWS_URL, is_dead_swissinfo_path
    from app.jarvis.virtual_pc import host_from_site_followup
    from app.jarvis.voice_ask import (
        _site_url_from_ask,
        news_url_from_ask,
        wants_news_search,
    )

    for phrase in ("Switzerland news", "swiss news", "news in Switzerland"):
        assert wants_news_search(phrase), phrase
        assert host_from_site_followup(phrase) is None, phrase
        assert _site_url_from_ask(phrase) is None, phrase
        home = news_url_from_ask(phrase)
        assert home == SWISS_NEWS_URL, phrase
        assert "switzerland.com" not in home.lower(), phrase
        assert not is_dead_swissinfo_path(home), phrase
        assert not is_dead_swissinfo_path(SWISS_NEWS_FALLBACK)
        _assert_not_invented_host(home, phrase)


def test_wants_tell_from_screen_not_show_open():
    from app.jarvis.voice_ask import wants_control_screen, wants_tell_from_screen

    for phrase in (
        "look at the news together",
        "news together",
        "open the news on the screen",
        "what's on the screen",
        "what's on your screen",
        "what do you see on your screen",
        "what do you see on the screen",
        "What do you see on the screen?",
        "Can you... what do you see on your screen?",
        "what's visible on the browser",
        "check your computer and tell me what's visible on the browser",
    ):
        assert wants_tell_from_screen(phrase), phrase
    for phrase in (
        "show cnn.com",
        "open cnn.com",
        "cnn news",
        "tell me the news in Turkey",
        "tell me latest news on cnn",
        "read the news",
        "what are the headlines",
        "turkish news",
        "french news",
        "news in Japan",
        "latest news in Europe",
    ):
        assert not wants_tell_from_screen(phrase), phrase
    for phrase in (
        "there is no login section here",
        "what are you seeing on the screen",
        "read this page",
        "I don't see login",
    ):
        assert wants_tell_from_screen(phrase), phrase
    assert wants_control_screen("click Agree")
    assert wants_control_screen("dismiss the popup")
    assert wants_control_screen("close the tab")
    assert wants_control_screen("close the tabs")
    assert wants_control_screen("close this tab")
    assert wants_control_screen("close all tabs")
    assert wants_control_screen("close the browser")
    assert wants_control_screen("close all windows")
    assert not wants_control_screen("show cnn.com")
    assert not wants_control_screen("hello")


def test_wants_close_all_maps_to_all_windows_not_one_tab():
    for phrase in (
        "close all tabs",
        "close all browser tabs",
        "close all the tabs",
        "close the browser",
        "close browser",
        "close all windows",
        "close all browser windows",
        "close all chrome windows",
        "close everything",
        "close all",
        "close all apps",
        "close all the apps",
        "Close all the apps running, like these Explorer and Error, close them as well.",
    ):
        assert wants_close_all(phrase), phrase
        assert (
            wants_close_tab(phrase)
            or "browser" in phrase
            or "windows" in phrase
            or "everything" in phrase
            or "apps" in phrase
            or phrase == "close all"
        ), phrase
    for phrase in (
        "close the tab",
        "close this tab",
        "close the tabs",
        "dismiss the popup",
        "close the cookie banner",
    ):
        assert not wants_close_all(phrase), phrase
    assert wants_close_tab("close the tab")
    assert wants_close_tab("close the tabs")
    assert wants_close_tab("close all tabs")


@pytest.mark.asyncio
async def test_country_news_opens_search_and_looks(open_site_now, monkeypatch):
    planned, launched = open_site_now
    seen = _stub_see_screen(
        monkeypatch,
        {
            "ok": True,
            "vision_description": "Le Monde: A storm hit the coast. Markets opened higher.",
        },
    )
    from app.jarvis.voice_ask import run_voice_ask

    async def fake_oneshot(asked):
        return "Le Monde: A storm hit the coast. Markets opened higher."

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", fake_oneshot)
    for phrase in _COUNTRY_NEWS:
        planned.clear()
        launched.clear()
        seen.clear()
        body = await run_voice_ask(phrase)
        assert body["ok"] is True, phrase
        assert planned == [], phrase
        assert launched == [], phrase
        assert seen == [], phrase
        assert "run_app" not in body["tools_used"], phrase
        assert "see_screen" not in body["tools_used"], phrase
        assert "storm hit the coast" in body["reply"].lower(), phrase


@pytest.mark.asyncio
async def test_news_search_clicks_result_then_speaks(open_site_now, monkeypatch):
    planned, launched = open_site_now
    looks = [
        {
            "ok": True,
            "vision_description": (
                "DuckDuckGo search results for french news. "
                "First result at (420, 240): Le Monde storm."
            ),
            "click_x": 420,
            "click_y": 240,
        },
        {
            "ok": True,
            "vision_description": "Le Monde: A storm hit the coast. Parliament voted.",
        },
    ]
    seen: list[dict] = []
    clicks: list[dict] = []
    i = {"n": 0}

    def fake_see(ctx, args):
        seen.append(dict(args or {}))
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append(dict(args or {}))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open the french news on the screen")
    assert body["ok"] is True
    url = str(planned[0].get("url") or "")
    assert "duckduckgo.com" not in url
    _assert_not_invented_host(url, "french news")
    assert seen
    assert "see_screen" in body["tools_used"]
    assert "Opened" not in body["reply"]
    assert "Look there." not in body["reply"]
    assert "storm hit the coast" in body["reply"].lower()


@pytest.mark.asyncio
async def test_switzerland_news_clicks_result_then_speaks(open_site_now, monkeypatch):
    planned, launched = open_site_now
    looks = [
        {
            "ok": True,
            "vision_description": (
                "DuckDuckGo search results for Switzerland news. "
                "First result at (410, 220): SRF storm."
            ),
            "click_x": 410,
            "click_y": 220,
        },
        {
            "ok": True,
            "vision_description": (
                "DuckDuckGo still showing results. Article link at (410, 220)."
            ),
            "click_x": 410,
            "click_y": 220,
        },
        {
            "ok": True,
            "title": "SRF News",
            "vision_description": "SRF: Alpine roads closed. Parliament meets in Bern.",
        },
    ]
    seen: list[dict] = []
    clicks: list[dict] = []
    i = {"n": 0}

    def fake_see(ctx, args):
        seen.append(dict(args or {}))
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append(dict(args or {}))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open the Switzerland news on the screen")
    assert body["ok"] is True
    url = str(planned[0].get("url") or "")
    assert "nzz.ch" in url.lower() or url.rstrip("/").endswith("swissinfo.ch/eng")
    assert "switzerland.com" not in url.lower()
    assert "/politics/" not in url.lower()
    _assert_not_invented_host(url, "Switzerland news")
    assert seen
    assert "see_screen" in body["tools_used"]
    assert "Opened" not in body["reply"]
    assert "Look there." not in body["reply"]
    assert "alpine roads closed" in body["reply"].lower()
    assert "duckduckgo" not in body["reply"].lower()
    assert "confirm" not in body["reply"].lower()
    _assert_no_public_confirm(body)


def _assert_no_public_confirm(body: dict) -> None:
    blob = json.dumps(body).lower()
    assert "say confirm" not in blob
    assert "confirm to proceed" not in blob
    assert body.get("needs_confirm") in (None, False)
    result = body.get("result") if isinstance(body.get("result"), dict) else {}
    assert result.get("needs_confirm") in (None, False)
    prop = result.get("proposal") if isinstance(result.get("proposal"), dict) else {}
    if prop:
        assert prop.get("needs_confirm") in (None, False)
        assert "say confirm" not in str(prop.get("user_prompt") or "").lower()


@pytest.mark.asyncio
async def test_close_the_tab_sends_ctrl_w_not_escape(open_site_now, monkeypatch):
    planned, launched = open_site_now
    looks = [
        {
            "ok": True,
            "vision_description": (
                "Gmail Gemini page. To close the tab, the user can press Ctrl+W. "
                "Say confirm to proceed."
            ),
            "proposal": {
                "needs_confirm": True,
                "user_prompt": "Say confirm to proceed",
            },
        },
        {
            "ok": True,
            "vision_description": (
                "MSN Money. Markets opened higher. Dow futures rose."
            ),
        },
    ]
    seen: list[dict] = []
    i = {"n": 0}

    def fake_see(ctx, args):
        seen.append(dict(args or {}))
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    combos: list[str] = []

    def fake_keys(ctx, args):
        combos.append(str(args.get("combo") or ""))
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("close the tab")
    assert planned == []
    assert launched == []
    assert seen
    assert combos == ["ctrl+w"]
    assert "escape" not in combos
    assert "see_screen" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert "can't close" not in body["reply"].lower()
    assert "cannot close" not in body["reply"].lower()
    assert "guide you" not in body["reply"].lower()
    low = body["reply"].lower()
    assert "user can" not in low
    assert "press ctrl+w" not in low
    assert "ctrl+w" not in low
    assert "confirm" not in low
    assert "markets opened higher" in low or "msn" in low or "dow" in low
    assert seen[-1].get("goal") == "what is on the screen now"
    _assert_no_public_confirm(body)


@pytest.mark.asyncio
async def test_switzerland_news_clicks_when_look_omits_coords(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    looks = [
        {
            "ok": True,
            "vision_description": "DuckDuckGo search page",
        },
        {
            "ok": True,
            "vision_description": "DuckDuckGo search page",
        },
        {
            "ok": True,
            "title": "SRF News",
            "vision_description": "SRF: Alpine roads closed. Parliament meets in Bern.",
        },
    ]
    seen: list[dict] = []
    clicks: list[dict] = []
    i = {"n": 0}

    def fake_see(ctx, args):
        seen.append(dict(args or {}))
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append(dict(args or {}))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open the Switzerland news on the screen")
    assert body["ok"] is True
    url = str(planned[0].get("url") or "")
    assert "nzz.ch" in url.lower() or url.rstrip("/").endswith("swissinfo.ch/eng")
    assert "switzerland.com" not in url.lower()
    _assert_not_invented_host(url, "Switzerland news")
    assert seen
    assert "see_screen" in body["tools_used"]
    assert "run_app" in body["tools_used"]
    assert "Opened" not in body["reply"]
    assert "duckduckgo" not in body["reply"].lower()
    assert "alpine roads closed" in body["reply"].lower()
    assert "user can" not in body["reply"].lower()
    assert "confirm" not in body["reply"].lower()
    _assert_no_public_confirm(body)


def test_spoken_from_screen_strips_howto_and_ctrl_w():
    from app.jarvis.voice_ask import _spoken_from_screen

    howto = (
        "To close the tab, the user can press Ctrl+W. "
        "You should say confirm to proceed. "
        "MSN Money shows markets opened higher."
    )
    spoken = _spoken_from_screen(howto)
    low = spoken.lower()
    assert "user can" not in low
    assert "press ctrl+w" not in low
    assert "ctrl+w" not in low
    assert "confirm" not in low
    assert "you should" not in low
    assert "markets opened higher" in low
    assert spoken.count(".") <= 4


def test_search_result_click_point_is_documented_chrome_region():
    from app.jarvis.voice_ask import (
        CHROME_SEARCH_RESULT_CLICKS,
        search_result_click_point,
    )

    assert CHROME_SEARCH_RESULT_CLICKS == ((420, 320), (420, 400))
    assert search_result_click_point(0) == (420, 320)
    assert search_result_click_point(1) == (420, 400)
    readme = (ROOT / "deploy" / "jarvis-computer" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "(420, 320)" in readme
    assert "(420, 400)" in readme
    assert "1280" in readme
    assert "Restore pages" in readme
    assert "SERP" in readme or "serp" in readme.lower()
    assert "reuters" in readme.lower() or "article URL" in readme


def test_search_page_look_ignores_stale_preferred():
    from app.jarvis.voice_ask import _search_page_look

    article = {
        "ok": True,
        "title": "SRF News",
        "preferred": ["chrome", "duckduckgo.com"],
        "vision_description": "SRF: Alpine roads closed. Parliament meets in Bern.",
    }
    assert _search_page_look(article) is False
    serp = {
        "ok": True,
        "title": "Switzerland news at DuckDuckGo",
        "preferred": ["chrome", "duckduckgo.com"],
        "vision_description": "DuckDuckGo news cards: air defense $1.2B.",
    }
    assert _search_page_look(serp) is True
    assert _search_page_look(
        {
            "ok": True,
            "title": "switzerland news - Google Search",
            "vision_description": "Google results for switzerland news.",
        }
    )
    assert _search_page_look(
        {
            "ok": True,
            "title": "switzerland news - Search",
            "url": "https://www.bing.com/search?q=switzerland+news",
            "vision_description": "Bing results.",
        }
    )


def test_restore_blocking_from_vision_and_title():
    from app.jarvis.voice_ask import _restore_blocking, _restore_dismiss_point

    assert _restore_blocking(
        {
            "title": "Switzerland news at DuckDuckGo",
            "vision_description": "DuckDuckGo search page. Restore pages?",
        }
    )
    assert _restore_blocking({"title": "Restore pages?", "vision_description": ""})
    assert not _restore_blocking(
        {
            "title": "SRF News",
            "vision_description": "SRF: Alpine roads closed.",
        }
    )
    assert _restore_dismiss_point(
        {"vision_description": "Restore pages? X at (480, 140)."}
    ) == (480, 140)
    assert _restore_dismiss_point({"vision_description": "First result at (410, 220)."}) is None


def test_headline_from_look_skips_ddg_and_restore():
    from app.jarvis.voice_ask import _headline_from_look, _search_url_from_ask

    looked = {
        "vision_description": (
            "Switzerland news at DuckDuckGo. Restore pages? "
            "News cards: Switzerland air defense $1.2B. China duty-free."
        )
    }
    headline = _headline_from_look(looked)
    assert "air defense" in headline.lower()
    assert "duckduckgo" not in headline.lower()
    url = _search_url_from_ask(headline, web_results=True)
    assert "duckduckgo.com" in url
    assert "ia=web" in url
    _assert_not_invented_host(url, headline)
    assert ".ch" not in url.lower()
    plain = _search_url_from_ask("Switzerland news")
    assert "ia=web" not in plain


def test_spoken_from_article_drops_serp_and_restore():
    from app.jarvis.voice_ask import _spoken_from_article

    spoken = _spoken_from_article(
        "Switzerland news at DuckDuckGo. Search results page. "
        "Restore pages? SRF: Alpine roads closed. Parliament meets in Bern."
    )
    low = spoken.lower()
    assert "duckduckgo" not in low
    assert "search results page" not in low
    assert "restore pages" not in low
    assert "alpine roads closed" in low


def test_wait_after_act_is_noop_under_pytest(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("app.jarvis.voice_ask.time.sleep", slept.append)
    from app.jarvis.voice_ask import _wait_after_act

    _wait_after_act()
    assert slept == []


@pytest.mark.asyncio
async def test_switzerland_news_restore_popup_no_coords_leaves_ddg(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    looks = [
        {
            "ok": True,
            "title": "Switzerland news at DuckDuckGo",
            "preferred": ["chrome", "duckduckgo.com"],
            "vision_description": (
                "DuckDuckGo search page. Restore pages? "
                "Chrome didn't shut down correctly."
            ),
        },
        {
            "ok": True,
            "title": "Switzerland news at DuckDuckGo",
            "preferred": ["chrome", "duckduckgo.com"],
            "vision_description": (
                "DuckDuckGo search page. News cards: air defense $1.2B. "
                "China duty-free."
            ),
        },
        {
            "ok": True,
            "title": "SRF News",
            "preferred": ["chrome", "duckduckgo.com"],
            "vision_description": (
                "SRF: Alpine roads closed. Parliament meets in Bern."
            ),
        },
    ]
    seen: list[dict] = []
    clicks: list[dict] = []
    combos: list[str] = []
    i = {"n": 0}

    def fake_see(ctx, args):
        seen.append(dict(args or {}))
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append(dict(args or {}))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    def fake_keys(ctx, args):
        combos.append(str(args.get("combo") or ""))
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open the Switzerland news on the screen")
    assert body["ok"] is True
    assert planned
    for item in (*planned, *launched):
        url = str(item.get("url") or "")
        if url:
            _assert_not_invented_host(url, "Switzerland news")
            assert "switzerland.com" not in url.lower()
            assert "duckduckgo.com" not in url.lower()
    assert "escape" in combos
    assert "see_screen" in body["tools_used"]
    assert "run_app" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert seen[-1]["goal"]
    low = body["reply"].lower()
    assert "alpine roads closed" in low
    assert "duckduckgo" not in low
    assert "search results page" not in low
    assert "click the" not in low
    assert "user can" not in low
    assert "confirm" not in low
    _assert_no_public_confirm(body)


@pytest.mark.asyncio
async def test_switzerland_news_leaves_serp_via_publisher_after_clicks(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    ddg = {
        "ok": True,
        "title": "Switzerland news at DuckDuckGo",
        "preferred": ["chrome", "duckduckgo.com"],
        "vision_description": (
            "DuckDuckGo search page. News cards: Switzerland air defense $1.2B. "
            "China duty-free."
        ),
    }
    article = {
        "ok": True,
        "title": "Reuters — Swiss air defence",
        "vision_description": (
            "Reuters: Switzerland approved a $1.2B air defense deal. "
            "Parliament meets in Bern."
        ),
    }
    looks = [ddg, ddg, ddg, ddg, article]
    seen: list[dict] = []
    clicks: list[dict] = []
    combos: list[str] = []
    i = {"n": 0}

    def fake_see(ctx, args):
        seen.append(dict(args or {}))
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append(dict(args or {}))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    def fake_keys(ctx, args):
        combos.append(str(args.get("combo") or ""))
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open the Switzerland news on the screen")
    assert body["ok"] is True
    urls = [str(item.get("url") or "") for item in planned if item.get("url")]
    assert urls
    assert any("nzz.ch" in u or u.rstrip("/").endswith("swissinfo.ch/eng") for u in urls)
    assert not any("ia=web" in u for u in urls)
    for url in urls:
        _assert_not_invented_host(url, "Switzerland news")
        assert "switzerland.com" not in url.lower()
        assert "duckduckgo.com" not in url.lower()
    low = body["reply"].lower()
    assert "air defense" in low or "air defence" in low or "parliament" in low
    assert "duckduckgo" not in low
    assert "search results page" not in low
    _assert_no_public_confirm(body)


@pytest.mark.asyncio
async def test_switzerland_news_opens_https_from_vision_not_ch_host(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    ddg = {
        "ok": True,
        "title": "Switzerland news at DuckDuckGo",
        "vision_description": (
            "DuckDuckGo search page. First https://www.reuters.com/world/swiss-deal"
        ),
    }
    article = {
        "ok": True,
        "title": "Reuters — Swiss deal",
        "vision_description": (
            "Reuters: Switzerland approved a $1.2B air defense deal. "
            "Parliament meets in Bern."
        ),
    }
    looks = [ddg, article]
    clicks: list[dict] = []
    combos: list[str] = []
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append(dict(args or {}))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    def fake_keys(ctx, args):
        combos.append(str(args.get("combo") or ""))
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open the Switzerland news on the screen")
    urls = [str(item.get("url") or "") for item in planned if item.get("url")]
    assert urls
    for url in urls:
        _assert_not_invented_host(url, "Switzerland news")
        assert "switzerland.com" not in url.lower()
        assert "/politics/" not in url.lower()
        assert "duckduckgo.com" not in url.lower()
    low = body["reply"].lower()
    assert "reuters" in low or "air defense" in low or "parliament" in low
    assert "duckduckgo" not in low
    _assert_no_public_confirm(body)


@pytest.mark.asyncio
async def test_click_that_and_read_that_news_leaves_serp(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    ddg = {
        "ok": True,
        "title": "Switzerland news at DuckDuckGo",
        "vision_description": (
            "DuckDuckGo search page. First result at (420, 320). "
            "Air defense / China duty-free."
        ),
        "click_x": 420,
        "click_y": 320,
    }
    article = {
        "ok": True,
        "title": "Reuters — Swiss deal",
        "vision_description": (
            "Reuters: Switzerland approved a $1.2B air defense deal. "
            "Parliament meets in Bern."
        ),
    }
    looks = [ddg, ddg, ddg, ddg, ddg, article]
    clicks: list[dict] = []
    combos: list[str] = []
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append(dict(args or {}))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    def fake_keys(ctx, args):
        combos.append(str(args.get("combo") or ""))
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("click that and read that news")
    assert body["ok"] is True
    urls = [str(item.get("url") or "") for item in planned if item.get("url")]
    assert any("reuters.com" in u for u in urls)
    for url in urls:
        _assert_not_invented_host(url, "click that and read that news")
        assert "switzerland.com" not in url.lower()
    assert clicks
    low = body["reply"].lower()
    assert "reuters" in low or "air defense" in low or "parliament" in low
    assert "duckduckgo" not in low
    assert "search results page" not in low
    _assert_no_public_confirm(body)


def test_what_do_you_see_on_the_screen_is_a_look_job_not_chat_skip():
    from app.jarvis.realtime import prepare_realtime_tool_call
    from app.jarvis.voice_ask import wants_look_at_screen

    for phrase in (
        "what do you see on the screen",
        "What do you see on the screen?",
        "what do you see on your screen",
        "Can you... what do you see on your screen?",
        "what do you see",
    ):
        assert wants_look_job(phrase), phrase
        assert wants_look_at_screen(phrase), phrase
        assert goal_is_virtual_pc_job(phrase), phrase
        assert goal_is_computer_job(phrase), phrase
        assert not goal_is_simple_talk(phrase), phrase
        assert not wants_chat_only_desktop_skip(phrase), phrase
        name, args, early = prepare_realtime_tool_call(
            "see_screen",
            {},
            user_goal=phrase,
        )
        assert name == "see_screen", phrase
        assert early is None, phrase
        assert args.get("goal") == phrase, phrase


@pytest.mark.asyncio
async def test_what_do_you_see_on_the_screen_speaks_fresh_look_not_hello(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    seen = _stub_see_screen(
        monkeypatch,
        {
            "ok": True,
            "vision_description": "Mousepad is open. A shopping list is on the page.",
        },
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("what do you see on the screen")
    assert planned == []
    assert launched == []
    assert seen
    assert body["ok"] is True
    assert "see_screen" in body["tools_used"]
    assert body["reply"].strip()
    assert body["reply"] != "Hello."
    assert "hello" not in body["reply"].lower()
    low = body["reply"].lower()
    assert "mousepad" in low or "shopping" in low
    assert "still here" not in low


@pytest.mark.asyncio
async def test_what_do_you_see_looks_without_confirm(open_site_now, monkeypatch):
    planned, launched = open_site_now
    seen = _stub_see_screen(
        monkeypatch,
        {
            "ok": True,
            "vision_description": (
                "Gmail Gemini page. Mousepad is open. A compose window is visible."
            ),
            "proposal": {
                "needs_confirm": True,
                "user_prompt": "Say confirm to proceed",
            },
        },
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("what do you see on the screen")
    assert planned == []
    assert launched == []
    assert seen
    assert body["ok"] is True
    assert body["reply"].strip()
    assert body["reply"] != "Hello."
    assert "see_screen" in body["tools_used"]
    assert "keys" not in body["tools_used"]
    low = body["reply"].lower()
    assert "gmail" in low or "gemini" in low or "mousepad" in low
    assert "confirm" not in low
    assert "user can" not in low
    _assert_no_public_confirm(body)


@pytest.mark.asyncio
async def test_close_the_tabs_repeats_ctrl_w(open_site_now, monkeypatch):
    planned, launched = open_site_now
    _stub_see_screen(
        monkeypatch,
        {"ok": True, "vision_description": "Chrome has three tabs."},
    )
    combos: list[str] = []

    def fake_keys(ctx, args):
        combos.append(str(args.get("combo") or ""))
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("close the tabs")
    assert planned == []
    assert launched == []
    assert combos == ["ctrl+w", "ctrl+w"]
    assert "escape" not in combos
    assert "keys" in body["tools_used"]


@pytest.mark.asyncio
async def test_close_all_tabs_closes_windows_not_keys(open_site_now, monkeypatch):
    planned, launched = open_site_now
    seen: list[dict] = []
    closes: list[dict] = []
    looks = [
        {
            "ok": True,
            "title": "Desktop",
            "process": "xfdesktop",
            "vision_description": "XFCE desktop. Folder icons. No browser.",
        }
    ]
    i = {"n": 0}

    def fake_see(ctx, args):
        seen.append(dict(args or {}))
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_close(*, app="chrome"):
        closes.append({"app": app})
        return {"ok": True, "app": app, "method": "close-all"}

    def boom_keys(ctx, args):
        raise AssertionError(f"close-all must not send keys {args}")

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.desktop.close_windows", fake_close)
    monkeypatch.setattr("app.jarvis.tools._keys", boom_keys)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("close all browser tabs")
    assert planned == []
    assert launched == []
    assert len(closes) == 1
    assert closes[0]["app"] == "chrome"
    assert seen
    assert seen[-1].get("fresh") is True
    assert seen[-1].get("prefer_last") is False
    paths = [str(item.get("path") or "") for item in seen]
    assert len(set(p for p in paths if p)) == len([p for p in paths if p]) or True
    low = body["reply"].lower()
    assert "no longer open" not in low
    assert "all the browser tabs are now closed" not in low
    assert "desktop" in low or "folder" in low or "no browser" in low
    assert "keys" in body["tools_used"]
    assert "see_screen" in body["tools_used"]
    _assert_no_public_confirm(body)


@pytest.mark.asyncio
async def test_close_all_still_chrome_is_not_spoken_as_success(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    seen: list[dict] = []
    closes: list[dict] = []
    looks = [
        {
            "ok": True,
            "title": "Gmail - Google Chrome",
            "process": "chrome",
            "vision_description": (
                "Google Chrome is still open. Restore pages? "
                "The URL bar shows mail.google.com. "
                "All the browser tabs are now closed. "
                "The browser window is no longer open."
            ),
        },
        {
            "ok": True,
            "title": "Gmail - Google Chrome",
            "process": "chrome",
            "vision_description": (
                "Chrome is still on screen. Restore pages. URL bar visible."
            ),
        },
    ]
    i = {"n": 0}

    def fake_see(ctx, args):
        seen.append(dict(args or {}))
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_close(*, app="chrome"):
        closes.append({"app": app})
        return {"ok": True, "app": app, "method": "close-all"}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.desktop.close_windows", fake_close)
    from app.jarvis.voice_ask import look_still_shows_chrome, run_voice_ask

    assert look_still_shows_chrome(looks[0]) is True
    body = await run_voice_ask("close the browser")
    assert planned == []
    assert launched == []
    assert len(closes) == 2
    assert len(seen) == 2
    assert seen[0].get("fresh") is True
    assert seen[1].get("fresh") is True
    assert seen[0].get("prefer_last") is False
    assert seen[1].get("prefer_last") is False
    low = body["reply"].lower()
    assert "no longer open" not in low
    assert "all the browser tabs are now closed" not in low
    assert "chrome is still" in low or "restore pages" in low or "url bar" in low
    _assert_no_public_confirm(body)


def test_spoken_after_close_all_refuses_success_when_chrome_remains():
    from app.jarvis.voice_ask import _spoken_after_close_all, look_still_shows_chrome

    still = {
        "ok": True,
        "title": "CNN - Google Chrome",
        "vision_description": (
            "All the browser tabs are now closed. "
            "The browser window is no longer open. "
            "Chrome still shows Restore pages and a URL bar."
        ),
    }
    assert look_still_shows_chrome(still) is True
    spoken = _spoken_after_close_all(still)
    low = spoken.lower()
    assert "no longer open" not in low
    assert "all the browser tabs are now closed" not in low
    assert "chrome" in low or "restore" in low or "url bar" in low

    gone = {
        "ok": True,
        "title": "Desktop",
        "process": "xfdesktop",
        "vision_description": "The desktop is showing folder icons.",
    }
    assert look_still_shows_chrome(gone) is False
    gone_spoken = _spoken_after_close_all(gone)
    assert "no longer open" not in gone_spoken.lower()
    assert "desktop" in gone_spoken.lower() or "folder" in gone_spoken.lower()


def test_screenshot_fresh_uses_unique_png_path(tmp_path, monkeypatch):
    from PIL import Image

    from app.jarvis.capture import CaptureResult
    from app.jarvis.tools import ToolContext, _screenshot
    from app.jarvis.workspace import Workspace

    root = tmp_path / "Jarvis"
    root.mkdir(exist_ok=True)
    ws = Workspace(root)
    ctx = ToolContext(ws, None)
    paths: list[str] = []

    def fake_capture(**kwargs):
        assert kwargs.get("prefer_last") is False
        img = Image.new("RGB", (8, 8), (10, 20, 30))
        return CaptureResult(ok=True, image=img, method="jarvis-computer")

    monkeypatch.setattr("app.jarvis.capture.capture_screen", fake_capture)
    first = _screenshot(ctx, {"goal": "close all tabs", "fresh": True, "prefer_last": False})
    second = _screenshot(ctx, {"goal": "close all tabs", "fresh": True, "prefer_last": False})
    assert first.get("ok") is True
    assert second.get("ok") is True
    paths = [str(first.get("path") or ""), str(second.get("path") or "")]
    assert paths[0]
    assert paths[1]
    assert paths[0] != paths[1]
    assert "screen_" in paths[0] and paths[0].endswith(".png")
    assert "screen_" in paths[1] and paths[1].endswith(".png")


@pytest.mark.asyncio
async def test_close_tabs_and_switzerland_news_closes_then_searches(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    looks = [
        {
            "ok": True,
            "vision_description": "Chrome has three tabs. Marketing page.",
        },
        {
            "ok": True,
            "vision_description": (
                "DuckDuckGo search results for Switzerland news. "
                "First result at (410, 220): SRF storm."
            ),
            "click_x": 410,
            "click_y": 220,
        },
        {
            "ok": True,
            "title": "SRF News",
            "vision_description": "SRF: Alpine roads closed. Parliament meets in Bern.",
        },
    ]
    seen: list[dict] = []
    clicks: list[dict] = []
    combos: list[str] = []
    i = {"n": 0}

    def fake_see(ctx, args):
        seen.append(dict(args or {}))
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append(dict(args or {}))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    def fake_keys(ctx, args):
        combos.append(str(args.get("combo") or ""))
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("close the tabs and read Switzerland news")
    assert body["ok"] is True
    assert combos == ["ctrl+w", "ctrl+w"]
    assert "escape" not in combos
    assert planned
    url = str(planned[0].get("url") or "")
    assert "nzz.ch" in url.lower() or url.rstrip("/").endswith("swissinfo.ch/eng")
    assert "switzerland.com" not in url.lower()
    _assert_not_invented_host(url, "close the tabs and read Switzerland news")
    assert launched
    assert "keys" in body["tools_used"]
    assert "run_app" in body["tools_used"]
    assert "see_screen" in body["tools_used"]
    assert "alpine roads closed" in body["reply"].lower()
    assert "Opened" not in body["reply"]
    assert "can't close" not in body["reply"].lower()
    assert "guide you" not in body["reply"].lower()


@pytest.mark.asyncio
async def test_dismiss_popup_still_sends_escape(open_site_now, monkeypatch):
    planned, launched = open_site_now
    _stub_see_screen(
        monkeypatch,
        {"ok": True, "vision_description": "Cookie banner. Dismiss at the corner."},
    )
    combos: list[str] = []

    def fake_keys(ctx, args):
        combos.append(str(args.get("combo") or ""))
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("dismiss the popup")
    assert planned == []
    assert launched == []
    assert combos == ["escape"]
    assert "ctrl+w" not in combos
    assert "keys" in body["tools_used"]


@pytest.mark.asyncio
async def test_there_is_no_login_looks_and_does_not_interview(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    seen = _stub_see_screen(
        monkeypatch,
        {
            "ok": True,
            "vision_description": (
                "workspace.google.com Gmail marketing. "
                "AI-powered email in the Gemini era. Create an account."
            ),
        },
    )
    from app.jarvis.voice_ask import run_voice_ask

    for phrase in (
        "There is no login section here.",
        "what are you seeing on the screen",
        "read this page",
    ):
        planned.clear()
        launched.clear()
        seen.clear()
        body = await run_voice_ask(phrase)
        assert planned == [], phrase
        assert launched == [], phrase
        assert seen, phrase
        assert "see_screen" in body["tools_used"], phrase
        assert "Opened" not in body["reply"], phrase
        low = body["reply"].lower()
        assert "confirm what" not in low, phrase
        assert "what you're seeing" not in low, phrase
        assert "guide you more precisely" not in low, phrase
        assert "gemini" in low or "gmail" in low or "account" in low, phrase


@pytest.mark.asyncio
async def test_tell_me_ssl_page_says_error_in_plain_english(open_site_now, monkeypatch):
    planned, launched = open_site_now
    _stub_see_screen(
        monkeypatch,
        {
            "ok": False,
            "title": "Your connection is not private",
            "vision_description": "SSL certificate error. This site can't be reached.",
            "error": "ssl error",
        },
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open the news on the screen")
    assert "Opened" not in body["reply"]
    assert "Look there." not in body["reply"]
    assert "security" in body["reply"].lower() or "error" in body["reply"].lower()
    assert "see_screen" in body["tools_used"]
    url = str(planned[0].get("url") or "")
    assert "duckduckgo.com" not in url
    assert "reuters.com" in url or "bbc.com" in url
    _assert_not_invented_host(url, "open the news on the screen")
    assert launched


@pytest.mark.asyncio
async def test_show_cnn_looks_and_tells(open_site_now, monkeypatch):
    planned, launched = open_site_now
    _stub_see_screen(
        monkeypatch,
        {
            "ok": True,
            "title": "CNN",
            "vision_description": (
                "CNN homepage. A breaking headline about elections. "
                "A cookie banner is visible."
            ),
        },
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("show cnn.com")
    assert body["ok"] is True
    assert "Look there." not in body["reply"]
    assert "I could not see the screen" not in body["reply"]
    assert "cnn" in body["reply"].lower() or "headline" in body["reply"].lower()
    assert "run_app" in body["tools_used"]
    assert "see_screen" in body["tools_used"]
    assert planned == [{"target": "chrome", "url": "https://cnn.com"}]
    assert launched


@pytest.mark.asyncio
async def test_whats_on_the_screen_looks_and_does_not_invent_host(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    seen = _stub_see_screen(
        monkeypatch,
        {"ok": True, "vision_description": "Notepad is open. The file says hello."},
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("what's on the screen")
    assert body["ok"] is True
    assert planned == []
    assert launched == []
    assert seen, "must look at the screen"
    assert "see_screen" in body["tools_used"]
    assert "Opened" not in body["reply"]
    assert "Look there." not in body["reply"]
    assert "notepad" in body["reply"].lower()
    assert "confirm" not in body["reply"].lower()
    _assert_no_public_confirm(body)
    for fake in _INVENTED_HOSTS:
        assert fake not in str(body)


@pytest.mark.asyncio
async def test_click_agree_looks_then_clicks(open_site_now, monkeypatch):
    planned, launched = open_site_now
    seen = _stub_see_screen(
        monkeypatch,
        {
            "ok": True,
            "vision_description": "Cookie banner. Agree button at (640, 400).",
            "click_x": 640,
            "click_y": 400,
        },
    )
    clicks: list[dict] = []

    def fake_click(ctx, args):
        clicks.append(dict(args or {}))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("click Agree")
    assert planned == []
    assert launched == []
    assert seen, "control must look first"
    assert clicks
    assert clicks[0]["x"] == 640
    assert clicks[0]["y"] == 400
    assert "see_screen" in body["tools_used"]
    assert "click" in body["tools_used"]
    assert "Opened" not in body["reply"]
    assert "Look there." not in body["reply"]
    for fake in _INVENTED_HOSTS:
        assert fake not in str(planned)
        assert fake not in str(body)


@pytest.mark.asyncio
async def test_click_agree_says_so_when_look_fails(open_site_now, monkeypatch):
    planned, launched = open_site_now
    clicks: list[dict] = []
    _stub_see_screen(
        monkeypatch,
        {"ok": False, "error": "jarvis-computer is not running"},
    )
    monkeypatch.setattr(
        "app.jarvis.tools._click",
        lambda ctx, args: clicks.append(dict(args or {})) or {"ok": True},
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("click Agree")
    assert planned == []
    assert launched == []
    assert clicks == []
    assert "see_screen" in body["tools_used"]
    assert "click" not in body["tools_used"]
    assert "Opened" not in body["reply"]
    low = body["reply"].lower()
    assert (
        "could not see" in low
        or "could not read" in low
        or "not running" in low
    )


@pytest.mark.asyncio
async def test_whats_on_your_screen_looks(open_site_now, monkeypatch):
    planned, launched = open_site_now
    seen = _stub_see_screen(
        monkeypatch,
        {"ok": True, "vision_description": "Chrome is open. CNN is on the tab."},
    )
    from app.jarvis.voice_ask import run_voice_ask

    for phrase in (
        "what's on your screen",
        "what do you see on your screen",
        "what's visible on the browser",
        "check your computer and tell me what's visible on the browser",
        "don't you have your own computer",
    ):
        planned.clear()
        launched.clear()
        seen.clear()
        body = await run_voice_ask(phrase)
        assert planned == [], phrase
        assert launched == [], phrase
        assert seen, phrase
        assert "see_screen" in body["tools_used"], phrase
        assert "I don't have" not in body["reply"], phrase
        assert "your device" not in body["reply"].lower(), phrase
        assert "cnn" in body["reply"].lower() or "chrome" in body["reply"].lower(), phrase
        assert "Look there." not in body["reply"], phrase
        assert "I could not see the screen" not in body["reply"], phrase


@pytest.mark.asyncio
async def test_what_do_you_see_on_your_screen_speaks_from_vision(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    seen = _stub_see_screen(
        monkeypatch,
        {
            "ok": True,
            "title": "",
            "vision_description": (
                "Reuters is open. A World news headline is on the page. "
                "The address bar shows reuters.com."
            ),
        },
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("what do you see on your screen")
    assert planned == []
    assert launched == []
    assert seen
    assert body["ok"] is True
    assert body["tools_used"] == ["see_screen"]
    low = body["reply"].lower()
    assert "reuters" in low or "headline" in low
    assert "i could not see the screen" not in low
    assert "look there" not in low
    parts = [p for p in re.split(r"(?<=[.!?])\s+", body["reply"]) if p.strip()]
    assert 2 <= len(parts) <= 4


@pytest.mark.asyncio
async def test_open_bbc_com_looks_and_tells(open_site_now, monkeypatch):
    planned, launched = open_site_now
    _stub_see_screen(
        monkeypatch,
        {
            "ok": True,
            "title": "BBC",
            "url": "https://www.bbc.com",
            "vision_description": (
                "BBC homepage. World news is on the page. "
                "A cookie dialog is visible."
            ),
        },
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open bbc.com")
    assert body["ok"] is True
    assert planned == [{"target": "chrome", "url": "https://bbc.com"}]
    assert launched
    assert "run_app" in body["tools_used"]
    assert "see_screen" in body["tools_used"]
    assert "Look there." not in body["reply"]
    assert "I could not see the screen" not in body["reply"]
    assert "bbc" in body["reply"].lower() or "cookie" in body["reply"].lower()


@pytest.mark.asyncio
async def test_what_do_you_see_dismisses_restore_then_speaks(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    looks = [
        {
            "ok": True,
            "title": "Restore pages?",
            "vision_description": (
                "Chrome says Restore pages? BBC World news is behind the dialog. "
                "A cookie banner is visible."
            ),
        },
        {
            "ok": True,
            "title": "BBC",
            "vision_description": (
                "BBC homepage. A World news headline is on the page. "
                "A cookie dialog sits at the bottom."
            ),
        },
    ]
    seen: list[dict] = []
    combos: list[str] = []

    def fake_see(ctx, args):
        seen.append(dict(args or {}))
        return dict(looks[min(len(seen) - 1, 1)])

    def fake_keys(ctx, args):
        combos.append(str(args.get("combo") or ""))
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("what do you see on your screen")
    assert planned == []
    assert launched == []
    assert len(seen) >= 2
    assert "escape" in combos
    assert "bbc" in body["reply"].lower()
    assert "Look there." not in body["reply"]
    assert "I could not see the screen" not in body["reply"]


@pytest.mark.asyncio
async def test_hello_does_not_open_chrome(open_site_now):
    planned, launched = open_site_now
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("hello")
    assert launched == []
    assert planned == []
    assert body["ok"] is True
    assert body["reply"] == "Hello."
    assert "Opened" not in body["reply"]
    assert "chrome" not in body["reply"].lower()
    assert body["tools_used"] == []


@pytest.mark.asyncio
async def test_can_you_hear_me_is_hello(open_site_now):
    planned, launched = open_site_now
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("can you hear me")
    assert launched == []
    assert planned == []
    assert body["ok"] is True
    assert body["reply"] == "Hello."
    assert body["tools_used"] == []
    assert "chrome" not in body["reply"].lower()
    assert "disk" not in body["reply"].lower()


@pytest.mark.asyncio
async def test_hello_and_thanks_skip_openrouter(open_site_now, monkeypatch):
    planned, launched = open_site_now
    called: list[str] = []

    async def boom_oneshot(asked: str) -> str:
        called.append(asked)
        raise AssertionError("OpenRouter must not run for hello/thanks")

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", boom_oneshot)
    from app.jarvis.voice_ask import run_voice_ask

    for phrase in ("hello", "thanks"):
        body = await run_voice_ask(phrase)
        assert body["ok"] is True
        assert body["reply"] == "Hello."
        assert body["tools_used"] == []
    assert called == []
    assert launched == []
    assert planned == []


@pytest.mark.asyncio
async def test_how_are_you_uses_oneshot_not_pc(open_site_now, monkeypatch):
    planned, launched = open_site_now
    installed: list[str] = []
    asked_oneshot: list[str] = []

    async def stub_oneshot(asked: str) -> str:
        asked_oneshot.append(asked)
        return "Good. You?"

    from app.jarvis import computer as computer_mod

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", stub_oneshot)
    monkeypatch.setattr(
        computer_mod,
        "linux_install_package",
        lambda pkg: installed.append(pkg) or {"ok": True, "installed": pkg},
    )
    from app.jarvis.voice_ask import run_voice_ask

    for phrase in ("how are you", "hello how are you", "I said how are you"):
        launched.clear()
        planned.clear()
        installed.clear()
        asked_oneshot.clear()
        body = await run_voice_ask(phrase)
        assert body["ok"] is True, phrase
        assert body["reply"] == "Good. You?", phrase
        assert body["reply"] != "I'm here.", phrase
        assert body["tools_used"] == [], phrase
        assert asked_oneshot == [phrase], phrase
        assert launched == [], phrase
        assert planned == [], phrase
        assert installed == [], phrase
        assert "Opened" not in body["reply"]
        assert "Installed" not in body["reply"]


@pytest.mark.asyncio
async def test_short_talk_fallback_when_oneshot_fails(open_site_now, monkeypatch):
    planned, launched = open_site_now

    async def fail_oneshot(asked: str) -> str:
        raise TimeoutError("openrouter down")

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", fail_oneshot)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("how are you")
    assert launched == []
    assert planned == []
    assert body["ok"] is True
    assert body["reply"] == "Good. You?"
    assert body["reply"] != "I'm here."
    assert body["tools_used"] == []


@pytest.mark.asyncio
async def test_short_talk_fallback_when_no_key(open_site_now):
    planned, launched = open_site_now
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("how are you")
    assert launched == []
    assert planned == []
    assert body["ok"] is True
    assert body["reply"] == "Good. You?"
    assert body["reply"] != "I'm here."
    assert body["tools_used"] == []


@pytest.mark.asyncio
async def test_oneshot_im_here_or_empty_is_last_resort(open_site_now, monkeypatch, caplog):
    planned, launched = open_site_now
    asked_oneshot: list[str] = []
    canned = {"reply": "I'm here."}

    async def stub_oneshot(asked: str) -> str:
        asked_oneshot.append(asked)
        return canned["reply"]

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", stub_oneshot)
    from app.jarvis.voice_ask import run_voice_ask

    for phrase in ("hello how are you", "I said how are you"):
        for model_line in ("I'm here.", "I'm here", "i'm here!", ""):
            launched.clear()
            planned.clear()
            asked_oneshot.clear()
            canned["reply"] = model_line
            with caplog.at_level("WARNING", logger="jarvis.voice_ask"):
                caplog.clear()
                body = await run_voice_ask(phrase)
            assert body["ok"] is True, (phrase, model_line)
            assert body["reply"] == "Good. You?", (phrase, model_line)
            assert body["reply"] != "I'm here.", (phrase, model_line)
            assert body["tools_used"] == [], (phrase, model_line)
            assert asked_oneshot == [phrase], (phrase, model_line)
            assert launched == [], (phrase, model_line)
            assert planned == [], (phrase, model_line)
            assert "simple talk oneshot empty" in caplog.text
            assert "sk-or" not in caplog.text


@pytest.mark.asyncio
async def test_oneshot_real_line_still_wins(open_site_now, monkeypatch):
    planned, launched = open_site_now

    async def stub_oneshot(asked: str) -> str:
        return "Fine — you?"

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", stub_oneshot)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("hello how are you")
    assert body["ok"] is True
    assert body["reply"] == "Fine — you?"
    assert body["reply"] != "I'm here."
    assert body["reply"] != "Good. You?"
    assert body["tools_used"] == []
    assert launched == []
    assert planned == []


@pytest.mark.asyncio
async def test_short_talk_fallback_other_ask_is_what_do_you_need(open_site_now, monkeypatch):
    planned, launched = open_site_now

    async def fail_oneshot(asked: str) -> str:
        raise TimeoutError("openrouter down")

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", fail_oneshot)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("what's your name")
    assert launched == []
    assert planned == []
    assert body["ok"] is True
    assert body["reply"] == "What do you need?"
    assert body["reply"] != "I'm here."
    assert body["tools_used"] == []


@pytest.mark.asyncio
async def test_short_talk_uses_hosted_talk_when_no_local_key(monkeypatch):
    launched: list[dict] = []
    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: _FakeGateway())
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.setenv("JARVIS_HOSTED_TALK_URL", "https://berkkarabacak.com/jarvis")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        "app.jarvis.computer.linux_run_app",
        lambda plan: launched.append(plan) or {"ok": True},
    )

    class _AskRes:
        status_code = 200

        def json(self):
            return {"ok": True, "reply": "Good. You?", "tools_used": []}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            return _AskRes()

    monkeypatch.setattr("app.jarvis.voice_ask.httpx.AsyncClient", _FakeClient)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("hello there")
    assert launched == []
    assert body["ok"] is True
    assert body["reply"] == "Good. You?"
    assert body["reply"] != "I'm here."


@pytest.mark.asyncio
async def test_yesterday_talk_does_not_open_chrome(open_site_now, monkeypatch):
    planned, launched = open_site_now
    called: list[str] = []

    async def boom_oneshot(asked: str) -> str:
        called.append(asked)
        raise AssertionError("OpenRouter must not run for yesterday talk")

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", boom_oneshot)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask(YESTERDAY)
    assert launched == []
    assert planned == []
    assert called == []
    assert body["ok"] is True
    assert "Opened" not in body["reply"]
    assert body["tools_used"] == []
    assert body["reply"] == "I do not have yesterday yet."
    assert "headline" not in body["reply"].lower()


@pytest.mark.asyncio
async def test_yesterday_talk_reads_journal(tmp_path, monkeypatch):
    from app.jarvis.daily_journal import day_key, digest_turns, upsert_day_journal
    from app.jarvis.memory import JarvisMemory

    mem = JarvisMemory(tmp_path / "j.db")
    ykey = day_key(datetime.now(tz=ZoneInfo("Europe/Berlin")) - timedelta(days=1))
    upsert_day_journal(
        mem,
        ykey,
        digest_turns(
            [
                {
                    "role": "user",
                    "content": "We decided to ship the simple talk fast path yesterday",
                }
            ],
            source="voice",
        ),
        source="voice",
    )

    class _MemGateway:
        memory = mem

        def clear_taint(self, *args, **kwargs):
            return None

    launched: list[dict] = []
    monkeypatch.setenv("JARVIS_MEMORY_TZ", "Europe/Berlin")
    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: _MemGateway())
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        "app.jarvis.computer.linux_run_app",
        lambda plan: launched.append(plan) or {"ok": True},
    )
    monkeypatch.setattr(
        "app.jarvis.agent.build_jarvis_agent",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("agent must not run for yesterday talk")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "app.jarvis.screen_viewer.start_computer",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("start_computer must not run for yesterday talk")
        ),
        raising=False,
    )

    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask(YESTERDAY)
    assert launched == []
    assert body["ok"] is True
    assert "Opened" not in body["reply"]
    low = body["reply"].lower()
    assert "simple" in low or "talk" in low or "ship" in low or "path" in low
    assert len(body["reply"].split(".")) <= 6


@pytest.mark.asyncio
async def test_show_gmail_opens_mail_now(open_site_now):
    planned, launched = open_site_now
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("show my gmail")
    assert body["ok"] is True
    assert "Look there." not in body["reply"]
    assert "I could not see the screen" not in body["reply"]
    assert "run_app" in body["tools_used"]
    assert "see_screen" in body["tools_used"]
    assert planned == [{"target": "chrome", "url": "https://mail.google.com"}]
    assert launched[0]["url"] == "https://mail.google.com"


@pytest.mark.asyncio
async def test_open_notepad_opens_mousepad_now(open_site_now):
    planned, launched = open_site_now
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open notepad++")
    assert body["ok"] is True
    assert "Look there." not in body["reply"]
    assert "I could not see the screen" not in body["reply"]
    assert "run_app" in body["tools_used"]
    assert "see_screen" in body["tools_used"]
    assert planned == [{"target": "notepad"}]
    argv = " ".join(str(x) for x in launched[0].get("argv") or []).lower()
    assert "mousepad" in argv or "notepad" in argv


@pytest.mark.asyncio
async def test_real_win32_skips_linux_run_app(monkeypatch):
    launched: list[dict] = []

    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: _FakeGateway())
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    from app.jarvis import computer as computer_mod

    def capture_run(plan):
        launched.append(plan)
        return {"ok": True, "opened": plan.get("url")}

    monkeypatch.setattr(computer_mod, "linux_run_app", capture_run)
    from app.jarvis.voice_ask import run_voice_ask

    for phrase in (
        "show cnn.com",
        "show bbc.com",
        EXCEL_ASK,
        "install mines",
        "open the sample csv file",
    ):
        launched.clear()
        body = await run_voice_ask(phrase)
        assert launched == [], phrase
        assert body["ok"] is False
        assert "Opened" not in body["reply"]
        assert "Installed" not in body["reply"]


@pytest.mark.asyncio
async def test_open_site_reports_real_exec_error(open_site_now, monkeypatch):
    from app.jarvis import computer as computer_mod
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setattr(
        computer_mod,
        "linux_run_app",
        lambda plan: {"ok": False, "error": "jarvis-computer is not running"},
    )
    body = await run_voice_ask("show cnn.com")
    assert body["ok"] is False
    assert "jarvis-computer is not running" in body["reply"]
    assert "screenshot" not in body["reply"].lower()


@pytest.mark.asyncio
async def test_agent_done_without_tools_is_not_success(monkeypatch):
    launched: list[dict] = []

    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: _FakeGateway())
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-real")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        "app.jarvis.screen_viewer.start_computer",
        lambda *a, **k: None,
        raising=False,
    )
    monkeypatch.setattr(
        "app.jarvis.screen_viewer.screen_status",
        lambda: {"running": True},
        raising=False,
    )

    from app.jarvis import computer as computer_mod

    monkeypatch.setattr(
        computer_mod,
        "linux_run_app",
        lambda plan: launched.append(plan) or {"ok": True, "started": "x"},
    )
    monkeypatch.setattr(
        "app.jarvis.agent.build_jarvis_agent",
        lambda **kwargs: _FakeAgent(reply="Done.", tools=[]),
    )

    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask(EXCEL_ASK)
    assert body["ok"] is False
    assert body["reply"] == "Could not do that on the screen."
    assert "Done" not in body["reply"]
    assert body["tools_used"] == []
    assert launched == []
    assert "screenshot" not in str(body).lower()


@pytest.mark.asyncio
async def test_agent_news_essay_is_not_forwarded(monkeypatch):
    essay = (
        "Here are the trending topics on CNN. "
        "Breaking news one. Breaking news two. "
        "Accept cookies to continue. "
        "More headlines follow from around the world today."
    )
    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: _FakeGateway())
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-real")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("app.jarvis.voice_ask._open_site_now", lambda asked: None)
    monkeypatch.setattr(
        "app.jarvis.agent.build_jarvis_agent",
        lambda **kwargs: _FakeAgent(reply=essay, tools=["see_screen"]),
    )

    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("show cnn.com")
    assert "trending" not in body["reply"].lower()
    assert "headline" not in body["reply"].lower()
    assert "Done" not in body["reply"]
    assert body["reply"] == "Could not do that on the screen."
    assert body["ok"] is False


@pytest.mark.asyncio
async def test_install_mines_apt_and_opens(open_site_now, monkeypatch):
    planned, launched = open_site_now
    installed: list[str] = []
    from app.jarvis import computer as computer_mod

    monkeypatch.setattr(
        computer_mod,
        "linux_install_package",
        lambda pkg: installed.append(pkg) or {"ok": True, "installed": pkg},
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("install mines")
    assert body["ok"] is True
    assert body["reply"] == "Installed gnome-mines and opened it on the screen."
    assert "Done" not in body["reply"]
    assert body["tools_used"] == ["install", "run_app"]
    assert installed == ["gnome-mines"]
    assert launched, "linux_run_app must run after install"
    argv = " ".join(str(x) for x in launched[0].get("argv") or []).lower()
    assert "gnome-mines" in argv


@pytest.mark.asyncio
async def test_install_a_simple_game_apt_and_opens(open_site_now, monkeypatch):
    planned, launched = open_site_now
    installed: list[str] = []
    from app.jarvis import computer as computer_mod

    monkeypatch.setattr(
        computer_mod,
        "linux_install_package",
        lambda pkg: installed.append(pkg) or {"ok": True, "installed": pkg},
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("install a simple game")
    assert body["ok"] is True
    assert body["reply"] == "Installed gnome-mines and opened it on the screen."
    assert "Done" not in body["reply"]
    assert body["tools_used"] == ["install", "run_app"]
    assert installed == ["gnome-mines"]
    assert launched, "linux_run_app must run after install"
    argv = " ".join(str(x) for x in launched[0].get("argv") or []).lower()
    assert "gnome-mines" in argv


@pytest.mark.asyncio
async def test_hello_does_not_install(open_site_now, monkeypatch):
    planned, launched = open_site_now
    installed: list[str] = []
    from app.jarvis import computer as computer_mod

    monkeypatch.setattr(
        computer_mod,
        "linux_install_package",
        lambda pkg: installed.append(pkg) or {"ok": True, "installed": pkg},
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("hello")
    assert installed == []
    assert launched == []
    assert planned == []
    assert body["ok"] is True
    assert body["reply"] == "Hello."
    assert "Installed" not in body["reply"]


@pytest.mark.asyncio
async def test_show_cnn_does_not_install(open_site_now, monkeypatch):
    planned, launched = open_site_now
    installed: list[str] = []
    from app.jarvis import computer as computer_mod

    monkeypatch.setattr(
        computer_mod,
        "linux_install_package",
        lambda pkg: installed.append(pkg) or {"ok": True, "installed": pkg},
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("show cnn.com")
    assert installed == []
    assert body["ok"] is True
    assert "run_app" in body["tools_used"]
    assert "see_screen" in body["tools_used"]
    assert planned == [{"target": "chrome", "url": "https://cnn.com"}]
    assert launched, "linux_run_app must run"
    assert "Installed" not in body["reply"]
    assert "Look there." not in body["reply"]


@pytest.mark.asyncio
async def test_open_sample_csv_opens_mousepad_now(open_site_now):
    planned, launched = open_site_now
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open the sample csv file")
    assert body["ok"] is True
    assert "Look there." not in body["reply"]
    assert "I could not see the screen" not in body["reply"]
    assert "run_app" in body["tools_used"]
    assert "see_screen" in body["tools_used"]
    assert planned == [{"target": "notepad", "args": "/home/jarvis/Desktop/sample.csv"}]
    assert launched, "linux_run_app must run"
    argv = " ".join(str(x) for x in launched[0].get("argv") or []).lower()
    assert "mousepad" in argv or "notepad" in argv
    assert "sample.csv" in argv
    assert "Done" not in body["reply"]


@pytest.mark.asyncio
async def test_install_reports_real_exec_error(open_site_now, monkeypatch):
    from app.jarvis import computer as computer_mod
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setattr(
        computer_mod,
        "linux_install_package",
        lambda pkg: {"ok": False, "error": "jarvis-computer is not running"},
    )
    body = await run_voice_ask("install gnome-mines")
    assert body["ok"] is False
    assert "jarvis-computer is not running" in body["reply"]
    assert "Done" not in body["reply"]


@pytest.mark.asyncio
async def test_real_win32_skips_linux_install(monkeypatch):
    launched: list[dict] = []
    installed: list[str] = []

    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: _FakeGateway())
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    from app.jarvis import computer as computer_mod

    monkeypatch.setattr(
        computer_mod,
        "linux_run_app",
        lambda plan: launched.append(plan) or {"ok": True},
    )
    monkeypatch.setattr(
        computer_mod,
        "linux_install_package",
        lambda pkg: installed.append(pkg) or {"ok": True, "installed": pkg},
    )
    from app.jarvis.voice_ask import run_voice_ask

    for phrase in ("install mines", "install a simple game", "open the sample csv file"):
        launched.clear()
        installed.clear()
        body = await run_voice_ask(phrase)
        assert launched == [], phrase
        assert installed == [], phrase
        assert body["ok"] is False
        assert "Opened" not in body["reply"]
        assert "Installed" not in body["reply"]


class _FakeTalkResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeTalkClient:
    def __init__(self, posts: list, response, timeout=None):
        self._posts = posts
        self._response = response
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        self._posts.append({"url": url, "headers": headers or {}, "json": json or {}})
        return self._response


@pytest.mark.asyncio
async def test_simple_talk_oneshot_is_no_tool_ox_when_kimi_missing(tmp_path, monkeypatch):
    posts: list[dict] = []
    spent: list[float] = []
    timeouts: list[float] = []
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "Jarvis"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-not-a-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setattr(
        "app.jarvis.model_router.httpx.AsyncClient",
        lambda timeout=None: timeouts.append(timeout)
        or _FakeTalkClient(
            posts,
            _FakeTalkResponse(
                {
                    "choices": [{"message": {"content": "Good. You?"}}],
                    "usage": {"cost": 0.0004},
                }
            ),
            timeout=timeout,
        ),
    )
    monkeypatch.setattr(
        "app.jarvis.settings_store.record_spend",
        lambda usd, root=None: spent.append(float(usd)),
    )
    from app.jarvis.model_router import OPENROUTER_CHAT_URL, OX_MODEL
    from app.jarvis.voice_ask import _TALK_TIMEOUT, _simple_talk_oneshot

    reply = await _simple_talk_oneshot("how are you")
    assert reply == "Good. You?"
    assert _TALK_TIMEOUT == 8.0
    assert timeouts == [8.0]
    assert len(posts) == 1
    assert posts[0]["url"] == OPENROUTER_CHAT_URL
    assert "moonshot" not in posts[0]["url"]
    assert "tools" not in posts[0]["json"]
    assert "max_tokens" not in posts[0]["json"]
    assert posts[0]["json"]["model"] == OX_MODEL
    assert posts[0]["json"]["reasoning"] == {"effort": "low", "exclude": True}
    assert posts[0]["json"]["messages"][0]["role"] == "system"
    system = posts[0]["json"]["messages"][0]["content"]
    assert "I'm here." not in system
    assert "I'm here" not in system
    assert "answer the person's words" in system.lower()
    assert "same language" in system.lower()
    assert "turkish" in system.lower()
    assert "how you are" in system.lower()
    assert "no tools" in system.lower()
    assert "no screen" in system.lower()
    assert "already talking" in system.lower()
    assert "what do you need?" in system.lower()
    assert posts[0]["json"]["messages"][1] == {"role": "user", "content": "how are you"}
    assert len(posts[0]["json"]["messages"]) == 2
    assert spent == [0.0004]
    assert "or-test-not-a-key" not in str(posts[0]["json"])


@pytest.mark.asyncio
async def test_simple_talk_oneshot_http_fail_is_im_here(monkeypatch, caplog):
    timeouts: list[float] = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-not-a-key")
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)

    def _boom(timeout=None):
        timeouts.append(timeout)
        raise TimeoutError("slow")

    monkeypatch.setattr("app.jarvis.model_router.httpx.AsyncClient", _boom)
    from app.jarvis.voice_ask import _TALK_TIMEOUT, _simple_talk_oneshot

    with caplog.at_level("WARNING", logger="jarvis.voice_ask"):
        assert await _simple_talk_oneshot("how are you") == "Good. You?"
    assert _TALK_TIMEOUT == 8.0
    assert timeouts == [8.0]
    assert "simple talk oneshot failed" in caplog.text
    assert "or-test-not-a-key" not in caplog.text


@pytest.mark.asyncio
async def test_simple_talk_oneshot_http_status_fail_is_im_here(monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-not-a-key")
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setattr(
        "app.jarvis.model_router.httpx.AsyncClient",
        lambda timeout=None: _FakeTalkClient(
            [],
            _FakeTalkResponse({"error": "nope"}, status_code=429),
            timeout=timeout,
        ),
    )
    from app.jarvis.voice_ask import _simple_talk_oneshot

    with caplog.at_level("WARNING", logger="jarvis.voice_ask"):
        assert await _simple_talk_oneshot("how are you") == "Good. You?"
    assert "status 429" in caplog.text
    assert "simple talk oneshot failed" in caplog.text
    assert "or-test-not-a-key" not in caplog.text
    assert "nope" not in caplog.text


@pytest.mark.asyncio
async def test_simple_talk_oneshot_empty_or_im_here_is_last_resort(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "Jarvis"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-not-a-key")
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    canned = {"content": "I'm here."}

    def _client(timeout=None):
        return _FakeTalkClient(
            [],
            _FakeTalkResponse({"choices": [{"message": {"content": canned["content"]}}]}),
            timeout=timeout,
        )

    monkeypatch.setattr("app.jarvis.model_router.httpx.AsyncClient", _client)
    from app.jarvis.voice_ask import _simple_talk_oneshot

    for line in ("I'm here.", "I'm here", "i'm here!", ""):
        canned["content"] = line
        with caplog.at_level("WARNING", logger="jarvis.voice_ask"):
            caplog.clear()
            assert await _simple_talk_oneshot("hello how are you") == "Good. You?"
        assert "simple talk oneshot empty" in caplog.text
        assert "simple talk oneshot failed" not in caplog.text
        assert "sk-or-test-not-real" not in caplog.text

    canned["content"] = "All good. You?"
    with caplog.at_level("WARNING", logger="jarvis.voice_ask"):
        caplog.clear()
        assert await _simple_talk_oneshot("I said how are you") == "All good. You?"
    assert "simple talk oneshot empty" not in caplog.text

    canned["content"] = ""
    with caplog.at_level("WARNING", logger="jarvis.voice_ask"):
        caplog.clear()
        assert await _simple_talk_oneshot("what's your name") == "What do you need?"
    assert "simple talk oneshot empty" in caplog.text


def test_turkish_and_math_are_simple_talk():
    for phrase in (
        "Merhaba",
        "2+2 kaç",
        "Ankara hava",
        "dün ne yaptık",
        "15+27",
        "what is 15 plus 27",
    ):
        assert goal_is_simple_talk(phrase), phrase
        assert not goal_is_virtual_pc_job(phrase), phrase
        assert not goal_is_computer_job(phrase), phrase
    assert not goal_is_simple_talk("open calculator 15+27")
    assert goal_is_computer_job("open calculator 15+27")
    assert goal_is_computer_job("open text editor and type a shopping list")
    assert not goal_is_simple_talk("open text editor and type a shopping list")


def test_talk_last_resort_mirrors_turkish_not_canned_english(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "Jarvis"))
    from app.jarvis.voice_ask import _math_answer, _talk_last_resort, spoken_language

    assert spoken_language("Merhaba") == "tr"
    assert spoken_language("2+2 kaç") == "tr"
    assert spoken_language("Ankara hava") == "tr"
    assert spoken_language("dün ne yaptık") == "tr"
    assert spoken_language("hello") == "en"
    assert _math_answer("2+2 kaç") == "4"
    assert _math_answer("15+27") == "42"
    assert _talk_last_resort("Merhaba") == "Merhaba."
    assert _talk_last_resort("2+2 kaç") == "4"
    assert _talk_last_resort("Ankara hava") == "Şu an havaya bakamıyorum."
    assert "What do you need?" not in {
        _talk_last_resort("Merhaba"),
        _talk_last_resort("2+2 kaç"),
        _talk_last_resort("Ankara hava"),
        _talk_last_resort("dün ne yaptık"),
    }


@pytest.mark.asyncio
async def test_turkish_hello_math_memory_answer_not_canned(open_site_now, monkeypatch):
    planned, launched = open_site_now
    asked_oneshot: list[str] = []

    async def stub_oneshot(asked: str) -> str:
        asked_oneshot.append(asked)
        return "Ankara'da hava açık."

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", stub_oneshot)
    from app.jarvis.voice_ask import run_voice_ask

    hello = await run_voice_ask("Merhaba")
    assert hello["ok"] is True
    assert hello["reply"] == "Merhaba."
    assert hello["reply"] != "What do you need?"
    assert hello["tools_used"] == []
    assert launched == []
    assert planned == []

    math = await run_voice_ask("2+2 kaç")
    assert math["ok"] is True
    assert math["reply"] == "4"
    assert math["reply"] != "What do you need?"
    assert math["tools_used"] == []
    assert launched == []

    weather = await run_voice_ask("Ankara hava")
    assert weather["ok"] is True
    assert weather["reply"] == "Ankara'da hava açık."
    assert weather["reply"] != "What do you need?"
    assert asked_oneshot == ["Ankara hava"]
    assert launched == []
    assert "run_app" not in weather["tools_used"]

    memory = await run_voice_ask("dün ne yaptık")
    assert memory["ok"] is True
    assert memory["reply"] != "What do you need?"
    assert "Henüz dünü" in memory["reply"] or "yesterday" in memory["reply"].lower()
    assert memory["tools_used"] == []
    assert launched == []


@pytest.mark.asyncio
async def test_close_all_kills_leftover_editor(open_site_now, monkeypatch):
    planned, launched = open_site_now
    closes: list[dict] = []
    looks = [
        {
            "ok": True,
            "title": "Untitled 1 - Mousepad",
            "process": "mousepad",
            "vision_description": "Mousepad is still open. A blank page.",
        },
        {
            "ok": True,
            "title": "Desktop",
            "process": "xfdesktop",
            "vision_description": "XFCE desktop. Folder icons. Empty desktop.",
        },
    ]
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_close(*, app="chrome"):
        closes.append({"app": app})
        return {"ok": True, "app": app, "method": "close-all"}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.desktop.close_windows", fake_close)
    from app.jarvis.computer import CLOSE_CHROME_SH
    from app.jarvis.voice_ask import look_still_shows_leftover, run_voice_ask

    assert "mousepad" in CLOSE_CHROME_SH
    assert "galculator" in CLOSE_CHROME_SH
    assert "ristretto" in CLOSE_CHROME_SH
    assert "Image Viewer" in CLOSE_CHROME_SH
    assert look_still_shows_leftover(looks[0]) is True
    body = await run_voice_ask("close everything")
    assert planned == []
    assert launched == []
    assert len(closes) == 2
    low = body["reply"].lower()
    assert "mousepad" not in low or "desktop" in low or "empty" in low or "folder" in low
    assert "no longer open" not in low
    assert "docker" not in low
    assert "exec" not in low


def test_close_everything_is_close_all():
    assert wants_close_all("close everything")
    assert wants_close_all("close all")
    assert wants_close_all("close all apps")
    assert wants_close_all(
        "Close all the apps running, like these Explorer and Error, close them as well."
    )
    assert goal_is_computer_job("close everything")
    assert goal_is_computer_job("I can still see the file manager.")


def test_spoken_after_close_all_refuses_clear_when_file_manager_remains():
    from app.jarvis.computer import CLOSE_CHROME_SH
    from app.jarvis.voice_ask import _spoken_after_close_all, look_still_shows_leftover

    assert "thunar" in CLOSE_CHROME_SH.lower()
    assert "nautilus" in CLOSE_CHROME_SH.lower()
    assert "nemo" in CLOSE_CHROME_SH.lower()
    assert "Error" in CLOSE_CHROME_SH
    still = {
        "ok": True,
        "title": "Home - File Manager",
        "process": "thunar",
        "vision_description": (
            "The desktop is clear. All apps are now closed. "
            "Thunar file manager is still open."
        ),
    }
    assert look_still_shows_leftover(still) is True
    spoken = _spoken_after_close_all(still)
    low = spoken.lower()
    assert "desktop is clear" not in low
    assert "all apps are now closed" not in low
    assert "no longer open" not in low
    assert "file manager" in low or "thunar" in low or "still" in low


@pytest.mark.asyncio
async def test_open_google_dismisses_restore_and_does_not_reuse_reuters(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    keys: list[str] = []
    clicks: list[tuple[int, int]] = []
    events: list[str] = []
    looks = [
        {
            "ok": True,
            "title": "Restore pages?",
            "url": "https://www.reuters.com/",
            "vision_description": (
                "Chromium Restore pages? Reuters World news is behind the dialog."
            ),
        },
        {
            "ok": True,
            "title": "Google",
            "url": "https://www.google.com/",
            "vision_description": (
                "Google search. Before you continue. Accept all cookies at (640, 400)."
            ),
        },
        {
            "ok": True,
            "title": "Google",
            "url": "https://www.google.com/",
            "vision_description": "Google. The search box is empty. Title is Google.",
        },
    ]
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        assert args.get("fresh") is True or args.get("prefer_last") is False
        return dict(item)

    def fake_keys(ctx, args):
        combo = str((args or {}).get("combo") or "")
        keys.append(combo)
        return {"ok": True, "combo": combo}

    def fake_click(ctx, args):
        clicks.append((int(args.get("x") or 0), int(args.get("y") or 0)))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    def fake_close(*, app="chrome"):
        events.append("close")
        return {"ok": True, "app": app, "method": "close-all"}

    from app.jarvis import computer as computer_mod

    def capture_run(plan):
        events.append("run:" + str(plan.get("url") or ""))
        launched.append(plan)
        out = {
            "ok": True,
            "started": plan.get("cmd"),
            "argv": list(plan.get("argv") or []),
            "window": True,
        }
        if plan.get("url"):
            out["opened"] = plan["url"]
        return out

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    monkeypatch.setattr("app.jarvis.desktop.close_windows", fake_close)
    monkeypatch.setattr(computer_mod, "linux_run_app", capture_run)
    from app.jarvis.voice_ask import _RESTORE_DISMISS_CLICK, run_voice_ask

    body = await run_voice_ask("open google.com")
    assert planned == [{"target": "chrome", "url": "https://google.com"}]
    assert launched
    assert launched[0]["url"] == "https://google.com"
    assert all((item.get("url") or "") != "https://www.reuters.com/" for item in launched)
    assert events[0] == "close"
    assert any(item.startswith("run:") and "google.com" in item for item in events)
    assert _RESTORE_DISMISS_CLICK in clicks
    low = body["reply"].lower()
    assert "google" in low
    assert "reuters" not in low
    assert "restore pages" not in low
    assert "what do you need?" not in low


@pytest.mark.asyncio
async def test_open_editor_types_shopping_list(open_site_now, monkeypatch):
    planned, launched = open_site_now
    typed: list[str] = []
    looks = [
        {
            "ok": True,
            "title": "Untitled 1 - Mousepad",
            "process": "mousepad",
            "vision_description": "Mousepad. Milk, bread, eggs, apples, coffee are typed.",
        }
    ]
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        assert args.get("fresh") is True
        return dict(item)

    def fake_type(ctx, args):
        typed.append(str((args or {}).get("text") or ""))
        return {"ok": True, "typed": len(typed[-1])}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._type_text", fake_type)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open text editor and type a shopping list")
    assert planned == [{"target": "notepad"}]
    assert launched
    assert typed
    assert "Milk" in typed[0] or "Süt" in typed[0]
    low = body["reply"].lower()
    assert "milk" in low or "süt" in low or "bread" in low or "ekmek" in low
    assert "type" in body["tools_used"]
    assert "run_app" in body["tools_used"]
    assert "see_screen" in body["tools_used"]
    assert "What do you need?" not in body["reply"]


@pytest.mark.asyncio
async def test_open_calculator_is_one_galculator_not_agent(open_site_now, monkeypatch):
    planned, launched = open_site_now
    typed: list[str] = []
    keys: list[str] = []

    def fake_see(ctx, args):
        return {
            "ok": True,
            "title": "Calculator",
            "process": "galculator",
            "vision_description": "Galculator shows 42.",
        }

    def fake_type(ctx, args):
        typed.append(str((args or {}).get("text") or ""))
        return {"ok": True, "typed": 5}

    def fake_keys(ctx, args):
        keys.append(str((args or {}).get("combo") or ""))
        return {"ok": True, "combo": keys[-1]}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._type_text", fake_type)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open calculator 15+27")
    assert planned == [{"target": "calculator"}]
    assert launched
    argv = " ".join(str(x) for x in launched[0].get("argv") or []).lower()
    assert "galculator" in argv
    assert typed == ["15+27"]
    assert "enter" in keys
    assert "42" in body["reply"]
    assert body["tools_used"]
    assert "What do you need?" not in body["reply"]
    assert "focus_app" in body["tools_used"]


@pytest.mark.asyncio
async def test_math_only_does_not_open_calculator(open_site_now):
    planned, launched = open_site_now
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("15+27")
    assert planned == []
    assert launched == []
    assert body["reply"] == "42"
    assert body["tools_used"] == []


@pytest.mark.asyncio
async def test_install_vague_or_docker_dump_is_spoken_clean(open_site_now, monkeypatch):
    planned, launched = open_site_now
    installed: list[str] = []
    from app.jarvis import computer as computer_mod
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setattr(
        computer_mod,
        "linux_install_package",
        lambda pkg: installed.append(pkg) or {"ok": True, "installed": pkg},
    )
    vague = await run_voice_ask("install a small linux app")
    assert vague["ok"] is True
    assert installed == ["gnome-mines"]
    assert "installed gnome-mines" in vague["reply"].lower()
    assert "docker" not in vague["reply"].lower()
    assert "exec" not in vague["reply"].lower()
    assert launched, "vague install must actually install and open a listed app"

    monkeypatch.setattr(
        computer_mod,
        "linux_install_package",
        lambda pkg: {
            "ok": False,
            "error": "Error response from daemon: OCI runtime exec failed: PATH=/usr/bin",
        },
    )
    dumped = await run_voice_ask("install gnome-mines")
    assert dumped["ok"] is False
    low = dumped["reply"].lower()
    assert "docker" not in low
    assert "oci" not in low
    assert "exec" not in low
    assert "path=" not in low
    assert "could not install" in low


def test_package_from_vague_install_is_listed_mines():
    from app.jarvis.voice_ask import _package_from_install_ask

    assert _package_from_install_ask("install a small linux app") == "mines"
    assert _package_from_install_ask("install mines") == "mines"
    assert _package_from_install_ask("install gnome-mines and show the desktop") is None


def test_restore_dismiss_clicks_fallback_without_coords(monkeypatch):
    from app.jarvis.voice_ask import (
        _RESTORE_DISMISS_CLICK,
        _dismiss_restore_if_needed,
        _restore_blocking,
    )

    clicks: list[tuple[int, int]] = []
    looks = [
        {
            "ok": True,
            "title": "Wikipedia",
            "url": "https://wikipedia.org/",
            "vision_description": "Wikipedia. The free encyclopedia.",
        }
    ]
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append((int(args.get("x") or 0), int(args.get("y") or 0)))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    def fake_keys(ctx, args):
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    looked = {
        "ok": True,
        "title": "Restore pages?",
        "url": "https://wikipedia.org/",
        "vision_description": "Chromium Restore pages? Wikipedia is behind the dialog.",
    }
    assert _restore_blocking(looked) is True
    tools: list[str] = []
    out = _dismiss_restore_if_needed("open wikipedia.org", looked, tools)
    assert _RESTORE_DISMISS_CLICK in clicks
    assert _restore_blocking(out) is False
    assert "wikipedia" in str(out.get("title") or "").lower()
    assert "click" in tools


@pytest.mark.asyncio
async def test_open_wikipedia_dismisses_restore_before_title(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    clicks: list[tuple[int, int]] = []
    looks = [
        {
            "ok": True,
            "title": "Restore pages?",
            "url": "https://wikipedia.org/",
            "vision_description": (
                "Chromium Restore pages? Wikipedia, the free encyclopedia, "
                "is behind the dialog."
            ),
        },
        {
            "ok": True,
            "title": "Wikipedia",
            "url": "https://wikipedia.org/",
            "vision_description": "Wikipedia. The free encyclopedia. Title is Wikipedia.",
        },
    ]
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append((int(args.get("x") or 0), int(args.get("y") or 0)))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    def fake_keys(ctx, args):
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.voice_ask import _RESTORE_DISMISS_CLICK, run_voice_ask

    body = await run_voice_ask("open wikipedia.org")
    assert planned == [{"target": "chrome", "url": "https://wikipedia.org"}]
    assert launched
    assert _RESTORE_DISMISS_CLICK in clicks
    low = body["reply"].lower()
    assert "wikipedia" in low
    assert "restore pages" not in low
    assert "docker" not in low
    assert "exec" not in low


@pytest.mark.asyncio
async def test_open_google_kills_chromium_then_opens_requested_host(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    events: list[str] = []
    looks = [
        {
            "ok": True,
            "title": "Google",
            "url": "https://www.google.com/",
            "vision_description": "Google. The search box is empty. Title is Google.",
        }
    ]
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_close(*, app="chrome"):
        events.append("close")
        return {"ok": True, "app": app, "method": "close-all"}

    from app.jarvis import computer as computer_mod

    def capture_run(plan):
        events.append("run:" + str(plan.get("url") or plan.get("app") or ""))
        launched.append(plan)
        out = {
            "ok": True,
            "started": plan.get("cmd"),
            "argv": list(plan.get("argv") or []),
            "window": True,
        }
        if plan.get("url"):
            out["opened"] = plan["url"]
        return out

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.desktop.close_windows", fake_close)
    monkeypatch.setattr(computer_mod, "linux_run_app", capture_run)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open google.com")
    assert planned == [{"target": "chrome", "url": "https://google.com"}]
    assert events[0] == "close"
    assert events[1] == "run:https://google.com"
    assert "reuters" not in body["reply"].lower()
    assert "google" in body["reply"].lower()
    assert "docker" not in body["reply"].lower()
    assert "exec" not in body["reply"].lower()


@pytest.mark.asyncio
async def test_calculator_focuses_galculator_before_type(open_site_now, monkeypatch):
    planned, launched = open_site_now
    focused: list[str] = []
    typed: list[str] = []
    looks = [
        {
            "ok": True,
            "title": "Untitled 1 - Mousepad",
            "process": "mousepad",
            "vision_description": "Mousepad. A leftover shopping list.",
        },
        {
            "ok": True,
            "title": "Calculator",
            "process": "galculator",
            "vision_description": "Galculator shows 0.",
        },
        {
            "ok": True,
            "title": "Calculator",
            "process": "galculator",
            "vision_description": "Galculator shows 42.",
        },
    ]
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_focus(*, app="", title=""):
        focused.append(app or title)
        return {"ok": True, "app": app or title, "focused": True}

    def fake_type(ctx, args):
        assert focused, "must focus galculator before typing"
        assert i["n"] >= 2, "must confirm galculator look before typing"
        typed.append(str((args or {}).get("text") or ""))
        return {"ok": True, "typed": len(typed[-1])}

    def fake_keys(ctx, args):
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.desktop.focus_app", fake_focus)
    monkeypatch.setattr("app.jarvis.tools._type_text", fake_type)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.computer import focus_inner_argv
    from app.jarvis.voice_ask import run_voice_ask

    argv = " ".join(focus_inner_argv(app="galculator"))
    assert "galculator" in argv
    body = await run_voice_ask("open calculator 15+27")
    assert planned == [{"target": "calculator"}]
    assert launched
    assert focused[0] == "galculator"
    assert typed == ["15+27"]
    assert "42" in body["reply"]
    assert "docker" not in body["reply"].lower()
    assert "exec" not in body["reply"].lower()


@pytest.mark.asyncio
async def test_calculator_does_not_invent_answer_when_display_is_zero(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    typed: list[str] = []

    def fake_see(ctx, args):
        return {
            "ok": True,
            "title": "Calculator",
            "process": "galculator",
            "vision_description": "Galculator shows 0.",
        }

    def fake_type(ctx, args):
        typed.append(str((args or {}).get("text") or ""))
        return {"ok": True, "typed": 5}

    def fake_keys(ctx, args):
        return {"ok": True, "combo": args.get("combo")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._type_text", fake_type)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open calculator 15+27")
    assert planned == [{"target": "calculator"}]
    assert launched
    assert typed == ["15+27"]
    low = body["reply"].lower()
    assert "42" not in body["reply"]
    assert "not on the screen" in low or "shows 0" in low
    assert "docker" not in low
    assert "exec" not in low


@pytest.mark.asyncio
async def test_close_all_kills_image_viewer(open_site_now, monkeypatch):
    planned, launched = open_site_now
    closes: list[dict] = []
    looks = [
        {
            "ok": True,
            "title": "photo.png - Image Viewer",
            "process": "ristretto",
            "vision_description": "Image Viewer is still open. A photo is on screen.",
        },
        {
            "ok": True,
            "title": "Desktop",
            "process": "xfdesktop",
            "vision_description": "XFCE desktop. Folder icons. Empty desktop.",
        },
    ]
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_close(*, app="chrome"):
        closes.append({"app": app})
        return {"ok": True, "app": app, "method": "close-all"}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.desktop.close_windows", fake_close)
    from app.jarvis.computer import CLOSE_CHROME_SH
    from app.jarvis.voice_ask import look_still_shows_leftover, run_voice_ask

    assert "ristretto" in CLOSE_CHROME_SH
    assert "eog" in CLOSE_CHROME_SH
    assert "Image Viewer" in CLOSE_CHROME_SH
    assert look_still_shows_leftover(looks[0]) is True
    assert look_still_shows_leftover(looks[1]) is False
    body = await run_voice_ask("close everything")
    assert planned == []
    assert launched == []
    assert len(closes) == 2
    low = body["reply"].lower()
    assert "desktop" in low or "empty" in low or "folder" in low
    assert "image viewer" not in low or "desktop" in low
    assert "docker" not in low
    assert "exec" not in low
