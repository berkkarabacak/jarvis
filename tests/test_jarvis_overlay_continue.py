"""Talk computer jobs dismiss overlays, then keep going. Never Sign in / Restore / Pay."""

from __future__ import annotations

import pytest

from app.jarvis.overlay import (
    RESTORE_DISMISS_CLICK,
    SANDBOX_DISMISS_CLICK,
    SIGNIN_DISMISS_CLICK,
    dismiss_blocking_overlays,
    look_has_blocking_overlay,
    look_is_empty_desktop,
    look_is_footer,
    overlay_dismiss_plan,
    overlay_kind,
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
)
from app.jarvis.virtual_pc import (
    after_see_must_act,
    goal_is_computer_job,
    goal_is_simple_talk,
    wants_web_job,
)

ROME = "find a hotel in central Rome"


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


def test_ask_abort_ms_web_job_is_minutes_hello_stays_short():
    assert ask_abort_ms("hello") == ASK_TALK_ABORT_MS
    assert ask_abort_ms("hello") == 12_000
    assert ask_abort_ms(ROME) == ASK_WEB_ABORT_MS
    assert ask_abort_ms(ROME) == 180_000
    assert ask_abort_ms("use Chrome to find a hotel") == ASK_WEB_ABORT_MS
    assert ask_abort_ms("search for a hotel in Rome") == ASK_WEB_ABORT_MS
    assert ask_abort_ms("book a hotel in central Rome") == ASK_WEB_ABORT_MS
    assert ask_abort_ms("open booking.com and look for a hotel") == ASK_WEB_ABORT_MS
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


def test_web_search_query_strips_url_and_find():
    assert "Rome" in web_search_query(ROME) or "rome" in web_search_query(ROME).lower()
    assert "booking" not in web_search_query(
        "find a hotel in central Rome on booking.com"
    ).lower()
    assert "grinder" in web_search_query("go to bol.com and find a coffee grinder")


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
    for looked in (desktop, footer, empty):
        body = _speak_web_job(ROME, looked, ["see_screen"], opened=True)
        low = body["reply"].lower()
        assert "look at the screen" not in low
        assert "turquoise" not in low
        assert "all rights reserved" not in low
        assert "destinations we love" not in low
        via = _speak_looked(looked, ["see_screen"], opened=True, asked=ROME)
        assert "look at the screen" not in via["reply"].lower()
        assert "turquoise" not in via["reply"].lower()
    picked = _speak_web_job(ROME, pick, ["see_screen"], opened=True)
    assert "eden" in picked["reply"].lower() or "hotel" in picked["reply"].lower()
    assert "look at the screen" not in picked["reply"].lower()


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
