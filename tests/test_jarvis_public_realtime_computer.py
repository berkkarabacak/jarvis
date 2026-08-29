"""Public / hosted Realtime talks on jarvis-computer, not a Windows laptop."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.jarvis.computer import JARVIS_COMPUTER, resolve_desktop_backend
from app.jarvis.realtime import (
    JARVIS_PUBLIC_REALTIME_INSTRUCTIONS,
    JARVIS_REALTIME_INSTRUCTIONS,
    build_instructions,
    prepare_realtime_tool_call,
    realtime_model,
    session_instructions,
    tools_for_realtime,
)
from app.jarvis.virtual_pc import (
    goal_is_computer_job,
    goal_is_simple_talk,
    hosted_linux_talk,
    wants_chat_only_desktop_skip,
    wants_look_job,
)

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "deploy" / "jarvis-public" / "index.html"


@pytest.fixture(autouse=True)
def _reset_last_look():
    from app.jarvis.capture import reset_last_look

    reset_last_look()
    yield
    reset_last_look()


def test_hosted_linux_talk_ignores_windows_host_os_pin():
    assert hosted_linux_talk({"JARVIS_HOST_OS": "windows"}) is True
    assert hosted_linux_talk(platform="linux") is True
    assert hosted_linux_talk(platform="win32") is False


def test_realtime_instructions_mirror_speaker_language():
    for text in (JARVIS_PUBLIC_REALTIME_INSTRUCTIONS, JARVIS_REALTIME_INSTRUCTIONS):
        low = text.lower()
        assert "the page locale" in low
        assert "after they speak, answer in the language they just used" in low
        assert "that overrides the locale" in low
        assert "never pick a random romance language" in low
        assert "olá" in low
        assert "do not switch mid-conversation unless they switched" in low
        assert "do not guess a language from a name" in low
        assert "pronunciation" in low
        assert "improve my english" in low
        assert "how do i say" in low
        assert "no tools for that" in low
        assert "coach in the language they asked in" in low
        assert "hello / how are you: just talk" in low
        assert "oi! eu estou bem" not in low
        assert "default spoken language is english" not in low
        assert "if unsure, english" not in low
        assert low.find("the page locale") < low.find("you are jarvis")


def test_public_realtime_instructions_are_not_windows_laptop():
    text = JARVIS_PUBLIC_REALTIME_INSTRUCTIONS
    low = text.lower()
    assert "berkly's hosted page" in low or "berkly" in low
    assert "jarvis-computer" in low
    assert "screen pane" in low
    assert "windows laptop" not in low
    assert "c: drive" not in low
    assert "c:" not in text
    assert "windows host" not in low
    assert "your device" in low
    assert "i don't have a screen view" in low
    assert "see_screen" in text
    assert "vision_description" in text
    assert "get_disk_space" in text
    assert "never call get_disk_space unless" in low
    assert "spawn_child" in text
    assert "helpers are extra" in low
    assert "i'll make five different games" in low
    assert "child_limit is not a stop" in low
    assert "making the next ones" in low
    assert "always speak a real sentence" in low
    assert "never stay silent" in low
    assert "never say only {}" in low or "never say only {}" in text.lower()
    assert "ctrl+w" in low
    assert "close-all" in low or "every chrome window" in low
    assert "window is no longer open" in low
    assert "can't close tabs" in low or "cannot close tabs" in low
    assert "what are you seeing" in low
    assert "guide you more precisely" in low
    assert "never" in low
    assert "duckduckgo" in low
    assert "restore pages" in low
    assert "serp is not done" in low
    assert "after a click batch" in low or "batch clicks" in low
    assert "reuters" in low
    assert "swissinfo" in low or "nzz.ch" in low
    assert "never tell them to click" in low
    assert "news-card" in low or "news card" in low
    assert "do not invent hosts" in low
    assert "skip focus_app" in low
    assert "do not catalog" in low or "catalog of icons" in low
    assert "one short line" in low
    assert "batch clicks" in low or "click batch" in low
    assert "speak a short brief" in low
    assert "3 short headlines" in low or "3 headlines" in low
    assert "you might need to click accept" in low
    assert "i could not see the screen" in low
    assert "look there" in low
    assert "never say" in low
    assert JARVIS_PUBLIC_REALTIME_INSTRUCTIONS != JARVIS_REALTIME_INSTRUCTIONS
    assert "windows laptop" in JARVIS_REALTIME_INSTRUCTIONS.lower()
    assert "ctrl+w" in JARVIS_REALTIME_INSTRUCTIONS.lower()
    shared = JARVIS_REALTIME_INSTRUCTIONS.lower()
    assert "serp is not done" in shared
    assert "batch clicks" in shared or "after a click batch" in shared
    assert "do not catalog" in shared or "catalog of icons" in shared
    assert "one short line" in shared
    assert "reuters" in shared
    assert "i could not see the screen" in shared
    assert "look there" in shared
    assert "i'll make five different games" in shared
    assert "child_limit is not a stop" in shared
    assert "making the next ones" in shared


def test_hosted_session_uses_public_instructions():
    assert hosted_linux_talk() is True
    text = session_instructions()
    assert text == JARVIS_PUBLIC_REALTIME_INSTRUCTIONS
    built = build_instructions()
    assert "Windows laptop" not in built
    assert "C:" not in built
    assert "jarvis-computer" in built.lower()
    assert "list_github_repos" in built


def test_get_disk_space_is_not_the_lead_open_tool():
    tools = tools_for_realtime()
    assert tools
    assert tools[0]["name"] != "get_disk_space"
    disk = next(t for t in tools if t["name"] == "get_disk_space")
    low = str(disk.get("description") or "").lower()
    assert "only when the user asked" in low
    assert "use whenever" not in low
    assert "even if they also said" not in low
    see = next(t for t in tools if t["name"] == "see_screen")
    assert "jarvis-computer" in str(see.get("description") or "").lower()


def test_public_see_screen_and_run_app_bind_to_jarvis_computer(monkeypatch):
    monkeypatch.setenv("JARVIS_HOST_OS", "windows")
    for goal in (
        "what's on your screen",
        "see_screen",
        "run_app chrome",
        "what's visible on the browser",
        "what do you see on your screen",
    ):
        assert resolve_desktop_backend(goal=goal) == JARVIS_COMPUTER, goal

    name, args, early = prepare_realtime_tool_call(
        "see_screen",
        {"goal": "what's on your screen"},
        user_goal="what's on your screen",
    )
    assert early is None
    assert name == "see_screen"
    assert args["computer"] == JARVIS_COMPUTER

    name, args, early = prepare_realtime_tool_call(
        "run_app",
        {"target": "chrome"},
        user_goal="open chrome",
    )
    assert early is None
    assert args["computer"] == JARVIS_COMPUTER


def test_public_tools_run_refuses_unsolicited_disk():
    name, args, early = prepare_realtime_tool_call(
        "get_disk_space",
        {},
        user_goal="what do you see on your screen",
    )
    assert name == "get_disk_space"
    assert early is not None
    assert early["ok"] is False
    assert "see_screen" in str(early.get("error") or "").lower()

    name, args, early = prepare_realtime_tool_call("get_disk_space", {}, user_goal="")
    assert early is not None
    assert early["ok"] is False

    name, args, early = prepare_realtime_tool_call(
        "get_disk_space",
        {},
        user_goal="how much free space",
    )
    assert early is None


def test_public_spoken_news_does_not_open_chrome():
    for goal in ("french news", "latest news in Europe", "get me the news"):
        name, args, early = prepare_realtime_tool_call(
            "run_app",
            {"target": "chrome"},
            user_goal=goal,
        )
        assert name == "run_app", goal
        assert early is not None, goal
        assert early.get("skipped") is True, goal
        assert "spoken news" in str(early.get("reason") or ""), goal
        assert not args.get("url"), goal


def test_public_open_news_on_screen_uses_homepage():
    name, args, early = prepare_realtime_tool_call(
        "run_app",
        {"target": "chrome"},
        user_goal="open the french news on the screen",
    )
    assert early is None
    assert name == "run_app"
    assert args["computer"] == JARVIS_COMPUTER
    url = str(args.get("url") or "")
    assert "duckduckgo.com" not in url
    assert "reuters.com" in url or "bbc.com" in url
    assert "french.com" not in url.lower()


def test_switzerland_news_on_screen_becomes_homepage_not_404_slug():
    from app.jarvis.serp import SWISS_NEWS_URL, is_dead_swissinfo_path

    for goal in (
        "open the Switzerland news on the screen",
        "show the swiss news on the screen",
        "open news in Switzerland on the screen",
    ):
        name, args, early = prepare_realtime_tool_call(
            "run_app",
            {"target": "chrome"},
            user_goal=goal,
        )
        assert early is None, goal
        assert name == "run_app", goal
        url = str(args.get("url") or "").lower()
        assert "duckduckgo.com" not in url, goal
        assert url.rstrip("/") == SWISS_NEWS_URL.rstrip("/").lower(), goal
        assert not is_dead_swissinfo_path(url), goal
        assert "switzerland.com" not in url, goal
        assert "swiss.com" not in url, goal


def test_keys_schema_says_ctrl_w_closes_tab():
    tools = tools_for_realtime()
    keys = next(t for t in tools if t["name"] == "keys")
    low = str(keys.get("description") or "").lower()
    assert "ctrl+w" in low
    assert "close tab" in low
    assert "close_tab" not in {t["name"] for t in tools}


def test_news_rewrite_uses_user_goal_when_args_omit_goal():
    name, args, early = prepare_realtime_tool_call(
        "run_app",
        {"target": "chrome"},
        user_goal="open the switzerland news on the screen",
    )
    assert early is None
    assert name == "run_app"
    url = str(args.get("url") or "").lower()
    assert "nzz.ch" in url
    assert "duckduckgo.com" not in url
    assert "switzerland.com" not in url
    assert args.get("goal") == "open the switzerland news on the screen"


def test_close_tab_keys_are_ctrl_w_not_escape():
    name, args, early = prepare_realtime_tool_call(
        "keys",
        {"combo": "escape"},
        user_goal="close the tab",
    )
    assert early is None
    assert name == "keys"
    assert args["computer"] == JARVIS_COMPUTER
    assert args["combo"] == "ctrl+w"

    name, args, early = prepare_realtime_tool_call(
        "keys",
        {"combo": "escape"},
        user_goal="close the tabs",
    )
    assert args["combo"] == "ctrl+w"

    name, args, early = prepare_realtime_tool_call(
        "keys",
        {"combo": "ctrl+tab"},
        user_goal="switch tab",
    )
    assert args["combo"] == "ctrl+tab"


def test_close_all_keys_are_close_all_not_escape_or_ctrl_w():
    for goal in (
        "close all tabs",
        "close all browser tabs",
        "close the browser",
        "close all windows",
        "close all browser windows",
        "close all apps",
        "Close all the apps running, like these Explorer and Error, close them as well.",
    ):
        name, args, early = prepare_realtime_tool_call(
            "keys",
            {"combo": "escape"},
            user_goal=goal,
        )
        assert early is None, goal
        assert name == "keys", goal
        assert args["computer"] == JARVIS_COMPUTER, goal
        assert args["combo"] == "close-all", goal
        assert args["combo"] != "ctrl+w", goal
        assert args["combo"] != "escape", goal

    name, args, early = prepare_realtime_tool_call(
        "see_screen",
        {"goal": "close all tabs"},
        user_goal="close all tabs",
    )
    assert args.get("fresh") is True
    assert args.get("prefer_last") is False

    name, args, early = prepare_realtime_tool_call(
        "focus_app",
        {"app": "chrome"},
        user_goal="close all browser tabs",
    )
    assert early is not None
    assert early.get("skipped") is True
    assert "focus_app" in str(early.get("reason") or "")

    name, args, early = prepare_realtime_tool_call(
        "run_app",
        {"target": "chrome"},
        user_goal="close the browser",
    )
    assert early is not None
    assert early.get("skipped") is True

    name, args, early = prepare_realtime_tool_call(
        "click",
        {"x": 10, "y": 20},
        user_goal="close all windows",
    )
    assert early is not None
    assert early.get("skipped") is True


def test_voice_stays_openai_realtime_when_key_exists(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-secret-value-XXXX")
    monkeypatch.delenv("OPENAI_REALTIME_MODEL", raising=False)
    from app.jarvis.hosted_openai import openai_api_key
    from app.jarvis.realtime import listen_mode, realtime_available, realtime_model

    assert openai_api_key()
    assert realtime_available() is True
    assert listen_mode() == "openai_realtime"
    assert realtime_model() == "gpt-realtime"


def test_hosted_linux_realtime_model_is_gpt_realtime(monkeypatch):
    monkeypatch.delenv("OPENAI_REALTIME_MODEL", raising=False)
    assert hosted_linux_talk() is True
    assert realtime_model() == "gpt-realtime"
    monkeypatch.setenv("OPENAI_REALTIME_MODEL", "gpt-realtime-mini")
    assert realtime_model() == "gpt-realtime-mini"


def test_windows_realtime_model_stays_mini(monkeypatch):
    monkeypatch.delenv("OPENAI_REALTIME_MODEL", raising=False)
    monkeypatch.setattr("app.jarvis.virtual_pc.sys.platform", "win32")
    assert hosted_linux_talk() is False
    assert realtime_model() == "gpt-realtime-mini"


def test_screen_and_browser_asks_are_computer_jobs_not_refuse_lines():
    for phrase in (
        "what's on your screen",
        "what do you see on your screen",
        "what do you see on the screen",
        "What do you see on the screen?",
        "Can you... what do you see on your screen?",
        "your computer",
        "what's on the browser",
        "what's visible on the browser",
        "check your computer and tell me what's visible on the browser",
        "don't you have your own computer",
        "close the tab",
        "close the tabs",
        "close all tabs",
        "close the browser",
        "close all windows",
        "open the Switzerland news on the screen",
        "there is no login section here",
        "what are you seeing on the screen",
        "read this page",
        "look",
        "close the tabs and read Switzerland news",
        "show bbc.com",
        "what do you see",
        "Close all the apps running, like these Explorer and Error, close them as well.",
        "close all apps",
        "I can still see the file manager.",
        "No, I can still see the file manager.",
    ):
        assert goal_is_computer_job(phrase), phrase
        assert not goal_is_simple_talk(phrase), phrase
    for phrase in ("Switzerland news", "latest news in Europe", "get me the news"):
        assert not goal_is_computer_job(phrase), phrase
        assert goal_is_simple_talk(phrase), phrase


def test_hello_and_can_you_hear_me_are_not_pc_jobs():
    for phrase in ("hello", "can you hear me"):
        assert goal_is_simple_talk(phrase), phrase
        assert not goal_is_computer_job(phrase), phrase
        assert not wants_look_job(phrase), phrase


def test_what_do_you_see_is_look_job_not_realtime_skip():
    for phrase in (
        "what do you see on the screen",
        "What do you see on the screen?",
        "what do you see on your screen",
        "Can you... what do you see on your screen?",
        "what do you see",
    ):
        assert wants_look_job(phrase), phrase
        assert not wants_chat_only_desktop_skip(phrase), phrase
        assert goal_is_computer_job(phrase), phrase
        assert not goal_is_simple_talk(phrase), phrase
        name, args, early = prepare_realtime_tool_call(
            "see_screen",
            {},
            user_goal=phrase,
        )
        assert name == "see_screen", phrase
        assert early is None, phrase
        assert not (early or {}).get("skipped"), phrase
        assert args.get("goal") == phrase, phrase
    name, args, early = prepare_realtime_tool_call(
        "see_screen",
        {"goal": "Really?"},
        user_goal="what do you see on the screen",
    )
    assert early is None
    assert args.get("goal") == "what do you see on the screen"
    name, args, early = prepare_realtime_tool_call(
        "see_screen",
        {"goal": "what do you see on the screen"},
        user_goal="can you hear me",
    )
    assert early is None
    assert args.get("goal") == "what do you see on the screen"
    low = JARVIS_PUBLIC_REALTIME_INSTRUCTIONS.lower()
    assert "what you see" in low
    assert "do not skip" in low
    assert "do not stay silent" in low
    assert "do not only say hello" in low


def test_public_page_keeps_duplex_transcript_and_no_keys():
    page = PAGE.read_text(encoding="utf-8")
    low = page.lower()
    assert "setLiveYou" in page
    assert "setLiveJarvis" in page
    assert "RTCPeerConnection" in page
    assert "Mute me" in page or "mute-me" in page
    assert "sk-" not in page
    assert "api key" not in low
    assert "jarvis-screen.html" not in low
    assert "ceo.html" not in page
    assert "OPENAI_API_KEY" not in page
    assert "function connectRealtime" in page


def test_win32_prepare_does_not_force_jarvis_computer(monkeypatch):
    monkeypatch.setattr("app.jarvis.virtual_pc.sys.platform", "win32")
    name, args, early = prepare_realtime_tool_call(
        "see_screen",
        {"goal": "what's on my screen"},
        user_goal="what's on my screen",
    )
    assert early is None
    assert args.get("computer") != JARVIS_COMPUTER


@pytest.mark.asyncio
async def test_tools_run_see_screen_binds_jarvis_computer(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_HOST_OS", "windows")
    bound: list[str] = []

    def fake_see(ctx, args):
        from app.jarvis.computer import current_desktop_backend

        bound.append(str(args.get("computer") or current_desktop_backend() or ""))
        return {"ok": True, "vision_description": "Chrome shows CNN."}

    from app.jarvis import tools as tools_mod

    monkeypatch.setattr(tools_mod, "_see_screen", fake_see)
    monkeypatch.setitem(tools_mod._DISPATCH, "see_screen", fake_see)
    from app.jarvis import gateway as gw
    from app.jarvis import settings_store
    from app.config import get_settings
    from httpx import ASGITransport, AsyncClient

    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            await ac.post(
                "/api/jarvis/taint/clear",
                json={"source": "realtime", "goal": "what's on your screen"},
            )
            r = await ac.post(
                "/api/jarvis/tools/run",
                json={"name": "see_screen", "arguments": {"goal": "what's on your screen"}},
            )
    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "see_screen"
    assert body["result"].get("ok") is True
    assert JARVIS_COMPUTER in bound or body["result"].get("computer") == JARVIS_COMPUTER


@pytest.mark.asyncio
async def test_tools_run_skips_unsolicited_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    called: list[str] = []

    def boom_disk(*_a, **_k):
        called.append("disk")
        raise AssertionError("get_disk_space must not run unsolicited")

    monkeypatch.setattr("app.jarvis.tools._disk_space", boom_disk)
    from app.jarvis import gateway as gw
    from app.jarvis import settings_store
    from app.config import get_settings
    from httpx import ASGITransport, AsyncClient

    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            await ac.post(
                "/api/jarvis/taint/clear",
                json={"source": "realtime", "goal": "what do you see on your screen"},
            )
            r = await ac.post(
                "/api/jarvis/tools/run",
                json={"name": "get_disk_space", "arguments": {}},
            )
    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    assert r.status_code == 200
    assert called == []
    assert r.json()["result"].get("ok") is False
    assert r.json()["result"].get("skipped") == "get_disk_space"


@pytest.mark.asyncio
async def test_tools_run_news_rewrites_from_tracker_when_args_omit_goal(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_HOST_OS", "windows")
    opened: list[dict] = []

    def fake_run(ctx, args):
        opened.append(dict(args or {}))
        return {"ok": True, "opened": args.get("url"), "computer": JARVIS_COMPUTER}

    from app.jarvis import tools as tools_mod

    monkeypatch.setattr(tools_mod, "_run_app", fake_run)
    monkeypatch.setitem(tools_mod._DISPATCH, "run_app", fake_run)
    from app.jarvis import gateway as gw
    from app.jarvis import settings_store
    from app.config import get_settings
    from httpx import ASGITransport, AsyncClient

    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            await ac.post(
                "/api/jarvis/taint/clear",
                    json={"source": "realtime", "goal": "open the switzerland news on the screen"},
            )
            r = await ac.post(
                "/api/jarvis/tools/run",
                json={"name": "run_app", "arguments": {"target": "chrome"}},
            )
    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "run_app"
    url = str((opened[0] if opened else body.get("result") or {}).get("url") or "")
    if not url:
        url = str((body.get("result") or {}).get("opened") or "")
    low = url.lower()
    if opened:
        low = str(opened[0].get("url") or url).lower()
    assert "nzz.ch" in low or low.rstrip("/").endswith("swissinfo.ch/eng")
    assert "duckduckgo.com" not in low
    assert "switzerland.com" not in low
    assert "/politics/" not in low


def test_serp_is_not_done_and_leave_url_never_invents_host():
    from app.jarvis.serp import (
        click_hits_serp_chrome,
        click_missed_search,
        leave_serp_url,
        look_is_serp,
        wants_leave_serp,
        wants_open_or_read_article,
    )

    serp = {
        "ok": True,
        "title": "Switzerland news at DuckDuckGo",
        "vision_description": (
            "DuckDuckGo search results. Air defense $1.2B. China duty-free."
        ),
    }
    article = {
        "ok": True,
        "title": "Reuters — Swiss deal",
        "vision_description": "Reuters: Parliament meets in Bern.",
    }
    assert look_is_serp(serp) is True
    assert look_is_serp(article) is False
    assert click_missed_search(serp, serp) is True
    assert click_missed_search(serp, article) is False
    assert wants_open_or_read_article("click that and read that news")
    assert wants_open_or_read_article("open the news")
    assert wants_leave_serp("Switzerland news", serp)
    assert wants_leave_serp("Yes.", serp)
    assert click_hits_serp_chrome(250, 270) is True
    assert click_hits_serp_chrome(420, 320) is False
    from_look = leave_serp_url(
        {
            "title": "Switzerland news at DuckDuckGo",
            "vision_description": "First https://www.reuters.com/world/swiss-deal",
        }
    )
    assert from_look is not None
    assert "reuters.com" in from_look
    assert "switzerland.com" not in from_look
    named = leave_serp_url(
        {
            "title": "Switzerland news at DuckDuckGo",
            "vision_description": "News cards from swissinfo and NZZ.",
        },
        allow_default=False,
    )
    assert named is not None
    assert "swissinfo.ch" in named or "nzz.ch" in named
    fallback = leave_serp_url(serp, "Switzerland news")
    assert fallback == "https://www.nzz.ch/"
    assert "switzerland.com" not in fallback
    assert "duckduckgo" not in fallback
    assert "swissinfo.ch/eng/" not in fallback or fallback.rstrip("/").endswith("/eng")


def test_prepare_rewrites_serp_click_to_article_url():
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.realtime import prepare_realtime_tool_call

    reset_last_look()
    remember_last_look(
        {
            "ok": True,
            "title": "Switzerland news at DuckDuckGo",
            "vision_description": (
                "DuckDuckGo results. https://www.reuters.com/world/swiss-deal "
                "air defense / China duty-free"
            ),
        }
    )
    name, args, early = prepare_realtime_tool_call(
        "click",
        {"x": 234, "y": 341},
        user_goal="click that and read that news",
    )
    assert early is None
    assert name == "run_app"
    url = str(args.get("url") or "")
    assert "reuters.com" in url
    assert "switzerland.com" not in url
    assert "duckduckgo.com" not in url
    reset_last_look()


def test_prepare_search_box_click_leaves_serp_not_same_pixels():
    from app.jarvis.capture import remember_last_look, reset_last_look, reset_serp_click_misses
    from app.jarvis.realtime import prepare_realtime_tool_call

    reset_last_look()
    reset_serp_click_misses()
    remember_last_look(
        {
            "ok": True,
            "title": "Switzerland news at DuckDuckGo",
            "vision_description": (
                "DuckDuckGo search page. News cards: air defense / China duty-free."
            ),
        }
    )
    name, args, early = prepare_realtime_tool_call(
        "click",
        {"x": 250, "y": 270},
        user_goal="click that and read that news",
    )
    assert early is None
    assert name == "run_app"
    url = str(args.get("url") or "")
    assert "reuters.com" in url or "nzz.ch" in url or "bbc.com" in url
    assert "duckduckgo.com" not in url
    assert "switzerland.com" not in url

    name, args, early = prepare_realtime_tool_call(
        "click",
        {"x": 420, "y": 320},
        user_goal="open the Switzerland news on the screen",
    )
    assert name == "click"
    assert args.get("x") == 420
    reset_last_look()


def test_prepare_second_serp_click_must_leave():
    from app.jarvis.capture import (
        note_serp_click_miss,
        remember_last_look,
        reset_last_look,
        reset_serp_click_misses,
    )
    from app.jarvis.realtime import prepare_realtime_tool_call

    reset_last_look()
    reset_serp_click_misses()
    remember_last_look(
        {
            "ok": True,
            "title": "Switzerland news at DuckDuckGo",
            "vision_description": "DuckDuckGo search results for Switzerland news.",
        }
    )
    note_serp_click_miss()
    name, args, early = prepare_realtime_tool_call(
        "click",
        {"x": 330, "y": 250},
        user_goal="Yes.",
    )
    assert early is None
    assert name == "run_app"
    assert "reuters.com" in str(args.get("url") or "")
    assert "switzerland.com" not in str(args.get("url") or "")
    reset_last_look()


def test_click_still_on_ddg_is_not_navigation(monkeypatch):
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.desktop import reset_input_backend, set_input_backend
    from app.jarvis.tools import ToolContext, _click
    from app.jarvis.workspace import Workspace, default_workspace

    reset_last_look()
    remember_last_look(
        {
            "ok": True,
            "title": "Switzerland news at DuckDuckGo",
            "vision_description": "DuckDuckGo search results for Switzerland news.",
        }
    )
    set_input_backend(
        {
            "click": lambda **kwargs: {
                "ok": True,
                "x": kwargs["x"],
                "y": kwargs["y"],
                "button": kwargs.get("button", "left"),
            }
        }
    )
    ddg = {
        "ok": True,
        "title": "Switzerland news at DuckDuckGo",
        "vision_description": "DuckDuckGo search page. Air defense / China duty-free.",
    }
    article = {
        "ok": True,
        "title": "Reuters — Swiss deal",
        "vision_description": "Reuters: Parliament meets in Bern.",
    }
    looks = [ddg, article]
    opened: list[str] = []
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        remember_last_look(item)
        return dict(item)

    def fake_open(url):
        opened.append(str(url))
        return {"ok": True, "opened": url}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.voice_ask._open_chrome_url", fake_open)
    monkeypatch.setattr("app.jarvis.voice_ask._wait_after_act", lambda: None)
    try:
        result = _click(
            ToolContext(Workspace(default_workspace()), None),
            {"x": 420, "y": 320, "goal": "Switzerland news"},
        )
    finally:
        reset_input_backend()
        reset_last_look()
    assert result.get("ok") is True
    assert result.get("still_search") is False
    assert result.get("navigated") is True
    assert result.get("left_via") == "run_app"
    assert opened
    assert "switzerland.com" not in opened[0]
    assert "duckduckgo.com" not in opened[0]
    assert "nzz.ch" in opened[0] or "reuters.com" in opened[0] or "bbc.com" in opened[0]
