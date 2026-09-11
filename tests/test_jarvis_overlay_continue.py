"""Talk computer jobs dismiss overlays, then keep going. Never Sign in / Restore / Pay."""

from __future__ import annotations

import re
import time

import pytest

from app.jarvis.overlay import (
    BLANK_LOOKS_BEFORE_OMNIBOX,
    BOOKING_DATES_CLICK,
    BOOKING_DEST_CLICK,
    BOOKING_SEARCH_CLICK,
    HOTEL_SEARCH_ALT_MAX,
    HOTEL_BOUNCE_BOOKING_BEFORE_ALT,
    HOTEL_SEARCH_REOPEN_MAX,
    HOTEL_ALT_BLANK_BEFORE_FALLBACK,
    MEMORY_SAVER_DISMISS_CLICK,
    NEW_TAB_CLICK,
    NEW_TAB_FOCUS_CLICKS,
    OMNIBOX_CLICK,
    OVERLAY_DISMISS_MAX,
    RESTORE_DISMISS_CLICK,
    SANDBOX_DISMISS_CLICK,
    SEARCH_BOX_CLICK,
    SIGNIN_DISMISS_CLICK,
    WEB_LOOK_PAUSE_S,
    CAPTCHA_FOCUS_MIN_S,
    alt_web_search_typed,
    ask_wants_hotel,
    continue_web_search,
    dismiss_blocking_overlays,
    hotel_alt_fallback_url,
    hotel_alt_travel_url,
    hotel_destination,
    hotel_option_lines,
    hotel_stay_dates,
    hotel_travel_url,
    hotel_typed_query,
    look_has_blocking_overlay,
    look_has_hotel_results,
    look_is_booking_bounce,
    look_is_booking_searchresults,
    look_is_hotel_search_pending,
    look_is_hotel_alt_host,
    look_lost_hotel_alt,
    look_is_travel_site,
    look_is_unfinished_hotel_search,
    needs_hotel_followthrough,
    look_is_captcha,
    look_is_empty_desktop,
    look_is_focused_new_tab,
    look_has_unfocused_new_tab,
    look_is_footer,
    look_is_abuse_block,
    look_is_http_error,
    look_is_leftover_for_ask,
    look_is_nl_retailer,
    look_is_retailer_block,
    ask_wants_shop,
    next_retailer_fallback_url,
    retailer_fallback_urls,
    look_is_leftover_surface,
    look_is_loading_or_blank,
    look_is_page_ready,
    look_is_travel_search_form,
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
    ASK_WEB_FIRST_ATTEMPT_S,
    ASK_WEB_REPLY_HEADROOM_S,
    _BOOKING_BOUNCED,
    _HOTEL_ALT_FAILED,
    _RETAILER_BLOCKED,
    _WEB_STUCK,
    ask_abort_ms,
    ask_deadline_s,
    remaining_ask_deadline_s,
    web_job_deadline,
    wants_control_screen,
)
from app.jarvis.virtual_pc import (
    after_see_must_act,
    goal_is_computer_job,
    goal_is_simple_talk,
    wants_web_job,
)

ROME = "find a hotel in central Rome"
GRINDER = "go to bol.com and find a coffee grinder"
LIVE_CART = (
    "go to bol.com, add two real in-stock products to cart, dismiss popups, "
    "no checkout, reply with names+euro prices."
)
WEATHER = "use Chrome to look up the weather in Amsterdam"
LIVE_WEATHER = (
    "Open Chrome. Look, click and type like a person. "
    "Look up today's weather in Amsterdam."
)
LIVE_ITALY_HOTEL = (
    "Use the computer. Find available hotels under 2000 Euro total in central Italy "
    "(Rome, Florence, or Tuscany) for a stay sometime in the next 3 months. "
    "Open a real travel site, search real dates and prices, dismiss popups, and reply "
    "with 3 concrete options: hotel name, city, check-in/out dates, nights, and total "
    "price in euros. Do not invent. Do not book or pay."
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
    assert wants_web_job(LIVE_CART) is True
    assert wants_web_job(LIVE_ITALY_HOTEL) is True
    assert goal_is_computer_job(LIVE_ITALY_HOTEL) is True
    assert goal_is_simple_talk(LIVE_ITALY_HOTEL) is False
    assert after_see_must_act(LIVE_ITALY_HOTEL) is True
    assert wants_control_screen(LIVE_ITALY_HOTEL) is True
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
    assert ask_abort_ms(LIVE_ITALY_HOTEL) == ASK_WEB_ABORT_MS
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
    assert ASK_WEB_REPLY_HEADROOM_S >= 20.0
    assert ASK_WEB_FIRST_ATTEMPT_S <= 120.0
    hotel_left = web_job_deadline(LIVE_ITALY_HOTEL) - time.monotonic()
    assert hotel_left <= ASK_WEB_FIRST_ATTEMPT_S + 0.5
    assert hotel_left < 180.0 - ASK_WEB_REPLY_HEADROOM_S + 0.5


def _iso_date_in(text: str) -> bool:
    return bool(re.search(r"20\d{2}-\d{2}-\d{2}", text or ""))


def _typed_is_user_query(text: str) -> bool:
    low = (text or "").lower()
    banned = (
        "like a person",
        "open chrome",
        "look, click",
        "see_screen",
        "use the computer",
        "dismiss popups",
        "do not invent",
        "do not book",
        "concrete options",
        "reply with",
    )
    return not any(token in low for token in banned)


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


def test_web_search_query_strips_use_the_computer_and_option_list():
    """Live Italy hotel ask must type destination + budget, never coaching."""
    q = web_search_query(LIVE_ITALY_HOTEL)
    low = q.lower()
    assert "hotel" in low
    assert any(token in low for token in ("italy", "rome", "florence", "tuscany"))
    assert "2000" in low or "euro" in low
    assert _typed_is_user_query(q)
    assert "use the computer" not in low
    assert "dismiss popups" not in low
    assert "do not invent" not in low
    assert "do not book" not in low
    assert "concrete options" not in low
    assert "reply with" not in low
    url = hotel_travel_url(LIVE_ITALY_HOTEL)
    assert "booking.com" in url
    assert "checkin=" in url and "checkout=" in url
    checkin, checkout = hotel_stay_dates()
    assert checkin.isoformat() in url
    assert checkout.isoformat() in url
    assert ask_wants_hotel(LIVE_ITALY_HOTEL) is True


# Live 2026-09-11 SHA 8de1618: Booking searchresults URL + Genius modal.
# Vision named the address bar / "hotels in" but no readable prices.
# OCR mashed the heading to "Signin, savemoney". Ask returned _WEB_STUCK
# with only run_app + see_screen — no click/keys.
LIVE_BOOKING_GENIUS = {
    "ok": True,
    "title": "Booking.com | Official site",
    "url": (
        "https://www.booking.com/searchresults.html?"
        "ss=available+hotels+under+2000+Euro+total+in+central+Italy+"
        "Rome+Florence+or+Tuscany&checkin=2026-10-02&checkout=2026-10-05"
    ),
    "vision_description": (
        "Booking.com official site. The address bar shows a search-results URL "
        "for hotels in central Italy, Rome, Florence, or Tuscany under 2000 Euro. "
        "A white Genius popup: Signin, savemoney. Signin to save10% or more with "
        "a free Booking.com membership. Signin or register. Close X at (920, 170). "
        "No readable hotel names or prices."
    ),
}

# Same stuck frame when vision names the URL and a covering modal, not Genius.
LIVE_BOOKING_GENIUS_URL_ONLY = {
    "ok": True,
    "title": "Booking.com | Official site",
    "url": (
        "https://www.booking.com/searchresults.html?"
        "ss=hotels+in+central+Italy+Rome+Florence+Tuscany"
    ),
    "vision_description": (
        "Booking.com official site. Search-results URL for hotels in Rome, "
        "Florence, or Tuscany. A sign-in modal covers the list. "
        "No readable hotel names or prices."
    ),
}


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


def test_live_genius_mashed_ocr_is_signin_not_hotel_results():
    """Live Booking Genius: mashed 'Signin, savemoney' must dismiss, not finish."""
    q = web_search_query(LIVE_ITALY_HOTEL)
    for looked in (LIVE_BOOKING_GENIUS, LIVE_BOOKING_GENIUS_URL_ONLY):
        assert overlay_kind(looked, goal=LIVE_ITALY_HOTEL) == "signin"
        assert look_has_blocking_overlay(looked, goal=LIVE_ITALY_HOTEL) is True
        assert look_has_hotel_results(looked) is False
        assert look_is_travel_site(looked) is True
        assert needs_web_query(LIVE_ITALY_HOTEL, looked, q) is True
        plan = overlay_dismiss_plan(looked, goal=LIVE_ITALY_HOTEL)
        assert plan is not None
        assert plan.kind == "signin"
        assert plan.click is not None
        assert plan.keys == "escape"
        assert plan.click != (0, 0)
    assert overlay_dismiss_plan(LIVE_BOOKING_GENIUS).click == (920, 170)
    # Priced Genius badges on a result list are not the sign-in modal.
    priced = {
        "ok": True,
        "title": "Hotels in Rome — Booking.com",
        "url": "https://www.booking.com/searchresults.html",
        "vision_description": (
            "Hotels in central Rome. Hotel Eden. Genius 10% off. "
            "Prices from 180 EUR."
        ),
    }
    assert overlay_kind(priced, goal=LIVE_ITALY_HOTEL) is None
    assert look_has_hotel_results(priced) is True
    assert needs_web_query(LIVE_ITALY_HOTEL, priced, q) is False


def test_speak_web_job_genius_is_not_web_stuck():
    """A Genius-blocked first look must not finalize as _WEB_STUCK."""
    from app.jarvis.voice_ask import _speak_web_job

    body = _speak_web_job(
        LIVE_ITALY_HOTEL,
        dict(LIVE_BOOKING_GENIUS),
        ["run_app", "see_screen"],
        opened=True,
    )
    assert body["reply"] != _WEB_STUCK
    assert "i could not finish the search" not in body["reply"].lower()


# Live 2026-09-11 SHA 8571716 / PR #35: Booking landing + Genius *banner*
# (not the mashed Signin modal). URL leaked the ask. Vision coached
# "enter search criteria" / "no priced hotel names". tools_used was only
# run_app + see_screen; reply was _WEB_STUCK. "hotel names" must not
# count as a listed property.
LIVE_BOOKING_HOMEPAGE_BANNER = {
    "ok": True,
    "title": "Booking.com | Official site",
    "url": (
        "https://www.booking.com/index.html?"
        "ss=available+hotels+under+2000+Euro+total+in+central+Italy"
    ),
    "vision_description": (
        "Booking.com official site. landing/index.html loading. "
        "Unlock flight savings with members-only deals. "
        "Genius promotional banner. Search in your own words. "
        "Family-friendly apartments in Paris. Select dates. "
        "Check-in date. Check-out date. Enter search criteria. "
        "No priced hotel names."
    ),
}

LIVE_BOOKING_HOMEPAGE_NO_OVERLAY = {
    "ok": True,
    "title": "Booking.com | Official site",
    "url": (
        "https://www.booking.com/index.html?"
        "ss=available hotels under 2000 Euro total in central Italy"
    ),
    "vision_description": (
        "Booking.com official site. landing/index.html loading. "
        "Search in your own words. Select dates. Check-in date. "
        "Enter search criteria. No priced hotel names. "
        "hotel name, city, check-in/out dates, total price in euros."
    ),
}


def test_live_booking_homepage_is_form_not_hotel_results():
    """Homepage / Genius banner / 'hotel names' coaching is not priced options."""
    from app.jarvis.voice_ask import _speak_web_job

    q = web_search_query(LIVE_ITALY_HOTEL)
    dest = hotel_destination(LIVE_ITALY_HOTEL)
    typed_q = hotel_typed_query(LIVE_ITALY_HOTEL)
    assert dest.lower() == "rome"
    assert "rome" in typed_q.lower()
    assert "check-in" in typed_q.lower() and "check-out" in typed_q.lower()
    assert "use the computer" not in typed_q.lower()
    assert "2000" not in hotel_travel_url(LIVE_ITALY_HOTEL)
    for looked in (LIVE_BOOKING_HOMEPAGE_BANNER, LIVE_BOOKING_HOMEPAGE_NO_OVERLAY):
        assert look_is_travel_site(looked) is True
        assert look_is_travel_search_form(looked) is True
        assert look_has_hotel_results(looked) is False
        assert needs_web_query(LIVE_ITALY_HOTEL, looked, q) is True
        assert search_box_point(looked) is not None
        body = _speak_web_job(
            LIVE_ITALY_HOTEL,
            dict(looked),
            ["run_app", "see_screen"],
            opened=True,
        )
        assert body["reply"] != _WEB_STUCK
        assert body["reply"].lower() != "i could not finish the search"
    # Homepage Genius promo is marketing next to the form — not a modal.
    # Treating it as signin loops dismiss and never types (live SHA bf81e28).
    assert overlay_kind(LIVE_BOOKING_HOMEPAGE_BANNER, goal=LIVE_ITALY_HOTEL) is None
    assert overlay_dismiss_plan(LIVE_BOOKING_HOMEPAGE_BANNER, goal=LIVE_ITALY_HOTEL) is None
    # Coaching-only look has no overlay — still must type, not finish.
    assert overlay_kind(LIVE_BOOKING_HOMEPAGE_NO_OVERLAY, goal=LIVE_ITALY_HOTEL) is None
    assert overlay_dismiss_plan(LIVE_BOOKING_HOMEPAGE_NO_OVERLAY, goal=LIVE_ITALY_HOTEL) is None


def test_continue_web_search_booking_homepage_types_dates_not_stuck():
    """First Booking landing look must click and/or type — never stop."""
    from app.jarvis.voice_ask import _speak_web_job

    form = {
        "ok": True,
        "title": "Booking.com | Official site",
        "url": "https://www.booking.com/",
        "vision_description": (
            "Booking.com. Where are you going? Search box is empty at (640, 320)."
        ),
    }
    for start in (LIVE_BOOKING_HOMEPAGE_BANNER, LIVE_BOOKING_HOMEPAGE_NO_OVERLAY):
        clicks: list[tuple[int, int]] = []
        typed: list[str] = []
        keys: list[str] = []

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
            if typed:
                return dict(ITALY_HOTEL_RESULTS)
            return dict(form)

        out = continue_web_search(
            dict(start),
            goal=LIVE_ITALY_HOTEL,
            click=click,
            type_text=type_text,
            keys=press,
            look_again=look_again,
        )
        assert clicks or typed, "Booking homepage must click or type before return"
        assert typed, "must type destination / dates on the Booking form"
        assert BOOKING_DEST_CLICK in clicks or BOOKING_DATES_CLICK in clicks
        assert SEARCH_BOX_CLICK not in clicks or BOOKING_DEST_CLICK in clicks
        assert all(_typed_is_user_query(t) for t in typed), typed
        blob = " ".join(typed).lower()
        assert "google.com" not in blob
        assert "use the computer" not in blob
        assert "available hotels under 2000" not in blob
        assert any(
            token in blob for token in ("rome", "italy", "hotel", "check-in", "checkin")
        ), typed
        assert (
            "check-in" in blob
            or "checkin=" in blob
            or any(_iso_date_in(t) for t in typed)
        )
        spoken = _speak_web_job(
            LIVE_ITALY_HOTEL,
            out,
            ["run_app", "see_screen", "click", "type", "keys"],
            opened=True,
        )
        assert spoken["reply"] != _WEB_STUCK
        assert look_has_hotel_results(out) or out.get("_typed_query")


@pytest.mark.asyncio
async def test_voice_ask_booking_homepage_not_web_stuck_from_see_only(
    monkeypatch, tmp_path
):
    """Hotel ask that opens Booking must click/type before any _WEB_STUCK."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    for start in (LIVE_BOOKING_HOMEPAGE_BANNER, LIVE_BOOKING_HOMEPAGE_NO_OVERLAY):
        clicks: list[tuple[int, int]] = []
        typed: list[str] = []
        keys: list[str] = []
        launched: list[dict] = []
        looks = [
            dict(start),
            {
                "ok": True,
                "title": "Booking.com | Official site",
                "url": "https://www.booking.com/",
                "vision_description": (
                    "Booking.com. Where are you going? "
                    "Search box is empty at (640, 320)."
                ),
            },
            dict(ITALY_HOTEL_RESULTS),
        ]
        _patch_voice_ask_web(
            monkeypatch,
            looks,
            clicks=clicks,
            typed=typed,
            keys=keys,
            launched=launched,
        )
        body = await run_voice_ask(LIVE_ITALY_HOTEL)
        tools = list(body.get("tools_used") or [])
        assert tools != ["run_app", "see_screen"]
        assert "click" in tools or "type" in tools or "keys" in tools
        assert clicks or typed
        assert typed, "must type a clean destination + dates"
        typed_blob = " ".join(typed).lower()
        assert "available hotels under 2000" not in typed_blob
        assert _typed_is_user_query(typed_blob)
        assert body["reply"] != _WEB_STUCK
        assert "i could not finish the search" not in body["reply"].lower()
        low = body["reply"].lower()
        assert "eden" in low or "hotel" in low or "typed the search" in low
        assert "click" in tools
        assert "type" in tools


# Live 2026-09-11 SHA bf81e28 / PR #36: Genius *homepage* banner (not the
# mashed Sign-in modal). Destination and dates stayed blank. continue loop
# classified the banner as signin and dismissed until nginx 504.
LIVE_BOOKING_HOMEPAGE_PAINTED = {
    "ok": True,
    "title": "Booking.com | Official site",
    "url": (
        "https://www.booking.com/index.html?"
        "label=gen173nr-1FCAEoggI46AdIM1gEaDKIAQGYATG4ARfIAQzYAQHoAQGIAgGoAgG4Ag"
    ),
    "vision_description": (
        "Booking.com homepage. Unlock Flight savings with members-only deals. "
        "Genius promotional banner. Yellow airplane. Search in your own words. "
        "Where are you going? Destination is empty. Select dates. "
        "Check-in date. Check-out date. Search form is empty. "
        "No priced hotel names."
    ),
}


def test_live_painted_booking_homepage_is_form_not_overlay():
    """Painted Genius hero + empty form is not a modal and not hotel results."""
    q = web_search_query(LIVE_ITALY_HOTEL)
    looked = LIVE_BOOKING_HOMEPAGE_PAINTED
    assert look_is_travel_search_form(looked) is True
    assert look_has_hotel_results(looked) is False
    assert overlay_kind(looked, goal=LIVE_ITALY_HOTEL) is None
    assert needs_web_query(LIVE_ITALY_HOTEL, looked, q) is True
    assert search_box_point(looked) == BOOKING_DEST_CLICK
    assert search_box_point(looked) != SEARCH_BOX_CLICK
    # Coaching / budget leak still must not count as a priced list.
    leak = {
        "ok": True,
        "title": "Booking.com | Official site",
        "url": "https://www.booking.com/index.html?ss=hotels+under+2000+Euro",
        "vision_description": (
            "hotel names. hotel name, city. 2000 Euro. No priced hotel names."
        ),
    }
    assert look_has_hotel_results(leak) is False


def test_continue_web_search_persistent_genius_banner_types_form():
    """Same Genius homepage every look must click+type — not dismiss-loop."""
    from app.jarvis.voice_ask import _speak_web_job

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = {"n": 0}

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
        looks["n"] += 1
        return dict(LIVE_BOOKING_HOMEPAGE_PAINTED)

    out = continue_web_search(
        dict(LIVE_BOOKING_HOMEPAGE_PAINTED),
        goal=LIVE_ITALY_HOTEL,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        deadline=time.monotonic() + 30,
    )
    assert OVERLAY_DISMISS_MAX <= 2
    assert HOTEL_SEARCH_REOPEN_MAX >= 4
    assert HOTEL_SEARCH_ALT_MAX >= 1
    assert typed, "Genius homepage must type destination / dates"
    assert BOOKING_DEST_CLICK in clicks
    assert BOOKING_DATES_CLICK in clicks
    assert BOOKING_SEARCH_CLICK in clicks or "enter" in keys
    assert SIGNIN_DISMISS_CLICK not in clicks
    blob = " ".join(typed).lower()
    assert "rome" in blob
    assert any(_iso_date_in(t) for t in typed) or "checkin=" in blob
    assert "use the computer" not in blob
    assert "available hotels under 2000" not in blob
    spoken = _speak_web_job(
        LIVE_ITALY_HOTEL,
        out,
        ["run_app", "see_screen", "click", "type", "keys"],
        opened=True,
    )
    assert spoken["reply"] != _WEB_STUCK
    assert "i opened the page" not in spoken["reply"].lower()
    assert "i typed the search" not in spoken["reply"].lower()
    assert "bounced" in spoken["reply"].lower()
    assert look_has_hotel_results(out) is False
    assert look_is_travel_search_form(out) is True
    assert out.get("_typed_query")
    assert out.get("_hotel_reopened") or any("searchresults.html" in t for t in typed)


@pytest.mark.asyncio
async def test_voice_ask_painted_booking_homepage_uses_click_and_type(
    monkeypatch, tmp_path
):
    """Live ask path must record click+type on the empty Booking form."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(LIVE_BOOKING_HOMEPAGE_PAINTED),
        dict(LIVE_BOOKING_HOMEPAGE_PAINTED),
        dict(LIVE_BOOKING_HOMEPAGE_PAINTED),
    ]
    _patch_voice_ask_web(
        monkeypatch, looks, clicks=clicks, typed=typed, keys=keys
    )
    body = await run_voice_ask(LIVE_ITALY_HOTEL)
    tools = list(body.get("tools_used") or [])
    assert tools != ["run_app", "see_screen"]
    assert "click" in tools
    assert "type" in tools
    assert typed
    assert BOOKING_DEST_CLICK in clicks
    blob = " ".join(typed).lower()
    assert "rome" in blob
    assert "use the computer" not in blob
    assert body["reply"] != _WEB_STUCK
    assert "i typed the search" not in body["reply"].lower()
    assert "i opened the page" not in body["reply"].lower()
    assert "180" not in body["reply"]
    assert "bounced" in body["reply"].lower()
    assert any("searchresults.html" in t for t in typed)


# Live 2026-09-11 SHA 9a483b4 / PR #37: typed dest/dates (and a dated
# searchresults URL) then finalized "I typed the search." noVNC briefly
# showed searchresults.html?ss=Rome&checkin=… then bounced to index
# with blank dest/dates. Vision on the ask reply was the homepage.
LIVE_BOOKING_SEARCHRESULTS_LOADING = {
    "ok": True,
    "title": "Booking.com",
    "url": (
        "https://www.booking.com/searchresults.html?"
        "ss=Rome&checkin=2026-10-02&checkout=2026-10-05"
    ),
    "vision_description": (
        "Booking.com search results. The page is still loading. "
        "A white loading screen. No priced hotel names."
    ),
}

PRICED_ROME_HOTELS = {
    "ok": True,
    "title": "Hotels in Rome — Booking.com",
    "url": (
        "https://www.booking.com/searchresults.html?"
        "ss=Rome&checkin=2026-10-02&checkout=2026-10-05"
    ),
    "vision_description": (
        "Hotels in Rome. Hotel Eden. From 180 EUR. "
        "Hotel Artemide. From 210 EUR. "
        "Hotel Forum. From 165 EUR."
    ),
}


def test_live_searchresults_loading_is_pending_not_homepage():
    """Dated searchresults URL that is still loading is in-progress."""
    loading = LIVE_BOOKING_SEARCHRESULTS_LOADING
    home = LIVE_BOOKING_HOMEPAGE_PAINTED
    assert look_is_booking_searchresults(loading) is True
    assert look_is_hotel_search_pending(loading) is True
    assert look_is_travel_search_form(loading) is False
    assert look_has_hotel_results(loading) is False
    assert look_is_booking_searchresults(home) is False
    assert look_is_hotel_search_pending(home) is False
    assert look_is_travel_search_form(home) is True
    assert look_has_hotel_results(PRICED_ROME_HOTELS) is True
    assert look_is_hotel_search_pending(PRICED_ROME_HOTELS) is False
    lines = hotel_option_lines(PRICED_ROME_HOTELS)
    blob = " ".join(lines).lower()
    assert "eden" in blob
    assert "180" in blob
    assert hotel_option_lines(home) == []


def test_speak_web_job_homepage_after_type_is_not_typed_success():
    """Homepage + empty dest/dates after type is not 'I typed the search.'"""
    from app.jarvis.voice_ask import _speak_web_job

    tools = ["run_app", "see_screen", "click", "type", "keys"]
    home = dict(LIVE_BOOKING_HOMEPAGE_PAINTED)
    home["_typed_query"] = hotel_typed_query(LIVE_ITALY_HOTEL)
    bounced = _speak_web_job(LIVE_ITALY_HOTEL, home, tools, opened=True)
    assert bounced["reply"] != _WEB_STUCK
    assert bounced["reply"] == _BOOKING_BOUNCED
    assert "i typed the search" not in bounced["reply"].lower()
    assert "i opened the page" not in bounced["reply"].lower()
    assert "bounced" in bounced["reply"].lower()
    loading = dict(LIVE_BOOKING_SEARCHRESULTS_LOADING)
    loading["_typed_query"] = hotel_typed_query(LIVE_ITALY_HOTEL)
    pending = _speak_web_job(LIVE_ITALY_HOTEL, loading, tools, opened=True)
    assert pending["reply"].lower() == "i typed the search."
    priced = _speak_web_job(
        LIVE_ITALY_HOTEL, dict(PRICED_ROME_HOTELS), tools, opened=True
    )
    low = priced["reply"].lower()
    assert "eden" in low
    assert "180" in low
    assert "i typed the search" not in low
    assert "2000" not in low


def test_continue_web_search_homepage_bounce_reopens_searchresults():
    """After type, empty homepage must re-run the dated URL and wait."""
    from app.jarvis.voice_ask import _speak_web_job

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    urls_typed = {"n": 0}

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def type_text(*, text="", **_k):
        typed.append(str(text))
        if "searchresults.html" in str(text):
            urls_typed["n"] += 1
        return {"ok": True}

    def press(*, combo="", **_k):
        keys.append(str(combo))
        return {"ok": True}

    def look_again():
        if urls_typed["n"] >= 2:
            return dict(PRICED_ROME_HOTELS)
        return dict(LIVE_BOOKING_HOMEPAGE_PAINTED)

    out = continue_web_search(
        dict(LIVE_BOOKING_HOMEPAGE_PAINTED),
        goal=LIVE_ITALY_HOTEL,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        deadline=time.monotonic() + 30,
    )
    assert urls_typed["n"] >= 2, typed
    assert any("searchresults.html" in t for t in typed)
    assert any("checkin=" in t for t in typed)
    assert BOOKING_SEARCH_CLICK in clicks or OMNIBOX_CLICK in clicks
    assert look_has_hotel_results(out) is True
    spoken = _speak_web_job(
        LIVE_ITALY_HOTEL,
        out,
        ["run_app", "see_screen", "click", "type", "keys"],
        opened=True,
    )
    low = spoken["reply"].lower()
    assert "i typed the search" not in low
    assert "eden" in low
    assert "180" in low
    assert spoken["reply"] != _WEB_STUCK


@pytest.mark.asyncio
async def test_voice_ask_homepage_bounce_finishes_with_priced_hotels(
    monkeypatch, tmp_path
):
    """Ask path: type, bounce to empty homepage, re-run URL, then options."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(LIVE_BOOKING_HOMEPAGE_PAINTED),
        dict(LIVE_BOOKING_HOMEPAGE_PAINTED),
        dict(LIVE_BOOKING_SEARCHRESULTS_LOADING),
        dict(LIVE_BOOKING_HOMEPAGE_PAINTED),
        dict(PRICED_ROME_HOTELS),
    ]
    _patch_voice_ask_web(
        monkeypatch, looks, clicks=clicks, typed=typed, keys=keys
    )
    body = await run_voice_ask(LIVE_ITALY_HOTEL)
    tools = list(body.get("tools_used") or [])
    assert "click" in tools
    assert "type" in tools
    assert any("searchresults.html" in t for t in typed)
    low = body["reply"].lower()
    assert "i typed the search" not in low
    assert "eden" in low
    assert "180" in low
    assert body["reply"] != _WEB_STUCK


# Live 2026-09-11 SHA 64e891d / PR #38: run_app opened dated
# searchresults.html (white results pane), then Booking bounced to
# index.html?label=… Genius homepage. Reopen never ran — reply was
# "I opened the page." and noVNC never left the homepage.
LIVE_BOOKING_SEARCHRESULTS_WHITE_PANE = {
    "ok": True,
    "title": "Booking.com",
    "url": (
        "https://www.booking.com/searchresults.html?"
        "ss=Rome&checkin=2026-10-02&checkout=2026-10-05"
    ),
    "vision_description": (
        "Booking.com. A blank white results area. Select dates. "
        "Genius. No priced hotel names."
    ),
}

LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE = {
    "ok": True,
    "title": "Booking.com | Official site",
    "url": (
        "https://www.booking.com/index.html?"
        "label=gen173nr-10FCAEoggI46AdIM1gEaDKIAQGYATG4ARfIAQzYAQHoAQGIAgGoAg"
    ),
    "vision_description": (
        "Unlock Flight savings with members-only deals. "
        "Genius flight savings. Empty Check-in and Check-out. "
        "Search button. Coaching to enter a destination."
    ),
}

GOOGLE_HOTELS_ROME = {
    "ok": True,
    "title": "Hotels in Rome - Google Travel",
    "url": (
        "https://www.google.com/travel/hotels/Rome?q=Rome+hotels"
        "&checkin=2026-10-02&checkout=2026-10-05"
    ),
    "vision_description": (
        "Google Hotels. Hotels in Rome. Hotel Eden. From 180 EUR. "
        "Hotel Artemide. From 210 EUR."
    ),
}

# Live 2026-09-11 SHA 35d5797 / PR #40: run_app opened
# google.com/travel/search?q=Rome+hotels&dates=… but the tab stayed
# blank (302 /travel/unsupported). Ask finalized "I typed the search."
# and see_screen flipped back to Booking. /travel/hotels does the same
# from this IP. html.duckduckgo.com hotels queries paint names+prices.
LIVE_GOOGLE_TRAVEL_BLANK = {
    "ok": True,
    "title": "Google Travel",
    "url": (
        "https://www.google.com/travel/search?q=Rome+hotels"
        "&dates=2026-10-02,2026-10-05"
    ),
    "vision_description": (
        "Chromium. A blank white page. Still loading. "
        "No hotel names. No prices."
    ),
}

LIVE_GOOGLE_TRAVEL_UNSUPPORTED = {
    "ok": True,
    "title": "Google Travel",
    "url": "https://www.google.com/travel/unsupported?q=Rome+hotels",
    "vision_description": "A blank white page. Nothing has loaded.",
}

DDG_HOTELS_ROME = {
    "ok": True,
    "title": "Rome hotels at DuckDuckGo",
    "url": (
        "https://html.duckduckgo.com/html/?q=Rome+hotels"
        "+check-in+2026-10-02+check-out+2026-10-05"
    ),
    "vision_description": (
        "DuckDuckGo. 10 Best Rome Hotels. Hotel Eden. From 180 EUR. "
        "Hotel Artemide. From 210 EUR."
    ),
}

# Live 2026-09-11 SHA fd4bcaf / PR #39: bounce message fired, but Google
# Hotels never opened. End state was join.booking.com list-your-property
# with Chromium Memory Saver toast. tools_used had one run_app host.
LIVE_BOOKING_LIST_YOUR_PROPERTY = {
    "ok": True,
    "title": "List Your Apartment, Hotel, Vacation Home, or B&B on Booking.com",
    "url": (
        "https://join.booking.com/index.html?"
        "label=gen173nr-10CAQoggJCC3NYXjaF9yb21B-gBMYgBAZgBMsIBCtgBA"
    ),
    "vision_description": (
        "List anything on Booking.com. Register for free. "
        "Genius flights homepage. Empty Check-in and Check-out. "
        "Make Chromium faster. Memory Saver frees up memory from "
        "inactive tabs so it can be used by active tabs. "
        "No thanks. Turn on."
    ),
}


def test_blank_white_searchresults_is_pending_not_homepage():
    """White results pane on searchresults.html is pending, not a form."""
    white = LIVE_BOOKING_SEARCHRESULTS_WHITE_PANE
    home = LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE
    assert look_is_booking_searchresults(white) is True
    assert look_is_hotel_search_pending(white) is True
    assert look_is_travel_search_form(white) is False
    assert look_has_hotel_results(white) is False
    assert look_is_travel_search_form(home) is True
    assert look_is_hotel_search_pending(home) is False
    assert look_is_booking_bounce(home, saw_searchresults=True) is True
    assert look_is_booking_bounce(home, saw_searchresults=False) is False
    assert look_is_booking_bounce(white, saw_searchresults=True) is False


def test_continue_web_search_searchresults_then_homepage_reopens_run_app():
    """Homepage after a prior searchresults look must run_app the dated URL."""
    from app.jarvis.voice_ask import _speak_web_job

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    opened: list[str] = []

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def type_text(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def press(*, combo="", **_k):
        keys.append(str(combo))
        return {"ok": True}

    def open_url(url: str = "", **_k):
        opened.append(str(url))
        return {"ok": True, "url": url}

    def look_again():
        if opened:
            return dict(PRICED_ROME_HOTELS)
        return dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE)

    out = continue_web_search(
        dict(LIVE_BOOKING_SEARCHRESULTS_WHITE_PANE),
        goal=LIVE_ITALY_HOTEL,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        open_url=open_url,
        deadline=time.monotonic() + 30,
    )
    assert opened, "bounce must run_app searchresults, not idle on homepage"
    assert any("searchresults.html" in u for u in opened), opened
    assert any("checkin=" in u for u in opened)
    assert look_has_hotel_results(out) is True
    spoken = _speak_web_job(
        LIVE_ITALY_HOTEL,
        out,
        ["run_app", "see_screen", "click", "type", "keys"],
        opened=True,
    )
    low = spoken["reply"].lower()
    assert "i opened the page" not in low
    assert "i typed the search" not in low
    assert "eden" in low
    assert "180" in low


def test_continue_web_search_booking_bounce_uses_google_hotels_alt():
    """Persistent Booking homepage bounce must try Google Hotels."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    opened: list[str] = []

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def type_text(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def press(*, combo="", **_k):
        return {"ok": True}

    def open_url(url: str = "", **_k):
        opened.append(str(url))
        return {"ok": True, "url": url}

    def look_again():
        if any("google.com/travel" in u for u in opened):
            return dict(GOOGLE_HOTELS_ROME)
        return dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE)

    out = continue_web_search(
        dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE)
        | {"_saw_searchresults": True, "_typed_query": hotel_typed_query(LIVE_ITALY_HOTEL)},
        goal=LIVE_ITALY_HOTEL,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        open_url=open_url,
        deadline=time.monotonic() + 30,
    )
    alt = hotel_alt_travel_url(LIVE_ITALY_HOTEL)
    assert any("google.com/travel" in u for u in opened), opened
    assert any("searchresults.html" in u for u in opened), opened
    assert "travel/hotels" in alt
    assert "checkin=" in alt and "checkout=" in alt
    assert look_has_hotel_results(out) is True
    from app.jarvis.voice_ask import _speak_web_job

    spoken = _speak_web_job(
        LIVE_ITALY_HOTEL,
        out,
        ["run_app", "see_screen", "click", "type", "keys"],
        opened=True,
    )
    low = spoken["reply"].lower()
    assert "eden" in low
    assert "180" in low
    assert "i opened the page" not in low


def test_list_your_property_after_searchresults_is_bounce_not_results():
    """join.booking.com / List your apartment is a bounce homepage."""
    listed = LIVE_BOOKING_LIST_YOUR_PROPERTY
    assert look_is_travel_site(listed) is True
    assert look_is_travel_search_form(listed) is True
    assert look_has_hotel_results(listed) is False
    assert look_is_booking_searchresults(listed) is False
    assert look_is_hotel_search_pending(listed) is False
    assert look_is_booking_bounce(listed, saw_searchresults=True) is True
    assert look_is_booking_bounce(listed, saw_searchresults=False) is False
    assert overlay_kind(listed, goal=LIVE_ITALY_HOTEL) == "memory_saver"
    plan = overlay_dismiss_plan(listed, goal=LIVE_ITALY_HOTEL)
    assert plan is not None
    assert plan.kind == "memory_saver"
    assert plan.click == MEMORY_SAVER_DISMISS_CLICK
    assert plan.click != (0, 0)


def test_memory_saver_toast_dismisses_no_thanks_not_turn_on():
    """Chromium Memory Saver must not steal focus from the search."""
    toast = {
        "ok": True,
        "title": "Booking.com",
        "url": "https://www.booking.com/index.html?label=gen",
        "vision_description": (
            "Make Chromium faster. Memory Saver frees up memory from "
            "inactive tabs. No thanks at (1000, 208). Turn on at (1140, 208)."
        ),
    }
    assert overlay_kind(toast) == "memory_saver"
    plan = overlay_dismiss_plan(toast)
    assert plan is not None
    assert plan.kind == "memory_saver"
    assert plan.click == (1000, 208)
    assert plan.click != (1140, 208)
    named = {
        "vision_description": (
            "Memory-saving notification. No thanks at (968, 190)."
        )
    }
    named_plan = overlay_dismiss_plan(named)
    assert named_plan is not None
    assert named_plan.click == (968, 190)


def test_continue_web_search_bounce_opens_google_hotels_before_stuck():
    """After searchresults → homepage, run_app Google Hotels before bounce reply."""
    from app.jarvis.voice_ask import _BOOKING_BOUNCED, _HOTEL_ALT_FAILED, _speak_web_job

    opened: list[str] = []
    clicks: list[tuple[int, int]] = []

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def type_text(*, text="", **_k):
        return {"ok": True}

    def press(*, combo="", **_k):
        return {"ok": True}

    def open_url(url: str = "", **_k):
        opened.append(str(url))
        return {"ok": True, "url": url}

    def look_again():
        if any("google.com/travel" in u for u in opened):
            return dict(GOOGLE_HOTELS_ROME)
        return dict(LIVE_BOOKING_LIST_YOUR_PROPERTY)

    out = continue_web_search(
        dict(LIVE_BOOKING_SEARCHRESULTS_WHITE_PANE),
        goal=LIVE_ITALY_HOTEL,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        open_url=open_url,
        deadline=time.monotonic() - 1,
    )
    assert any("google.com/travel" in u for u in opened), opened
    assert HOTEL_BOUNCE_BOOKING_BEFORE_ALT == 1
    assert look_has_hotel_results(out) is True
    spoken = _speak_web_job(
        LIVE_ITALY_HOTEL,
        out,
        ["run_app", "see_screen", "click", "type", "keys"],
        opened=True,
    )
    low = spoken["reply"].lower()
    assert "eden" in low
    assert "180" in low
    assert spoken["reply"] not in {_BOOKING_BOUNCED, _HOTEL_ALT_FAILED, _WEB_STUCK}
    assert MEMORY_SAVER_DISMISS_CLICK in clicks or overlay_kind(
        LIVE_BOOKING_LIST_YOUR_PROPERTY
    ) == "memory_saver"


def test_continue_web_search_expired_deadline_still_opens_google_hotels():
    """Deadline on a confirmed bounce must not skip the Google Hotels host."""
    opened: list[str] = []

    def click(*, x, y, **_k):
        return {"ok": True}

    def type_text(*, text="", **_k):
        return {"ok": True}

    def press(*, combo="", **_k):
        return {"ok": True}

    def open_url(url: str = "", **_k):
        opened.append(str(url))
        return {"ok": True, "url": url}

    def look_again():
        if any("google.com/travel" in u for u in opened):
            return dict(GOOGLE_HOTELS_ROME)
        return dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE)

    out = continue_web_search(
        dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE)
        | {"_saw_searchresults": True, "_typed_query": hotel_typed_query(LIVE_ITALY_HOTEL)},
        goal=LIVE_ITALY_HOTEL,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        open_url=open_url,
        deadline=time.monotonic() - 5,
    )
    assert any("google.com/travel" in u for u in opened), opened
    assert look_has_hotel_results(out) is True


def test_hotel_alt_urls_prefer_hotels_then_ddg_html():
    """jarvis-computer: /travel/search and /travel/hotels stay blank.

    curl 2026-09-11: both 302 to /travel/unsupported (empty body).
    html.duckduckgo.com/?q=Rome+hotels paints '10 Best Rome Hotels
    (From US$87)' and Tripadvisor from $76. Primary alt is still
    /travel/hotels (some networks paint a list); fallback is DDG HTML.
    """
    alt = hotel_alt_travel_url(LIVE_ITALY_HOTEL)
    fallback = hotel_alt_fallback_url(LIVE_ITALY_HOTEL)
    assert "google.com/travel/hotels" in alt
    assert "travel/search" not in alt
    assert "checkin=" in alt and "checkout=" in alt
    assert "html.duckduckgo.com/html" in fallback
    assert "hotels" in fallback
    assert "rome" in fallback.lower()


def test_blank_google_travel_after_alt_is_pending_not_typed_success():
    """After hotel_alt run_app, a blank Travel look is pending, not done."""
    from app.jarvis.voice_ask import _speak_web_job

    blank = LIVE_GOOGLE_TRAVEL_BLANK
    assert look_is_hotel_alt_host(blank) is True
    assert look_is_hotel_search_pending(blank) is True
    assert look_has_hotel_results(blank) is False
    assert look_is_travel_search_form(blank) is False
    assert look_lost_hotel_alt(blank) is False
    assert look_is_loading_or_blank(blank) is True
    unsupported = LIVE_GOOGLE_TRAVEL_UNSUPPORTED
    assert look_is_hotel_alt_host(unsupported) is True
    assert look_is_hotel_search_pending(unsupported) is True
    assert look_is_loading_or_blank(unsupported) is True
    tools = ["run_app", "see_screen", "click", "type", "keys"]
    item = dict(blank)
    item["_hotel_alt"] = True
    item["_typed_query"] = hotel_typed_query(LIVE_ITALY_HOTEL)
    item["_saw_searchresults"] = True
    spoken = _speak_web_job(LIVE_ITALY_HOTEL, item, tools, opened=True)
    low = spoken["reply"].lower()
    assert "i typed the search" not in low
    assert spoken["reply"] == _HOTEL_ALT_FAILED
    assert "180" not in spoken["reply"]


def test_booking_homepage_after_alt_is_lost_tab_not_typed_success():
    """Homepage Booking look after alt opened must not finalize typed-search."""
    from app.jarvis.voice_ask import _speak_web_job

    home = dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE)
    assert look_lost_hotel_alt(home) is True
    assert look_is_hotel_alt_host(home) is False
    home["_hotel_alt"] = True
    home["_typed_query"] = hotel_typed_query(LIVE_ITALY_HOTEL)
    home["_saw_searchresults"] = True
    spoken = _speak_web_job(
        LIVE_ITALY_HOTEL,
        home,
        ["run_app", "see_screen", "click", "type", "keys"],
        opened=True,
    )
    low = spoken["reply"].lower()
    assert "i typed the search" not in low
    assert spoken["reply"] == _HOTEL_ALT_FAILED


def test_continue_web_search_blank_google_travel_keeps_looking():
    """Blank Google Travel after alt is pending — keep looking, then prices."""
    from app.jarvis.voice_ask import _speak_web_job

    opened: list[str] = []
    looks = {"n": 0}

    def click(*, x, y, **_k):
        return {"ok": True}

    def type_text(*, text="", **_k):
        return {"ok": True}

    def press(*, combo="", **_k):
        return {"ok": True}

    def open_url(url: str = "", **_k):
        opened.append(str(url))
        return {"ok": True, "url": url}

    def look_again():
        looks["n"] += 1
        if any("html.duckduckgo.com" in u for u in opened):
            return dict(DDG_HOTELS_ROME)
        if any("google.com/travel" in u for u in opened):
            if looks["n"] >= HOTEL_ALT_BLANK_BEFORE_FALLBACK + 1:
                return dict(GOOGLE_HOTELS_ROME)
            return dict(LIVE_GOOGLE_TRAVEL_BLANK)
        return dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE)

    out = continue_web_search(
        dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE)
        | {"_saw_searchresults": True, "_typed_query": hotel_typed_query(LIVE_ITALY_HOTEL)},
        goal=LIVE_ITALY_HOTEL,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        open_url=open_url,
        deadline=time.monotonic() + 30,
    )
    assert any("google.com/travel" in u for u in opened), opened
    assert looks["n"] >= 2, looks
    assert look_has_hotel_results(out) is True
    spoken = _speak_web_job(
        LIVE_ITALY_HOTEL,
        out,
        ["run_app", "see_screen", "click", "type", "keys"],
        opened=True,
    )
    low = spoken["reply"].lower()
    assert "i typed the search" not in low
    assert "eden" in low
    assert "180" in low


def test_continue_web_search_booking_homepage_after_alt_refocuses():
    """After alt opened, a Booking homepage look refocuses/reopens the alt."""
    from app.jarvis.voice_ask import _speak_web_job

    opened: list[str] = []
    typed: list[str] = []
    clicks: list[tuple[int, int]] = []

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def type_text(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def press(*, combo="", **_k):
        return {"ok": True}

    def open_url(url: str = "", **_k):
        opened.append(str(url))
        return {"ok": True, "url": url}

    def look_again():
        blob = " ".join(opened + typed)
        if "google.com/travel" in blob or "duckduckgo.com" in blob:
            return dict(GOOGLE_HOTELS_ROME)
        return dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE)

    out = continue_web_search(
        dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE)
        | {
            "_saw_searchresults": True,
            "_typed_query": hotel_typed_query(LIVE_ITALY_HOTEL),
            "_hotel_alt": True,
        },
        goal=LIVE_ITALY_HOTEL,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        open_url=open_url,
        deadline=time.monotonic() + 30,
    )
    assert look_lost_hotel_alt(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE) is True
    assert (
        any("google.com/travel" in u for u in opened)
        or any("google.com/travel" in t or "duckduckgo.com" in t for t in typed)
        or clicks
    ), (opened, typed, clicks)
    assert look_has_hotel_results(out) is True
    spoken = _speak_web_job(
        LIVE_ITALY_HOTEL,
        out,
        ["run_app", "see_screen", "click", "type", "keys"],
        opened=True,
    )
    low = spoken["reply"].lower()
    assert "i typed the search" not in low
    assert "eden" in low
    assert "180" in low


def test_continue_web_search_priced_alt_finishes_with_options():
    """A priced Google Hotels / DDG list may finish with name + price lines."""
    from app.jarvis.voice_ask import _speak_web_job

    opened: list[str] = []

    def click(*, x, y, **_k):
        return {"ok": True}

    def type_text(*, text="", **_k):
        return {"ok": True}

    def press(*, combo="", **_k):
        return {"ok": True}

    def open_url(url: str = "", **_k):
        opened.append(str(url))
        return {"ok": True, "url": url}

    def look_again():
        return dict(GOOGLE_HOTELS_ROME)

    out = continue_web_search(
        dict(LIVE_GOOGLE_TRAVEL_BLANK)
        | {
            "_hotel_alt": True,
            "_typed_query": hotel_typed_query(LIVE_ITALY_HOTEL),
            "_saw_searchresults": True,
        },
        goal=LIVE_ITALY_HOTEL,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        open_url=open_url,
        deadline=time.monotonic() + 30,
    )
    assert look_has_hotel_results(out) is True
    spoken = _speak_web_job(
        LIVE_ITALY_HOTEL,
        out,
        ["run_app", "see_screen"],
        opened=True,
    )
    low = spoken["reply"].lower()
    assert "eden" in low
    assert "180" in low
    assert "i typed the search" not in low
    lines = hotel_option_lines(GOOGLE_HOTELS_ROME)
    assert any("eden" in line.lower() for line in lines)


def test_speak_web_job_alt_failed_says_google_hotels_failed():
    """After a real Google Hotels attempt, do not pretend Booking-only stuck."""
    from app.jarvis.voice_ask import _HOTEL_ALT_FAILED, _speak_web_job

    tools = ["run_app", "see_screen", "click", "type", "keys"]
    home = dict(LIVE_BOOKING_LIST_YOUR_PROPERTY)
    home["_typed_query"] = hotel_typed_query(LIVE_ITALY_HOTEL)
    home["_saw_searchresults"] = True
    home["_hotel_reopened"] = True
    home["_hotel_alt"] = True
    home["_hotel_bounced"] = True
    spoken = _speak_web_job(LIVE_ITALY_HOTEL, home, tools, opened=True)
    assert spoken["reply"] == _HOTEL_ALT_FAILED
    assert "google hotels" in spoken["reply"].lower()
    assert "180" not in spoken["reply"]


def test_speak_web_job_empty_homepage_after_type_is_not_opened_success():
    """Empty homepage after type is a bounce stuck line, not success."""
    from app.jarvis.voice_ask import _speak_web_job

    tools = ["run_app", "see_screen", "click", "type", "keys"]
    home = dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE)
    home["_typed_query"] = hotel_typed_query(LIVE_ITALY_HOTEL)
    home["_saw_searchresults"] = True
    home["_hotel_reopened"] = True
    spoken = _speak_web_job(LIVE_ITALY_HOTEL, home, tools, opened=True)
    low = spoken["reply"].lower()
    assert spoken["reply"] == _BOOKING_BOUNCED
    assert "i opened the page" not in low
    assert "i typed the search" not in low
    assert "bounced" in low
    assert "180" not in low


@pytest.mark.asyncio
async def test_voice_ask_searchresults_bounce_reopens_via_run_app(
    monkeypatch, tmp_path
):
    """Ask path: searchresults → homepage bounce → extra run_app → prices."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    launched: list[dict] = []
    looks = [
        dict(LIVE_BOOKING_SEARCHRESULTS_WHITE_PANE),
        dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE),
        dict(PRICED_ROME_HOTELS),
    ]
    _patch_voice_ask_web(
        monkeypatch,
        looks,
        clicks=clicks,
        typed=typed,
        keys=keys,
        launched=launched,
    )
    body = await run_voice_ask(LIVE_ITALY_HOTEL)
    urls = [str(p.get("url") or "") for p in launched]
    assert len([u for u in urls if "searchresults.html" in u]) >= 2, urls
    low = body["reply"].lower()
    assert "i opened the page" not in low
    assert "i typed the search" not in low
    assert "eden" in low
    assert "180" in low
    assert body["reply"] != _WEB_STUCK


@pytest.mark.asyncio
async def test_voice_ask_booking_bounce_opens_google_hotels_before_stuck(
    monkeypatch, tmp_path
):
    """Ask path: searchresults → list-your-property must run_app Google Hotels."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    launched: list[dict] = []
    n = {"i": 0}

    def fake_see(ctx, args):
        if any("google.com/travel" in str(p.get("url") or "") for p in launched):
            return dict(GOOGLE_HOTELS_ROME)
        n["i"] += 1
        if n["i"] == 1:
            return dict(LIVE_BOOKING_SEARCHRESULTS_WHITE_PANE)
        return dict(LIVE_BOOKING_LIST_YOUR_PROPERTY)

    looks = [dict(LIVE_BOOKING_SEARCHRESULTS_WHITE_PANE)]
    _patch_voice_ask_web(
        monkeypatch,
        looks,
        clicks=clicks,
        typed=typed,
        keys=keys,
        launched=launched,
    )
    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    body = await run_voice_ask(LIVE_ITALY_HOTEL)
    urls = [str(p.get("url") or "") for p in launched]
    assert any("google.com/travel" in u for u in urls), urls
    assert any("searchresults.html" in u for u in urls), urls
    assert "run_app" in list(body.get("tools_used") or [])
    low = body["reply"].lower()
    assert "eden" in low
    assert "180" in low
    assert "i opened the page" not in low
    assert "i typed the search" not in low
    assert body["reply"] != _WEB_STUCK
    assert body["reply"] != _BOOKING_BOUNCED


@pytest.mark.asyncio
async def test_voice_ask_blank_google_travel_after_alt_waits_for_prices(
    monkeypatch, tmp_path
):
    """Ask path: after alt run_app, blank Travel is pending until prices."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    launched: list[dict] = []
    n = {"i": 0, "alt": 0}

    def fake_see(ctx, args):
        urls = [str(p.get("url") or "") for p in launched]
        if any("html.duckduckgo.com" in u or "google.com/travel" in u for u in urls):
            n["alt"] += 1
            if n["alt"] >= 3:
                return dict(GOOGLE_HOTELS_ROME)
            return dict(LIVE_GOOGLE_TRAVEL_BLANK)
        n["i"] += 1
        if n["i"] == 1:
            return dict(LIVE_BOOKING_SEARCHRESULTS_WHITE_PANE)
        return dict(LIVE_BOOKING_LIST_YOUR_PROPERTY)

    looks = [dict(LIVE_BOOKING_SEARCHRESULTS_WHITE_PANE)]
    _patch_voice_ask_web(
        monkeypatch,
        looks,
        clicks=clicks,
        typed=typed,
        keys=keys,
        launched=launched,
    )
    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    body = await run_voice_ask(LIVE_ITALY_HOTEL)
    urls = [str(p.get("url") or "") for p in launched]
    assert any("google.com/travel" in u or "duckduckgo.com" in u for u in urls), urls
    low = body["reply"].lower()
    assert "i typed the search" not in low
    assert "eden" in low
    assert "180" in low
    assert body["reply"] != _WEB_STUCK


@pytest.mark.asyncio
async def test_voice_ask_booking_homepage_after_alt_refocuses(
    monkeypatch, tmp_path
):
    """Ask path: Booking homepage after alt must refocus alt, then prices."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    launched: list[dict] = []
    n = {"i": 0, "after_alt": 0}

    def fake_see(ctx, args):
        urls = [str(p.get("url") or "") for p in launched]
        alt_opened = any(
            "google.com/travel" in u or "duckduckgo.com" in u for u in urls
        ) or any(
            "google.com/travel" in t or "duckduckgo.com" in t for t in typed
        )
        if alt_opened:
            n["after_alt"] += 1
            if n["after_alt"] == 1:
                return dict(LIVE_BOOKING_HOMEPAGE_AFTER_BOUNCE)
            return dict(GOOGLE_HOTELS_ROME)
        n["i"] += 1
        if n["i"] == 1:
            return dict(LIVE_BOOKING_SEARCHRESULTS_WHITE_PANE)
        return dict(LIVE_BOOKING_LIST_YOUR_PROPERTY)

    looks = [dict(LIVE_BOOKING_SEARCHRESULTS_WHITE_PANE)]
    _patch_voice_ask_web(
        monkeypatch,
        looks,
        clicks=clicks,
        typed=typed,
        keys=keys,
        launched=launched,
    )
    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    body = await run_voice_ask(LIVE_ITALY_HOTEL)
    urls = [str(p.get("url") or "") for p in launched]
    assert any("google.com/travel" in u or "duckduckgo.com" in u for u in urls) or any(
        "google.com/travel" in t or "duckduckgo.com" in t for t in typed
    ), (urls, typed)
    low = body["reply"].lower()
    assert "i typed the search" not in low
    assert "eden" in low
    assert "180" in low


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
    assert search_box_point(HOMEPAGE_NO_BOX) == BOOKING_DEST_CLICK
    assert search_box_point(HOMEPAGE_NO_BOX) != SEARCH_BOX_CLICK
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
    assert BOOKING_DEST_CLICK in clicks
    assert SEARCH_BOX_CLICK not in clicks
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
    assert BOOKING_DEST_CLICK in clicks
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
    assert BOOKING_DEST_CLICK in clicks
    assert "enter" in keys
    assert out.get("_typed_query")
    assert "Eden" in str(out.get("vision_description") or "")


def _patch_voice_ask_web(
    monkeypatch, looks, *, clicks, typed, keys=None, launched=None
):
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
        if launched is not None:
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
        return {"ok": True, "cmd": "chrome", "argv": ["chromium"], **args}

    def fake_focus(*, app="", title=""):
        return {"ok": True, "app": app or title, "focused": True}

    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    monkeypatch.setattr("app.jarvis.desktop.focus_app", fake_focus)
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
    assert BOOKING_DEST_CLICK in clicks
    assert SEARCH_BOX_CLICK not in clicks
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

# Live 2026-09-11 aicontrolroom.nl: bol.com IP-abuse wall. Vision saw the
# block; ask finalized "I typed the search." because the --no-sandbox
# banner counted as overlay typed-success.
LIVE_BOL_ABUSE_BLOCK = {
    "ok": True,
    "title": "bol.com - Chromium",
    "url": "https://www.bol.com/",
    "vision_description": (
        "You are using an unsupported command-line flag --no-sandbox. "
        "Your access to bol.com has been temporarily blocked due to possible "
        "abuse from this IP address. This may be caused by use of a VPN, "
        "an outdated browser, or automated scripts. Contact "
        "customerservice@bol.com. No products. No cart."
    ),
}

LIVE_COOLBLUE_ABUSE_BLOCK = {
    "ok": True,
    "title": "Coolblue - Chromium",
    "url": "https://www.coolblue.nl/",
    "vision_description": (
        "Your access to coolblue.nl has been temporarily blocked due to "
        "possible abuse from this IP address. Automated scripts. No products."
    ),
}

LIVE_AMAZON_NL_ABUSE_BLOCK = {
    "ok": True,
    "title": "Amazon.nl - Chromium",
    "url": "https://www.amazon.nl/",
    "vision_description": (
        "Access denied. Your access to amazon.nl has been temporarily "
        "blocked due to possible abuse from this IP address."
    ),
}

COOLBLUE_TWO_PRODUCTS = {
    "ok": True,
    "title": "Coolblue",
    "url": "https://www.coolblue.nl/",
    "vision_description": (
        "Coolblue. Two in-stock items. Philips Sonicare. 89 euro. "
        "Bosch kettle. 49 euro. Two items in the basket."
    ),
}

AMAZON_NL_TWO_PRODUCTS = {
    "ok": True,
    "title": "Amazon.nl",
    "url": "https://www.amazon.nl/",
    "vision_description": (
        "Amazon.nl. Two in-stock items. Sony headphones. 79 euro. "
        "Logitech mouse. 29 euro. Two items in the basket."
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

# Live leftover: Chromium New Tab on Google, vision starts on Google then
# cuts toward the hotel ask. Must not count as hotel results.
LEFTOVER_GOOGLE_NEWTAB_HOTEL = {
    "ok": True,
    "title": "New Tab - Chromium",
    "url": "chrome://newtab",
    "vision_description": (
        "A Chromium New Tab showing the Google homepage. The Google logo, "
        "a search box, Debian, Web Store. Then looking for hotels in Rome, "
        "Florence, or Tuscany under 2000 Euro."
    ),
}

LEFTOVER_GOOGLE_HOME_HOTEL = {
    "ok": True,
    "title": "Google",
    "url": "https://www.google.com/",
    "vision_description": (
        "Google homepage. The Google logo and a search box. "
        "Then the goal is to find hotels in central Italy."
    ),
}

ITALY_HOTEL_RESULTS = {
    "ok": True,
    "title": "Hotels in Rome — Booking.com",
    "url": "https://www.booking.com/searchresults.html",
    "vision_description": (
        "Hotels in central Rome. Hotel Eden. Prices from 180 EUR. "
        "Check-in 12 Oct, check-out 15 Oct, 3 nights."
    ),
}

# Live 2026-09-11: first look after typing is a Google SERP whose title
# still has coaching words. No Booking, no dates, no hotel prices.
LIVE_GOOGLE_SERP_HOTEL = {
    "ok": True,
    "title": (
        "Use the computer. available hotels under 2000 Euro total in "
        "central Italy - Google Search"
    ),
    "url": (
        "https://www.google.com/search?q=Use+the+computer.+available+hotels+"
        "under+2000+Euro+total+in+central+Italy"
    ),
    "vision_description": (
        "The focused window is a web browser displaying Google. "
        "The search query reads Use the computer. available hotels under "
        "2000 Euro total in central Italy. AI overview unavailable. "
        "People also ask."
    ),
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


def test_bol_abuse_block_is_not_typed_success():
    """Live bol.com IP-abuse wall is a block, not a typed search."""
    from app.jarvis.voice_ask import _speak_web_job

    block = LIVE_BOL_ABUSE_BLOCK
    assert ask_wants_shop(LIVE_CART) is True
    assert ask_wants_shop(GRINDER) is True
    assert look_is_abuse_block(block) is True
    assert look_is_http_error(block) is True
    assert look_is_retailer_block(block) is True
    assert look_is_nl_retailer(block) is True
    assert look_has_blocking_overlay(block) is True
    assert overlay_kind(block) == "sandbox"
    assert look_is_leftover_for_ask(block, LIVE_CART) is True
    assert look_is_web_page(block) is False
    assert search_box_point(block) is None
    assert look_is_page_ready(block, LIVE_CART) is False
    urls = retailer_fallback_urls()
    assert urls[0] == "https://www.coolblue.nl/"
    assert urls[1] == "https://www.amazon.nl/"
    assert next_retailer_fallback_url(block, []) == "https://www.coolblue.nl/"
    assert next_retailer_fallback_url(block, ["https://www.coolblue.nl/"]) == (
        "https://www.amazon.nl/"
    )
    assert next_retailer_fallback_url(LIVE_AMAZON_NL_ABUSE_BLOCK, urls) is None
    tools = ["run_app", "see_screen", "click", "type", "keys"]
    typed = dict(block)
    typed["_typed_query"] = "two real in-stock products"
    spoken = _speak_web_job(LIVE_CART, typed, tools, opened=True)
    low = spoken["reply"].lower()
    assert spoken["reply"] != "I typed the search."
    assert "i typed the search" not in low
    assert spoken["reply"] == _WEB_STUCK
    overlay_only = _speak_web_job(LIVE_CART, dict(block), tools, opened=True)
    assert "i typed the search" not in overlay_only["reply"].lower()
    failed = dict(block)
    failed["_typed_query"] = "two real in-stock products"
    failed["_retailer_tried"] = list(urls)
    failed["_retailer_blocked"] = True
    after = _speak_web_job(LIVE_CART, failed, tools, opened=True)
    assert after["reply"] == _RETAILER_BLOCKED
    assert "i typed the search" not in after["reply"].lower()
    assert "coolblue" in after["reply"].lower()
    assert "amazon" in after["reply"].lower()


def test_automated_scripts_alone_is_not_an_abuse_block():
    """Developer-guide copy is not a retailer IP wall."""
    guide = {
        "ok": True,
        "title": "Developer Guide — bol.com",
        "url": "https://developers.bol.com/",
        "vision_description": (
            "If you're a developer, check developers.bol.com. "
            "Automated scripts that collect data should use the Open API."
        ),
    }
    assert look_is_abuse_block(guide) is False
    assert look_is_http_error(guide) is False
    assert look_is_retailer_block(guide) is False
    assert look_is_nl_retailer(guide) is True


def test_retailer_fallback_requires_a_retailer_host():
    """Google / leftover 403 is leftover recovery, not Coolblue."""
    google_403 = {
        "ok": True,
        "title": "Access Denied",
        "url": "https://www.google.com/",
        "vision_description": "Access Denied HTTP 403. Unusual leftover tab.",
    }
    assert look_is_http_error(google_403) is True
    assert look_is_nl_retailer(google_403) is False
    assert look_is_retailer_block(google_403) is False
    opened: list[str] = []

    def click(*, x, y, **_k):
        return {"ok": True}

    def type_text(*, text="", **_k):
        return {"ok": True}

    def press(*, combo="", **_k):
        return {"ok": True}

    def open_url(url: str = "", **_k):
        opened.append(str(url))
        return {"ok": True, "url": url}

    def look_again():
        return dict(google_403)

    continue_web_search(
        dict(google_403),
        goal=LIVE_CART,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        open_url=open_url,
        deadline=time.monotonic() + 5,
    )
    assert not any("coolblue.nl" in u or "amazon.nl" in u for u in opened), opened


def test_hotel_bath_products_is_still_a_hotel_job():
    """Generic 'products' must not steal hotel follow-through."""
    asked = "find a hotel in Rome with sustainable bath products"
    assert ask_wants_hotel(asked) is True
    assert ask_wants_shop(asked) is False


def test_open_amazon_look_only_is_not_a_web_search_job():
    """A retailer hostname alone is look-and-tell, not search continuation."""
    asked = "open amazon.nl and tell me what is on the page"
    assert wants_web_job(asked) is False
    assert wants_web_job(LIVE_CART) is True
    assert wants_web_job(GRINDER) is True


def test_continue_web_search_retailer_block_opens_coolblue():
    """Shop abuse wall must run_app coolblue.nl before any typed-success."""
    from app.jarvis.voice_ask import _speak_web_job

    opened: list[str] = []
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []

    def click(*, x, y, **_k):
        clicks.append((int(x), int(y)))
        return {"ok": True}

    def type_text(*, text="", **_k):
        typed.append(str(text))
        return {"ok": True}

    def press(*, combo="", **_k):
        return {"ok": True}

    def open_url(url: str = "", **_k):
        opened.append(str(url))
        return {"ok": True, "url": url}

    def look_again():
        if any("coolblue.nl" in u for u in opened):
            return dict(COOLBLUE_TWO_PRODUCTS)
        return dict(LIVE_BOL_ABUSE_BLOCK)

    out = continue_web_search(
        dict(LIVE_BOL_ABUSE_BLOCK) | {"_typed_query": "two real in-stock products"},
        goal=LIVE_CART,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        open_url=open_url,
        deadline=time.monotonic() + 30,
    )
    assert any("coolblue.nl" in u for u in opened), opened
    assert opened[0] == "https://www.coolblue.nl/"
    assert look_is_retailer_block(out) is False
    spoken = _speak_web_job(
        LIVE_CART,
        out,
        ["run_app", "see_screen", "click", "type", "keys"],
        opened=True,
    )
    low = spoken["reply"].lower()
    assert "i typed the search" not in low
    assert "sonicare" in low or "philips" in low
    assert "89" in low


def test_continue_web_search_coolblue_block_opens_amazon_nl():
    """If coolblue is also blocked, immediately open amazon.nl."""
    opened: list[str] = []

    def click(*, x, y, **_k):
        return {"ok": True}

    def type_text(*, text="", **_k):
        return {"ok": True}

    def press(*, combo="", **_k):
        return {"ok": True}

    def open_url(url: str = "", **_k):
        opened.append(str(url))
        return {"ok": True, "url": url}

    def look_again():
        urls = " ".join(opened)
        if "amazon.nl" in urls:
            return dict(AMAZON_NL_TWO_PRODUCTS)
        if "coolblue.nl" in urls:
            return dict(LIVE_COOLBLUE_ABUSE_BLOCK)
        return dict(LIVE_BOL_ABUSE_BLOCK)

    out = continue_web_search(
        dict(LIVE_BOL_ABUSE_BLOCK),
        goal=LIVE_CART,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        open_url=open_url,
        deadline=time.monotonic() + 30,
    )
    assert any("coolblue.nl" in u for u in opened), opened
    assert any("amazon.nl" in u for u in opened), opened
    assert look_is_retailer_block(out) is False
    blob = str(out.get("vision_description") or "").lower()
    assert "sony" in blob or "79" in blob


def test_continue_web_search_all_retailer_fallbacks_blocked_is_stuck():
    """After coolblue and amazon.nl also block, mark blocked — not typed-success."""
    from app.jarvis.voice_ask import _speak_web_job

    opened: list[str] = []

    def click(*, x, y, **_k):
        return {"ok": True}

    def type_text(*, text="", **_k):
        return {"ok": True}

    def press(*, combo="", **_k):
        return {"ok": True}

    def open_url(url: str = "", **_k):
        opened.append(str(url))
        return {"ok": True, "url": url}

    def look_again():
        urls = " ".join(opened)
        if "amazon.nl" in urls:
            return dict(LIVE_AMAZON_NL_ABUSE_BLOCK)
        if "coolblue.nl" in urls:
            return dict(LIVE_COOLBLUE_ABUSE_BLOCK)
        return dict(LIVE_BOL_ABUSE_BLOCK)

    out = continue_web_search(
        dict(LIVE_BOL_ABUSE_BLOCK) | {"_typed_query": "two real in-stock products"},
        goal=LIVE_CART,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
        open_url=open_url,
        deadline=time.monotonic() + 30,
    )
    assert any("coolblue.nl" in u for u in opened), opened
    assert any("amazon.nl" in u for u in opened), opened
    assert out.get("_retailer_blocked") is True
    spoken = _speak_web_job(
        LIVE_CART,
        out,
        ["run_app", "see_screen", "click", "type", "keys"],
        opened=True,
    )
    assert spoken["reply"] == _RETAILER_BLOCKED
    assert "i typed the search" not in spoken["reply"].lower()


@pytest.mark.asyncio
async def test_voice_ask_bol_abuse_block_run_app_coolblue(monkeypatch, tmp_path):
    """Ask path: bol.com abuse wall must run_app coolblue.nl, not typed-search."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    launched: list[dict] = []

    def fake_see(ctx, args):
        urls = [str(p.get("url") or "") for p in launched]
        if any("coolblue.nl" in u for u in urls):
            return dict(COOLBLUE_TWO_PRODUCTS)
        return dict(LIVE_BOL_ABUSE_BLOCK)

    looks = [dict(LIVE_BOL_ABUSE_BLOCK)]
    _patch_voice_ask_web(
        monkeypatch,
        looks,
        clicks=clicks,
        typed=typed,
        keys=keys,
        launched=launched,
    )
    monkeypatch.setattr("app.jarvis.tools._see_screen", fake_see)
    body = await run_voice_ask(LIVE_CART)
    urls = [str(p.get("url") or "") for p in launched]
    assert any("coolblue.nl" in u for u in urls), urls
    assert "run_app" in list(body.get("tools_used") or [])
    low = body["reply"].lower()
    assert "i typed the search" not in low
    assert "sonicare" in low or "philips" in low
    assert "89" in low
    assert body["reply"] != _WEB_STUCK
    assert body["reply"] != _RETAILER_BLOCKED


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
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    assert settings_store.get_look_speed() == "off"
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
    reset_last_look()


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


def test_leftover_google_newtab_is_not_hotel_results():
    """Vision that names the hotel ask on a Google New Tab is not done."""
    assert look_is_focused_new_tab(LEFTOVER_GOOGLE_NEWTAB_HOTEL) is True
    assert look_is_loading_or_blank(LEFTOVER_GOOGLE_NEWTAB_HOTEL) is True
    assert look_has_hotel_results(LEFTOVER_GOOGLE_NEWTAB_HOTEL) is False
    assert look_has_hotel_results(LEFTOVER_GOOGLE_HOME_HOTEL) is False
    q = web_search_query(LIVE_ITALY_HOTEL)
    assert needs_web_query(LIVE_ITALY_HOTEL, LEFTOVER_GOOGLE_NEWTAB_HOTEL, q) is True
    assert needs_web_query(LIVE_ITALY_HOTEL, LEFTOVER_GOOGLE_HOME_HOTEL, q) is True
    assert look_has_hotel_results(ITALY_HOTEL_RESULTS) is True
    assert look_is_leftover_for_ask(LEFTOVER_GOOGLE_NEWTAB_HOTEL, LIVE_ITALY_HOTEL) is False


def test_google_serp_without_hotel_prices_is_unfinished():
    """A focused-window Google SERP is not hotel results and not done."""
    q = web_search_query(LIVE_ITALY_HOTEL)
    assert look_has_hotel_results(LIVE_GOOGLE_SERP_HOTEL) is False
    assert look_is_travel_site(LIVE_GOOGLE_SERP_HOTEL) is False
    assert look_is_unfinished_hotel_search(LIVE_GOOGLE_SERP_HOTEL) is True
    assert needs_hotel_followthrough(LIVE_ITALY_HOTEL, LIVE_GOOGLE_SERP_HOTEL, q) is True
    assert look_is_unfinished_hotel_search(ITALY_HOTEL_RESULTS) is False
    assert needs_hotel_followthrough(LIVE_ITALY_HOTEL, ITALY_HOTEL_RESULTS, q) is False


def test_continue_web_search_google_serp_types_travel_url_or_dates():
    """After the live Google SERP look, type Booking (or dates), do not stop."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []

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
        blob = " ".join(typed).lower()
        if "booking.com" in blob or "check-in" in blob or "checkin=" in blob:
            return dict(ITALY_HOTEL_RESULTS)
        return dict(LIVE_GOOGLE_SERP_HOTEL)

    out = continue_web_search(
        dict(LIVE_GOOGLE_SERP_HOTEL),
        goal=LIVE_ITALY_HOTEL,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
    )
    assert typed, "unfinished Google SERP must type a travel URL or dates"
    blob = " ".join(typed).lower()
    assert all(_typed_is_user_query(t) for t in typed), typed
    assert "use the computer" not in blob
    assert "dismiss popups" not in blob
    assert "do not invent" not in blob
    continued = (
        "booking.com" in blob
        or "check-in" in blob
        or "checkin=" in blob
        or any("202" in t for t in typed)
    )
    assert continued, typed
    assert out.get("_hotel_followed") or look_has_hotel_results(out)


def test_continue_web_search_google_newtab_hotel_leak_types():
    """Google New Tab whose caption leaks 'hotels in' must still type."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []

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
        if typed:
            return dict(ITALY_HOTEL_RESULTS)
        return dict(LEFTOVER_GOOGLE_NEWTAB_HOTEL)

    out = continue_web_search(
        dict(LEFTOVER_GOOGLE_NEWTAB_HOTEL),
        goal=LIVE_ITALY_HOTEL,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
    )
    assert typed, "leftover Google New Tab must type the hotel query"
    assert all(_typed_is_user_query(t) for t in typed), typed
    assert "use the computer" not in " ".join(typed).lower()
    assert any(
        token in t.lower()
        for t in typed
        for token in ("hotel", "rome", "italy", "florence", "tuscany")
    ), typed
    assert out.get("_typed_query") or "Eden" in str(out.get("vision_description") or "")


@pytest.mark.asyncio
async def test_voice_ask_leftover_google_newtab_hotel_keeps_going(
    monkeypatch, tmp_path
):
    """Live Italy hotel ask + leftover Google New Tab must type or run_app.

    dismiss popups must not stop after one see_screen. look_speed=off
    must not skip wait+type. Never _WEB_STUCK after only see_screen.
    """
    from app.jarvis import settings_store
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    assert settings_store.get_look_speed() == "off"
    reset_last_look()
    remember_last_look(dict(LEFTOVER_GOOGLE_NEWTAB_HOTEL))

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(LEFTOVER_GOOGLE_NEWTAB_HOTEL),
        dict(LEFTOVER_GOOGLE_NEWTAB_HOTEL),
        dict(LEFTOVER_GOOGLE_NEWTAB_HOTEL),
        dict(ITALY_HOTEL_RESULTS),
    ]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(LIVE_ITALY_HOTEL)
    tools = list(body.get("tools_used") or [])
    acted = {"type", "run_app"} & set(tools)
    assert acted, f"must type or open a travel/search URL, got {tools}"
    assert tools != ["see_screen"]
    assert body["reply"] != _WEB_STUCK
    if typed:
        blob = " ".join(typed).lower()
        assert all(_typed_is_user_query(t) for t in typed), typed
        assert "use the computer" not in blob
        assert "dismiss popups" not in blob
        assert "do not invent" not in blob
        assert any(
            token in blob for token in ("hotel", "rome", "italy", "florence", "tuscany")
        ), typed
    low = body["reply"].lower()
    assert "i could not finish the search" not in low
    reset_last_look()


@pytest.mark.asyncio
async def test_voice_ask_leftover_google_homepage_hotel_keeps_going(
    monkeypatch, tmp_path
):
    """Same path when last_look is the Google homepage, not chrome://newtab."""
    from app.jarvis import settings_store
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    reset_last_look()
    remember_last_look(dict(LEFTOVER_GOOGLE_HOME_HOTEL))

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(LEFTOVER_GOOGLE_HOME_HOTEL),
        dict(LEFTOVER_GOOGLE_HOME_HOTEL),
        dict(ITALY_HOTEL_RESULTS),
    ]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(LIVE_ITALY_HOTEL)
    tools = list(body.get("tools_used") or [])
    assert {"type", "run_app"} & set(tools)
    assert tools != ["see_screen"]
    assert body["reply"] != _WEB_STUCK
    reset_last_look()


def test_continue_web_search_genius_dismisses_then_types_dates():
    """First blocked Genius look must click/keys, then type — not stop."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(LIVE_BOOKING_GENIUS),
        {
            "ok": True,
            "title": "Booking.com | Official site",
            "url": "https://www.booking.com/",
            "vision_description": (
                "Booking.com. Where are you going? Search box is empty at (640, 320)."
            ),
        },
        dict(ITALY_HOTEL_RESULTS),
    ]
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
        goal=LIVE_ITALY_HOTEL,
        click=click,
        type_text=type_text,
        keys=press,
        look_again=look_again,
    )
    assert clicks, "Genius modal must be dismissed with a click"
    assert (920, 170) in clicks or SIGNIN_DISMISS_CLICK in clicks
    assert "escape" in keys
    assert typed, "after Genius dismiss, type destination or dates"
    assert all(_typed_is_user_query(t) for t in typed), typed
    blob = " ".join(typed).lower()
    assert "google.com" not in blob
    assert any(
        token in blob
        for token in ("hotel", "rome", "italy", "florence", "tuscany", "checkin")
    ), typed
    assert look_has_blocking_overlay(out) is False
    assert look_has_hotel_results(out) or out.get("_typed_query")


@pytest.mark.asyncio
async def test_voice_ask_live_italy_genius_dismisses_not_web_stuck(
    monkeypatch, tmp_path
):
    """Live Italy hotel ask + Genius modal: click/keys, then search. Stay on Booking."""
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    launched: list[dict] = []
    looks = [
        dict(LIVE_BOOKING_GENIUS),
        {
            "ok": True,
            "title": "Booking.com | Official site",
            "url": "https://www.booking.com/",
            "vision_description": (
                "Booking.com. Where are you going? Search box is empty at (640, 320)."
            ),
        },
        dict(ITALY_HOTEL_RESULTS),
    ]
    _patch_voice_ask_web(
        monkeypatch,
        looks,
        clicks=clicks,
        typed=typed,
        keys=keys,
        launched=launched,
    )

    body = await run_voice_ask(LIVE_ITALY_HOTEL)
    tools = list(body.get("tools_used") or [])
    assert "click" in tools or clicks, f"must dismiss Genius, tools={tools}"
    assert "keys" in tools or "escape" in keys
    assert clicks, "first blocked Genius look must click X / dismiss"
    assert (920, 170) in clicks or SIGNIN_DISMISS_CLICK in clicks
    assert typed, "after dismiss, continue toward destination / dates"
    assert all(_typed_is_user_query(t) for t in typed), typed
    typed_blob = " ".join(typed).lower()
    urls = " ".join(
        str(item.get("url") or item.get("opened") or "") for item in launched
    ).lower()
    assert "google.com/search" not in typed_blob
    assert "booking.com" in urls
    assert body["reply"] != _WEB_STUCK
    assert "i could not finish the search" not in body["reply"].lower()
    low = body["reply"].lower()
    assert "eden" in low or "hotel" in low or "typed the search" in low
    assert tools != ["run_app", "see_screen"]


def test_speak_web_job_hotel_serp_caption_is_not_the_reply():
    """A focused-window Google SERP caption is not 3 hotel options."""
    from app.jarvis.voice_ask import _speak_looked, _speak_web_job

    looked = dict(LIVE_GOOGLE_SERP_HOTEL)
    looked["_typed_query"] = web_search_query(LIVE_ITALY_HOTEL)
    body = _speak_web_job(
        LIVE_ITALY_HOTEL, looked, ["run_app", "see_screen", "type"], opened=True
    )
    low = body["reply"].lower()
    assert "focused window" not in low
    assert "the search query reads" not in low
    assert "ai overview" not in low
    via = _speak_looked(
        looked, ["run_app", "see_screen", "type"], opened=True, asked=LIVE_ITALY_HOTEL
    )
    assert "focused window" not in via["reply"].lower()
    assert "the search query reads" not in via["reply"].lower()
    picked = _speak_web_job(
        LIVE_ITALY_HOTEL, dict(ITALY_HOTEL_RESULTS), ["see_screen"], opened=True
    )
    assert "eden" in picked["reply"].lower() or "hotel" in picked["reply"].lower()


@pytest.mark.asyncio
async def test_voice_ask_hotel_google_serp_continues_not_caption(
    monkeypatch, tmp_path
):
    """Live stuck SERP: keep going (Booking URL or dates), never speak caption.

    look_speed=off must not skip followthrough. Typed text must not include
    Use the computer / dismiss popups / Do not invent.
    """
    from app.jarvis import settings_store
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    assert settings_store.get_look_speed() == "off"
    reset_last_look()
    remember_last_look(dict(LIVE_GOOGLE_SERP_HOTEL))

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    launched: list[dict] = []
    looks = [
        dict(LIVE_GOOGLE_SERP_HOTEL),
        dict(LIVE_GOOGLE_SERP_HOTEL),
        dict(ITALY_HOTEL_RESULTS),
    ]
    _patch_voice_ask_web(
        monkeypatch,
        looks,
        clicks=clicks,
        typed=typed,
        keys=keys,
        launched=launched,
    )

    body = await run_voice_ask(LIVE_ITALY_HOTEL)
    tools = list(body.get("tools_used") or [])
    urls = " ".join(
        str(item.get("url") or item.get("opened") or "") for item in launched
    ).lower()
    typed_blob = " ".join(typed).lower()
    continued = (
        "booking.com" in urls
        or "booking.com" in typed_blob
        or "check-in" in typed_blob
        or "checkin=" in typed_blob
        or any("202" in t for t in typed)
    )
    assert continued, f"tools={tools} typed={typed} urls={urls}"
    assert all(_typed_is_user_query(t) for t in typed), typed
    assert "use the computer" not in typed_blob
    assert "dismiss popups" not in typed_blob
    assert "do not invent" not in typed_blob
    low = body["reply"].lower()
    assert "focused window" not in low
    assert "the search query reads" not in low
    assert "ai overview" not in low
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
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.voice_ask import run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    assert settings_store.get_look_speed() == "off"
    reset_last_look()
    remember_last_look(dict(LEFTOVER_EXTENSIONS))

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
    reset_last_look()


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

GOOGLE_SORRY_UNUSED_TAB = {
    "ok": True,
    "title": GOOGLE_SORRY["title"],
    "url": GOOGLE_SORRY["url"],
    "vision_description": (
        GOOGLE_SORRY["vision_description"]
        + " A blank New Tab is not focused. Extensions tab still there."
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
    assert look_has_unfocused_new_tab(GOOGLE_SORRY) is False
    assert look_has_unfocused_new_tab(GOOGLE_SORRY_UNUSED_TAB) is True
    assert look_is_focused_new_tab(GOOGLE_SORRY_UNUSED_TAB) is False
    assert look_is_captcha(GOOGLE_SORRY_UNUSED_TAB) is True
    assert look_has_unfocused_new_tab(NEW_TAB_CHROME) is False
    assert look_is_web_page(GOOGLE_SORRY) is False
    assert look_is_captcha(WEATHER_AFTER_TYPE) is False
    assert look_is_captcha(LEFTOVER_EXTENSIONS) is False
    assert CAPTCHA_FOCUS_MIN_S >= 30.0
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


def _assert_alt_weather_typed(typed: list[str]) -> None:
    assert typed, "must omnibox-type a clean alt search URL after New Tab is focused"
    assert any(
        h in t.lower()
        for t in typed
        for h in ("duckduckgo.com", "bing.com", "weather.com", "accuweather")
    ), typed
    assert any("weather" in t.lower() or "amsterdam" in t.lower() for t in typed)
    assert all(_typed_is_user_query(t) for t in typed)
    assert all("google.com/search" not in t.lower() for t in typed)
    assert all("look" not in t.lower() for t in typed)
    assert all("click" not in t.lower() for t in typed)
    assert all("open chrome" not in t.lower() for t in typed)


def test_continue_web_search_sorry_unused_new_tab_focuses_then_types():
    """Leftover sorry + blank New Tab: focus New Tab, type ddg, never stuck."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    start = dict(GOOGLE_SORRY_UNUSED_TAB)
    start["_opened_new_tab"] = True
    out = _run_continue(
        [
            start,
            dict(GOOGLE_SORRY_UNUSED_TAB),
            dict(GOOGLE_SORRY_UNUSED_TAB),
            dict(GOOGLE_SORRY_UNUSED_TAB),
            dict(NEW_TAB_CHROME),
            dict(DDG_WEATHER),
        ],
        LIVE_WEATHER,
        clicks,
        typed,
        keys,
    )
    assert "ctrl+t" not in {k.lower() for k in keys}, (
        "New Tab already unused — click it, do not Ctrl+T again"
    )
    assert any(xy in NEW_TAB_FOCUS_CLICKS for xy in clicks), (
        "must click until New Tab is focused, same path as leftover Extensions"
    )
    assert OMNIBOX_CLICK in clicks
    assert SEARCH_BOX_CLICK not in clicks
    _assert_alt_weather_typed(typed)
    blob = str(out.get("vision_description") or "").lower()
    assert "amsterdam" in blob or "weather" in blob or "degrees" in blob
    assert "i'm not a robot" not in blob
    assert look_is_captcha(out) is False
    from app.jarvis.voice_ask import _speak_web_job

    spoken = _speak_web_job(
        LIVE_WEATHER,
        out,
        ["see_screen", "click", "type", "keys"],
        opened=False,
    )
    low = spoken["reply"].lower()
    assert "could not finish" not in low
    assert "i'm not a robot" not in low
    assert "amsterdam" in low or "weather" in low or "degrees" in low


def test_continue_web_search_sorry_first_focus_fail_retries_then_types():
    """First New Tab focus miss is not done — click again, then type ddg."""
    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    out = _run_continue(
        [
            dict(GOOGLE_SORRY),
            dict(GOOGLE_SORRY),
            dict(GOOGLE_SORRY),
            dict(GOOGLE_SORRY),
            dict(GOOGLE_SORRY),
            dict(NEW_TAB_CHROME),
            dict(DDG_WEATHER),
        ],
        LIVE_WEATHER,
        clicks,
        typed,
        keys,
    )
    assert keys.count("ctrl+t") == 1, "Ctrl+T once — then click the unused New Tab"
    assert any(xy in NEW_TAB_FOCUS_CLICKS for xy in clicks)
    assert OMNIBOX_CLICK in clicks
    _assert_alt_weather_typed(typed)
    assert look_is_captcha(out) is False
    from app.jarvis.voice_ask import _speak_web_job

    spoken = _speak_web_job(
        LIVE_WEATHER,
        out,
        ["see_screen", "click", "type", "keys"],
        opened=False,
    )
    assert "could not finish" not in spoken["reply"].lower()


def test_speak_web_job_unused_new_tab_is_not_success():
    """Speaking stuck while a blank New Tab sits unused is a fail — after type."""
    from app.jarvis.voice_ask import _speak_web_job

    unused = dict(GOOGLE_SORRY_UNUSED_TAB)
    unused["_opened_new_tab"] = True
    unused["_typed_query"] = web_search_query(LIVE_WEATHER)
    body = _speak_web_job(
        LIVE_WEATHER,
        unused,
        ["see_screen", "keys", "click", "type"],
        opened=False,
    )
    low = body["reply"].lower()
    assert "i'm not a robot" not in low
    assert "unusual traffic" not in low
    assert "146.148" not in low
    assert "i typed the search" not in low
    shown = dict(DDG_WEATHER)
    shown["_typed_query"] = web_search_query(LIVE_WEATHER)
    after = _speak_web_job(
        LIVE_WEATHER, shown, ["see_screen", "click", "type", "keys"], opened=False
    )
    after_low = after["reply"].lower()
    assert "amsterdam" in after_low or "weather" in after_low or "degrees" in after_low
    assert "could not finish" not in after_low


@pytest.mark.asyncio
async def test_voice_ask_sorry_unused_new_tab_look_speed_off(monkeypatch, tmp_path):
    """look_speed=off still focuses unused New Tab, types ddg. Hello stays fast."""
    from app.jarvis import settings_store
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.voice_ask import ask_abort_ms, run_voice_ask

    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    settings_store.save({"look_speed": "off"})
    assert settings_store.get_look_speed() == "off"
    assert ask_abort_ms("hello") == 12_000
    reset_last_look()
    remember_last_look(dict(GOOGLE_SORRY_UNUSED_TAB))

    clicks: list[tuple[int, int]] = []
    typed: list[str] = []
    keys: list[str] = []
    looks = [
        dict(GOOGLE_SORRY_UNUSED_TAB),
        dict(GOOGLE_SORRY_UNUSED_TAB),
        dict(GOOGLE_SORRY_UNUSED_TAB),
        dict(GOOGLE_SORRY_UNUSED_TAB),
        dict(NEW_TAB_CHROME),
        dict(DDG_WEATHER),
    ]
    _patch_voice_ask_web(monkeypatch, looks, clicks=clicks, typed=typed, keys=keys)

    body = await run_voice_ask(LIVE_WEATHER)
    assert "run_app" not in body["tools_used"]
    assert "click" in body["tools_used"]
    assert "type" in body["tools_used"]
    assert "keys" in body["tools_used"]
    assert any(xy in NEW_TAB_FOCUS_CLICKS for xy in clicks)
    assert OMNIBOX_CLICK in clicks
    assert SEARCH_BOX_CLICK not in clicks
    _assert_alt_weather_typed(typed)
    low = body["reply"].lower()
    assert "could not finish" not in low
    assert "i'm not a robot" not in low
    assert "unusual traffic" not in low
    assert "146.148" not in low
    assert "amsterdam" in low or "weather" in low or "degrees" in low
    reset_last_look()
