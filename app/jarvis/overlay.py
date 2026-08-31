"""Dismiss Chrome / site overlays, then keep going.

Talk computer jobs die on the first Restore pages? bubble, cookie wall,
Genius sign-in modal, or Chromium --no-sandbox infobar. After every look,
click a dismiss control (X, No thanks, Cancel, Reject, Not now) and look
again. Never Sign in, never Restore pages unless they asked to sign in,
never buy / pay / checkout.

Uses look / click / type only. Not Playwright. Not Selenium.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal

from app.jarvis.serp import look_blob

OverlayKind = Literal["restore", "sandbox", "signin", "cookie"]

# jarvis-computer Xvfb is 1280x720. Chromium chrome occupies y≈0–110.
# Restore pages? X: right edge of the crash-restore infobar under the toolbar.
RESTORE_DISMISS_CLICK = (1248, 92)
# --no-sandbox / unsupported-flag infobar sits one row below Restore.
SANDBOX_DISMISS_CLICK = (1248, 148)
# Booking.com Genius / generic sign-in card X (centered modal, not the window).
SIGNIN_DISMISS_CLICK = (920, 170)
# Destination / search box once the modal is gone. Mid-page on 1280x720,
# never a footer pixel. Only used when vision names a search field and
# does not give coordinates.
SEARCH_BOX_CLICK = (640, 320)
# Chromium omnibox / address bar on 1280x720 (y≈0–110 chrome, not the page).
OMNIBOX_CLICK = (420, 52)
# Seconds between looks while the tab is Untitled / blank / loading.
# look_speed=off does not skip this. 0.4s is not a wait.
WEB_LOOK_PAUSE_S = 2.0
# After this many Untitled/blank looks, type the query in the omnibox.
BLANK_LOOKS_BEFORE_OMNIBOX = 3
# jarvis-computer Xvfb is 1280x720. y≥560 is the footer band.
_FOOTER_Y = 560

_XY_RE = re.compile(r"\((\d{2,4})\s*,\s*(\d{2,4})\)")

_RESTORE_RE = re.compile(
    r"("
    r"restore pages|"
    r"restore popup|"
    r"restore[- ]pages|"
    r"didn['’]?t shut down correctly|"
    r"chrome didn['’]?t shut down|"
    r"sayfalar geri|"
    r"\brestore\b.{0,24}\b(pages|tabs|session)\b"
    r")",
    re.I,
)
_SANDBOX_RE = re.compile(
    r"("
    r"--no-sandbox|"
    r"no-sandbox|"
    r"unsupported command-line flag|"
    r"stability and security will suffer|"
    r"you are using an unsupported"
    r")",
    re.I,
)
_SIGNIN_RE = re.compile(
    r"("
    r"sign in, save money|"
    r"genius|"
    r"sign[\s-]?in (?:modal|dialog|popup|overlay|banner)|"
    r"login (?:modal|dialog|popup|overlay)|"
    r"save money by signing"
    r")",
    re.I,
)
_COOKIE_RE = re.compile(
    r"("
    r"accept(?:\s+all)?(?:\s+(?:and\s+)?continue)?|"
    r"i\s+agree|"
    r"agree\s+and\s+continue|"
    r"before you continue|"
    r"cookie\s+(?:banner|modal|consent|wall|notice)|"
    r"consent\s+(?:banner|modal|overlay)|"
    r"reject(?:\s+all)?(?:\s+cookies)?|"
    r"accept\s+(?:all\s+)?cookies"
    r")",
    re.I,
)
_EMPTY_DESKTOP_RE = re.compile(
    r"("
    r"\bturquoise\b|"
    r"\bteal\b.{0,48}\b(desktop|background|wallpaper|icons?)\b|"
    r"\b(desktop|background|wallpaper).{0,24}\bteal\b|"
    r"desktop\s+background|"
    r"wallpaper|"
    r"screenshot of (?:the )?(?:desktop|background)|"
    r"empty desktop|"
    r"plain (?:teal|turquoise|blue) (?:background|desktop)|"
    r"desktop icons|"
    r"recycle bin"
    r")",
    re.I,
)
_PAY_RE = re.compile(
    r"("
    r"\b(buy|pay|checkout|purchase)\b|"
    r"add to cart|"
    r"book now|"
    r"complete (?:the )?booking|"
    r"place order|"
    r"pay now"
    r")",
    re.I,
)
_DISMISS_LABEL_RE = re.compile(
    r"("
    r"\bno thanks\b|"
    r"\bnot now\b|"
    r"\bcancel\b|"
    r"\breject(?:\s+all)?(?:\s+cookies)?\b|"
    r"\bdismiss\b|"
    r"\bclose\b|"
    r"(?:the\s+)?(?:x|×)\s+(?:button|control)?"
    r")",
    re.I,
)
_DISMISS_XY_RE = re.compile(
    r"(?:"
    r"no thanks|not now|cancel|reject(?:\s+all)?(?:\s+cookies)?|"
    r"dismiss|close|(?:the\s+)?(?:x|×)"
    r")"
    r"(?:\s+button|\s+control)?"
    r"\s+(?:at\s+)?\((\d{2,4})\s*,\s*(\d{2,4})\)",
    re.I,
)
_COOKIE_ACCEPT_XY_RE = re.compile(
    r"(?:accept(?:\s+all)?|i\s+agree|agree|continue)"
    r"(?:\s+button|\s+and\s+continue)?"
    r"\s+(?:at\s+)?\((\d{2,4})\s*,\s*(\d{2,4})\)",
    re.I,
)
_NEVER_CLICK_RE = re.compile(
    r"("
    r"\bsign[\s-]?in\b|"
    r"\blog[\s-]?in\b|"
    r"\bregister\b|"
    r"\brestore pages\b|"
    r"\bbuy\b|"
    r"\bpay\b|"
    r"\bcheckout\b|"
    r"book now|"
    r"add to cart"
    r")",
    re.I,
)
_ASKED_SIGN_IN_RE = re.compile(
    r"\b(sign[\s-]?in|log[\s-]?in|log into)\b",
    re.I,
)
_SEARCH_FIELD_RE = re.compile(
    r"("
    r"search box|"
    r"search field|"
    r"search bar|"
    r"search form|"
    r"destination|"
    r"where are you going|"
    r"where to|"
    r"find your next stay|"
    r"omnibox|"
    r"empty search|"
    r"type (?:your )?(?:destination|city|query|place)"
    r")",
    re.I,
)
# Coords that belong to the search / destination field, not the first
# (x,y) on the page (that is often a footer link).
_SEARCH_XY_AFTER_RE = re.compile(
    r"(?:"
    r"search box|search field|search bar|destination|where are you going|"
    r"omnibox|empty search|type (?:your )?(?:destination|city|query|place)"
    r")"
    r"(?:[^.\n()]{0,80})?"
    r"\((\d{2,4})\s*,\s*(\d{2,4})\)",
    re.I,
)
_SEARCH_XY_BEFORE_RE = re.compile(
    r"\((\d{2,4})\s*,\s*(\d{2,4})\)"
    r"(?:[^.\n()]{0,40})?"
    r"(?:"
    r"search box|search field|search bar|destination|where are you going|omnibox"
    r")",
    re.I,
)
_EMPTY_DEST_RE = re.compile(
    r"search box is empty|destination is empty|where are you going|"
    r"empty destination|type your destination",
    re.I,
)
_HOTEL_RESULT_RE = re.compile(
    r"("
    r"\bhotels? in\b|"
    r"\bsearch results\b|"
    r"\bfrom \d+\s*(?:eur|usd|gbp|€|\$)\b|"
    r"\bhotel [A-Za-z]|"
    r"\bprices? from\b"
    r")",
    re.I,
)
# "hotel" on the Booking.com homepage is marketing, not a typed query.
_GENERIC_QUERY_WORD_RE = re.compile(
    r"^(?:hotels?|search|chrome|booking|find|stays?|rooms?|flights?|"
    r"homes?|apartments?|city|cities|destination|query|central|"
    r"using|use|please|the|and|for|in|a|an|to)$",
    re.I,
)
_FOOTER_RE = re.compile(
    r"("
    r"\bfooter\b|"
    r"all rights reserved|"
    r"copyright|"
    r"privacy(?:\s+policy)?|"
    r"terms of (?:service|use)|"
    r"cookie statement|"
    r"destinations we love|"
    r"scrolled to the (?:bottom|footer)"
    r")",
    re.I,
)
# A painted window title is not enough. Vision of a white / empty / spinner
# tab is not a loaded page — wait and look again before typing.
_LOADING_OR_BLANK_RE = re.compile(
    r"("
    r"about:blank|"
    r"\buntitled\b|"
    r"\bnew tab\b|"
    r"page mostly blank|"
    r"mostly blank|"
    r"still loading|"
    r"page is (?:still )?(?:blank|empty|loading)|"
    r"blank page|"
    r"empty page|"
    r"white (?:page|screen)|"
    r"nothing (?:has )?loaded|"
    r"\bspinner\b|"
    r"loading (?:the )?(?:page|site|document)"
    r")",
    re.I,
)


@dataclass(frozen=True)
class OverlayPlan:
    """One look/click/type step. Never a Sign in / Restore / Pay click."""

    kind: OverlayKind
    click: tuple[int, int] | None
    keys: str = "escape"
    reason: str = ""


def user_asked_sign_in(goal: str) -> bool:
    return bool(_ASKED_SIGN_IN_RE.search(goal or ""))


def look_is_empty_desktop(looked: dict[str, Any] | None) -> bool:
    """True when vision is the teal wallpaper, not a loaded page."""
    blob = look_blob(looked)
    if not blob.strip():
        return False
    title = str((looked or {}).get("title") or "").strip()
    if title and not re.search(
        r"chrome|chromium|desktop|xfce|untitled", title, re.I
    ):
        return False
    return bool(_EMPTY_DESKTOP_RE.search(blob))


def look_is_pay_control(text: str) -> bool:
    return bool(_PAY_RE.search(text or ""))


def _title_is_restore(looked: dict[str, Any] | None) -> bool:
    title = str((looked or {}).get("title") or "")
    try:
        from app.jarvis.desktop import is_dismissible_chrome_dialog

        if is_dismissible_chrome_dialog(title):
            return True
    except Exception:
        pass
    return bool(_RESTORE_RE.search(title))


def overlay_kind(
    looked: dict[str, Any] | None,
    *,
    goal: str = "",
) -> OverlayKind | None:
    """Highest-priority blocking overlay on this look, or None."""
    item = looked or {}
    blob = look_blob(item)
    if _title_is_restore(item) or _RESTORE_RE.search(blob):
        return "restore"
    if _SANDBOX_RE.search(blob):
        return "sandbox"
    if _SIGNIN_RE.search(blob) and not user_asked_sign_in(goal):
        return "signin"
    if _COOKIE_RE.search(blob):
        return "cookie"
    return None


def look_has_blocking_overlay(
    looked: dict[str, Any] | None,
    *,
    goal: str = "",
) -> bool:
    return overlay_kind(looked, goal=goal) is not None


def _xy_from_blob(blob: str) -> tuple[int, int] | None:
    match = _DISMISS_XY_RE.search(blob or "")
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _cookie_accept_xy(blob: str) -> tuple[int, int] | None:
    match = _COOKIE_ACCEPT_XY_RE.search(blob or "")
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _named_click_from_look(looked: dict[str, Any] | None) -> tuple[int, int] | None:
    item = looked or {}
    for key_x, key_y in (("click_x", "click_y"), ("x", "y")):
        if item.get(key_x) is None or item.get(key_y) is None:
            continue
        try:
            return int(item[key_x]), int(item[key_y])
        except (TypeError, ValueError):
            continue
    match = _XY_RE.search(look_blob(item))
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def overlay_dismiss_plan(
    looked: dict[str, Any] | None,
    *,
    goal: str = "",
    kind: OverlayKind | None = None,
) -> OverlayPlan | None:
    """Click X / No thanks / Cancel / Reject. Never Sign in / Restore / Pay."""
    found = kind or overlay_kind(looked, goal=goal)
    if found is None:
        return None
    blob = look_blob(looked)
    if found != "cookie" and look_is_pay_control(blob) and not _DISMISS_LABEL_RE.search(
        blob
    ):
        # A pay wall is not a dismissable cookie — do not click Buy.
        if found == "signin" and user_asked_sign_in(goal):
            return None
    named_dismiss = _xy_from_blob(blob)
    if found == "restore":
        return OverlayPlan(
            kind="restore",
            click=named_dismiss or RESTORE_DISMISS_CLICK,
            keys="escape",
            reason="Restore pages? — click the X, not Restore.",
        )
    if found == "sandbox":
        return OverlayPlan(
            kind="sandbox",
            click=named_dismiss or SANDBOX_DISMISS_CLICK,
            keys="escape",
            reason="Chromium --no-sandbox banner — click the X.",
        )
    if found == "signin":
        if user_asked_sign_in(goal):
            return None
        return OverlayPlan(
            kind="signin",
            click=named_dismiss or SIGNIN_DISMISS_CLICK,
            keys="escape",
            reason="Sign-in / Genius modal — click X / No thanks, never Sign in.",
        )
    # Cookie: prefer Reject / No thanks coords. Accept only when that is the
    # named control and no dismiss label is present (news walls).
    click = named_dismiss
    if click is None and not _DISMISS_LABEL_RE.search(blob):
        click = _cookie_accept_xy(blob) or _named_click_from_look(looked)
    return OverlayPlan(
        kind="cookie",
        click=click,
        keys="escape" if click is None or _DISMISS_LABEL_RE.search(blob) else "enter",
        reason="Cookie / consent — Reject or the named dismiss, never Sign in.",
    )


def _xy_in_page(x: int, y: int) -> bool:
    return 0 <= x <= 1280 and 0 <= y < _FOOTER_Y


def _search_field_xy(blob: str) -> tuple[int, int] | None:
    """Coords vision tied to the search / destination field. Not the footer."""
    for rx in (_SEARCH_XY_AFTER_RE, _SEARCH_XY_BEFORE_RE):
        match = rx.search(blob or "")
        if not match:
            continue
        x, y = int(match.group(1)), int(match.group(2))
        if _xy_in_page(x, y):
            return x, y
    return None


def look_is_footer(looked: dict[str, Any] | None) -> bool:
    """True when vision is the page footer, not the destination field."""
    blob = look_blob(looked)
    if _search_field_xy(blob):
        return False
    return bool(_FOOTER_RE.search(blob))


def look_has_hotel_results(looked: dict[str, Any] | None) -> bool:
    """True when vision shows hotel search results, not the homepage form."""
    blob = look_blob(looked)
    return bool(_HOTEL_RESULT_RE.search(blob)) and not look_is_footer(looked)


def look_is_empty_destination(looked: dict[str, Any] | None) -> bool:
    return bool(_EMPTY_DEST_RE.search(look_blob(looked)))


def look_is_loading_or_blank(looked: dict[str, Any] | None) -> bool:
    """True when the tab is still empty / loading — not ready to type.

    Off look_speed does not change this. A real site title with a blank
    or spinner caption is still not done.
    """
    item = looked or {}
    if item.get("page_ready") is False:
        return True
    blob = look_blob(item)
    title = str(item.get("title") or "")
    desc = str(item.get("vision_description") or "").strip()
    if _LOADING_OR_BLANK_RE.search(title) or _LOADING_OR_BLANK_RE.search(blob):
        return True
    if look_is_empty_desktop(item):
        return True
    if item.get("ok") and not desc and not title.strip():
        return True
    return False


def look_is_page_ready(looked: dict[str, Any] | None) -> bool:
    """True when the window is a loaded page, not wallpaper / blank / loading."""
    if look_is_loading_or_blank(looked) or look_is_empty_desktop(looked):
        return False
    return look_is_web_page(looked) or search_box_point(looked) is not None


def look_is_web_page(looked: dict[str, Any] | None) -> bool:
    """True for a loaded site, not wallpaper, footer, or a blank/loading tab."""
    if look_is_empty_desktop(looked) or look_is_footer(looked):
        return False
    if look_is_loading_or_blank(looked):
        return False
    item = looked or {}
    url = str(item.get("url") or "")
    if url and re.search(r"https?://", url, re.I):
        return True
    title = str(item.get("title") or "").strip()
    if title and not re.search(
        r"^(chrome|google chrome|chromium|desktop|xfce|untitled)\b",
        title,
        re.I,
    ):
        return True
    blob = look_blob(item)
    return bool(_SEARCH_FIELD_RE.search(blob))


def distinctive_query_tokens(query: str) -> list[str]:
    """Rome / grinder — not the generic 'hotel' on a booking homepage."""
    return [
        part
        for part in (query or "").split()
        if len(part) >= 3 and not _GENERIC_QUERY_WORD_RE.match(part)
    ]


def query_visible_on_look(looked: dict[str, Any] | None, query: str) -> bool:
    tokens = distinctive_query_tokens(query)
    if not tokens:
        return False
    blob = look_blob(looked).lower()
    return all(token.lower() in blob for token in tokens)


def needs_web_query(
    asked: str, looked: dict[str, Any] | None, query: str
) -> bool:
    """True until the query is typed or results are on screen.

    A homepage that only mentions a generic word from the ask is not done.
    A blank / loading look is not done.
    """
    if not (query or "").strip():
        return False
    if look_has_hotel_results(looked):
        return False
    if look_is_loading_or_blank(looked) or look_is_empty_desktop(looked):
        return True
    if look_has_blocking_overlay(looked, goal=asked):
        return True
    if look_is_empty_destination(looked) or look_is_footer(looked):
        return True
    if query_visible_on_look(looked, query):
        return False
    return True


def search_box_point(looked: dict[str, Any] | None) -> tuple[int, int] | None:
    """Where to type the destination. None if the field is not on screen.

    Prefer the (x,y) vision names next to the search / destination field.
    Do not click a hardcoded mid-page pixel when the look is the footer —
    on a scrolled page that pixel is copyright / legal links.
    A Booking.com homepage that never says "search box" still has a field —
    use SEARCH_BOX_CLICK after Home, never on the footer or wallpaper.
    """
    blob = look_blob(looked)
    named = _search_field_xy(blob)
    if named:
        return named
    click_xy = _named_click_from_look(looked)
    if (
        click_xy
        and _SEARCH_FIELD_RE.search(blob)
        and _xy_in_page(click_xy[0], click_xy[1])
        and not look_is_footer(looked)
    ):
        return click_xy
    if look_is_footer(looked) or look_is_empty_desktop(looked):
        return None
    if look_is_loading_or_blank(looked):
        return None
    if _SEARCH_FIELD_RE.search(blob) or look_is_web_page(looked):
        return SEARCH_BOX_CLICK
    return None


def _in_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _pause_after_web_act() -> None:
    if not _in_pytest():
        time.sleep(0.4)


def web_look_pause_s() -> float:
    """Seconds to sleep between looks while the page is still opening.

    look_speed=off does not skip this. Tests skip the sleep so they stay fast.
    """
    if _in_pytest():
        return 0.0
    return float(WEB_LOOK_PAUSE_S)


def _pause_for_page_load() -> None:
    wait = web_look_pause_s()
    if wait > 0:
        time.sleep(wait)


def _deadline_passed(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= float(deadline)


def _type_query_at(
    xy: tuple[int, int],
    query: str,
    current: dict[str, Any],
    *,
    click: Callable[..., dict[str, Any]],
    type_text: Callable[..., dict[str, Any]],
    keys: Callable[..., dict[str, Any]],
    look_again: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Click xy, type the query, Enter. Returns (look, typed)."""
    clicked = click(x=xy[0], y=xy[1])
    if not clicked or not clicked.get("ok"):
        return current, False
    _pause_after_web_act()
    typed = type_text(text=query)
    ok = bool(typed and typed.get("ok"))
    if ok:
        keys(combo="enter")
        current["_typed_query"] = query
    _pause_after_web_act()
    nxt = look_again() or current
    if ok:
        nxt["_typed_query"] = query
    return nxt, ok


def continue_web_search(
    looked: dict[str, Any] | None,
    *,
    goal: str,
    click: Callable[..., dict[str, Any]],
    type_text: Callable[..., dict[str, Any]],
    keys: Callable[..., dict[str, Any]],
    look_again: Callable[[], dict[str, Any]],
    scroll: Callable[..., dict[str, Any]] | None = None,
    max_rounds: int = 3,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Wait until the page is ready, click the field, type, Enter. Never pay.

    Product path after overlays. look_speed=off does not skip this.
    Sleep seconds between looks (not 0.4s) until a loaded page or ``deadline``.
    A blank / Untitled / loading look is not done — look again. After a few
    still-blank looks, type the query into the Chromium omnibox. Never return
    without type when a query is needed. A homepage that never says
    "search box" still types. Footer looks Home first — never (640, 320)
    on copyright.
    """
    query = web_search_query(goal)
    current = dict(looked or {})
    blob = look_blob(current)
    if look_is_pay_control(blob) and "hotel" not in blob.lower():
        return current
    if not (query or "").strip():
        return current
    typed_query = bool(current.get("_typed_query"))
    blank_looks = 0
    if deadline is not None:
        limit = 64
    else:
        limit = max(int(max_rounds), BLANK_LOOKS_BEFORE_OMNIBOX)

    def _mark(item: dict[str, Any]) -> dict[str, Any]:
        if typed_query:
            item["_typed_query"] = query
        return item

    for i in range(limit):
        blob = look_blob(current)
        if look_is_pay_control(blob) and "hotel" not in blob.lower():
            return _mark(current)
        if look_has_hotel_results(current) or not needs_web_query(
            goal, current, query
        ):
            return _mark(current)
        if typed_query:
            if _deadline_passed(deadline) or i >= BLANK_LOOKS_BEFORE_OMNIBOX:
                return _mark(current)
            _pause_for_page_load()
            current = _mark(look_again() or current)
            continue

        if look_is_footer(current):
            keys(combo="home")
            _pause_after_web_act()
            current = look_again() or current
            if search_box_point(current) is None and (
                look_is_footer(current) or look_is_empty_destination(current)
            ):
                if scroll is not None:
                    scroll(dy=5)
                    _pause_after_web_act()
                    current = look_again() or current
            xy = search_box_point(current)
            if xy is not None:
                current, typed_query = _type_query_at(
                    xy,
                    query,
                    current,
                    click=click,
                    type_text=type_text,
                    keys=keys,
                    look_again=look_again,
                )
            continue

        xy = search_box_point(current)
        if xy is not None:
            current, typed_query = _type_query_at(
                xy,
                query,
                current,
                click=click,
                type_text=type_text,
                keys=keys,
                look_again=look_again,
            )
            continue

        blank_looks += 1
        last = i >= limit - 1
        if (
            blank_looks >= BLANK_LOOKS_BEFORE_OMNIBOX
            or _deadline_passed(deadline)
            or last
        ):
            current, typed_query = _type_query_at(
                OMNIBOX_CLICK,
                query,
                current,
                click=click,
                type_text=type_text,
                keys=keys,
                look_again=look_again,
            )
            return _mark(current)
        _pause_for_page_load()
        current = look_again() or current

    if not typed_query:
        current, typed_query = _type_query_at(
            OMNIBOX_CLICK,
            query,
            current,
            click=click,
            type_text=type_text,
            keys=keys,
            look_again=look_again,
        )
    return _mark(current)


def dismiss_blocking_overlays(
    looked: dict[str, Any] | None,
    *,
    goal: str = "",
    click: Callable[..., dict[str, Any]],
    keys: Callable[..., dict[str, Any]],
    look_again: Callable[[], dict[str, Any]],
    max_rounds: int = 3,
) -> dict[str, Any]:
    """Look → dismiss → look, up to max_rounds. Product path for Talk/Chrome."""
    current = dict(looked or {})
    for _ in range(max(1, int(max_rounds))):
        plan = overlay_dismiss_plan(current, goal=goal)
        if plan is None:
            return current
        if plan.click is not None:
            click(x=plan.click[0], y=plan.click[1])
        if plan.keys:
            keys(combo=plan.keys)
        current = look_again() or current
    return current


def web_search_query(asked: str) -> str:
    """Words to type after overlays: 'hotel in central Rome', not the URL."""
    raw = (asked or "").strip()
    raw = re.sub(
        r"\b(please|can you|could you|on (?:the|your) (?:screen|computer)|"
        r"using chrome|use chrome|in chrome|with chrome)\b",
        " ",
        raw,
        flags=re.I,
    )
    raw = re.sub(
        r"https?://[^\s]+|[a-z0-9.-]+\.(?:com|nl|de|org|net|io|co|uk|edu|app)\b",
        " ",
        raw,
        flags=re.I,
    )
    raw = re.sub(
        r"\b(go to|goto|open|show|visit|browse|launch|find(?:\s+me)?|"
        r"search(?:\s+for)?|look\s+up|and)\b",
        " ",
        raw,
        flags=re.I,
    )
    raw = re.sub(r"\s+", " ", raw).strip(" .,!?")
    raw = re.sub(r"^(?:a|an|the)\s+", "", raw, flags=re.I)
    return raw or (asked or "").strip()
