"""Spoken news is a brief; on-screen news is one homepage — never a 404 hunt."""

from __future__ import annotations

import sys

import pytest

from app.jarvis.serp import (
    EUROPE_NEWS_FALLBACK,
    EUROPE_NEWS_URL,
    GENERIC_NEWS_FALLBACK,
    GENERIC_NEWS_URL,
    SWISS_NEWS_FALLBACK,
    SWISS_NEWS_URL,
    is_dead_swissinfo_path,
    is_working_news_url,
    leave_serp_url,
    look_has_cookie_overlay,
    look_is_404,
    look_is_dead_page,
    look_is_news_page,
    news_fallback_url,
    news_homepage_from_ask,
    news_region_from_ask,
)
from app.jarvis.taint import ALLOW, BLOCK, gate


class _FakeGateway:
    memory = None

    def clear_taint(self, *args, **kwargs):
        return None


@pytest.fixture
def open_site_now(monkeypatch):
    planned: list[dict] = []
    launched: list[dict] = []
    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: _FakeGateway())
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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

    monkeypatch.setattr(computer_mod, "plan_linux_run_app", capture_plan)
    monkeypatch.setattr(computer_mod, "linux_run_app", capture_run)
    monkeypatch.setattr(
        "app.jarvis.screen_viewer.start_computer",
        lambda *a, **k: None,
        raising=False,
    )
    monkeypatch.setattr(
        "app.jarvis.agent.build_jarvis_agent",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no agent")),
        raising=False,
    )
    from app.jarvis.capture import reset_look_target

    reset_look_target()
    yield planned, launched
    reset_look_target()


def _assert_working_news_url(url: str) -> None:
    low = (url or "").lower()
    assert url
    assert "switzerland.com" not in low
    assert "swiss.com" not in low
    assert "duckduckgo.com" not in low
    assert not is_dead_swissinfo_path(url)
    if "swissinfo.ch" in low:
        path = low.split("swissinfo.ch", 1)[-1].split("?", 1)[0].rstrip("/")
        assert path in {"", "/eng"}


def test_region_maps_to_working_homepage():
    assert news_region_from_ask("latest news in Europe") == "europe"
    assert news_region_from_ask("latest news Europe") == "europe"
    assert news_homepage_from_ask("latest news in Europe") == EUROPE_NEWS_URL
    assert news_homepage_from_ask("latest news in Europe", fallback=True) == EUROPE_NEWS_FALLBACK
    _assert_working_news_url(news_homepage_from_ask("latest news in Europe"))
    _assert_working_news_url(EUROPE_NEWS_FALLBACK)

    for phrase in (
        "latest news Switzerland",
        "Switzerland news",
        "swiss news",
        "news in Switzerland",
    ):
        assert news_region_from_ask(phrase) == "switzerland", phrase
        url = news_homepage_from_ask(phrase)
        assert url == SWISS_NEWS_URL, phrase
        _assert_working_news_url(url)
        _assert_working_news_url(SWISS_NEWS_FALLBACK)
        assert "swissinfo.ch/" not in url.lower() or url.rstrip("/").endswith("/eng")

    for phrase in ("tell me the news", "the news", "latest news", "what are the headlines"):
        assert news_region_from_ask(phrase) == "generic", phrase
        url = news_homepage_from_ask(phrase)
        assert url == GENERIC_NEWS_URL, phrase
        _assert_working_news_url(url)
        _assert_working_news_url(GENERIC_NEWS_FALLBACK)


def test_dead_swissinfo_slug_is_rejected():
    dead = "https://www.swissinfo.ch/eng/politics/dead-article-404/123456"
    assert is_dead_swissinfo_path(dead) is True
    assert is_working_news_url(dead) is False
    assert is_dead_swissinfo_path("https://www.swissinfo.ch/eng") is False
    assert is_dead_swissinfo_path("https://www.swissinfo.ch/") is False
    assert is_working_news_url("https://www.nzz.ch/") is True
    assert is_working_news_url("https://switzerland.com/") is False
    assert news_fallback_url("Switzerland news", dead) == SWISS_NEWS_URL
    left = leave_serp_url(
        {
            "title": "404",
            "vision_description": f"Not found {dead}",
        },
        "Switzerland news",
    )
    assert left is not None
    _assert_working_news_url(left)
    assert dead not in left


def test_leave_serp_switzerland_uses_working_homepage():
    serp = {
        "ok": True,
        "title": "Switzerland news at DuckDuckGo",
        "vision_description": "DuckDuckGo search results.",
    }
    url = leave_serp_url(serp, "Switzerland news")
    assert url == SWISS_NEWS_URL
    _assert_working_news_url(url)
    europe = leave_serp_url(serp, "latest news in Europe")
    assert europe == EUROPE_NEWS_URL
    generic = leave_serp_url(serp, "tell me the news")
    assert generic == GENERIC_NEWS_URL


def test_look_helpers_404_cookie_and_news_page():
    assert look_is_404(
        {"title": "404", "vision_description": "Page not found on swissinfo."}
    )
    assert look_is_dead_page({"title": "about:blank", "vision_description": ""})
    assert look_has_cookie_overlay(
        {
            "title": "BBC News",
            "vision_description": "Before you continue. Accept at (640, 360).",
        }
    )
    assert look_is_news_page(
        {
            "ok": True,
            "title": "BBC News — Europe",
            "url": "https://www.bbc.com/news/world/europe",
            "vision_description": (
                "Headlines: Ukraine talks resume. Storm hits Spain. Markets rise."
            ),
        }
    )
    assert not look_is_news_page(
        {
            "ok": True,
            "title": "Switzerland news at DuckDuckGo",
            "vision_description": "DuckDuckGo results.",
        }
    )


def test_taint_allows_news_tell_publisher_after_look():
    decision, reason = gate(
        "run_app",
        True,
        args={"target": "chrome", "url": EUROPE_NEWS_URL},
        user_goal="latest news in Europe",
    )
    assert decision == ALLOW
    assert reason == ""
    swiss, _ = gate(
        "run_app",
        True,
        args={"target": "chrome", "url": SWISS_NEWS_URL},
        user_goal="latest news Switzerland",
    )
    assert swiss == ALLOW
    blocked, why = gate(
        "run_app",
        True,
        args={"target": "chrome", "url": "https://evil.example"},
        user_goal="latest news in Europe",
    )
    assert blocked == BLOCK
    assert "untrusted" in why


def test_realtime_instructions_spoken_news_no_chrome_screen_jobs_use_tools():
    from app.jarvis.realtime import (
        JARVIS_PUBLIC_REALTIME_INSTRUCTIONS,
        JARVIS_REALTIME_INSTRUCTIONS,
    )

    for text in (JARVIS_PUBLIC_REALTIME_INSTRUCTIONS, JARVIS_REALTIME_INSTRUCTIONS):
        low = text.lower()
        assert "skip focus_app" in low
        assert "speak a short brief" in low
        assert "no chrome" in low or "no run_app" in low
        assert "accept" in low
        assert "3 short headlines" in low or "3 headlines" in low
        assert "never ask the person to click" in low
        assert "you might need to click accept" in low
        assert "do not narrate the 404" in low or "do not narrate" in low
        assert "switzerland.com" in low
        assert "swissinfo.ch/eng" in low
        assert "bbc.com/news/world/europe" in low


def test_prepare_spoken_news_does_not_open_chrome():
    from app.jarvis.capture import reset_last_look
    from app.jarvis.realtime import prepare_realtime_tool_call
    from app.jarvis.voice_ask import wants_news_tell

    reset_last_look()
    for goal in (
        "latest news in Europe",
        "Switzerland news",
        "tell me the news",
        "get me the news",
    ):
        assert wants_news_tell(goal), goal
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

    name, args, early = prepare_realtime_tool_call(
        "focus_app",
        {"app": "chrome"},
        user_goal="latest news in Europe",
    )
    assert early is not None
    assert early.get("skipped") is True
    assert "spoken news" in str(early.get("reason") or "")
    reset_last_look()


def test_prepare_open_news_on_screen_uses_homepage():
    from app.jarvis.capture import reset_last_look
    from app.jarvis.computer import JARVIS_COMPUTER
    from app.jarvis.realtime import prepare_realtime_tool_call

    reset_last_look()
    name, args, early = prepare_realtime_tool_call(
        "run_app",
        {"target": "chrome"},
        user_goal="open the news on the screen",
    )
    assert early is None
    assert name == "run_app"
    assert args["computer"] == JARVIS_COMPUTER
    _assert_working_news_url(str(args.get("url") or ""))
    assert args["url"] in {GENERIC_NEWS_URL, EUROPE_NEWS_URL}

    name, args, early = prepare_realtime_tool_call(
        "run_app",
        {"target": "chrome"},
        user_goal="open the Switzerland news on the screen",
    )
    assert early is None
    _assert_working_news_url(str(args.get("url") or ""))
    assert args["url"] == SWISS_NEWS_URL

    name, args, early = prepare_realtime_tool_call(
        "focus_app",
        {"app": "chrome"},
        user_goal="open the news on the screen",
    )
    assert early is not None
    assert early.get("skipped") is True
    assert "open/read/click/close" in str(early.get("reason") or "")
    reset_last_look()


def test_prepare_skips_reopen_when_already_on_news_page():
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.realtime import prepare_realtime_tool_call

    reset_last_look()
    remember_last_look(
        {
            "ok": True,
            "title": "BBC News — Europe",
            "url": EUROPE_NEWS_URL,
            "vision_description": (
                "Headlines: Ukraine talks resume. Storm hits Spain. Markets rise."
            ),
        }
    )
    name, args, early = prepare_realtime_tool_call(
        "run_app",
        {"target": "chrome", "url": "https://duckduckgo.com/?q=europe+news"},
        user_goal="open the news on the screen",
    )
    assert early is not None
    assert early.get("skipped") is True
    assert "already on a news page" in str(early.get("reason") or "")
    reset_last_look()


def test_prepare_404_rewrites_to_fallback_homepage():
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.realtime import prepare_realtime_tool_call

    reset_last_look()
    remember_last_look(
        {
            "ok": True,
            "title": "404",
            "url": "https://www.swissinfo.ch/eng/politics/dead/1",
            "vision_description": "Page not found.",
        }
    )
    name, args, early = prepare_realtime_tool_call(
        "run_app",
        {"target": "chrome", "url": "https://www.swissinfo.ch/eng/politics/dead/1"},
        user_goal="open the Switzerland news on the screen",
    )
    assert early is None
    assert name == "run_app"
    _assert_working_news_url(str(args.get("url") or ""))
    assert not is_dead_swissinfo_path(str(args.get("url") or ""))
    reset_last_look()


def test_tools_focus_app_skips_on_spoken_news_and_screen_open():
    from app.jarvis.tools import ToolContext, _focus_app
    from app.jarvis.workspace import Workspace, default_workspace

    spoken = _focus_app(
        ToolContext(Workspace(default_workspace()), None),
        {"app": "chrome", "goal": "latest news in Europe"},
    )
    assert spoken.get("ok") is True
    assert spoken.get("skipped") is True
    assert "spoken news" in str(spoken.get("reason") or "")

    opened = _focus_app(
        ToolContext(Workspace(default_workspace()), None),
        {"app": "chrome", "goal": "open the news on the screen"},
    )
    assert opened.get("ok") is True
    assert opened.get("skipped") is True
    assert "open/read/click/close" in str(opened.get("reason") or "")


def _stub_spoken_news(monkeypatch, reply="In Europe: Ukraine talks. A storm in Spain. Markets rose."):
    async def fake_oneshot(asked):
        return reply

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", fake_oneshot)


@pytest.mark.asyncio
async def test_voice_ask_europe_speaks_and_does_not_open_chrome(open_site_now, monkeypatch):
    planned, launched = open_site_now
    _stub_spoken_news(monkeypatch)
    from app.jarvis.voice_ask import run_voice_ask, wants_news_tell

    assert wants_news_tell("latest news in Europe")
    body = await run_voice_ask("latest news in Europe")
    assert body["ok"] is True
    assert planned == []
    assert launched == []
    assert "run_app" not in body["tools_used"]
    assert "see_screen" not in body["tools_used"]
    assert "focus_app" not in body["tools_used"]
    low = body["reply"].lower()
    assert "ukraine" in low
    assert "storm" in low
    assert "markets" in low
    assert "Opened" not in body["reply"]


@pytest.mark.asyncio
async def test_voice_ask_switzerland_speaks_and_does_not_open_chrome(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    _stub_spoken_news(
        monkeypatch,
        "Switzerland: Alpine roads closed. Parliament meets in Bern. The franc holds.",
    )
    from app.jarvis.voice_ask import run_voice_ask, wants_news_tell

    assert wants_news_tell("latest news Switzerland")
    body = await run_voice_ask("latest news Switzerland")
    assert planned == []
    assert launched == []
    assert "run_app" not in body["tools_used"]
    assert "alpine roads closed" in body["reply"].lower()
    assert "focus_app" not in body["tools_used"]


@pytest.mark.asyncio
async def test_voice_ask_tell_me_the_news_speaks_no_chrome(open_site_now, monkeypatch):
    planned, launched = open_site_now
    _stub_spoken_news(
        monkeypatch,
        "Oil prices slip. A ceasefire holds. Central banks meet.",
    )
    from app.jarvis.voice_ask import run_voice_ask, wants_news_tell

    assert wants_news_tell("tell me the news")
    body = await run_voice_ask("tell me the news")
    assert planned == []
    assert launched == []
    assert "run_app" not in body["tools_used"]
    assert "oil prices slip" in body["reply"].lower()
    assert "focus_app" not in body["tools_used"]


@pytest.mark.asyncio
async def test_voice_ask_dismisses_accept_and_does_not_ask_user(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    looks = [
        {
            "ok": True,
            "title": "BBC News",
            "url": EUROPE_NEWS_URL,
            "vision_description": (
                "Before you continue. Accept at (640, 360). Cookie consent."
            ),
            "click_x": 640,
            "click_y": 360,
        },
        {
            "ok": True,
            "title": "BBC News — Europe",
            "url": EUROPE_NEWS_URL,
            "vision_description": (
                "Ukraine talks resume. Storm hits Spain. Markets rise in Frankfurt."
            ),
        },
    ]
    clicks: list[dict] = []
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append(dict(args or {}))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open the news on the screen")
    assert clicks
    assert clicks[0]["x"] == 640
    assert clicks[0]["y"] == 360
    assert "click" in body["tools_used"]
    low = body["reply"].lower()
    assert "ukraine" in low
    assert "you might need to click" not in low
    assert "please click" not in low
    assert "accept" not in low


@pytest.mark.asyncio
async def test_voice_ask_404_opens_fallback_does_not_narrate(
    open_site_now, monkeypatch
):
    planned, launched = open_site_now
    looks = [
        {
            "ok": True,
            "title": "404",
            "url": "https://www.swissinfo.ch/eng/politics/dead/1",
            "vision_description": "404 Page not found. This swissinfo article is gone.",
        },
        {
            "ok": True,
            "title": "NZZ",
            "url": SWISS_NEWS_URL,
            "vision_description": (
                "Alpine roads closed. Parliament meets in Bern. Franc holds steady."
            ),
        },
    ]
    i = {"n": 0}

    def fake_see(ctx, args):
        item = looks[min(i["n"], len(looks) - 1)]
        i["n"] += 1
        return dict(item)

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("open the Switzerland news on the screen")
    urls = [str(item.get("url") or "") for item in planned if item.get("url")]
    assert urls
    assert SWISS_NEWS_URL in urls
    assert any("nzz.ch" in u or "swissinfo.ch/eng" == u.rstrip("/").split("://", 1)[-1].split("www.", 1)[-1] or u.rstrip("/").endswith("swissinfo.ch/eng") for u in urls)
    for url in urls:
        _assert_working_news_url(url)
    low = body["reply"].lower()
    assert "alpine roads closed" in low
    assert "404" not in low
    assert "page not found" not in low
    assert "this swissinfo article is gone" not in low


@pytest.mark.asyncio
async def test_already_on_bbc_just_looks_and_tells(open_site_now, monkeypatch):
    planned, launched = open_site_now
    from app.jarvis.capture import remember_last_look, reset_last_look

    reset_last_look()
    remember_last_look(
        {
            "ok": True,
            "title": "BBC News — Europe",
            "url": EUROPE_NEWS_URL,
            "vision_description": (
                "Headlines: Ukraine talks resume. Storm hits Spain. Markets rise."
            ),
        }
    )

    def fake_see(ctx, args):
        return {
            "ok": True,
            "title": "BBC News — Europe",
            "url": EUROPE_NEWS_URL,
            "vision_description": (
                "Ukraine talks resume. Storm hits Spain. Markets rise in Frankfurt."
            ),
        }

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    from app.jarvis.voice_ask import run_voice_ask

    _stub_spoken_news(
        monkeypatch,
        "Ukraine talks resume. Storm hits Spain. Markets rise in Frankfurt.",
    )
    body = await run_voice_ask("tell me the news")
    assert planned == []
    assert launched == []
    assert "ukraine" in body["reply"].lower()
    assert "run_app" not in body["tools_used"]
    assert "see_screen" not in body["tools_used"]
    reset_last_look()


def test_spoken_headlines_are_three_and_drop_cookie_404():
    from app.jarvis.voice_ask import _LOOK_FAILED, _spoken_headlines

    spoken = _spoken_headlines(
        "404 Page not found. Before you continue. "
        "Ukraine talks resume. Storm hits Spain. Markets rise. A fourth extra line."
    )
    low = spoken.lower()
    assert "404" not in low
    assert "page not found" not in low
    assert "before you continue" not in low
    assert "ukraine" in low
    assert spoken.count(".") <= 3
    hollow = _spoken_headlines("I opened the page. Here are the headlines that are visible.")
    assert hollow == _LOOK_FAILED


@pytest.mark.asyncio
async def test_voice_ask_show_bbc_com_opens_chrome(open_site_now, monkeypatch):
    planned, launched = open_site_now

    def fake_see(ctx, args):
        return {
            "ok": True,
            "title": "BBC",
            "url": "https://www.bbc.com",
            "vision_description": (
                "BBC homepage. World news and a cookie dialog are visible. "
                "A headline about Europe is on the page."
            ),
        }

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    from app.jarvis.voice_ask import run_voice_ask, wants_news_tell

    assert not wants_news_tell("show bbc.com")
    body = await run_voice_ask("show bbc.com")
    assert body["ok"] is True
    assert planned
    url = str(planned[0].get("url") or "")
    assert "bbc.com" in url.lower()
    assert "run_app" in body["tools_used"]
    assert "see_screen" in body["tools_used"]
    assert "Look there." not in body["reply"]
    assert "I could not see the screen" not in body["reply"]
    assert "bbc" in body["reply"].lower() or "headline" in body["reply"].lower()
    assert launched


@pytest.mark.asyncio
async def test_voice_ask_what_do_you_see_looks(open_site_now, monkeypatch):
    planned, launched = open_site_now

    def fake_see(ctx, args):
        return {
            "ok": True,
            "title": "NZZ",
            "url": SWISS_NEWS_URL,
            "vision_description": "Alpine roads closed. Parliament meets in Bern.",
        }

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    from app.jarvis.voice_ask import run_voice_ask, wants_news_tell

    assert not wants_news_tell("what do you see")
    body = await run_voice_ask("what do you see")
    assert planned == []
    assert launched == []
    assert "see_screen" in body["tools_used"]
    assert "alpine roads closed" in body["reply"].lower()
    assert "i could not see the screen" not in body["reply"].lower()
