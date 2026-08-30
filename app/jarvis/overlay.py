"""Dismiss Chrome / site overlays, then keep going.

Talk computer jobs die on the first Restore pages? bubble, cookie wall,
Genius sign-in modal, or Chromium --no-sandbox infobar. After every look,
click a dismiss control (X, No thanks, Cancel, Reject, Not now) and look
again. Never Sign in, never Restore pages unless they asked to sign in,
never buy / pay / checkout.

Uses look / click / type only. Not Playwright. Not Selenium.
"""

from __future__ import annotations

import re
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
    r"desktop\s+background|"
    r"wallpaper|"
    r"screenshot of (?:the )?(?:desktop|background)|"
    r"empty desktop|"
    r"plain (?:teal|turquoise|blue) (?:background|desktop)|"
    r"desktop icons"
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
    r"destination|"
    r"where are you going|"
    r"omnibox|"
    r"empty search|"
    r"type (?:your )?(?:destination|city|query)"
    r")",
    re.I,
)
# Coords that belong to the search / destination field, not the first
# (x,y) on the page (that is often a footer link).
_SEARCH_XY_AFTER_RE = re.compile(
    r"(?:"
    r"search box|search field|destination|where are you going|"
    r"omnibox|empty search|type (?:your )?(?:destination|city|query)"
    r")"
    r"(?:[^.\n()]{0,80})?"
    r"\((\d{2,4})\s*,\s*(\d{2,4})\)",
    re.I,
)
_SEARCH_XY_BEFORE_RE = re.compile(
    r"\((\d{2,4})\s*,\s*(\d{2,4})\)"
    r"(?:[^.\n()]{0,40})?"
    r"(?:"
    r"search box|search field|destination|where are you going|omnibox"
    r")",
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


def search_box_point(looked: dict[str, Any] | None) -> tuple[int, int] | None:
    """Where to type the destination. None if the field is not on screen.

    Prefer the (x,y) vision names next to the search / destination field.
    Do not click a hardcoded mid-page pixel when the look is the footer —
    on a scrolled page that pixel is copyright / legal links.
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
    if look_is_footer(looked):
        return None
    if _SEARCH_FIELD_RE.search(blob):
        return SEARCH_BOX_CLICK
    return None


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
