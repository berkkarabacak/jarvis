"""Talk computer jobs dismiss overlays, then keep going. Never Sign in / Restore / Pay."""

from __future__ import annotations

import pytest

from app.jarvis.overlay import (
    BLANK_LOOKS_BEFORE_OMNIBOX,
    NEW_TAB_CLICK,
    NEW_TAB_FOCUS_CLICKS,
    OMNIBOX_CLICK,
    RESTORE_DISMISS_CLICK,
    SANDBOX_DISMISS_CLICK,
    SEARCH_BOX_CLICK,
    SIGNIN_DISMISS_CLICK,
    WEB_LOOK_PAUSE_S,
    alt_web_search_typed,
    continue_web_search,
    dismiss_blocking_overlays,
    look_has_blocking_overlay,
    look_is_captcha,
    look_is_empty_desktop,
    look_is_focused_new_tab,
    look_is_footer,
    look_is_http_error,
    look_is_leftover_for_ask,
    look_is_leftover_surface,
    look_is_loading_or_blank,
    look_is_page_ready,
    look_is_web_page,
    needs_web_query,
    overlay_dismiss_plan,
    overlay_kind,
    query_visible_on_look,
    search_box_point,
    web_search_query,
)
from app.jarvis.voice_ask import (
    ASK_HIRE_ABORT_MS,
    ASK_LOOK_ABORT_MS,
    ASK_TALK_ABORT_MS,
    ASK_WEB_ABORT_MS,
    ask_abort_ms,
    ask_deadline_s,
    remaining_ask_deadline_s,
)
from app.jarvis.virtual_pc import (
    after_see_must_act,
    goal_is_computer_job,
    goal_is_simple_talk,
    wants_web_job,
)

ROME = "find a hotel in central Rome"
GRINDER = "go to bol.com and find a coffee grinder"
WEATHER = "use Chrome to look up the weather in Amsterdam"
LIVE_WEATHER = (
    "Open Chrome. Look, click and type like a person. "
    "Look up today's weather in Amsterdam."
)

UNTITLED_CHROME = {
    "ok": True,
    "title": "Untitled - Chromium",
    "url": "about:blank",
    "vision_description": "A blank Chromium window. The page is still loading.",
}

BLANK_HOMEPAGE = {
    "ok": True,
    "title": "Booking.com",
    "url": "https://www.booking.com/",
    "vision_description": (
        "Booking.com homepage. The page is mostly blank. A white loading screen."
    ),
}

BLANK_SHOP = {
    "ok": True,
    "title": "bol.com",
    "url": "https://www.bol.com/",
    "vision_description": (
        "bol.com homepage. The page is mostly blank. Still loading."
    ),
}


def test_rome_hotel_is_a_web_computer_job_not_look_and_tell():
    assert wants_web_job(ROME) is True
    assert goal_is_computer_job(ROME) is True
    assert goal_is_simple_talk(ROME) is False
    assert after_see_must_act(ROME) is True
    assert wants_web_job("what's on the screen") is False
    assert after_see_must_act("what's on the screen") is False
    assert goal_is_simple_talk("hello") is True
    assert wants_web_job("hello") is False
    assert wants_web_job("use Chrome to find a hotel in Rome") is True
    assert wants_web_job("use Chrome") is True
    assert wants_web_job(WEATHER) is True
    assert wants_web_job(GRINDER) is True
    assert goal_is_simple_talk(WEATHER) is False


def test_ask_abort_ms_web_job_is_minutes_hello_stays_short():
    assert ask_abort_ms("hello") == ASK_TALK_ABORT_MS
    assert ask_abort_ms("hello") == 12_000
    assert ask_abort_ms(ROME) == ASK_WEB_ABORT_MS
    assert ask_abort_ms(ROME) == 180_000
    assert ask_abort_ms("use Chrome to find a hotel") == ASK_WEB_ABORT_MS
    assert ask_abort_ms("search for a hotel in Rome") == ASK_WEB_ABORT_MS
    assert ask_abort_ms("book a hotel in central Rome") == ASK_WEB_ABORT_MS
    assert ask_abort_ms("open booking.com and look for a hotel") == ASK_WEB_ABORT_MS
    assert ask_abort_ms(WEATHER) == ASK_WEB_ABORT_MS
    assert ask_abort_ms(GRINDER) == ASK_WEB_ABORT_MS
    assert ask_abort_ms("what's on the screen") == ASK_LOOK_ABORT_MS
    assert ask_abort_ms("what's on the screen") == 30_000
    hire = (
        "Hire 10 OpenRouter children with spawn_child. "
        "Each writes a different pretty Tetris HTML."
    )
    assert ask_abort_ms(hire) == ASK_HIRE_ABORT_MS
    assert ask_deadline_s(ROME) == 180.0
    assert ask_deadline_s("hello") == 12.0
    assert ask_deadline_s("what's on the screen") == 30.0


def _typed_is_user_query(text: str) -> bool:
    low = (text or "").lower()
    return (
        "like a person" not in low
        and "open chrome" not in low
        and "look, click" not in low
        and "see_screen" not in low
    )


def test_web_search_query_strips_url_and_find():
    assert "Rome" in web_search_query(ROME) or "rome" in web_search_query(ROME).lower()
    assert "booking" not in web_search_query(
        "find a hotel in central Rome on booking.com"
    ).lower()
    assert "grinder" in web_search_query("go to bol.com and find a coffee grinder")


def test_web_search_query_strips_coaching_keeps_ask_tokens():
    """Never type 'Look, click and type like a person' / Open Chrome."""
    q = web_search_query(LIVE_WEATHER)
    low = q.lower()
    assert "weather" in low
    assert "amsterdam" in low
    assert _typed_is_user_query(q)
    assert "chrome" not in low
    assert "click" not in low
    assert "person" not in low
    hotel = web_search_query(
        "Open Chrome. Look, click and type like a person. find a hotel in central Rome."
    )
    h = hotel.lower()
    assert "rome" in h
    assert "hotel" in h
    assert _typed_is_user_query(hotel)
    assert "chrome" not in h
    shop = web_search_query(
        "Open Chrome. Look, click and type like a person. go to bol.com and find a coffee grinder"
    )
    s = shop.lower()
    assert "grinder" in s
    assert _typed_is_user_query(shop)


def test_overlay_kinds_from_live_failure():
    genius = {
        "ok": True,
        "title": "Booking.com",
        "vision_description": (
            "Booking.com Genius Sign in, save money modal. X button at (920, 170)."
        ),
    }
    restore = {
        "ok": True,
        "title": "Restore pages?",
        "vision_description": "Chromium Restore pages? Booking.com is behind it.",
    }
    sandbox = {
        "ok": True,
        "title": "Booking.com",
        "vision_description": (
            "You are using an unsupported command-line flag: --no-sandbox. "
            "Stability and security will suffer."
        ),
    }
    desktop = {
        "ok": True,
        "title": "",
        "vision_description": "A turquoise desktop background fills the screenshot.",
    }
    assert overlay_kind(genius) == "signin"
    assert overlay_kind(restore) == "restore"
    assert overlay_kind(sandbox) == "sandbox"
    assert look_has_blocking_overlay(genius) is True
    assert look_is_empty_desktop(desktop) is True
    assert look_is_empty_desktop(genius) is False


def test_dismiss_plan_never_clicks_sign_in_or_restore_or_pay():
    genius = {
        "vision_description": "Sign in, save money. X at (910, 165). Sign in button."
    }
    plan = overlay_dismiss_plan(genius)
    assert plan is not None
    assert plan.kind == "signin"
    assert plan.click == (910, 165)
    restore = overlay_dismiss_plan(
        {"title": "Restore pages?", "vision_description": "Restore pages?"}
    )
    assert restore is not None
    assert restore.click == RESTORE_DISMISS_CLICK
    sandbox = overlay_dismiss_plan(
        {"vision_description": "unsupported command-line flag: --no-sandbox"}
    )
    assert sandbox is not None
    assert sandbox.click == SANDBOX_DISMISS_CLICK
    assert overlay_dismiss_plan(
        {"vision_description": "Sign in, save money."},
        goal="please sign in to booking",
    ) is None
    pay = overlay_dismiss_plan(
        {"vision_description": "Checkout. Pay now. Book now."}
    )
    assert pay is None or pay.click != (0, 0)


def test_cookie_prefers_reject_coords():
    plan = overlay_dismiss_plan(
        {
            "vision_description": (
                "Cookie banner. Reject all cookies at (400, 620). Accept all at (700, 620)."
            )
        }
    )
    assert plan is not None
    assert plan.click == (400, 620)


def test_dismiss_blocking_overlays_then_continue_types():
    """Scripted product path: look → click X → look → type destination."""
    looks = [
        {
            "ok": True,
            "title": "Booking.com",
            "vision_description": "Genius Sign in, save money. X at (920, 170).",
        },
        {
            "ok": True,
            "title": "Booking.com",
            "vision_description": (
                "Booking.com. Where are you going? Search box is empty at (640, 320)."
            ),
        },
    ]
    clicks: list[tuple[int, int]] = []
    keys: list[str] = []
    i = {"n": 0}

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True, "x": x, "y": y}

    def press(*, combo, **_k):
        keys.append(str(combo))
        return {"ok": True, "combo": combo}

    def look_again():
        i["n"] += 1
        return dict(looks[min(i["n"], len(looks) - 1)])

    out = dismiss_blocking_overlays(
        looks[0],
        goal=ROME,
        click=click,
        keys=press,
        look_again=look_again,
    )
    assert (920, 170) in clicks
    assert "escape" in keys
    assert look_has_blocking_overlay(out) is False
    assert "Where are you going" in str(out.get("vision_description") or "")
    assert search_box_point(out) == (640, 320)


def test_search_box_point_uses_named_field_not_footer_pixel():
    footer = {
        "ok": True,
        "title": "Booking.com",
        "vision_description": (
            "Page scrolled to the footer. Copyright Booking.com. "
            "All rights reserved. Privacy. Destinations we love at (640, 680)."
        ),
    }
    named = {
        "ok": True,
        "title": "Booking.com",
        "vision_description": (
            "Where are you going? Search box is empty at (412, 210). "
            "Footer copyright at (640, 680)."
        ),
    }
    assert look_is_footer(footer) is True
    assert search_box_point(footer) is None
    assert look_is_footer(named) is False
    assert search_box_point(named) == (412, 210)


HOMEPAGE_NO_BOX = {
    "ok": True,
    "title": "Booking.com",
    "url": "https://www.booking.com/",
    "vision_description": (
        "Booking.com. Stays, flights, car rental. "
        "Find hotels, homes and more. A form at the top."
    ),
}


def test_search_box_point_homepage_without_search_box_words():
    """Live miss: homepage look never says 'search box' — still a field."""
    assert look_is_footer(HOMEPAGE_NO_BOX) is False
    assert look_is_empty_desktop(HOMEPAGE_NO_BOX) is False
    assert search_box_point(HOMEPAGE_NO_BOX) == SEARCH_BOX_CLICK
    assert search_box_point(HOMEPAGE_NO_BOX) == (640, 320)
    query = web_search_query(ROME)
    assert "hotel" in query.lower()
    assert needs_web_query(ROME, HOMEPAGE_NO_BOX, query) is True


def test_continue_web_search_types_on_homepage_without_search_box():
    looks = [
        HOMEPAGE_NO_BOX,
        {
            "ok": True,
            "title": "Hotels in Rome — Booking.com",
            "url": "https://www.booking.com/searchresults.html",
            "vision_description": (
                "Hotels in central Rome. Hotel Eden. Prices from 180 EUR."
            ),
        },
    ]
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    i = {"n": 0}

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def type_text(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def press(*, combo="", **_k):
        keys.append(str(combo))
        return {"ok": True}

    def look_again():
        i["n"] += 1
        return dict(looks[min(i["n"], len(looks) - 1)])

    out = continue_web_search(
        looks[0],
        goal=ROME,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
    )
    assert typed, "homepage without 'search box' must still type the query"
    assert any("Rome" in t or "rome" in t.lower() or "hotel" in t.lower() for t in typed)
    assert (640, 320) in clicks
    assert (640, 680) not in clicks
    assert "enter" in keys
    assert "Eden" in str(out.get("vision_description") or "")


@pytest.mark.asyncio
async def test_voice_ask_rome_dismisses_genius_then_types(
    monkeypatch,
):
    from app.jarvis import computer as computer_mod
    from app.jarvis.voice_ask import run_voice_ask

    planned: list[dict] = []
    launched: list[dict] = []
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    looks = [
        {
            "ok": True,
            "title": "Booking.com",
            "url": "https://www.booking.com/",
            "vision_description": (
                "Booking.com Genius Sign in, save money modal. "
                "X button at (920, 170)."
            ),
        },
        {
            "ok": True,
            "title": "Booking.com",
            "url": "https://www.booking.com/",
            "vision_description": (
                "Booking.com. Where are you going? Search box is empty at (640, 320)."
            ),
        },
        {
            "ok": True,
            "title": "Hotels in Rome — Booking.com",
            "url": "https://www.booking.com/searchresults.html",
            "vision_description": (
                "Hotels in central Rome. Hotel Eden. The First Roma. "
                "Prices from 180 EUR. No checkout."
            ),
        },
    ]
    n = {"i": 0}

    def fake_see(ctx, args):
        item = looks[min(n["i"], len(looks) - 1)]
        n["i"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append((int(args.get("x") or 0), int(args.get("y") or 0)))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    def fake_type(ctx, args):
        typed.append(str((args or {}).get("text") or ""))
        return {"ok": True, "typed": len(typed[-1])}

    def fake_keys(ctx, args):
        return {"ok": True, "combo": args.get("combo")}

    def fake_close(*, app="chrome"):
        return {"ok": True, "app": app, "method": "close-all"}

    def capture_run(plan):
        launched.append(plan)
        return {
            "ok": True,
            "started": plan.get("cmd"),
            "argv": list(plan.get("argv") or []),
            "window": True,
            "opened": plan.get("url"),
            "url": plan.get("url"),
        }

    def capture_plan(args):
        planned.append(dict(args))
        return {"ok": True, "cmd": "chrome", "argv": ["chromium"], **args}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    monkeypatch.setattr("app.jarvis.tools._type_text", fake_type)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    monkeypatch.setattr("app.jarvis.desktop.close_windows", fake_close)
    monkeypatch.setattr(computer_mod, "linux_run_app", capture_run)
    monkeypatch.setattr(computer_mod, "plan_linux_run_app", capture_plan)

    body = await run_voice_ask(ROME)
    assert planned, planned
    assert launched
    url = str(launched[0].get("url") or planned[0].get("url") or "")
    assert "google.com" in url or "booking.com" in url
    assert clicks, "must click a dismiss control"
    assert (920, 170) in clicks or SIGNIN_DISMISS_CLICK in clicks
    assert typed, "must type the destination after dismiss"
    assert any("Rome" in t or "rome" in t.lower() or "hotel" in t.lower() for t in typed)
    low = body["reply"].lower()
    assert "eden" in low or "roma" in low or "hotel" in low
    assert "turquoise" not in low
    assert "empty desktop" not in low
    assert body["reply"].strip().lower() not in {"done.", "done"}
    assert "sign in" not in low or "genius" not in low
    assert "look at the screen" not in low
    assert "turquoise" not in low
    assert "footer" not in low


@pytest.mark.asyncio
async def test_voice_ask_rome_scrolls_footer_then_types_named_field(
    monkeypatch,
):
    from app.jarvis import computer as computer_mod
    from app.jarvis.voice_ask import run_voice_ask

    planned: list[dict] = []
    launched: list[dict] = []
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        {
            "ok": True,
            "title": "Booking.com",
            "url": "https://www.booking.com/",
            "vision_description": (
                "Page scrolled to the footer. Copyright Booking.com. "
                "All rights reserved. Destinations we love at (640, 680)."
            ),
        },
        {
            "ok": True,
            "title": "Booking.com",
            "url": "https://www.booking.com/",
            "vision_description": (
                "Where are you going? Search box is empty at (412, 210)."
            ),
        },
        {
            "ok": True,
            "title": "Hotels in Rome — Booking.com",
            "url": "https://www.booking.com/searchresults.html",
            "vision_description": (
                "Hotels in central Rome. Hotel Eden. Prices from 180 EUR."
            ),
        },
    ]
    n = {"i": 0}

    def fake_see(ctx, args):
        item = looks[min(n["i"], len(looks) - 1)]
        n["i"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append((int(args.get("x") or 0), int(args.get("y") or 0)))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    def fake_type(ctx, args):
        typed.append(str((args or {}).get("text") or ""))
        return {"ok": True, "typed": len(typed[-1])}

    def fake_keys(ctx, args):
        keys.append(str(args.get("combo") or ""))
        return {"ok": True, "combo": args.get("combo")}

    def fake_scroll(ctx, args):
        return {"ok": True, "dy": args.get("dy")}

    def fake_close(*, app="chrome"):
        return {"ok": True, "app": app, "method": "close-all"}

    def capture_run(plan):
        launched.append(plan)
        return {
            "ok": True,
            "started": plan.get("cmd"),
            "argv": list(plan.get("argv") or []),
            "window": True,
            "opened": plan.get("url"),
            "url": plan.get("url"),
        }

    def capture_plan(args):
        planned.append(dict(args))
        return {"ok": True, "cmd": "chrome", "argv": ["chromium"], **args}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    monkeypatch.setattr("app.jarvis.tools._type_text", fake_type)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    monkeypatch.setattr("app.jarvis.tools._scroll", fake_scroll)
    monkeypatch.setattr("app.jarvis.desktop.close_windows", fake_close)
    monkeypatch.setattr(computer_mod, "linux_run_app", capture_run)
    monkeypatch.setattr(computer_mod, "plan_linux_run_app", capture_plan)

    body = await run_voice_ask(ROME)
    assert (640, 320) not in clicks
    assert (640, 680) not in clicks
    assert (412, 210) in clicks
    assert "home" in keys
    assert typed
    assert any("Rome" in t or "rome" in t.lower() or "hotel" in t.lower() for t in typed)
    low = body["reply"].lower()
    assert "eden" in low or "hotel" in low
    assert "look at the screen" not in low
    assert "turquoise" not in low
    assert "all rights reserved" not in low


def test_speak_web_job_never_look_at_screen_or_footer_caption():
    from app.jarvis.voice_ask import _speak_looked, _speak_web_job

    desktop = {
        "ok": True,
        "title": "",
        "vision_description": "A turquoise desktop background fills the screenshot.",
    }
    teal = {
        "ok": True,
        "title": "",
        "vision_description": (
            "A teal desktop with icons: Chrome, Files, Recycle Bin. "
            "You can access Chrome to search for hotels."
        ),
    }
    footer = {
        "ok": True,
        "title": "Booking.com",
        "vision_description": (
            "Footer. Copyright Booking.com. All rights reserved. "
            "Destinations we love."
        ),
    }
    empty = {
        "ok": True,
        "title": "Booking.com",
        "vision_description": "Where are you going? Search box is empty at (412, 210).",
    }
    pick = {
        "ok": True,
        "title": "Hotels in Rome",
        "vision_description": "Hotels in central Rome. Hotel Eden. Prices from 180 EUR.",
    }
    for looked in (desktop, teal, footer, empty, HOMEPAGE_NO_BOX, BLANK_HOMEPAGE):
        body = _speak_web_job(ROME, looked, ["see_screen"], opened=True)
        low = body["reply"].lower()
        assert "look at the screen" not in low
        assert "turquoise" not in low
        assert "teal" not in low
        assert "recycle" not in low
        assert "you can access chrome" not in low
        assert "you can open chrome" not in low
        assert "all rights reserved" not in low
        assert "destinations we love" not in low
        assert "mostly blank" not in low
        assert "white loading" not in low
        via = _speak_looked(looked, ["see_screen"], opened=True, asked=ROME)
        assert "look at the screen" not in via["reply"].lower()
        assert "turquoise" not in via["reply"].lower()
        assert "you can access chrome" not in via["reply"].lower()
        assert "mostly blank" not in via["reply"].lower()
    picked = _speak_web_job(ROME, pick, ["see_screen"], opened=True)
    assert "eden" in picked["reply"].lower() or "hotel" in picked["reply"].lower()
    assert "look at the screen" not in picked["reply"].lower()


@pytest.mark.asyncio
async def test_voice_ask_rome_types_on_homepage_without_search_box(
    monkeypatch,
):
    """Homepage look that never says 'search box' must still type Rome."""
    from app.jarvis import computer as computer_mod
    from app.jarvis.voice_ask import run_voice_ask

    planned: list[dict] = []
    launched: list[dict] = []
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    looks = [
        dict(HOMEPAGE_NO_BOX),
        {
            "ok": True,
            "title": "Hotels in Rome — Booking.com",
            "url": "https://www.booking.com/searchresults.html",
            "vision_description": (
                "Hotels in central Rome. Hotel Eden. The First Roma. "
                "Prices from 180 EUR. No checkout."
            ),
        },
    ]
    n = {"i": 0}

    def fake_see(ctx, args):
        item = looks[min(n["i"], len(looks) - 1)]
        n["i"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append((int(args.get("x") or 0), int(args.get("y") or 0)))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    def fake_type(ctx, args):
        typed.append(str((args or {}).get("text") or ""))
        return {"ok": True, "typed": len(typed[-1])}

    def fake_keys(ctx, args):
        return {"ok": True, "combo": args.get("combo")}

    def fake_close(*, app="chrome"):
        return {"ok": True, "app": app, "method": "close-all"}

    def capture_run(plan):
        launched.append(plan)
        return {
            "ok": True,
            "started": plan.get("cmd"),
            "argv": list(plan.get("argv") or []),
            "window": True,
            "opened": plan.get("url"),
            "url": plan.get("url"),
        }

    def capture_plan(args):
        planned.append(dict(args))
        return {"ok": True, "cmd": "chrome", "argv": ["chromium"], **args}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    monkeypatch.setattr("app.jarvis.tools._type_text", fake_type)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    monkeypatch.setattr("app.jarvis.desktop.close_windows", fake_close)
    monkeypatch.setattr(computer_mod, "linux_run_app", capture_run)
    monkeypatch.setattr(computer_mod, "plan_linux_run_app", capture_plan)

    body = await run_voice_ask(ROME)
    assert typed, "must type the destination on a homepage that omits 'search box'"
    assert any("Rome" in t or "rome" in t.lower() or "hotel" in t.lower() for t in typed)
    assert (640, 680) not in clicks
    low = body["reply"].lower()
    assert "eden" in low or "roma" in low or "hotel" in low
    assert "look at the screen" not in low
    assert "turquoise" not in low
    assert "teal" not in low
    assert "you can access chrome" not in low
    assert "you can open chrome" not in low
    assert "recycle" not in low


def test_see_again_after_overlays_types_web_query(monkeypatch):
    """Agent see_screen path must type before the model can speak a catalog."""
    from app.jarvis.tools import _see_again_after_overlays
    from app.jarvis.workspace import Workspace, default_workspace
    from app.jarvis.tools import ToolContext

    looks = [
        dict(HOMEPAGE_NO_BOX),
        {
            "ok": True,
            "title": "Hotels in Rome — Booking.com",
            "vision_description": (
                "Hotels in central Rome. Hotel Eden. Prices from 180 EUR."
            ),
        },
    ]
    n = {"i": 0}
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []

    def fake_see(ctx, args):
        n["i"] += 1
        return dict(looks[min(n["i"], len(looks) - 1)])

    def fake_click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def fake_type(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def fake_keys(*, combo="", **_k):
        return {"ok": True, "combo": combo}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.desktop.click", fake_click)
    monkeypatch.setattr("app.jarvis.desktop.type_text", fake_type)
    monkeypatch.setattr("app.jarvis.desktop.keys", fake_keys)

    ctx = ToolContext(Workspace(default_workspace()), None)
    out = _see_again_after_overlays(ctx, {"goal": ROME}, dict(HOMEPAGE_NO_BOX))
    assert typed, "see_screen on a hotel job must type the query"
    assert any("Rome" in t or "rome" in t.lower() or "hotel" in t.lower() for t in typed)
    assert (640, 320) in clicks
    assert "Eden" in str(out.get("vision_description") or "")


def test_annotate_see_screen_web_job_must_act():
    from app.jarvis.tools import annotate_see_screen

    looked = annotate_see_screen(
        {
            "ok": True,
            "vision_description": (
                "A turquoise desktop background fills the screenshot."
            ),
        },
        ROME,
    )
    assert looked.get("speak_now") is False
    assert looked.get("next_must") == ["click", "type", "keys"]


def test_blank_or_loading_look_is_not_a_ready_page():
    """A site title with a blank/loading caption is not done. Generic, not hotel-only."""
    assert look_is_loading_or_blank(BLANK_HOMEPAGE) is True
    assert look_is_loading_or_blank(BLANK_SHOP) is True
    assert look_is_web_page(BLANK_HOMEPAGE) is False
    assert look_is_web_page(BLANK_SHOP) is False
    assert search_box_point(BLANK_HOMEPAGE) is None
    assert search_box_point(BLANK_SHOP) is None
    assert needs_web_query(ROME, BLANK_HOMEPAGE, web_search_query(ROME)) is True
    assert needs_web_query(GRINDER, BLANK_SHOP, web_search_query(GRINDER)) is True
    assert look_is_loading_or_blank(HOMEPAGE_NO_BOX) is False
    assert look_is_empty_desktop(BLANK_HOMEPAGE) is False


def test_continue_web_search_waits_then_types_after_blank_look():
    """First look blank/loading — look again, then type. Not a hotel-only path."""
    looks = [
        dict(BLANK_HOMEPAGE),
        dict(HOMEPAGE_NO_BOX),
        {
            "ok": True,
            "title": "Hotels in Rome — Booking.com",
            "vision_description": (
                "Hotels in central Rome. Hotel Eden. Prices from 180 EUR."
            ),
        },
    ]
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    i = {"n": 0}

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def type_text(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def press(*, combo="", **_k):
        keys.append(str(combo))
        return {"ok": True}

    def look_again():
        i["n"] += 1
        return dict(looks[min(i["n"], len(looks) - 1)])

    out = continue_web_search(
        looks[0],
        goal=ROME,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
    )
    assert typed, "blank/loading first look must wait, then type"
    assert any("Rome" in t or "rome" in t.lower() or "hotel" in t.lower() for t in typed)
    assert (640, 320) in clicks
    assert "enter" in keys
    assert out.get("_typed_query")
    assert "Eden" in str(out.get("vision_description") or "")


def _patch_voice_ask_web(monkeypatch, looks, *, clicks, typed, keys=None):
    from app.jarvis import computer as computer_mod

    n = {"i": 0}

    def fake_see(ctx, args):
        item = looks[min(n["i"], len(looks) - 1)]
        n["i"] += 1
        return dict(item)

    def fake_click(ctx, args):
        clicks.append((int(args.get("x") or 0), int(args.get("y") or 0)))
        return {"ok": True, "x": args.get("x"), "y": args.get("y")}

    def fake_type(ctx, args):
        typed.append(str((args or {}).get("text") or ""))
        return {"ok": True, "typed": len(typed[-1])}

    def fake_keys(ctx, args):
        if keys is not None:
            keys.append(str(args.get("combo") or ""))
        return {"ok": True, "combo": args.get("combo")}

    def fake_close(*, app="chrome"):
        return {"ok": True, "app": app, "method": "close-all"}

    def capture_run(plan):
        return {
            "ok": True,
            "started": plan.get("cmd"),
            "argv": list(plan.get("argv") or []),
            "window": True,
            "opened": plan.get("url"),
            "url": plan.get("url"),
        }

    def capture_plan(args):
        return {"ok": True, "cmd": "chrome", "argv": ["chromium"], **args}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.tools._click", fake_click)
    monkeypatch.setattr("app.jarvis.tools._type_text", fake_type)
    monkeypatch.setattr("app.jarvis.tools._keys", fake_keys)
    monkeypatch.setattr("app.jarvis.desktop.close_windows", fake_close)
    monkeypatch.setattr(computer_mod, "linux_run_app", capture_run)
    monkeypatch.setattr(computer_mod, "plan_linux_run_app", capture_plan)


@pytest.mark.asyncio
async def test_voice_ask_blank_look_types_before_speak_look_speed_off(
    monkeypatch, tmp_path
):
    """Hotel-shaped example: blank first look + look_speed=off still types."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    assert settings_store.get_look_speed() == "off"

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(BLANK_HOMEPAGE),
        dict(HOMEPAGE_NO_BOX),
        {
            "ok": True,
            "title": "Hotels in Rome — Booking.com",
            "url": "https://www.booking.com/searchresults.html",
            "vision_description": (
                "Hotels in central Rome. Hotel Eden. Prices from 180 EUR."
            ),
        },
    ]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(ROME)
    assert "click" in body["tools_used"]
    assert "type" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert typed, "look_speed=off must not skip typing after a blank look"
    assert any("Rome" in t or "rome" in t.lower() or "hotel" in t.lower() for t in typed)
    low = body["reply"].lower()
    assert "eden" in low or "hotel" in low
    assert "mostly blank" not in low
    assert "white loading" not in low
    assert "you can open chrome" not in low
    assert "turquoise" not in low
    assert "look at the screen" not in low


@pytest.mark.asyncio
async def test_voice_ask_blank_look_types_non_hotel_web_job(monkeypatch, tmp_path):
    """Same path for a non-hotel find/search job. Not Booking.com-only."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(BLANK_SHOP),
        {
            "ok": True,
            "title": "bol.com",
            "url": "https://www.bol.com/",
            "vision_description": (
                "bol.com. Search box is empty at (640, 320). Coffee machines."
            ),
        },
        {
            "ok": True,
            "title": "coffee grinder — bol.com",
            "url": "https://www.bol.com/nl/nl/s/?searchtext=coffee+grinder",
            "vision_description": (
                "Search results for coffee grinder. Baratza Encore. From 89 EUR."
            ),
        },
    ]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(GRINDER)
    assert "click" in body["tools_used"]
    assert "type" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert typed
    assert any("grinder" in t.lower() or "coffee" in t.lower() for t in typed)
    low = body["reply"].lower()
    assert "baratza" in low or "encore" in low or "grinder" in low
    assert "mostly blank" not in low
    assert "you can open chrome" not in low
    assert "look at the screen" not in low


def test_see_again_after_overlays_types_after_blank_look(monkeypatch):
    """Agent see_screen path: blank first look still types before speak."""
    from app.jarvis.tools import ToolContext, _see_again_after_overlays
    from app.jarvis.workspace import Workspace, default_workspace

    looks = [
        dict(BLANK_SHOP),
        {
            "ok": True,
            "title": "bol.com",
            "vision_description": "Search box is empty at (640, 320).",
        },
        {
            "ok": True,
            "title": "coffee grinder — bol.com",
            "vision_description": (
                "Search results for coffee grinder. Baratza Encore. From 89 EUR."
            ),
        },
    ]
    n = {"i": 0}
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []

    def fake_see(ctx, args):
        n["i"] += 1
        return dict(looks[min(n["i"], len(looks) - 1)])

    def fake_click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def fake_type(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def fake_keys(*, combo="", **_k):
        return {"ok": True, "combo": combo}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.desktop.click", fake_click)
    monkeypatch.setattr("app.jarvis.desktop.type_text", fake_type)
    monkeypatch.setattr("app.jarvis.desktop.keys", fake_keys)

    ctx = ToolContext(Workspace(default_workspace()), None)
    out = _see_again_after_overlays(ctx, {"goal": GRINDER}, dict(BLANK_SHOP))
    assert typed, "see_screen on a blank shop look must type the query"
    assert any("grinder" in t.lower() or "coffee" in t.lower() for t in typed)
    assert (640, 320) in clicks
    assert out.get("_typed_query")
    assert "Encore" in str(out.get("vision_description") or "")


def test_see_again_leftover_403_focuses_new_tab_before_type(monkeypatch):
    """see_screen leftover 403: one Ctrl+T, click New Tab, then omnibox type."""
    from app.jarvis.tools import ToolContext, _see_again_after_overlays
    from app.jarvis.workspace import Workspace, default_workspace

    looks = [
        dict(LEFTOVER_SHOP),
        dict(LEFTOVER_SHOP),
        dict(NEW_TAB_CHROME),
        dict(WEATHER_AFTER_TYPE),
    ]
    n = {"i": 0}
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []

    def fake_see(ctx, args):
        n["i"] += 1
        return dict(looks[min(n["i"], len(looks) - 1)])

    def fake_click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def fake_type(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def fake_keys(*, combo="", **_k):
        keys.append(str(combo))
        return {"ok": True, "combo": combo}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.desktop.click", fake_click)
    monkeypatch.setattr("app.jarvis.desktop.type_text", fake_type)
    monkeypatch.setattr("app.jarvis.desktop.keys", fake_keys)

    ctx = ToolContext(Workspace(default_workspace()), None)
    out = _see_again_after_overlays(ctx, {"goal": LIVE_WEATHER}, dict(LEFTOVER_SHOP))
    assert keys.count("ctrl+t") == 1
    assert any(xy in NEW_TAB_FOCUS_CLICKS for xy in clicks)
    assert OMNIBOX_CLICK in clicks
    assert typed
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    assert SEARCH_BOX_CLICK not in clicks
    assert out.get("_typed_query")
    assert "click" in (out.get("_tools_used") or [])
    assert "type" in (out.get("_tools_used") or [])
    assert "keys" in (out.get("_tools_used") or [])
    blob = str(out.get("vision_description") or "").lower()
    assert "403" not in blob
    assert "bol.com" not in blob or "weather" in blob


def test_annotate_see_screen_leftover_does_not_speak():
    from app.jarvis.tools import annotate_see_screen

    looked = annotate_see_screen(dict(LEFTOVER_SHOP), LIVE_WEATHER)
    assert looked.get("speak_now") is False
    assert looked.get("next_must") == ["click", "type", "keys"]
    hint = str(looked.get("hint") or "").lower()
    assert "leftover" in hint or "new tab" in hint or "omnibox" in hint


def test_web_look_pause_is_seconds_not_a_fraction():
    """Live wait between Untitled looks is seconds. 0.4s is not a wait."""
    assert WEB_LOOK_PAUSE_S >= 1.0
    assert BLANK_LOOKS_BEFORE_OMNIBOX >= 2
    assert OMNIBOX_CLICK[1] < 110
    assert OMNIBOX_CLICK != SEARCH_BOX_CLICK
    assert NEW_TAB_CLICK[1] < 40
    assert NEW_TAB_CLICK in NEW_TAB_FOCUS_CLICKS


def test_untitled_look_is_not_a_ready_page():
    assert look_is_loading_or_blank(UNTITLED_CHROME) is True
    assert look_is_web_page(UNTITLED_CHROME) is False
    assert search_box_point(UNTITLED_CHROME) is None
    assert needs_web_query(WEATHER, UNTITLED_CHROME, web_search_query(WEATHER)) is True


def test_continue_web_search_untitled_waits_then_types_field():
    """Untitled first look must keep looking, then type the real field."""
    looks = [
        dict(UNTITLED_CHROME),
        dict(UNTITLED_CHROME),
        dict(HOMEPAGE_NO_BOX),
        {
            "ok": True,
            "title": "Hotels in Rome — Booking.com",
            "vision_description": (
                "Hotels in central Rome. Hotel Eden. Prices from 180 EUR."
            ),
        },
    ]
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    i = {"n": 0}

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def type_text(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def press(*, combo="", **_k):
        keys.append(str(combo))
        return {"ok": True}

    def look_again():
        i["n"] += 1
        return dict(looks[min(i["n"], len(looks) - 1)])

    out = continue_web_search(
        looks[0],
        goal=ROME,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
    )
    assert i["n"] >= 2, "Untitled must be looked at more than once before type"
    assert typed, "Untitled first look must wait, then type"
    assert any("Rome" in t or "rome" in t.lower() or "hotel" in t.lower() for t in typed)
    assert SEARCH_BOX_CLICK in clicks
    assert OMNIBOX_CLICK not in clicks
    assert "enter" in keys
    assert out.get("_typed_query")
    assert "Eden" in str(out.get("vision_description") or "")


def test_continue_web_search_untitled_types_omnibox_after_few_looks():
    """Still Untitled after a few looks — type the omnibox. Never return without type."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    i = {"n": 0}

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def type_text(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def press(*, combo="", **_k):
        keys.append(str(combo))
        return {"ok": True}

    def look_again():
        i["n"] += 1
        return dict(UNTITLED_CHROME)

    out = continue_web_search(
        dict(UNTITLED_CHROME),
        goal=WEATHER,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
    )
    assert i["n"] >= 2, "must keep looking at Untitled before omnibox type"
    assert typed, "never return without type on a still-Untitled tab"
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    assert OMNIBOX_CLICK in clicks
    assert SEARCH_BOX_CLICK not in clicks
    assert "enter" in keys
    assert out.get("_typed_query")


def test_speak_web_job_untitled_is_not_still_opening():
    """Do not speak the opening-stuck caption after one Untitled look."""
    from app.jarvis.voice_ask import _speak_looked, _speak_web_job

    body = _speak_web_job(
        WEATHER, dict(UNTITLED_CHROME), ["run_app", "see_screen"], opened=True
    )
    low = body["reply"].lower()
    assert "still opening" not in low
    assert "mostly blank" not in low
    assert "you can open chrome" not in low
    via = _speak_looked(
        dict(UNTITLED_CHROME), ["run_app", "see_screen"], opened=True, asked=WEATHER
    )
    assert "still opening" not in via["reply"].lower()
    typed = dict(UNTITLED_CHROME)
    typed["_typed_query"] = "weather in Amsterdam"
    after = _speak_web_job(
        WEATHER, typed, ["run_app", "see_screen", "click", "type", "keys"], opened=True
    )
    assert "still opening" not in after["reply"].lower()
    assert "could not finish" not in after["reply"].lower()


@pytest.mark.asyncio
async def test_voice_ask_untitled_first_look_waits_then_types(monkeypatch, tmp_path):
    """Untitled first look + look_speed=off still waits, then records click+type+keys."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    assert settings_store.get_look_speed() == "off"
    assert remaining_ask_deadline_s(ROME) >= 12.0

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(UNTITLED_CHROME),
        dict(UNTITLED_CHROME),
        dict(UNTITLED_CHROME),
        dict(HOMEPAGE_NO_BOX),
        {
            "ok": True,
            "title": "Hotels in Rome — Booking.com",
            "url": "https://www.booking.com/searchresults.html",
            "vision_description": (
                "Hotels in central Rome. Hotel Eden. Prices from 180 EUR."
            ),
        },
    ]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(ROME)
    assert "click" in body["tools_used"]
    assert "type" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert typed, "Untitled first look must wait then type before speak"
    assert any("Rome" in t or "rome" in t.lower() or "hotel" in t.lower() for t in typed)
    low = body["reply"].lower()
    assert "still opening" not in low
    assert "could not finish" not in low
    assert "eden" in low or "hotel" in low
    assert "look at the screen" not in low
    assert "you can open chrome" not in low


@pytest.mark.asyncio
async def test_voice_ask_untitled_non_shop_job_same_path(monkeypatch, tmp_path):
    """A non-shop / non-hotel job takes the same wait-then-type path."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(UNTITLED_CHROME),
        dict(UNTITLED_CHROME),
        dict(UNTITLED_CHROME),
        {
            "ok": True,
            "title": "Google",
            "url": "https://www.google.com/",
            "vision_description": "Google. Search box is empty at (640, 320).",
        },
        {
            "ok": True,
            "title": "weather in Amsterdam - Google Search",
            "url": "https://www.google.com/search?q=weather+amsterdam",
            "vision_description": (
                "Search results for weather in Amsterdam. "
                "12 degrees. Clear skies."
            ),
        },
    ]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(WEATHER)
    assert "click" in body["tools_used"]
    assert "type" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert typed
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    low = body["reply"].lower()
    assert "still opening" not in low
    assert "could not finish" not in low
    assert "amsterdam" in low or "weather" in low or "degrees" in low
    assert "you can open chrome" not in low
    assert "look at the screen" not in low


@pytest.mark.asyncio
async def test_voice_ask_untitled_does_not_speak_stuck_while_opening(
    monkeypatch, tmp_path
):
    """Stuck caption is not allowed while Untitled is still opening inside the deadline."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [dict(UNTITLED_CHROME)]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(GRINDER)
    assert remaining_ask_deadline_s(GRINDER) > 0
    assert "type" in body["tools_used"]
    assert "click" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert typed, "must type into the omnibox before any spoken reply"
    assert any("grinder" in t.lower() or "coffee" in t.lower() for t in typed)
    assert OMNIBOX_CLICK in clicks
    low = body["reply"].lower()
    assert "still opening" not in low
    assert "could not finish" not in low
    assert "you can open chrome" not in low
    assert "turquoise" not in low


LEFTOVER_SHOP = {
    "ok": True,
    "title": "www.bol.com - Chromium",
    "url": "https://www.bol.com/",
    "vision_description": (
        "The visible desktop screenshot shows a browser window titled "
        "www.bol.com - Chromium. The page displays an HTTP 403 error. "
        "Three leftover shop tabs stay on screen."
    ),
}

LEFTOVER_WEATHER = {
    "ok": True,
    "title": "weather in Amsterdam - Google Search",
    "url": "https://www.google.com/search?q=weather+amsterdam",
    "vision_description": (
        "Search results for weather in Amsterdam. 12 degrees. Clear skies."
    ),
}

WEATHER_AFTER_TYPE = {
    "ok": True,
    "title": "today's weather in Amsterdam - Google Search",
    "url": "https://www.google.com/search?q=today+weather+amsterdam",
    "vision_description": (
        "Today's weather in Amsterdam. 12 degrees. Clear skies. No rain."
    ),
}

SHOP_AFTER_TYPE = {
    "ok": True,
    "title": "coffee grinder — bol.com",
    "url": "https://www.bol.com/nl/nl/s/?searchtext=coffee+grinder",
    "vision_description": (
        "Search results for coffee grinder. Baratza Encore. From 89 EUR."
    ),
}

NEW_TAB_CHROME = {
    "ok": True,
    "title": "New Tab - Chromium",
    "url": "chrome://newtab",
    "vision_description": "A Chromium New Tab. The omnibox is empty.",
}

LEFTOVER_EXTENSIONS = {
    "ok": True,
    "title": "Extensions - Chromium",
    "url": "chrome://extensions",
    "vision_description": (
        "Chromium focused on chrome://extensions (uBlock Origin Lite). "
        "Omnibox chrome://extensions. bol.com 403 not focused. "
        "New Tab not focused. No weather query."
    ),
}

LEFTOVER_SETTINGS = {
    "ok": True,
    "title": "Settings - Chromium",
    "url": "chrome://settings",
    "vision_description": "Chromium Settings. Search settings. No weather query.",
}

LEFTOVER_THUNAR = {
    "ok": True,
    "title": "Thunar",
    "url": "",
    "vision_description": "Thunar file manager is open. Home folder.",
}

LEFTOVER_TERMINAL = {
    "ok": True,
    "title": "Terminal",
    "url": "",
    "vision_description": "xfce4-terminal is focused. A shell prompt.",
}

LEFTOVER_UNRELATED = {
    "ok": True,
    "title": "Python (programming language) - Wikipedia",
    "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "vision_description": "Wikipedia article about the Python programming language.",
}

LEFTOVER_403_CAPTION = (
    'The focused window is titled "www.bol.com - Chromium." '
    'The page displays an error message stating, "Access Denied" HTTP 403.'
)


def test_leftover_title_is_not_a_ready_page_for_this_ask():
    """Shop vs weather, weather vs shop — leftover is not done. Hotel homepage is."""
    assert look_is_leftover_for_ask(LEFTOVER_SHOP, WEATHER) is True
    assert look_is_page_ready(LEFTOVER_SHOP, WEATHER) is False
    assert needs_web_query(WEATHER, LEFTOVER_SHOP, web_search_query(WEATHER)) is True
    assert look_is_leftover_for_ask(LEFTOVER_WEATHER, GRINDER) is True
    assert look_is_page_ready(LEFTOVER_WEATHER, GRINDER) is False
    assert needs_web_query(GRINDER, LEFTOVER_WEATHER, web_search_query(GRINDER)) is True
    assert look_is_leftover_for_ask(HOMEPAGE_NO_BOX, ROME) is False
    assert look_is_page_ready(HOMEPAGE_NO_BOX, ROME) is True
    assert look_is_leftover_for_ask(UNTITLED_CHROME, WEATHER) is False
    assert look_is_http_error(LEFTOVER_SHOP) is True
    assert look_is_focused_new_tab(LEFTOVER_SHOP) is False
    assert look_is_focused_new_tab(NEW_TAB_CHROME) is True
    assert look_is_focused_new_tab(UNTITLED_CHROME) is True
    assert look_is_leftover_surface(LEFTOVER_EXTENSIONS) is True
    assert look_is_leftover_for_ask(LEFTOVER_EXTENSIONS, WEATHER) is True
    assert look_is_leftover_for_ask(LEFTOVER_EXTENSIONS, LIVE_WEATHER) is True
    assert look_is_page_ready(LEFTOVER_EXTENSIONS, WEATHER) is False
    assert look_is_focused_new_tab(LEFTOVER_EXTENSIONS) is False
    assert look_is_web_page(LEFTOVER_EXTENSIONS) is False
    assert search_box_point(LEFTOVER_EXTENSIONS) is None
    assert needs_web_query(WEATHER, LEFTOVER_EXTENSIONS, web_search_query(WEATHER)) is True
    assert look_is_leftover_surface(NEW_TAB_CHROME) is False
    for leftover in (
        LEFTOVER_SETTINGS,
        LEFTOVER_THUNAR,
        LEFTOVER_TERMINAL,
        LEFTOVER_UNRELATED,
    ):
        assert look_is_leftover_for_ask(leftover, WEATHER) is True, leftover["title"]
        assert look_is_focused_new_tab(leftover) is False, leftover["title"]
    for leftover in (LEFTOVER_SETTINGS, LEFTOVER_THUNAR, LEFTOVER_TERMINAL):
        assert look_is_leftover_surface(leftover) is True, leftover["title"]
        assert search_box_point(leftover) is None, leftover["title"]
    still_shop = dict(LEFTOVER_SHOP)
    still_shop["vision_description"] = (
        "www.bol.com HTTP 403. Two New Tab tabs sit on the right of the strip."
    )
    assert look_is_focused_new_tab(still_shop) is False
    assert wants_web_job(LIVE_WEATHER) is True


def _run_continue(looks, goal, clicks, typed, keys):
    i = {"n": 0}

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def type_text(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def press(*, combo="", **_k):
        keys.append(str(combo))
        return {"ok": True}

    def look_again():
        i["n"] += 1
        return dict(looks[min(i["n"], len(looks) - 1)])

    return continue_web_search(
        looks[0],
        goal=goal,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
    )


def test_continue_web_search_leftover_shop_types_weather_in_new_tab():
    """Leftover shop look + weather ask: Ctrl+T or omnibox, never the shop field."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    out = _run_continue(
        [dict(LEFTOVER_SHOP), dict(WEATHER_AFTER_TYPE)],
        WEATHER,
        clicks,
        typed,
        keys,
    )
    assert typed, "leftover shop must type THIS weather query"
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    new_tab = "ctrl+t" in {k.lower() for k in keys} or OMNIBOX_CLICK in clicks
    assert new_tab, "must Ctrl+T or omnibox-type, not the leftover shop field"
    assert SEARCH_BOX_CLICK not in clicks
    assert "enter" in keys
    assert out.get("_typed_query")
    blob = str(out.get("vision_description") or "").lower()
    assert "amsterdam" in blob or "weather" in blob or "degrees" in blob
    assert "403" not in blob
    assert "bol.com" not in blob or "weather" in blob


def test_continue_web_search_ctrl_t_without_focus_clicks_new_tab():
    """Ctrl+T that leaves leftover 403 focused is a fail — click New Tab first."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    out = _run_continue(
        [
            dict(LEFTOVER_SHOP),
            dict(LEFTOVER_SHOP),
            dict(NEW_TAB_CHROME),
            dict(WEATHER_AFTER_TYPE),
        ],
        WEATHER,
        clicks,
        typed,
        keys,
    )
    assert keys.count("ctrl+t") == 1, "Ctrl+T once — do not spray empty tabs"
    assert any(xy in NEW_TAB_FOCUS_CLICKS for xy in clicks), (
        "must click the new tab until title is New Tab, not leftover"
    )
    assert OMNIBOX_CLICK in clicks
    assert typed, "weather query must be typed after New Tab is focused"
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    assert SEARCH_BOX_CLICK not in clicks
    assert look_is_focused_new_tab(out) or "weather" in str(
        out.get("vision_description") or ""
    ).lower()
    blob = str(out.get("title") or "").lower()
    assert "bol.com" not in blob
    assert "403" not in str(out.get("vision_description") or "").lower()


def test_continue_web_search_leftover_weather_types_shop_in_new_tab():
    """Leftover weather look + shop ask takes the same new-tab / omnibox path."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    out = _run_continue(
        [dict(LEFTOVER_WEATHER), dict(SHOP_AFTER_TYPE)],
        GRINDER,
        clicks,
        typed,
        keys,
    )
    assert typed
    assert any("grinder" in t.lower() or "coffee" in t.lower() for t in typed)
    new_tab = "ctrl+t" in {k.lower() for k in keys} or OMNIBOX_CLICK in clicks
    assert new_tab, "must Ctrl+T or omnibox-type the shop query"
    assert SEARCH_BOX_CLICK not in clicks
    assert "enter" in keys
    assert out.get("_typed_query")
    blob = str(out.get("vision_description") or "").lower()
    assert "grinder" in blob or "baratza" in blob or "encore" in blob
    assert "amsterdam" not in blob or "grinder" in blob


def test_speak_web_job_never_speaks_leftover_caption():
    from app.jarvis.voice_ask import _speak_looked, _speak_web_job

    for looked, asked in (
        (LEFTOVER_SHOP, WEATHER),
        (LEFTOVER_WEATHER, GRINDER),
    ):
        body = _speak_web_job(asked, dict(looked), ["see_screen"], opened=False)
        low = body["reply"].lower()
        assert "bol.com" not in low
        assert "www.bol.com" not in low
        assert "403" not in low
        assert "visible desktop screenshot" not in low
        assert "look at the screen" not in low
        via = _speak_looked(dict(looked), ["see_screen"], opened=False, asked=asked)
        assert "bol.com" not in via["reply"].lower()
        assert "visible desktop screenshot" not in via["reply"].lower()
    typed = dict(LEFTOVER_SHOP)
    typed["_typed_query"] = "today's weather in Amsterdam"
    after = _speak_web_job(
        WEATHER,
        typed,
        ["see_screen", "click", "type", "keys"],
        opened=False,
    )
    low = after["reply"].lower()
    assert "bol.com" not in low
    assert "visible desktop screenshot" not in low
    assert "403" not in low
    assert "i typed the search" not in low


def test_speak_looked_without_asked_never_leaks_leftover_403():
    """_speak_web_job leftover guard must run even when asked was omitted."""
    from app.jarvis.voice_ask import (
        _reply_leaks_leftover,
        _speak_looked,
        spoken_job_line,
    )

    leaked = _speak_looked(dict(LEFTOVER_SHOP), ["see_screen"], opened=False)
    low = leaked["reply"].lower()
    assert "bol.com" not in low
    assert "www.bol.com" not in low
    assert "403" not in low
    assert "focused window is titled" not in low
    assert "access" not in low or "denied" not in low
    assert _reply_leaks_leftover(LEFTOVER_403_CAPTION, WEATHER) is True
    assert _reply_leaks_leftover(LEFTOVER_403_CAPTION, LIVE_WEATHER) is True
    line = spoken_job_line(LEFTOVER_403_CAPTION)
    assert "bol.com" not in line.lower() or line == "I looked."


@pytest.mark.asyncio
async def test_voice_ask_leftover_shop_types_weather_look_speed_off(
    monkeypatch, tmp_path
):
    """Chrome already on leftover shop: type weather in a new tab, never the caption."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    assert settings_store.get_look_speed() == "off"

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [dict(LEFTOVER_SHOP), dict(WEATHER_AFTER_TYPE)]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(WEATHER)
    assert "click" in body["tools_used"]
    assert "type" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert typed, "look_speed=off must not skip leftover new-tab type"
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    new_tab = "ctrl+t" in {k.lower() for k in keys} or OMNIBOX_CLICK in clicks
    assert new_tab
    assert SEARCH_BOX_CLICK not in clicks
    low = body["reply"].lower()
    assert "amsterdam" in low or "weather" in low or "degrees" in low
    assert "bol.com" not in low
    assert "www.bol.com" not in low
    assert "403" not in low
    assert "visible desktop screenshot" not in low
    assert "look at the screen" not in low


@pytest.mark.asyncio
async def test_voice_ask_leftover_weather_types_shop_same_path(
    monkeypatch, tmp_path
):
    """Leftover weather look + shop ask: same new-tab / omnibox path."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [dict(LEFTOVER_WEATHER), dict(SHOP_AFTER_TYPE)]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(GRINDER)
    assert "click" in body["tools_used"]
    assert "type" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert typed
    assert any("grinder" in t.lower() or "coffee" in t.lower() for t in typed)
    new_tab = "ctrl+t" in {k.lower() for k in keys} or OMNIBOX_CLICK in clicks
    assert new_tab
    assert SEARCH_BOX_CLICK not in clicks
    low = body["reply"].lower()
    assert "grinder" in low or "baratza" in low or "encore" in low
    assert "amsterdam" not in low or "grinder" in low
    assert "look at the screen" not in low


@pytest.mark.asyncio
async def test_tell_from_current_screen_leftover_shop_no_run_app(
    monkeypatch, tmp_path
):
    """Chrome already open — no run_app. Leftover shop is not spoken."""
    from app.jarvis.voice_ask import _tell_from_current_screen

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [dict(LEFTOVER_SHOP), dict(WEATHER_AFTER_TYPE)]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = _tell_from_current_screen(WEATHER)
    assert "run_app" not in body["tools_used"]
    assert "see_screen" in body["tools_used"]
    assert "click" in body["tools_used"]
    assert "type" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert typed
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    new_tab = "ctrl+t" in {k.lower() for k in keys} or OMNIBOX_CLICK in clicks
    assert new_tab
    low = body["reply"].lower()
    assert "amsterdam" in low or "weather" in low or "degrees" in low
    assert "bol.com" not in low
    assert "visible desktop screenshot" not in low


@pytest.mark.asyncio
async def test_voice_ask_leftover_403_focuses_new_tab_then_types(
    monkeypatch, tmp_path
):
    """Live leftover 403: one Ctrl+T, focus New Tab, type weather. Never leftover speech."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    assert settings_store.get_look_speed() == "off"

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(LEFTOVER_SHOP),
        dict(LEFTOVER_SHOP),
        dict(NEW_TAB_CHROME),
        dict(WEATHER_AFTER_TYPE),
    ]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(LIVE_WEATHER)
    assert "run_app" not in body["tools_used"]
    assert "click" in body["tools_used"]
    assert "type" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert keys.count("ctrl+t") == 1, "Ctrl+T without focus is a fail — do not spray tabs"
    assert any(xy in NEW_TAB_FOCUS_CLICKS for xy in clicks)
    assert OMNIBOX_CLICK in clicks
    assert typed, "must type THIS weather query after New Tab is focused"
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    assert SEARCH_BOX_CLICK not in clicks
    low = body["reply"].lower()
    assert "amsterdam" in low or "weather" in low or "degrees" in low
    assert "bol.com" not in low
    assert "www.bol.com" not in low
    assert "403" not in low
    assert "focused window is titled" not in low
    assert "visible desktop screenshot" not in low
    assert not low.rstrip().endswith('"access')
    assert "access." not in low


@pytest.mark.asyncio
async def test_voice_ask_leftover_last_look_skips_run_app(monkeypatch, tmp_path):
    """A leftover last_look is enough — no run_app, same New Tab path."""
    from app.jarvis import settings_store
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    reset_last_look()
    remember_last_look(dict(LEFTOVER_SHOP))

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(LEFTOVER_SHOP),
        dict(LEFTOVER_SHOP),
        dict(NEW_TAB_CHROME),
        dict(WEATHER_AFTER_TYPE),
    ]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(WEATHER)
    assert "run_app" not in body["tools_used"]
    assert "click" in body["tools_used"]
    assert "type" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert keys.count("ctrl+t") == 1
    assert any(xy in NEW_TAB_FOCUS_CLICKS for xy in clicks)
    assert typed
    low = body["reply"].lower()
    assert "bol.com" not in low
    assert "403" not in low
    reset_last_look()


def test_continue_web_search_leftover_extensions_types_weather_in_new_tab():
    """Leftover Extensions + weather: Ctrl+T, focus New Tab, omnibox-type THIS ask."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    acts: list[str] = []
    looks = [
        dict(LEFTOVER_EXTENSIONS),
        dict(LEFTOVER_EXTENSIONS),
        dict(NEW_TAB_CHROME),
        dict(WEATHER_AFTER_TYPE),
    ]
    i = {"n": 0}

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        acts.append("click")
        return {"ok": True}

    def type_text(*, text="", **_k):
        typed.append(str(text))
        acts.append("type")
        return {"ok": True}

    def press(*, combo="", **_k):
        keys.append(str(combo))
        acts.append("keys")
        return {"ok": True}

    def look_again():
        i["n"] += 1
        acts.append("look")
        return dict(looks[min(i["n"], len(looks) - 1)])

    out = continue_web_search(
        looks[0],
        goal=LIVE_WEATHER,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
    )
    assert keys.count("ctrl+t") == 1
    assert any(xy in NEW_TAB_FOCUS_CLICKS for xy in clicks)
    assert OMNIBOX_CLICK in clicks
    assert typed, "leftover Extensions must omnibox-type THIS weather query"
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    assert all(_typed_is_user_query(t) for t in typed)
    assert SEARCH_BOX_CLICK not in clicks
    assert "enter" in keys
    assert out.get("_typed_query")
    assert "look" in acts
    assert acts.index("type") < max(idx for idx, name in enumerate(acts) if name == "look"), (
        "after type must look again before speak"
    )
    blob = str(out.get("vision_description") or "").lower()
    title = str(out.get("title") or "").lower()
    assert "amsterdam" in blob or "weather" in blob or "degrees" in blob
    assert "extensions" not in title
    assert "ublock" not in blob or "weather" in blob
    assert look_is_leftover_for_ask(out, LIVE_WEATHER) is False


def test_speak_web_job_extensions_typed_is_not_success():
    """Speaking 'I typed the search' with Extensions still focused is a fail."""
    from app.jarvis.voice_ask import _speak_looked, _speak_web_job

    typed = dict(LEFTOVER_EXTENSIONS)
    typed["_typed_query"] = "today's weather in Amsterdam"
    tools = ["see_screen", "click", "type", "keys"]
    body = _speak_web_job(LIVE_WEATHER, typed, tools, opened=False)
    low = body["reply"].lower()
    assert "i typed the search" not in low
    assert "ublock" not in low
    assert "extensions" not in low
    assert "chrome://extensions" not in low
    via = _speak_looked(typed, tools, opened=False, asked=LIVE_WEATHER)
    assert "i typed the search" not in via["reply"].lower()
    assert "ublock" not in via["reply"].lower()
    shown = dict(WEATHER_AFTER_TYPE)
    shown["_typed_query"] = "today's weather in Amsterdam"
    after = _speak_web_job(LIVE_WEATHER, shown, tools, opened=False)
    after_low = after["reply"].lower()
    assert "amsterdam" in after_low or "weather" in after_low or "degrees" in after_low
    assert "extensions" not in after_low


def test_see_again_leftover_extensions_focuses_new_tab_before_type(monkeypatch):
    """see_screen leftover Extensions: one Ctrl+T, click New Tab, then omnibox type."""
    from app.jarvis.tools import ToolContext, _see_again_after_overlays
    from app.jarvis.workspace import Workspace, default_workspace

    looks = [
        dict(LEFTOVER_EXTENSIONS),
        dict(LEFTOVER_EXTENSIONS),
        dict(NEW_TAB_CHROME),
        dict(WEATHER_AFTER_TYPE),
    ]
    n = {"i": 0}
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []

    def fake_see(ctx, args):
        n["i"] += 1
        return dict(looks[min(n["i"], len(looks) - 1)])

    def fake_click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def fake_type(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def fake_keys(*, combo="", **_k):
        keys.append(str(combo))
        return {"ok": True, "combo": combo}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.desktop.click", fake_click)
    monkeypatch.setattr("app.jarvis.desktop.type_text", fake_type)
    monkeypatch.setattr("app.jarvis.desktop.keys", fake_keys)

    ctx = ToolContext(Workspace(default_workspace()), None)
    out = _see_again_after_overlays(ctx, {"goal": LIVE_WEATHER}, dict(LEFTOVER_EXTENSIONS))
    assert keys.count("ctrl+t") == 1
    assert any(xy in NEW_TAB_FOCUS_CLICKS for xy in clicks)
    assert OMNIBOX_CLICK in clicks
    assert typed
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    assert SEARCH_BOX_CLICK not in clicks
    assert out.get("_typed_query")
    assert "click" in (out.get("_tools_used") or [])
    assert "type" in (out.get("_tools_used") or [])
    assert "keys" in (out.get("_tools_used") or [])
    blob = str(out.get("vision_description") or "").lower()
    assert "ublock" not in blob or "weather" in blob
    assert "extensions" not in str(out.get("title") or "").lower()


def test_annotate_see_screen_leftover_extensions_does_not_speak():
    from app.jarvis.tools import annotate_see_screen

    looked = annotate_see_screen(dict(LEFTOVER_EXTENSIONS), LIVE_WEATHER)
    assert looked.get("speak_now") is False
    assert looked.get("next_must") == ["click", "type", "keys"]
    hint = str(looked.get("hint") or "").lower()
    assert "leftover" in hint or "new tab" in hint or "omnibox" in hint


@pytest.mark.asyncio
async def test_voice_ask_leftover_extensions_focuses_new_tab_then_types(
    monkeypatch, tmp_path
):
    """Live leftover Extensions: New Tab + omnibox weather. Never 'I typed the search'."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    assert settings_store.get_look_speed() == "off"

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(LEFTOVER_EXTENSIONS),
        dict(LEFTOVER_EXTENSIONS),
        dict(NEW_TAB_CHROME),
        dict(WEATHER_AFTER_TYPE),
    ]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(LIVE_WEATHER)
    assert "run_app" not in body["tools_used"]
    assert "click" in body["tools_used"]
    assert "type" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert keys.count("ctrl+t") == 1
    assert any(xy in NEW_TAB_FOCUS_CLICKS for xy in clicks)
    assert OMNIBOX_CLICK in clicks
    assert typed, "must type THIS weather query after New Tab is focused"
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    assert all(_typed_is_user_query(t) for t in typed)
    assert SEARCH_BOX_CLICK not in clicks
    low = body["reply"].lower()
    assert "i typed the search" not in low
    assert "amsterdam" in low or "weather" in low or "degrees" in low
    assert "ublock" not in low
    assert "extensions" not in low
    assert "chrome://extensions" not in low
    assert "bol.com" not in low


GOOGLE_SORRY = {
    "ok": True,
    "title": (
        "https://www.google.com/search?q=Look+click+and+type+like+a+person+"
        "weather+Amsterdam"
    ),
    "url": (
        "https://www.google.com/sorry/index?continue="
        "https://www.google.com/search%3Fq%3DLook%2Bclick%2Btype%2Bweather"
    ),
    "vision_description": (
        "Google sorry page. I'm not a robot checkbox. Unusual traffic from "
        "your computer network. IP 146.148.38.150. No weather result."
    ),
}

GOOGLE_SORRY_HOTEL = {
    "ok": True,
    "title": "https://www.google.com/search?q=hotel+in+central+Rome",
    "url": (
        "https://www.google.com/sorry/index?continue="
        "https://www.google.com/search%3Fq%3Dhotel%2BRome"
    ),
    "vision_description": (
        "I'm not a robot. Unusual traffic from your computer network. "
        "No hotel results."
    ),
}

DDG_WEATHER = {
    "ok": True,
    "title": "today's weather in Amsterdam at DuckDuckGo",
    "url": "https://duckduckgo.com/?q=today%27s+weather+in+Amsterdam",
    "vision_description": (
        "DuckDuckGo results. Amsterdam weather. 12 degrees. Clear skies."
    ),
}

BING_HOTEL = {
    "ok": True,
    "title": "hotel in central Rome - Search",
    "url": "https://www.bing.com/search?q=hotel+in+central+Rome",
    "vision_description": (
        "Bing results. Hotels in central Rome. Eden. From 180 EUR."
    ),
}

LIVE_HOTEL = (
    "Open Chrome. Look, click and type like a person. "
    "find a hotel in central Rome."
)


def test_sorry_captcha_look_is_not_this_ask():
    """google.com/sorry / I'm not a robot is leftover, not a result page."""
    assert look_is_captcha(GOOGLE_SORRY) is True
    assert look_is_captcha(GOOGLE_SORRY_HOTEL) is True
    assert look_is_leftover_for_ask(GOOGLE_SORRY, LIVE_WEATHER) is True
    assert look_is_leftover_for_ask(GOOGLE_SORRY_HOTEL, LIVE_HOTEL) is True
    assert look_is_page_ready(GOOGLE_SORRY, LIVE_WEATHER) is False
    assert look_is_page_ready(GOOGLE_SORRY_HOTEL, ROME) is False
    assert needs_web_query(
        LIVE_WEATHER, GOOGLE_SORRY, web_search_query(LIVE_WEATHER)
    ) is True
    assert needs_web_query(ROME, GOOGLE_SORRY_HOTEL, web_search_query(ROME)) is True
    assert query_visible_on_look(GOOGLE_SORRY, web_search_query(LIVE_WEATHER)) is False
    assert search_box_point(GOOGLE_SORRY) is None
    assert overlay_dismiss_plan(GOOGLE_SORRY, goal=LIVE_WEATHER) is None
    assert overlay_kind(GOOGLE_SORRY, goal=LIVE_WEATHER) is None
    assert look_is_focused_new_tab(GOOGLE_SORRY) is False
    assert look_is_web_page(GOOGLE_SORRY) is False
    assert look_is_captcha(WEATHER_AFTER_TYPE) is False
    assert look_is_captcha(LEFTOVER_EXTENSIONS) is False
    alt = alt_web_search_typed(web_search_query(LIVE_WEATHER), LIVE_WEATHER)
    assert "weather" in alt.lower() or "amsterdam" in alt.lower()
    assert any(h in alt.lower() for h in ("duckduckgo.com", "bing.com", "weather."))
    assert "google.com/search" not in alt.lower()
    assert _typed_is_user_query(alt)


def test_continue_web_search_sorry_after_type_opens_alt_search():
    """Sorry look after type is not success — new tab + ddg/bing/weather query."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    start = dict(GOOGLE_SORRY)
    start["_typed_query"] = web_search_query(LIVE_WEATHER)
    out = _run_continue(
        [start, dict(GOOGLE_SORRY), dict(NEW_TAB_CHROME), dict(DDG_WEATHER)],
        LIVE_WEATHER,
        clicks,
        typed,
        keys,
    )
    assert typed, "captcha after type must type THIS ask on another search site"
    assert any(
        h in t.lower()
        for t in typed
        for h in ("duckduckgo.com", "bing.com", "weather.com", "accuweather")
    ), typed
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    assert all(_typed_is_user_query(t) for t in typed)
    assert keys.count("ctrl+t") == 1
    assert any(xy in NEW_TAB_FOCUS_CLICKS for xy in clicks)
    assert OMNIBOX_CLICK in clicks
    assert SEARCH_BOX_CLICK not in clicks
    assert "enter" in keys
    blob = str(out.get("vision_description") or "").lower()
    assert "amsterdam" in blob or "weather" in blob or "degrees" in blob
    assert "i'm not a robot" not in blob
    assert "unusual traffic" not in blob
    assert look_is_captcha(out) is False


def test_continue_web_search_sorry_hotel_uses_alt_search():
    """Captcha recovery is generic — hotel ask goes to ddg/bing, not Google."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    start = dict(GOOGLE_SORRY_HOTEL)
    start["_typed_query"] = web_search_query(LIVE_HOTEL)
    out = _run_continue(
        [start, dict(GOOGLE_SORRY_HOTEL), dict(NEW_TAB_CHROME), dict(BING_HOTEL)],
        LIVE_HOTEL,
        clicks,
        typed,
        keys,
    )
    assert typed
    assert any(
        h in t.lower()
        for t in typed
        for h in ("duckduckgo.com", "bing.com", "weather.com")
    ), typed
    assert any("rome" in t.lower() or "hotel" in t.lower() for t in typed)
    assert all(_typed_is_user_query(t) for t in typed)
    assert SEARCH_BOX_CLICK not in clicks
    blob = str(out.get("vision_description") or "").lower()
    assert "rome" in blob or "hotel" in blob or "eden" in blob
    assert "i'm not a robot" not in blob


def test_speak_web_job_never_speaks_captcha():
    """Do not speak I'm not a robot / unusual traffic / IP as the answer."""
    from app.jarvis.voice_ask import _speak_looked, _speak_web_job

    typed = dict(GOOGLE_SORRY)
    typed["_typed_query"] = web_search_query(LIVE_WEATHER)
    tools = ["see_screen", "click", "type", "keys"]
    body = _speak_web_job(LIVE_WEATHER, typed, tools, opened=False)
    low = body["reply"].lower()
    assert "i'm not a robot" not in low
    assert "not a robot" not in low
    assert "unusual traffic" not in low
    assert "146.148" not in low
    assert "captcha" not in low
    assert "i typed the search" not in low
    via = _speak_looked(typed, tools, opened=False, asked=LIVE_WEATHER)
    via_low = via["reply"].lower()
    assert "i'm not a robot" not in via_low
    assert "unusual traffic" not in via_low
    assert "146.148" not in via_low
    shown = dict(DDG_WEATHER)
    shown["_typed_query"] = web_search_query(LIVE_WEATHER)
    after = _speak_web_job(LIVE_WEATHER, shown, tools, opened=False)
    after_low = after["reply"].lower()
    assert "amsterdam" in after_low or "weather" in after_low or "degrees" in after_low
    assert "robot" not in after_low


def test_annotate_see_screen_captcha_does_not_speak():
    from app.jarvis.tools import annotate_see_screen

    looked = annotate_see_screen(dict(GOOGLE_SORRY), LIVE_WEATHER)
    assert looked.get("speak_now") is False
    assert looked.get("next_must") == ["click", "type", "keys"]
    hint = str(looked.get("hint") or "").lower()
    assert "captcha" in hint or "duckduckgo" in hint or "bing" in hint or "new tab" in hint
    assert "robot" in hint or "duckduckgo" in hint or "bing" in hint


@pytest.mark.asyncio
async def test_voice_ask_sorry_after_type_look_speed_off(monkeypatch, tmp_path):
    """look_speed=off still new-tabs to ddg/bing after a sorry look. Hello stays fast."""
    from app.jarvis import settings_store
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.voice_ask import ask_abort_ms, run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    assert settings_store.get_look_speed() == "off"
    assert ask_abort_ms("hello") == 12_000
    reset_last_look()
    remember_last_look(dict(GOOGLE_SORRY))

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(GOOGLE_SORRY),
        dict(GOOGLE_SORRY),
        dict(NEW_TAB_CHROME),
        dict(DDG_WEATHER),
    ]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(LIVE_WEATHER)
    assert "run_app" not in body["tools_used"]
    assert "click" in body["tools_used"]
    assert "type" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert typed
    assert any(
        h in t.lower()
        for t in typed
        for h in ("duckduckgo.com", "bing.com", "weather.com", "accuweather")
    ), typed
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    assert all(_typed_is_user_query(t) for t in typed)
    assert SEARCH_BOX_CLICK not in clicks
    low = body["reply"].lower()
    assert "i'm not a robot" not in low
    assert "unusual traffic" not in low
    assert "146.148" not in low
    assert "amsterdam" in low or "weather" in low or "degrees" in low
    reset_last_look()
