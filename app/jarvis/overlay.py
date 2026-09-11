"""Dismiss Chrome / site overlays, then keep going.

Talk computer jobs die on the first Restore pages? bubble, cookie wall,
Genius sign-in modal, Chromium --no-sandbox infobar, or Memory Saver
toast. After every look, click a dismiss control (X, No thanks, Cancel,
Reject, Not now) and look again. Never Sign in, never Restore pages
unless they asked to sign in, never buy / pay / checkout. Never Turn on
Memory Saver. A sorry / captcha / I'm-not-a-robot look is
not the answer — Ctrl+T once, click until New Tab is focused, then type
THIS ask on DuckDuckGo, Bing, or a weather site. Never type into the
sorry tab. Never click I'm not a robot.

Uses look / click / type only. Not Playwright. Not Selenium.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Literal
from urllib.parse import quote_plus

from app.jarvis.serp import look_blob

OverlayKind = Literal["restore", "sandbox", "signin", "cookie", "memory_saver"]

# jarvis-computer Xvfb is 1280x720. Chromium chrome occupies y≈0–110.
# Restore pages? X: right edge of the crash-restore infobar under the toolbar.
RESTORE_DISMISS_CLICK = (1248, 92)
# --no-sandbox / unsupported-flag infobar sits one row below Restore.
SANDBOX_DISMISS_CLICK = (1248, 148)
# Booking.com Genius / generic sign-in card X (centered modal, not the window).
SIGNIN_DISMISS_CLICK = (920, 170)
# Destination / search box once the modal is gone. Mid-page on 1280x720,
# never a footer pixel. Only used when vision names a search field and
# does not give coordinates. On Booking's homepage this hits the Genius
# airplane — use BOOKING_* clicks for that form.
SEARCH_BOX_CLICK = (640, 320)
# Booking.com homepage search widget on 1280x720. The white destination /
# dates / Search bar sits below the Genius hero, not at (640, 320).
BOOKING_DEST_CLICK = (220, 500)
BOOKING_DATES_CLICK = (560, 500)
BOOKING_SEARCH_CLICK = (1148, 500)
# Persistent hero / failed dismiss: stop clicking X and fill the form.
OVERLAY_DISMISS_MAX = 2
# Coolblue 2026-09-11 CMP on jarvis-computer 1280x720 (live SHA 7cd1c7c).
# Centered white "COOKIES. Smaakmakers." card. Green Alles accepteren
# sits bottom-right of the card, left of Zelf instellen. Weigeren is
# absent on this layout; other CMP variants put Reject to the left.
# Never click Zelf instellen (preferences). Escape does not close it.
COOLBLUE_COOKIE_ACCEPT_CLICK = (888, 520)
COOLBLUE_COOKIE_REJECT_CLICK = (720, 520)
COOLBLUE_COOKIE_DISMISS_CLICKS: tuple[tuple[int, int], ...] = (
    COOLBLUE_COOKIE_ACCEPT_CLICK,
    COOLBLUE_COOKIE_REJECT_CLICK,
)
# Coolblue / amazon.nl / bol.com cart job on 1280×720 after cookies.
# Header search — not mid-page categories. Product tiles on zoeken.
# PDP In winkelwagen is the right column. Basket icon is top-right.
# Never the cookie-man / footer / checkout.
COOLBLUE_SEARCH_CLICK = (520, 72)
COOLBLUE_PRODUCT_CLICKS: tuple[tuple[int, int], ...] = (
    (320, 380),
    (720, 380),
)
COOLBLUE_ADD_BASKET_CLICK = (1040, 400)
COOLBLUE_BASKET_CLICK = (1188, 72)
# Two different in-stock electronics. Never the coaching essay / "in-stock".
CART_PRODUCT_QUERIES: tuple[str, ...] = ("usb-c kabel", "hdmi kabel")
CART_ADD_TARGET = 2
# searchresults.html briefly loaded then bounced to index: one dated
# Booking reopen, then immediately the hotel alt host. After that alt
# run_app, keep looking on that tab — do not switch back to Booking.
# Google Travel /search and /hotels both 302 to /travel/unsupported
# (blank body) on jarvis-computer (live 2026-09-11 SHA 35d5797). The
# URL that paints names+prices from this IP is DuckDuckGo HTML
# (`hotel_alt_fallback_url`). Try /travel/hotels first; if the look
# stays blank, open that DDG list. More Booking reopens are not used
# after the alt. Do not idle on the homepage.
HOTEL_SEARCH_REOPEN_MAX = 4
HOTEL_SEARCH_ALT_MAX = 1
HOTEL_BOUNCE_BOOKING_BEFORE_ALT = 1
HOTEL_ALT_LOOKS_MAX = 8
HOTEL_ALT_BLANK_BEFORE_FALLBACK = 2
# Chromium "Make Chromium faster" / Memory Saver toast (top-right on
# 1280x720). No thanks — never Turn on. Steals omnibox focus.
MEMORY_SAVER_DISMISS_CLICK = (1000, 208)
MEMORY_SAVER_DISMISS_MAX = 2
# Chromium omnibox / address bar on 1280x720 (y≈0–110 chrome, not the page).
OMNIBOX_CLICK = (420, 52)
# Newest tab on the tab strip (above the omnibox). keys(ctrl+t) often opens
# a New Tab without focusing it — click until the title is New Tab / Untitled.
NEW_TAB_CLICK = (720, 16)
NEW_TAB_FOCUS_CLICKS = ((560, 16), (720, 16), (880, 16))
# Seconds between looks while the tab is Untitled / blank / loading.
# look_speed=off does not skip this. 0.4s is not a wait.
WEB_LOOK_PAUSE_S = 2.0
# After this many Untitled/blank looks, type the query in the omnibox.
BLANK_LOOKS_BEFORE_OMNIBOX = 3
# First captcha / New Tab focus miss: keep clicking at least this long.
# look_speed=off does not skip. Tests skip the wall clock.
CAPTCHA_FOCUS_MIN_S = 30.0
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
# Chromium Memory Saver / "Make Chromium faster" toast. Not a site modal.
_MEMORY_SAVER_RE = re.compile(
    r"("
    r"make chromium faster|"
    r"make chrome faster|"
    r"memory[\s-]?saver|"
    r"memory[\s-]?saving|"
    r"frees up memory from inactive tabs|"
    r"free up memory from inactive"
    r")",
    re.I,
)
# Live Booking Genius OCR often concatenates the heading
# ("Signin, savemoney") and misses spaces. "Genius" on a priced
# hotel card is a loyalty badge, not this modal.
_SIGNIN_RE = re.compile(
    r"("
    r"sign[\s-]?in,?\s*save[\s-]?money|"
    r"signin,?\s*savemoney|"
    r"sign[\s-]?in\s+to\s+save|"
    r"save\s*money\s+by\s+signing|"
    r"\bgenius\b.{0,96}(?:sign[\s-]?in|save\s*money|savemoney|modal|dialog|popup|membership)|"
    r"(?:sign[\s-]?in|save\s*money|savemoney|modal|dialog|popup|membership).{0,96}\bgenius\b|"
    r"sign[\s-]?in (?:modal|dialog|popup|overlay|banner|card)|"
    r"login (?:modal|dialog|popup|overlay)|"
    r"sign[\s-]?in.{0,40}save\s*\d+\s*%|"
    r"free(?:\s+\w+)?\s+booking\.com\s+membership"
    r")",
    re.I,
)
# Modal / dialog language — Genius badges on a result list do not have this.
_SIGNIN_MODAL_RE = re.compile(
    r"("
    r"\b(?:modal|dialog|popup|overlay|banner|card)\b|"
    r"sign[\s-]?in,?\s*save[\s-]?money|"
    r"signin,?\s*savemoney|"
    r"sign[\s-]?in\s+to\s+save|"
    r"sign[\s-]?in or register|"
    r"membership|"
    r"(?:the\s+)?(?:x|×)\s+(?:button|control)"
    r")",
    re.I,
)
# A covering dialog on Booking with no readable prices — dismiss, do not finish.
_COVERING_MODAL_RE = re.compile(
    r"("
    r"(?:modal|dialog|popup|overlay)\s+(?:covers?|covering|blocks?|blocking)|"
    r"(?:covers?|covering|blocks?|blocking).{0,48}(?:modal|dialog|popup|overlay)|"
    r"sign[\s-]?in (?:modal|dialog|popup|overlay|banner|card)"
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
    r"accept\s+(?:all\s+)?cookies|"
    r"alles\s*accepteren|"
    r"alles\s*weigeren|"
    r"cookievoorkeuren|"
    r"\bweigeren\b|"
    r"\btoestaan\b|"
    r"smaakmakers|"
    r"zelf\s*instellen"
    r")",
    re.I,
)
# Coolblue "COOKIES. Smaakmakers." card — with or without button coords.
_COOLBLUE_COOKIE_RE = re.compile(
    r"("
    r"smaakmakers|"
    r"zelf\s*instellen|"
    r"alles\s*accepteren|"
    r"alles\s*weigeren|"
    r"\bweigeren\b|"
    r"cookievoorkeuren|"
    r"(?<![+\w])cookies?\s*[.:]"
    r")",
    re.I,
)
# "No cookie modal" / "cookie modal gone" is a cleared homepage, not CMP.
_COOKIE_ABSENT_RE = re.compile(
    r"("
    r"(?:^|[.\s])(?:no|without|not a)\s+"
    r"cookie(?:s)?(?:\s+(?:banner|modal|consent|wall|notice|card))?|"
    r"cookie(?:s)?(?:\s+(?:banner|modal|consent|wall|notice|card))?\s+"
    r"(?:gone|cleared|dismissed|closed|accepted)"
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
# Real payment UI only. "Add to cart" / a shop checkout button is the
# cart job — not a reason to abort. Constraint phrases are stripped
# before this runs.
_PAY_RE = re.compile(
    r"("
    r"\bpay now\b|"
    r"place (?:the )?order|"
    r"complete (?:the )?(?:booking|purchase|payment|order)|"
    r"enter (?:your )?(?:card|credit card|payment)|"
    r"book now|"
    r"\bproceed to (?:checkout|payment)\b"
    r")",
    re.I,
)
_ASK_PAY_RE = re.compile(
    r"("
    r"\b(?:please\s+)?(?:check\s*out|checkout)\b|"
    r"\b(?:please\s+)?(?:pay|purchase)\b|"
    r"enter (?:your )?(?:card|credit card)|"
    r"complete (?:the )?(?:checkout|payment|purchase|order)|"
    r"place (?:the )?order|"
    r"pay (?:now|for|with)|"
    r"\bbuy (?:it|this|now|with)\b"
    r")",
    re.I,
)
_CART_JOB_RE = re.compile(
    r"("
    r"\badd\b.{0,80}\b(?:cart|basket)\b|"
    r"\bto\s+(?:the\s+)?(?:cart|basket)\b|"
    r"\bin-stock\b|"
    r"\bcart confirmation\b"
    r")",
    re.I,
)
_CART_PRICE_RE = re.compile(
    r"("
    r"€\s*\d|"
    r"\b\d+[.,]?\d*\s*(?:euro|eur|€)\b|"
    r"\b(?:euro|eur)\s*\d+"
    r")",
    re.I,
)
_CART_CONFIRM_RE = re.compile(
    r"("
    r"\btwo items\b|"
    r"\b(?:\d+|two|2)\s+items?\s+in\s+(?:the\s+)?(?:cart|basket|winkelwagen|mandje)\b|"
    r"\bin (?:the |your )?(?:cart|basket)\b|"
    r"\bin (?:de )?(?:winkelwagen|mandje)\b"
    r")",
    re.I,
)
_CART_EMPTY_RE = re.compile(
    r"("
    r"\bno (?:items? )?in (?:the )?(?:cart|basket|winkelwagen|mandje)\b|"
    r"\bno basket\b|"
    r"\bbasket (?:is )?empty\b|"
    r"\bempty basket\b|"
    r"\bnot in the basket\b|"
    r"\bbasket yet\b|"
    r"\b0 items?\s+in\s+(?:the\s+)?(?:cart|basket)\b"
    r")",
    re.I,
)
_SHOP_HOME_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:coolblue\.nl|amazon\.nl|bol\.com)/?(?:\?|#|$)",
    re.I,
)
_SHOP_HOME_RE = re.compile(
    r"("
    r"\bhomepage\b|"
    r"\bnieuwsbrief\b|"
    r"\bnewsletter\b|"
    r"\bklantenservice\b|"
    r"\bcategorie(?:ën|en)?\b|"
    r"\bcategories\b|"
    r"zoeken naar"
    r")",
    re.I,
)
_SHOP_SEARCH_URL_RE = re.compile(
    r"("
    r"coolblue\.nl/zoeken|"
    r"amazon\.nl/s\?|"
    r"bol\.com/.*/s(?:/|\?)|"
    r"[?&](?:query|k|searchtext)="
    r")",
    re.I,
)
_SHOP_SEARCH_RE = re.compile(
    r"("
    r"search results|"
    r"zoekresultaten|"
    r"product tiles|"
    r"results for"
    r")",
    re.I,
)
_SHOP_PDP_URL_RE = re.compile(
    r"("
    r"coolblue\.nl/product|"
    r"amazon\.nl/(?:dp|gp/product)/|"
    r"bol\.com/.*/p/"
    r")",
    re.I,
)
_SHOP_PDP_RE = re.compile(
    r"("
    r"\bproduct(?:pagina| page)\b|"
    r"in winkelwagen|"
    r"in mandje|"
    r"add to (?:the )?(?:cart|basket)"
    r")",
    re.I,
)
_SHOP_BASKET_URL_RE = re.compile(
    r"("
    r"coolblue\.nl/winkelwagen|"
    r"amazon\.nl/gp/cart|"
    r"bol\.com/.*/(?:basket|winkelwagen)"
    r")",
    re.I,
)
_ADD_BASKET_XY_RE = re.compile(
    r"(?:"
    r"in winkelwagen|in mandje|add to (?:the )?(?:cart|basket)"
    r")"
    r"(?:[^.\n()]{0,80})?"
    r"\((\d{2,4})\s*,\s*(\d{2,4})\)",
    re.I,
)
_PRODUCT_TILE_XY_RE = re.compile(
    r"(?:"
    r"first product|second product|product tile|product card|"
    r"search result"
    r")"
    r"(?:[^.\n()]{0,80})?"
    r"\((\d{2,4})\s*,\s*(\d{2,4})\)",
    re.I,
)
_BASKET_ICON_XY_RE = re.compile(
    r"(?:"
    r"winkelwagen|basket|cart"
    r")(?:\s+icon)?"
    r"(?:[^.\n()]{0,40})?"
    r"\((\d{2,4})\s*,\s*(\d{2,4})\)",
    re.I,
)
_CART_FILLER_RE = re.compile(
    r"\b("
    r"add|two|products?|items?|basket|cart|only|confirm|"
    r"they|are|in-stock|stock|winkelwagen|mandje"
    r")\b",
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
    r"\bweigeren\b|"
    r"alles\s*weigeren|"
    r"(?:the\s+)?(?:x|×)\s+(?:button|control)?"
    r")",
    re.I,
)
_DISMISS_XY_RE = re.compile(
    r"(?:"
    r"no thanks|not now|cancel|reject(?:\s+all)?(?:\s+cookies)?|"
    r"dismiss|close|weigeren|alles\s*weigeren|(?:the\s+)?(?:x|×)"
    r")"
    r"(?:\s+button|\s+control)?"
    r"\s+(?:at\s+)?\((\d{2,4})\s*,\s*(\d{2,4})\)",
    re.I,
)
_COOKIE_ACCEPT_XY_RE = re.compile(
    r"(?:accept(?:\s+all)?|i\s+agree|agree|continue|alles\s*accepteren)"
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
    r"add to cart|"
    r"i['’]?m not a robot|"
    r"not a robot|"
    r"\bcaptcha\b|"
    r"\brecaptcha\b"
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
    r"search in your own words|"
    r"select(?:\s+your)?\s+dates|"
    r"check-?in date|"
    r"enter search criteria|"
    r"type (?:your )?(?:destination|city|query|place)"
    r")",
    re.I,
)
# Coords that belong to the search / destination field, not the first
# (x,y) on the page (that is often a footer link).
_SEARCH_XY_AFTER_RE = re.compile(
    r"(?:"
    r"search box|search field|search bar|destination|where are you going|"
    r"omnibox|empty search|search in your own words|select(?:\s+your)?\s+dates|"
    r"enter search criteria|"
    r"type (?:your )?(?:destination|city|query|place)"
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
    r"empty destination|type your destination|enter search criteria|"
    r"search in your own words|search form is empty|"
    r"select(?:\s+your)?\s+dates|"
    r"empty check-?in|check-?in(?:/|\s+and\s+)?(?:out)?(?:\s+date)?(?:\s+is)?\s+empty|"
    r"check-?in and check-?out|check-?in/?out",
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
# Coaching ("hotel name, city") / "no priced hotel names" is not a listing.
_GENERIC_HOTEL_NAME = (
    r"names?|search|results?|deals?|form|page|site|options?|ask|query|"
    r"list|card|booking|finder|criteria|savings?|banner|promo"
)
_NAMED_HOTEL_RE = re.compile(
    r"\bhotel\s+(?!" + _GENERIC_HOTEL_NAME + r"\b)[A-Za-z]{2,}",
    re.I,
)
# Stay prices on a result card — not the ask budget leaked in a URL.
_STAY_PRICE_RE = re.compile(
    r"("
    r"\bfrom \d+\s*(?:eur|usd|gbp|€|\$)\b|"
    r"\bprices? from\b|"
    r"\b\d+\s*(?:eur|usd|gbp|€)\s+(?:per\s+(?:night|stay)|total|off)\b|"
    r"[€$£]\s*\d+"
    r")",
    re.I,
)
# Booking homepage / empty search form — not a result list.
_TRAVEL_FORM_RE = re.compile(
    r"("
    r"index\.html|"
    r"official site|"
    r"search in your own words|"
    r"select(?:\s+your)?\s+dates|"
    r"check-?in date|"
    r"check-?in/?out|"
    r"where are you going|"
    r"enter search criteria|"
    r"landing(?:\s+page)?|"
    r"\bhomepage\b|"
    r"search box is empty|"
    r"destination is empty|"
    r"search form is empty|"
    r"members?-only deals|"
    r"flight savings|"
    r"genius (?:flight|label)"
    r")",
    re.I,
)
_BOOKING_HOMEPAGE_URL_RE = re.compile(
    r"("
    r"join\.booking\.com|"
    r"booking\.com/(?:index\.html|flights?|flight-deals|sign-?in)(?:\?|#|$)|"
    r"booking\.com/(?:index\.html)?(?:\?|#|$)|"
    r"booking\.com/?$"
    r")",
    re.I,
)
_BOOKING_SEARCHRESULTS_RE = re.compile(
    r"booking\.com/searchresults|searchresults\.html",
    re.I,
)
# Partner listing / Genius flights after a dated searchresults bounce.
_LIST_YOUR_PROPERTY_RE = re.compile(
    r"("
    r"list\s+your\s+(?:apartment|hotel|property|guest\s*house|"
    r"vacation\s+home|home|b\s*&\s*b)|"
    r"list\s+anything\s+on\s+booking|"
    r"join\s+2[0-9,]+\s+other\s+listings"
    r")",
    re.I,
)
# Hero / promo Genius banner (not a loyalty badge on a priced card).
_GENIUS_BANNER_RE = re.compile(
    r"("
    r"\bgenius\b.{0,96}(?:banner|promo|promotional|members?-only|unlock|flight|savings|label)|"
    r"(?:banner|promo|promotional|members?-only|unlock|flight).{0,96}\bgenius\b|"
    r"unlock .{0,48}savings|"
    r"members?-only deals"
    r")",
    re.I,
)
# "Do not check out / pay / invent" and "no checkout" are constraints,
# not a payment UI and not a reason to abort a cart job.
_PAY_COACHING_RE = re.compile(
    r"("
    r"do\s+not\s+invent(?:,\s*check[\s-]?out,\s*or\s*pay)?"
    r"|do\s+not\s+(?:book|pay|check[\s-]?out)"
    r"(?:\s+or\s+(?:book|pay|check[\s-]?out))*"
    r"|don['’]?t\s+(?:book|pay|check[\s-]?out)"
    r"|never\s+(?:book|pay|check[\s-]?out)"
    r"|no\s+check[\s-]?out"
    r"|stop\s+before\s+(?:the\s+)?(?:payment|check[\s-]?out|checkout)"
    r")",
    re.I,
)
_HOTEL_DEST_IN_RE = re.compile(
    r"\b(?:in|near|around)\s+((?:central\s+|downtown\s+|greater\s+)?"
    r"[A-Za-z][A-Za-z]*(?:[\s-][A-Za-z]+){0,3})",
    re.I,
)
_HOTEL_DEST_PAREN_RE = re.compile(r"\(([A-Za-z][A-Za-z\s,/or-]+?)\)")
_BUDGET_TOKEN_RE = re.compile(
    r"^(?:euro|eur|usd|gbp|total|stay|sometime|months?|nights?|available|"
    r"under|next|for|a|an|the|or)$",
    re.I,
)
# "hotel" on the Booking.com homepage is marketing, not a typed query.
_GENERIC_QUERY_WORD_RE = re.compile(
    r"^(?:hotels?|search|chrome|chromium|booking|find|stays?|rooms?|flights?|"
    r"homes?|apartments?|city|cities|destination|query|central|"
    r"using|use|please|the|and|for|in|a|an|to|open|look|click|type|"
    r"person|like|see_screen|keys)$",
    re.I,
)
# "Look, click and type like a person" / Open Chrome / Use the computer —
# coaching, not the search. Also the live hotel-ask tail: dismiss popups,
# reply with N options, Do not invent / book / pay.
_COACHING_PHRASE_RE = re.compile(
    r"("
    r"look\s*,?\s*click\s+(?:and\s+)?type(?:\s+like\s+a\s+person)?|"
    r"click\s+and\s+type(?:\s+like\s+a\s+person)?|"
    r"type\s+like\s+a\s+person|"
    r"like\s+a\s+person|"
    r"open\s+(?:google\s+)?(?:chrome|chromium)|"
    r"use(?:\s+the)?\s+computer|"
    r"using(?:\s+the)?\s+computer|"
    r"open\s+a\s+real\s+(?:travel\s+)?site|"
    r"search\s+real\s+dates?(?:\s+and\s+prices?)?|"
    r"dismiss(?:\s+the)?\s+(?:popups?|overlays?|cookies?|modals?)|"
    r"do\s+not\s+invent(?:,\s*check[\s-]?out,\s*or\s*pay)?|"
    r"do\s+not\s+book(?:\s+or\s+pay)?|"
    r"do\s+not\s+(?:check[\s-]?out|pay)(?:\s+or\s+(?:check[\s-]?out|pay))?|"
    r"no\s+check[\s-]?out|"
    r"stop\s+before\s+(?:the\s+)?(?:payment|check[\s-]?out)|"
    r"reply\s+with\s+both\s+names|"
    r"names?,?\s*euro prices|"
    r"euro prices|"
    r"cart confirmation|"
    r"if\s+(?:coolblue|bol|amazon)(?:\s+or\s+(?:coolblue|bol|amazon))?"
    r"\s+is\s+blocked|"
    r"reply\s+with(?:\s+\d+)?\s+concrete\s+options|"
    r"concrete\s+options:?|"
    r"hotel\s+name,?\s*city|"
    r"check-in/?out\s+dates|"
    r"nights,?\s+(?:and\s+)?total\s+price(?:\s+in\s+euros?)?|"
    r"total\s+price\s+in\s+euros?|"
    r"see[_ ]screen|"
    r"\btools_used\b"
    r")",
    re.I,
)
_COACHING_LEFTOVER_RE = re.compile(
    r"\b(?:google\s+)?(?:chrome|chromium)\b",
    re.I,
)
# Vision dump / "Searching…" on a Google SERP is not hotel results.
_SEARCHING_CAPTION_RE = re.compile(
    r"("
    r"the focused window is|"
    r"the search query reads|"
    r"\bsearching\b|"
    r"ai overview (?:is )?unavailable|"
    r"can['’]?t generate an ai overview"
    r")",
    re.I,
)
_TRAVEL_SITE_RE = re.compile(
    r"("
    r"booking\.com|"
    r"hotels\.com|"
    r"\bexpedia\b|"
    r"kayak\.com|"
    r"\bairbnb\b|"
    r"google\.[^/\s]+/travel|"
    r"html\.duckduckgo\.com|"
    r"duckduckgo\.com/.{0,160}hotels"
    r")",
    re.I,
)
# Google Hotels / Travel or the DDG hotels list used after a Booking bounce.
# /travel/unsupported is still this host — just a blank look.
_HOTEL_ALT_HOST_RE = re.compile(
    r"("
    r"google\.[^/\s]+/travel|"
    r"google travel|"
    r"google hotels|"
    r"html\.duckduckgo\.com|"
    r"duckduckgo\.com/\?q=[^\s]*hotels"
    r")",
    re.I,
)
_GOOGLE_TRAVEL_UNSUPPORTED_RE = re.compile(
    r"google\.[^/\s]+/travel/unsupported",
    re.I,
)
# Google /sorry, I'm not a robot, unusual traffic — any find/search job.
_CAPTCHA_RE = re.compile(
    r"("
    r"google\.com/sorry|"
    r"/sorry/index|"
    r"/sorry\?|"
    r"i['’]?m not a robot|"
    r"not a robot|"
    r"unusual traffic|"
    r"detected unusual traffic|"
    r"verify (?:that )?you are (?:a )?human|"
    r"are you a robot|"
    r"\bcaptcha\b|"
    r"\brecaptcha\b"
    r")",
    re.I,
)
# Painted host in a title / URL. Chromium chrome is not a site.
_LOOK_HOST_RE = re.compile(
    r"\b(?:www\.)?([a-z0-9-]+\.(?:com|nl|de|org|net|io|co\.uk|co|uk|edu|app))\b",
    re.I,
)
_HTTP_ERROR_RE = re.compile(
    r"("
    r"\bhttp\s*403\b|"
    r"\b403\b(?:\s+(?:forbidden|error))?|"
    r"access denied|"
    r"this site can(?:not|'t|’t) be reached"
    r")",
    re.I,
)
# Retailer IP / abuse walls (bol.com live 2026-09-11). Not a 403 title —
# vision says temporarily blocked / possible abuse / automated scripts.
_ABUSE_BLOCK_RE = re.compile(
    r"("
    r"temporarily blocked|"
    r"possible abuse|"
    r"abuse from this ip|"
    r"blocked due to (?:possible )?abuse|"
    r"your access to .{0,80} (?:has been )?(?:temporarily )?blocked|"
    r"ip (?:address )?(?:has been )?(?:temporarily )?blocked|"
    r"blocked (?:for|due to) (?:possible )?abuse|"
    r"automated scripts?"
    r")",
    re.I,
)
# After a shop IP-block, leave the dead host. coolblue.nl then amazon.nl.
RETAILER_FALLBACK_URLS: tuple[str, ...] = (
    "https://www.coolblue.nl/",
    "https://www.amazon.nl/",
)
_NL_RETAILER_HOST_RE = re.compile(
    r"\b(?:www\.)?(bol\.com|coolblue\.nl|amazon\.nl)\b",
    re.I,
)
# chrome://extensions / settings and leftover desktop apps. Never type THIS
# ask here. chrome://newtab is a blank tab, not leftover.
_CHROME_INTERNAL_RE = re.compile(r"chrome://(?!new-?tab)", re.I)
_LEFTOVER_SURFACE_RE = re.compile(
    r"("
    r"\bublock(?:\s+origin)?\b|"
    r"(?:^|[\s\"“”'])extensions(?:\s*[-–—]|\s*$)|"
    r"\b(?:chromium|chrome|google chrome)\s+settings\b|"
    r"\bsettings\s+[-–—]\s+(?:chromium|google chrome|chrome)\b|"
    r"\bthunar\b|"
    r"\b(?:xfce4-)?terminal\b|"
    r"\bgnome-terminal\b|"
    r"\bfile manager\b"
    r")",
    re.I,
)
# Browser chrome / wallpaper titles are still opening, not leftover.
_BROWSER_CHROME_TITLE_RE = re.compile(
    r"^(chrome|google chrome|chromium|desktop|xfce|untitled)\b",
    re.I,
)
# Look-side topic from the leftover title / host, not the ask wording.
_LOOK_TOPIC_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "shop",
        re.compile(
            r"\b(bol\.com|amazon|coolblue|ebay|zalando|webshop|add to cart|shopping)\b",
            re.I,
        ),
    ),
    (
        "weather",
        re.compile(r"\b(weather|forecast|accuweather|°[cf]|degrees)\b", re.I),
    ),
    (
        "hotel",
        re.compile(
            r"\b(booking\.com|hotels?\.com|airbnb|expedia|hotels? in)\b",
            re.I,
        ),
    ),
    (
        "calculator",
        re.compile(r"\b(calculator|galculator)\b", re.I),
    ),
    (
        "news",
        re.compile(r"\b(reuters|bbc\.com|cnn|nzz|bloomberg|swissinfo)\b", re.I),
    ),
)
# Ask-side topic. Shop vs weather, hotel vs calculator — not the same job.
_ASK_TOPIC_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "shop",
        re.compile(
            r"\b(buy|shop|grinder|cart|coffee grinder|bol\.com|amazon|coolblue|products)\b",
            re.I,
        ),
    ),
    (
        "weather",
        re.compile(r"\b(weather|forecast|temperature)\b", re.I),
    ),
    (
        "hotel",
        re.compile(r"\b(hotel|booking|airbnb|stay)\b", re.I),
    ),
    (
        "calculator",
        re.compile(r"\b(calculator|galculator|compute)\b", re.I),
    ),
    (
        "news",
        re.compile(r"\b(news|headlines)\b", re.I),
    ),
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
    r"white (?:page|screen|pane|area)|"
    r"white (?:loading )?(?:results? )?(?:area|pane|screen)|"
    r"blank (?:white )?results|"
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


def _strip_pay_constraints(text: str) -> str:
    """Drop 'do not check out / pay' coaching so leftover 'pay' is not a hit."""
    cleaned = _PAY_COACHING_RE.sub(" ", text or "")
    cleaned = re.sub(
        r"\b(?:do\s+not|don['’]?t|never|no)\s+"
        r"(?:invent|book|pay|check[\s-]?out|checkout)\b",
        " ",
        cleaned,
        flags=re.I,
    )
    return cleaned


def look_is_pay_control(text: str, goal: str = "") -> bool:
    """True for a real payment form — not add-to-cart, not a do-not-pay ask.

    Cart / add-to-basket jobs keep going when the page says Add to cart
    or the ask says do not check out. Only a payment UI (or an ask that
    actually wants checkout) is this.
    """
    if ask_wants_cart(goal) and not ask_wants_payment(goal):
        return False
    cleaned = _strip_pay_constraints(text or "")
    return bool(_PAY_RE.search(cleaned))


def ask_wants_payment(asked: str) -> bool:
    """True only when they asked to pay / complete checkout / enter a card.

    'Do not check out', 'no checkout', 'stop before payment' are
    constraints — not this.
    """
    cleaned = _strip_pay_constraints(asked or "")
    return bool(_ASK_PAY_RE.search(cleaned))


def ask_wants_cart(asked: str) -> bool:
    """Add two in-stock products to a cart — stay on the retailer."""
    raw = asked or ""
    if not _CART_JOB_RE.search(raw):
        return False
    return ask_wants_shop(raw) or bool(_NL_RETAILER_HOST_RE.search(raw))


def look_has_cart_results(looked: dict[str, Any] | None) -> bool:
    """Two euro prices plus a cart/basket — names+prices, not a Google SERP."""
    if _look_is_search_engine(looked):
        return False
    blob = look_result_blob(looked)
    if _CART_EMPTY_RE.search(blob):
        return False
    return len(_CART_PRICE_RE.findall(blob)) >= 2 and bool(
        _CART_CONFIRM_RE.search(blob)
    )


def _title_is_restore(looked: dict[str, Any] | None) -> bool:
    title = str((looked or {}).get("title") or "")
    try:
        from app.jarvis.desktop import is_dismissible_chrome_dialog

        if is_dismissible_chrome_dialog(title):
            return True
    except Exception:
        pass
    return bool(_RESTORE_RE.search(title))


def look_result_blob(looked: dict[str, Any] | None) -> str:
    """Vision + title only. The address bar repeats the ask — not prices."""
    item = looked or {}
    return " ".join(
        str(item.get(key) or "") for key in ("vision_description", "title")
    )


def _named_hotel_in(blob: str) -> bool:
    return bool(_NAMED_HOTEL_RE.search(blob or ""))


def _stay_price_in(blob: str) -> bool:
    return bool(_STAY_PRICE_RE.search(blob or ""))


def _hotel_price_evidence(blob: str) -> bool:
    """True only for a listed property with a stay price — not coaching."""
    text = blob or ""
    return _named_hotel_in(text) and _stay_price_in(text)


def overlay_kind(
    looked: dict[str, Any] | None,
    *,
    goal: str = "",
) -> OverlayKind | None:
    """Highest-priority blocking overlay on this look, or None.

    Genius loyalty badges on a priced hotel list are not the sign-in
    modal. A covering dialog on Booking with no readable prices is.
    """
    if look_is_captcha(looked):
        # Never treat I'm not a robot as a cookie / sign-in dismiss.
        return None
    item = looked or {}
    blob = look_blob(item)
    if _title_is_restore(item) or _RESTORE_RE.search(blob):
        return "restore"
    if _SANDBOX_RE.search(blob):
        return "sandbox"
    if _MEMORY_SAVER_RE.search(blob):
        return "memory_saver"
    if not user_asked_sign_in(goal):
        result_blob = look_result_blob(item)
        # Mashed Sign-in modal / covering dialog. A Genius *homepage*
        # promotional banner is marketing next to an empty form — not this.
        # Treating that hero as signin loops dismiss forever and never types.
        signin_hit = bool(_SIGNIN_RE.search(blob))
        covering = bool(_COVERING_MODAL_RE.search(blob)) and look_is_travel_site(
            item
        )
        if signin_hit or covering:
            # Priced cards that mention Genius are not the modal — unless
            # vision also names a sign-in / save-money dialog.
            if _hotel_price_evidence(result_blob) and not _SIGNIN_MODAL_RE.search(
                blob
            ):
                pass
            else:
                return "signin"
    cookie_blob = _COOKIE_ABSENT_RE.sub(" ", blob)
    if _COOKIE_RE.search(cookie_blob) or look_is_coolblue_cookie_modal(item):
        return "cookie"
    return None


def look_has_blocking_overlay(
    looked: dict[str, Any] | None,
    *,
    goal: str = "",
) -> bool:
    found = overlay_kind(looked, goal=goal)
    # Memory Saver is a corner toast — dismiss it, but priced hotel
    # names on the page are still readable.
    return found is not None and found != "memory_saver"


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


def _cookie_fallback_click(
    looked: dict[str, Any] | None,
    *,
    dismisses: int = 0,
) -> tuple[int, int]:
    """Hardcoded CMP button when vision names no (x,y).

    Coolblue's live card has no Weigeren and no coords — click Alles
    accepteren first, then Weigeren on the next look. Never a random
    product / cookie-man pixel. Never Escape-only.
    """
    clicks = COOLBLUE_COOKIE_DISMISS_CLICKS
    idx = min(max(int(dismisses), 0), len(clicks) - 1)
    return clicks[idx]


def overlay_dismiss_plan(
    looked: dict[str, Any] | None,
    *,
    goal: str = "",
    kind: OverlayKind | None = None,
    dismisses: int = 0,
) -> OverlayPlan | None:
    """Click X / No thanks / Cancel / Reject. Never Sign in / Restore / Pay."""
    if look_is_captcha(looked):
        return None
    found = kind or overlay_kind(looked, goal=goal)
    if found is None:
        return None
    blob = look_blob(looked)
    if found != "cookie" and look_is_pay_control(blob, goal) and not _DISMISS_LABEL_RE.search(
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
    if found == "memory_saver":
        return OverlayPlan(
            kind="memory_saver",
            click=named_dismiss or MEMORY_SAVER_DISMISS_CLICK,
            keys="escape",
            reason="Chromium Memory Saver toast — No thanks, never Turn on.",
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
    # Cookie: named Weigeren / Reject, then named Accept, then the
    # Coolblue Alles accepteren pixel. A body-text "weigeren" without
    # coords is not a reason to send Escape only — that hung live.
    # Never _named_click_from_look (the cookie-man / a product).
    click = named_dismiss or _cookie_accept_xy(blob)
    if click is None:
        click = _cookie_fallback_click(looked, dismisses=dismisses)
    return OverlayPlan(
        kind="cookie",
        click=click,
        keys="escape" if _DISMISS_LABEL_RE.search(blob) else "enter",
        reason="Cookie / consent — Reject or Alles accepteren, never Sign in.",
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
    """True when vision is the page footer, not the destination field.

    A Coolblue cookie card that mentions cookie-en privacyverklaring is
    not the footer — Home-looping that modal burns the nginx 180s.
    """
    if overlay_kind(looked) == "cookie" or look_is_coolblue_cookie_modal(looked):
        return False
    blob = look_blob(looked)
    if _search_field_xy(blob):
        return False
    return bool(_FOOTER_RE.search(blob))


def look_is_travel_search_form(looked: dict[str, Any] | None) -> bool:
    """True for Booking homepage / empty date form — not a priced list.

    index.html, Official site, Genius promo, Search in your own words,
    Select dates, Enter search criteria. A searchresults.html URL is
    never this — the dest/dates chrome on a list is not a bounce home.
    """
    if not look_is_travel_site(looked):
        return False
    url = str((looked or {}).get("url") or "")
    title = str((looked or {}).get("title") or "")
    if _BOOKING_SEARCHRESULTS_RE.search(url) or _BOOKING_SEARCHRESULTS_RE.search(
        title
    ):
        return False
    if look_is_loading_or_blank(looked):
        return False
    if _hotel_price_evidence(look_result_blob(looked)):
        return False
    if _BOOKING_HOMEPAGE_URL_RE.search(url):
        return True
    blob = look_result_blob(looked)
    if _LIST_YOUR_PROPERTY_RE.search(blob) or _LIST_YOUR_PROPERTY_RE.search(title):
        return True
    return bool(
        _TRAVEL_FORM_RE.search(blob)
        or _EMPTY_DEST_RE.search(blob)
        or _GENIUS_BANNER_RE.search(blob)
    )


def look_is_booking_searchresults(looked: dict[str, Any] | None) -> bool:
    """True when the look is a Booking searchresults.html page / URL."""
    item = looked or {}
    blob = " ".join(
        str(item.get(key) or "")
        for key in ("url", "title", "vision_description")
    )
    return bool(_BOOKING_SEARCHRESULTS_RE.search(blob))


def look_is_hotel_search_pending(looked: dict[str, Any] | None) -> bool:
    """Loading or submitting a dated searchresults page — not homepage.

    In-progress after type. A blank / white results pane on
    searchresults.html is still pending. A blank Google Travel /
    Hotels look after the alt run_app is pending — not typed-success.
    An empty Booking index / dest+dates form is not this — that is
    a bounce (or a lost tab after the alt opened).
    """
    if look_has_hotel_results(looked):
        return False
    if look_is_hotel_alt_host(looked):
        return True
    if look_is_booking_searchresults(looked):
        return True
    if look_is_travel_search_form(looked):
        return False
    return bool(look_is_travel_site(looked) and look_is_loading_or_blank(looked))


def hotel_option_lines(looked: dict[str, Any] | None) -> list[str]:
    """Vision sentences that name a hotel or a stay price. Never invent.

    Name and price are often adjacent sentences. Up to three hotels
    (name + price) — never coaching or the ask budget.
    """
    if not look_has_hotel_results(looked):
        return []
    text = look_result_blob(looked)
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    kept = [p for p in parts if _named_hotel_in(p) or _stay_price_in(p)]
    return kept[:6]


def look_has_hotel_results(looked: dict[str, Any] | None) -> bool:
    """True when vision shows hotel search results, not the homepage form.

    A leftover Google New Tab / homepage that mentions the hotel ask
    ("hotels in Rome") is not a result list. A Booking search-results
    URL with no readable names or prices is not results. Coaching
    ("hotel name, city" / "no priced hotel names") is not results.
    Ask-budget "2000 Euro" in the address bar is not a stay price.
    A Genius / sign-in / cookie overlay covering the list is not
    results. Untitled / blank / loading is not results.
    look_speed=off does not change this.
    """
    if (
        look_is_loading_or_blank(looked)
        or look_is_focused_new_tab(looked)
        or look_is_empty_desktop(looked)
        or look_is_footer(looked)
        or look_is_leftover_surface(looked)
        or look_is_captcha(looked)
        or look_is_http_error(looked)
        or look_has_blocking_overlay(looked)
        or look_is_travel_search_form(looked)
    ):
        return False
    blob = look_result_blob(looked)
    if not _HOTEL_RESULT_RE.search(blob) and not _named_hotel_in(blob):
        return False
    # Named hotel + stay price in vision/title. Never the address bar.
    if not _hotel_price_evidence(blob):
        return False
    return True


def ask_wants_hotel(asked: str) -> bool:
    """Find / book a hotel — not weather or a shop search."""
    return ask_topic(asked) == "hotel"


def look_is_travel_site(looked: dict[str, Any] | None) -> bool:
    """Booking / Hotels.com / Google Hotels / DDG hotels — gather prices."""
    item = looked or {}
    blob = " ".join(
        str(item.get(key) or "")
        for key in ("url", "title", "vision_description")
    )
    return bool(_TRAVEL_SITE_RE.search(blob) or _HOTEL_ALT_HOST_RE.search(blob))


def look_is_hotel_alt_host(looked: dict[str, Any] | None) -> bool:
    """True when the focused tab is Google Travel/Hotels or DDG hotels.

    /travel/search on jarvis-computer paints blank (302 unsupported).
    /travel/hotels does the same from this IP. html.duckduckgo.com
    hotels queries paint names + prices (verified 2026-09-11).
    """
    item = looked or {}
    blob = " ".join(
        str(item.get(key) or "")
        for key in ("url", "title", "vision_description")
    )
    return bool(_HOTEL_ALT_HOST_RE.search(blob))


def look_lost_hotel_alt(looked: dict[str, Any] | None) -> bool:
    """Booking still focused after the alt host was opened.

    see_screen must not stay on index / searchresults / Genius while
    a Google / DDG hotels tab sits unused. Not results, not the alt.
    """
    if look_has_hotel_results(looked) or look_is_hotel_alt_host(looked):
        return False
    item = looked or {}
    url = str(item.get("url") or "")
    if re.search(r"booking\.com", url, re.I):
        return True
    return bool(
        look_is_booking_searchresults(looked)
        or look_is_travel_search_form(looked)
        or look_is_booking_bounce(looked, saw_searchresults=True)
    )


def look_is_unfinished_hotel_search(looked: dict[str, Any] | None) -> bool:
    """True for a Google/DDG SERP or Searching/focused-window caption.

    Concrete hotel name + price on a travel site is done. A leftover New
    Tab that only mentions the ask is not this — that still needs the
    query typed first.
    """
    if look_has_hotel_results(looked) or look_is_travel_site(looked):
        return False
    if _SEARCHING_CAPTION_RE.search(look_blob(looked)):
        return True
    return bool(_look_is_search_engine(looked))


def hotel_stay_dates(today: date | None = None) -> tuple[date, date]:
    """A real 3-night stay about three weeks out — next-3-months window."""
    start = (today or date.today()) + timedelta(days=21)
    return start, start + timedelta(days=3)


def hotel_date_query(today: date | None = None) -> str:
    checkin, checkout = hotel_stay_dates(today)
    return f"check-in {checkin.isoformat()} check-out {checkout.isoformat()}"


def hotel_destination(asked: str) -> str:
    """Rome / central Italy — not the full ask or coaching dump."""
    raw = _COACHING_PHRASE_RE.sub(" ", asked or "")
    raw = _COACHING_LEFTOVER_RE.sub(" ", raw)
    paren = _HOTEL_DEST_PAREN_RE.search(raw)
    if paren:
        first = re.split(r"\s*,\s*|\s+or\s+", paren.group(1), flags=re.I)[0]
        first = first.strip(" .,")
        if first and not _BUDGET_TOKEN_RE.match(first):
            return first
    place = _HOTEL_DEST_IN_RE.search(raw)
    if place:
        dest = place.group(1).strip(" .,")
        dest = re.sub(
            r"\s+(for|under|with|during|this|next|the|and)$",
            "",
            dest,
            flags=re.I,
        )
        dest = dest.strip(" .,")
        if dest and not _BUDGET_TOKEN_RE.match(dest):
            return dest
    tokens = [
        part
        for part in distinctive_query_tokens(web_search_query(asked))
        if not part.isdigit() and not _BUDGET_TOKEN_RE.match(part)
    ]
    if tokens:
        return " ".join(tokens[:3])
    return "hotel"


def hotel_typed_query(asked: str, today: date | None = None) -> str:
    """Clean destination + real check-in/out. Never the coaching essay."""
    dest = hotel_destination(asked)
    dates = hotel_date_query(today)
    if dest.lower() in {"hotel", "hotels"}:
        return f"hotels {dates}".strip()
    return f"{dest} hotels {dates}".strip()


def hotel_travel_url(asked: str, today: date | None = None) -> str:
    """Booking.com search with destination + real check-in/out dates."""
    dest = hotel_destination(asked) or "hotel"
    checkin, checkout = hotel_stay_dates(today)
    return (
        "https://www.booking.com/searchresults.html?"
        f"ss={quote_plus(dest)}"
        f"&checkin={checkin.isoformat()}"
        f"&checkout={checkout.isoformat()}"
    )


def hotel_alt_travel_url(asked: str, today: date | None = None) -> str:
    """First alt after a Booking bounce: Google /travel/hotels.

    Live 2026-09-11 SHA 35d5797: /travel/search?q=Rome+hotels&dates=…
    opened on jarvis-computer but stayed blank (302 /travel/unsupported,
    empty body). /travel/hotels?checkin=&checkout= does the same from
    this IP (curl 2026-09-11). Still try /travel/hotels first — some
    networks paint a list — then hotel_alt_fallback_url (DuckDuckGo
    HTML) when the look stays blank. Never invent prices.
    """
    dest = hotel_destination(asked) or "hotel"
    checkin, checkout = hotel_stay_dates(today)
    dest_path = quote_plus(dest)
    q = quote_plus(f"{dest} hotels")
    return (
        f"https://www.google.com/travel/hotels/{dest_path}"
        f"?q={q}&checkin={checkin.isoformat()}&checkout={checkout.isoformat()}"
    )


def hotel_alt_fallback_url(asked: str, today: date | None = None) -> str:
    """DuckDuckGo HTML hotels list — paints names+prices on this host.

    Verified 2026-09-11 from the jarvis-computer egress: html.duckduckgo.com
    returns '10 Best Rome Hotels (From US$87)', Tripadvisor from $76,
    Booking 'Check in Rome'. Google Travel /search and /hotels both
    302 to /travel/unsupported with a blank body. !g stays on DDG
    here (no bang redirect). Use the HTML endpoint so Chromium does
    not need the JS Travel UI.
    """
    dest = hotel_destination(asked) or "hotel"
    checkin, checkout = hotel_stay_dates(today)
    q = quote_plus(
        f"{dest} hotels check-in {checkin.isoformat()} "
        f"check-out {checkout.isoformat()}"
    )
    return f"https://html.duckduckgo.com/html/?q={q}"


def look_is_booking_bounce(
    looked: dict[str, Any] | None,
    *,
    saw_searchresults: bool = False,
) -> bool:
    """True when a dated searchresults look is now empty index / homepage.

    index.html, join.booking.com list-your-property, Genius flights,
    and any other booking.com URL that is not searchresults after a
    prior dated list — antibot bounce, not a priced stay.
    """
    if look_has_hotel_results(looked):
        return False
    if look_is_booking_searchresults(looked) or look_is_hotel_search_pending(
        looked
    ):
        return False
    prior = bool(saw_searchresults or (looked or {}).get("_saw_searchresults"))
    if not prior:
        return False
    item = looked or {}
    url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    blob = look_result_blob(item)
    if _BOOKING_HOMEPAGE_URL_RE.search(url):
        return True
    if _LIST_YOUR_PROPERTY_RE.search(url + " " + title + " " + blob):
        return True
    if re.search(r"booking\.com", url, re.I) and not _BOOKING_SEARCHRESULTS_RE.search(
        url
    ):
        return True
    return look_is_travel_search_form(looked)


def needs_hotel_followthrough(
    asked: str, looked: dict[str, Any] | None, query: str
) -> bool:
    """True when a hotel job is still on a SERP / caption with no prices.

    Query text visible on Google is not done. Speaking a focused-window
    caption is not done. look_speed=off does not change this.
    """
    if not ask_wants_hotel(asked):
        return False
    if look_has_hotel_results(looked) or look_is_travel_site(looked):
        return False
    if not look_is_unfinished_hotel_search(looked):
        return False
    if query_visible_on_look(looked, query) or (looked or {}).get("_typed_query"):
        return True
    return bool(_SEARCHING_CAPTION_RE.search(look_blob(looked)))


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
    if look_is_leftover_surface(item) or look_is_captcha(item):
        return False
    url = str(item.get("url") or "")
    if _GOOGLE_TRAVEL_UNSUPPORTED_RE.search(url):
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


def look_host_label(looked: dict[str, Any] | None) -> str:
    """bol.com / booking.com from the title or URL. Not chromium."""
    item = looked or {}
    blob = " ".join(
        str(item.get(key) or "") for key in ("url", "title", "vision_description")
    )
    match = _LOOK_HOST_RE.search(blob)
    if not match:
        return ""
    host = match.group(1).lower()
    if host.startswith("www."):
        host = host[4:]
    if host in {"google.com", "duckduckgo.com", "bing.com"}:
        return ""
    return host


def look_is_abuse_block(looked: dict[str, Any] | None) -> bool:
    """Retailer IP / abuse / automated-script wall from title or vision.

    bol.com paints this without HTTP 403 in the title. Typing a shop
    query here is not success. Fall back to another NL retailer.
    """
    return bool(_ABUSE_BLOCK_RE.search(look_blob(looked)))


def look_is_http_error(looked: dict[str, Any] | None) -> bool:
    """403 / unreachable / abuse leftover — not a page we type a shop query into."""
    blob = look_blob(looked)
    return bool(_HTTP_ERROR_RE.search(blob) or _ABUSE_BLOCK_RE.search(blob))


def look_is_retailer_block(looked: dict[str, Any] | None) -> bool:
    """Abuse / IP block / access denied — not a shop we can type into."""
    return look_is_http_error(looked) or look_is_abuse_block(looked)


def ask_wants_shop(asked: str) -> bool:
    """Find / buy / cart on a shop — not weather or a hotel search."""
    return ask_topic(asked) == "shop"


_SHOP_HOST_URLS: tuple[tuple[str, str], ...] = (
    ("coolblue.nl", "https://www.coolblue.nl/"),
    ("bol.com", "https://www.bol.com/"),
    ("amazon.nl", "https://www.amazon.nl/"),
)


def shop_home_url(asked: str) -> str | None:
    """First named NL retailer homepage. Never a Google search of the ask."""
    raw = asked or ""
    found: list[tuple[int, str]] = []
    for host, url in _SHOP_HOST_URLS:
        match = re.search(re.escape(host), raw, re.I)
        if match:
            found.append((match.start(), url))
    if found:
        found.sort(key=lambda item: item[0])
        return found[0][1]
    return None


def shop_typed_query(asked: str) -> str:
    """On-shop search tokens only. Never the coaching / do-not-pay essay."""
    raw = web_search_query(asked)
    raw = re.sub(
        r"\b("
        r"check[\s-]?out|checkout|pay|purchase|buy|"
        r"reply|names?|confirmation|blocked|cookies?|"
        r"dismiss|invent|different|real|both|euro|prices?"
        r")\b",
        " ",
        raw,
        flags=re.I,
    )
    raw = _CART_FILLER_RE.sub(" ", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" .,!?")
    tokens = distinctive_query_tokens(raw)
    if tokens:
        return " ".join(tokens[:6])
    if ask_wants_cart(asked):
        return shop_cart_queries(asked)[0]
    return raw


def shop_cart_queries(asked: str) -> tuple[str, ...]:
    """Two different in-stock searches. Never 'in-stock' or the essay."""
    return CART_PRODUCT_QUERIES


def look_is_shop_homepage(looked: dict[str, Any] | None) -> bool:
    """Coolblue / amazon / bol root — categories / newsletter, not a basket."""
    if not look_is_nl_retailer(looked):
        return False
    if look_is_coolblue_cookie_modal(looked):
        return False
    url = str((looked or {}).get("url") or "")
    if _SHOP_BASKET_URL_RE.search(url) or _SHOP_PDP_URL_RE.search(url):
        return False
    if _SHOP_SEARCH_URL_RE.search(url):
        return False
    blob = look_result_blob(looked)
    if (
        len(_CART_PRICE_RE.findall(blob)) >= 2
        and _CART_CONFIRM_RE.search(blob)
        and not _CART_EMPTY_RE.search(blob)
    ):
        return False
    if _SHOP_HOME_URL_RE.search(url):
        return True
    return bool(_SHOP_HOME_RE.search(blob))


def look_is_shop_search(looked: dict[str, Any] | None) -> bool:
    """Product list after a shop search — not the homepage and not the basket."""
    if look_has_cart_results(looked) or look_is_shop_homepage(looked):
        return False
    url = str((looked or {}).get("url") or "")
    if _SHOP_PDP_URL_RE.search(url) or _SHOP_BASKET_URL_RE.search(url):
        return False
    if _SHOP_SEARCH_URL_RE.search(url):
        return True
    return bool(_SHOP_SEARCH_RE.search(look_result_blob(looked)))


def look_is_shop_pdp(looked: dict[str, Any] | None) -> bool:
    """One product page with add-to-basket — not the cart itself."""
    if look_has_cart_results(looked):
        return False
    url = str((looked or {}).get("url") or "")
    if _SHOP_BASKET_URL_RE.search(url):
        return False
    if _SHOP_PDP_URL_RE.search(url):
        return True
    blob = look_result_blob(looked)
    if _SHOP_SEARCH_RE.search(blob) or look_is_shop_homepage(looked):
        return False
    return bool(_SHOP_PDP_RE.search(blob))


def look_is_unfinished_cart(looked: dict[str, Any] | None) -> bool:
    """Shop is open but two priced basket lines are not on screen."""
    if look_has_cart_results(looked):
        return False
    if look_is_retailer_block(looked) or look_is_captcha(looked):
        return False
    if look_is_coolblue_cookie_modal(looked):
        return False
    return look_is_nl_retailer(looked)


def needs_cart_followthrough(asked: str, looked: dict[str, Any] | None) -> bool:
    """Cart job still on the shop homepage / search / PDP — not done."""
    if not ask_wants_cart(asked):
        return False
    if look_has_cart_results(looked):
        return False
    return look_is_unfinished_cart(looked)


def cart_option_lines(looked: dict[str, Any] | None) -> list[str]:
    """Vision sentences that name a product or a euro price. Never invent."""
    if not look_has_cart_results(looked):
        return []
    text = look_result_blob(looked)
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    kept: list[str] = []
    for i, part in enumerate(parts):
        if not (_CART_PRICE_RE.search(part) or _CART_CONFIRM_RE.search(part)):
            continue
        if i and parts[i - 1] not in kept:
            prev = parts[i - 1]
            if len(prev.split()) <= 6 and not _CART_EMPTY_RE.search(prev):
                kept.append(prev)
        kept.append(part)
    return kept[:6]


def shop_basket_url(looked: dict[str, Any] | None, asked: str = "") -> str:
    """winkelwagen / cart URL for the focused shop. Never Google.

    Use the painted host. The ask may mention amazon.nl as a fallback —
    that must not open Amazon's cart while Coolblue is on screen.
    """
    host = look_host_label(looked)
    if "amazon.nl" in host:
        return "https://www.amazon.nl/gp/cart/view.html"
    if "bol.com" in host:
        return "https://www.bol.com/nl/nl/s/winkelwagen.html"
    if "coolblue" in host:
        return "https://www.coolblue.nl/winkelwagen"
    raw = asked or ""
    if re.search(r"amazon\.nl", raw, re.I) and not re.search(
        r"coolblue", raw, re.I
    ):
        return "https://www.amazon.nl/gp/cart/view.html"
    if re.search(r"bol\.com", raw, re.I) and not re.search(r"coolblue", raw, re.I):
        return "https://www.bol.com/nl/nl/s/winkelwagen.html"
    return "https://www.coolblue.nl/winkelwagen"


def add_to_basket_point(looked: dict[str, Any] | None) -> tuple[int, int] | None:
    """In winkelwagen / Add to basket. Never checkout."""
    blob = look_blob(looked)
    match = _ADD_BASKET_XY_RE.search(blob or "")
    if match:
        x, y = int(match.group(1)), int(match.group(2))
        if _xy_in_page(x, y) or y < 720:
            return x, y
    if look_is_nl_retailer(looked):
        return COOLBLUE_ADD_BASKET_CLICK
    return None


def product_tile_point(
    looked: dict[str, Any] | None, *, index: int = 0
) -> tuple[int, int] | None:
    """A search-result / homepage product tile. Not the footer."""
    blob = look_blob(looked)
    found = [
        (int(m.group(1)), int(m.group(2)))
        for m in _PRODUCT_TILE_XY_RE.finditer(blob or "")
        if _xy_in_page(int(m.group(1)), int(m.group(2)))
    ]
    if found:
        return found[min(max(int(index), 0), len(found) - 1)]
    clicks = COOLBLUE_PRODUCT_CLICKS
    return clicks[min(max(int(index), 0), len(clicks) - 1)]


def basket_icon_point(looked: dict[str, Any] | None) -> tuple[int, int]:
    """Header basket / winkelwagen. Not a product."""
    blob = look_blob(looked)
    match = _BASKET_ICON_XY_RE.search(blob or "")
    if match:
        x, y = int(match.group(1)), int(match.group(2))
        if 0 <= x <= 1280 and 0 <= y < 160:
            return x, y
    return COOLBLUE_BASKET_CLICK


def shop_search_click(looked: dict[str, Any] | None) -> tuple[int, int]:
    """Header search on an NL shop. Not mid-page categories."""
    named = search_box_point(looked)
    if named is not None:
        return named
    if look_is_coolblue_host(looked) or look_is_nl_retailer(looked):
        return COOLBLUE_SEARCH_CLICK
    return SEARCH_BOX_CLICK


def look_is_nl_retailer(looked: dict[str, Any] | None) -> bool:
    """bol.com / coolblue.nl / amazon.nl from the title or URL."""
    item = looked or {}
    blob = " ".join(
        str(item.get(key) or "") for key in ("url", "title", "vision_description")
    )
    return bool(_NL_RETAILER_HOST_RE.search(blob))


def look_is_coolblue_host(looked: dict[str, Any] | None) -> bool:
    """True when the focused tab is coolblue.nl."""
    item = looked or {}
    blob = " ".join(
        str(item.get(key) or "") for key in ("url", "title", "vision_description")
    )
    return bool(re.search(r"\b(?:www\.)?coolblue\.nl\b", blob, re.I))


def look_is_coolblue_cookie_modal(looked: dict[str, Any] | None) -> bool:
    """Coolblue COOKIES. Smaakmakers. card — coords optional.

    Live 2026-09-11: green Alles accepteren + Zelf instellen, no Weigeren
    button, no (x,y) from vision. Escape does not close it.
    """
    if not look_is_coolblue_host(looked):
        return False
    blob = _COOKIE_ABSENT_RE.sub(" ", look_blob(looked))
    return bool(_COOLBLUE_COOKIE_RE.search(blob))


def _url_host_label(url: str) -> str:
    raw = re.sub(r"^https?://", "", url or "", flags=re.I).split("/")[0].lower()
    if raw.startswith("www."):
        raw = raw[4:]
    return raw


def retailer_fallback_urls() -> tuple[str, ...]:
    """coolblue.nl first, then amazon.nl. Never the blocked host."""
    return RETAILER_FALLBACK_URLS


def next_retailer_fallback_url(
    looked: dict[str, Any] | None,
    tried: list[str] | tuple[str, ...] | None = None,
) -> str | None:
    """Next NL retailer after the blocked host. Skip current and already tried."""
    skip = {_url_host_label(url) for url in (tried or ()) if url}
    current = look_host_label(looked)
    if current:
        skip.add(current)
    for url in RETAILER_FALLBACK_URLS:
        host = _url_host_label(url)
        if host and host not in skip:
            return url
    return None


def look_is_captcha(looked: dict[str, Any] | None) -> bool:
    """Sorry / captcha / I'm not a robot / unusual traffic — not THIS ask.

    google.com/sorry, a robot checkbox, or unusual-traffic copy is not a
    weather / hotel / shop result. Never click I'm not a robot. Never
    speak that page as the answer. Any find / search / use-Chrome job.
    """
    item = looked or {}
    url = str(item.get("url") or "")
    if re.search(r"google\.com/sorry|/sorry/index|/sorry\?", url, re.I):
        return True
    return bool(_CAPTCHA_RE.search(look_blob(item)))


def look_is_leftover_surface(looked: dict[str, Any] | None) -> bool:
    """chrome://extensions, settings, Thunar, Terminal — never type THIS ask.

    Internal Chromium pages and leftover desktop apps are not a search field.
    chrome://newtab / Untitled / New Tab are still opening, not leftover.
    Title-only for Terminal / Thunar so page text like 'airport terminal'
    is not leftover.
    """
    item = looked or {}
    title = str(item.get("title") or "").strip()
    url = str(item.get("url") or "")
    desc = str(item.get("vision_description") or "")
    if (
        _CHROME_INTERNAL_RE.search(url)
        or _CHROME_INTERNAL_RE.search(title)
        or _CHROME_INTERNAL_RE.search(desc)
    ):
        return True
    if title and _LEFTOVER_SURFACE_RE.search(title):
        return True
    return bool(re.search(r"\bublock(?:\s+origin)?\b", desc, re.I))


def _look_is_search_engine(looked: dict[str, Any] | None) -> bool:
    """Google / DuckDuckGo / Bing — a place to type THIS ask, not leftover."""
    item = looked or {}
    url = str(item.get("url") or "")
    try:
        from app.jarvis.serp import is_search_engine_url, look_is_serp

        if url and is_search_engine_url(url):
            return True
        return bool(look_is_serp(item))
    except Exception:
        return bool(
            re.search(r"\b(google|duckduckgo|bing)(?:\s+search)?\b", look_blob(item), re.I)
        )


def look_is_focused_new_tab(looked: dict[str, Any] | None) -> bool:
    """True when the focused window title is New Tab / Untitled / about:blank.

    Vision of leftover shop tabs plus a New Tab on the right is not enough —
    the focused title must leave the leftover host. HTTP 403 is never a new tab.
    chrome://extensions / settings / Thunar are never a new tab.
    A sorry / captcha look is never a new tab.
    """
    if (
        look_is_http_error(looked)
        or look_is_leftover_surface(looked)
        or look_is_captcha(looked)
    ):
        return False
    title = str((looked or {}).get("title") or "").strip()
    if not title:
        return False
    try:
        from app.jarvis.desktop import is_placeholder_title

        if is_placeholder_title(title):
            return True
    except Exception:
        pass
    return bool(re.search(r"^(new tab|untitled|about:blank)\b", title, re.I))


def look_has_unfocused_new_tab(looked: dict[str, Any] | None) -> bool:
    """True when a blank New Tab / Untitled sits unused and is not focused.

    leftover sorry / Extensions plus a New Tab on the strip is this — click
    that tab, do not Ctrl+T again, do not type into the focused leftover.
    """
    if look_is_focused_new_tab(looked):
        return False
    return bool(re.search(r"\b(?:new tab|untitled)\b", look_blob(looked), re.I))


def _topic_from(blob: str, table: tuple[tuple[str, re.Pattern[str]], ...]) -> str:
    for name, rx in table:
        if rx.search(blob or ""):
            return name
    return ""


def look_topic(looked: dict[str, Any] | None) -> str:
    return _topic_from(look_blob(looked), _LOOK_TOPIC_RES)


def ask_topic(asked: str) -> str:
    return _topic_from(asked or "", _ASK_TOPIC_RES)


def look_is_leftover_for_ask(looked: dict[str, Any] | None, asked: str) -> bool:
    """True when this look is a previous job's tab, not THIS ask.

    A leftover shop title vs a weather ask (or weather vs shop, hotel vs
    calculator) is not done. HTTP 403 leftovers are not done. chrome://
    extensions / settings, Thunar, Terminal, and any leftover title
    unrelated to THIS ask are not done. A sorry / captcha / I'm-not-a-robot
    look is not done. Untitled / blank / wallpaper are not leftover — they
    are still opening. A Booking.com homepage for a hotel ask is the same
    job, not leftover. An abuse / IP-block page is leftover even when the
    host is in the ask. A coolblue / amazon.nl look for a shop ask is the
    same cart job, not leftover. look_speed=off does not change this.
    """
    query = web_search_query(asked)
    if look_is_captcha(looked):
        return True
    if (
        ask_wants_cart(asked)
        and _look_is_search_engine(looked)
        and not look_is_nl_retailer(looked)
    ):
        # Google of the cart essay is leftover — stay on / return to the shop.
        # A Coolblue homepage that says "no search results" is not Google.
        return True
    if query_visible_on_look(looked, query):
        return False
    host = look_host_label(looked)
    raw_ask = (asked or "").lower()
    if host and host in raw_ask and not look_is_http_error(looked):
        return False
    if look_is_http_error(looked):
        return True
    if ask_wants_shop(asked) and look_is_nl_retailer(looked):
        # coolblue / amazon after a bol.com block is the same cart job.
        return False
    if look_is_leftover_surface(looked):
        return True
    if look_is_loading_or_blank(looked) or look_is_empty_desktop(looked):
        return False
    if look_is_focused_new_tab(looked):
        return False
    look_t = look_topic(looked)
    ask_t = ask_topic(asked)
    if look_t and ask_t and look_t == ask_t:
        return False
    if look_t and ask_t and look_t != ask_t:
        return True
    return _look_title_unrelated_to_ask(looked, asked, look_t, ask_t, query)


def _look_title_unrelated_to_ask(
    looked: dict[str, Any] | None,
    asked: str,
    look_t: str,
    ask_t: str,
    query: str,
) -> bool:
    """Loaded window whose title is not THIS ask — leftover. New tab / SERP no."""
    if look_t and ask_t and look_t == ask_t:
        return False
    if _look_is_search_engine(looked):
        return False
    title = str((looked or {}).get("title") or "").strip()
    if not title or _BROWSER_CHROME_TITLE_RE.search(title):
        return False
    if ask_t or distinctive_query_tokens(query):
        return True
    return False


def look_is_page_ready(
    looked: dict[str, Any] | None, asked: str = ""
) -> bool:
    """True when the window is THIS ask's loaded page, not leftover / blank.

    A leftover title that does not match this ask is not a ready page.
    """
    if asked and look_is_leftover_for_ask(looked, asked):
        return False
    if look_is_loading_or_blank(looked) or look_is_empty_desktop(looked):
        return False
    return look_is_web_page(looked) or search_box_point(looked) is not None


def look_is_web_page(looked: dict[str, Any] | None) -> bool:
    """True for a loaded site, not wallpaper, footer, or a blank/loading tab."""
    if look_is_empty_desktop(looked) or look_is_footer(looked):
        return False
    if look_is_loading_or_blank(looked):
        return False
    if (
        look_is_leftover_surface(looked)
        or look_is_captcha(looked)
        or look_is_http_error(looked)
    ):
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
    if look_is_captcha(looked):
        # Query tokens in a /sorry continue= URL are not results.
        return False
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
    A leftover tab from a previous job is not done.
    A sorry / captcha look is not done — even if the URL repeats the query.
    """
    if not (query or "").strip():
        return False
    if look_is_captcha(looked) or look_is_leftover_for_ask(looked, asked):
        return True
    if look_has_blocking_overlay(looked, goal=asked):
        # Genius / cookie / Restore still up — not done. URL tokens from
        # searchresults.html are not priced options.
        return True
    if ask_wants_hotel(asked) and look_is_travel_search_form(looked):
        # Homepage / empty date form — type destination + dates.
        return True
    if look_has_hotel_results(looked):
        return False
    if look_has_cart_results(looked):
        return False
    if ask_wants_cart(asked) and look_is_nl_retailer(looked):
        # Homepage / PDP / search after cookies — not done until two
        # priced basket lines. A typed query on the shop root is not done.
        return True
    if look_is_loading_or_blank(looked) or look_is_empty_desktop(looked):
        return True
    if look_is_empty_destination(looked) or look_is_footer(looked):
        return True
    # Hotel job on Booking whose URL repeats the ask is not done until
    # vision shows a named hotel and a price.
    if ask_wants_hotel(asked) and look_is_travel_site(looked):
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
    use BOOKING_DEST_CLICK (not mid-page 640,320 — that is the Genius
    airplane). Never on the footer or wallpaper.
    Never the I'm-not-a-robot checkbox.
    """
    if look_is_captcha(looked) or look_is_http_error(looked):
        return None
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
    if look_is_leftover_surface(looked):
        return None
    if _SEARCH_FIELD_RE.search(blob) or look_is_web_page(looked):
        if look_is_travel_search_form(looked):
            return BOOKING_DEST_CLICK
        if look_is_nl_retailer(looked) and not look_is_shop_pdp(looked):
            return COOLBLUE_SEARCH_CLICK
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


def _ok_act(result: dict[str, Any] | None) -> bool:
    return bool(result and result.get("ok"))


def _fill_travel_search_form(
    current: dict[str, Any],
    goal: str,
    *,
    click: Callable[..., dict[str, Any]],
    type_text: Callable[..., dict[str, Any]],
    keys: Callable[..., dict[str, Any]],
    look_again: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Click Booking destination + dates, type city and stay dates, submit.

    Mid-page (640, 320) hits the Genius airplane. Tab/focus + known field
    clicks land on Booking's React inputs. If the form is still empty after
    that, type the dated searchresults URL in the omnibox.
    """
    dest = hotel_destination(goal)
    checkin, checkout = hotel_stay_dates()
    dest_xy = search_box_point(current) or BOOKING_DEST_CLICK
    clicked = click(x=dest_xy[0], y=dest_xy[1])
    if not _ok_act(clicked):
        keys(combo="tab")
    else:
        _pause_after_web_act()
        keys(combo="ctrl+a")
    dest_typed = type_text(text=dest)
    dest_ok = _ok_act(dest_typed)
    click(x=BOOKING_DATES_CLICK[0], y=BOOKING_DATES_CLICK[1])
    _pause_after_web_act()
    in_typed = type_text(text=checkin.isoformat())
    keys(combo="tab")
    out_typed = type_text(text=checkout.isoformat())
    keys(combo="enter")
    click(x=BOOKING_SEARCH_CLICK[0], y=BOOKING_SEARCH_CLICK[1])
    ok = dest_ok or _ok_act(in_typed) or _ok_act(out_typed)
    query = hotel_typed_query(goal)
    if ok:
        current["_typed_query"] = query
    _pause_after_web_act()
    nxt = look_again() or current
    if ok:
        nxt["_typed_query"] = query
    if look_is_travel_search_form(nxt) and not look_has_hotel_results(nxt):
        # Clicks missed React fields — navigate with a clean dated URL.
        nxt, url_ok = _type_query_at(
            OMNIBOX_CLICK,
            hotel_travel_url(goal),
            nxt,
            click=click,
            type_text=type_text,
            keys=keys,
            look_again=look_again,
        )
        ok = ok or url_ok
    return nxt, ok


def _focus_hotel_alt_tab(
    current: dict[str, Any],
    goal: str,
    *,
    click: Callable[..., dict[str, Any]],
    type_text: Callable[..., dict[str, Any]],
    keys: Callable[..., dict[str, Any]],
    look_again: Callable[[], dict[str, Any]],
    open_url: Callable[[str], dict[str, Any]] | None = None,
    focus: Callable[..., dict[str, Any]] | None = None,
    fallback: bool = False,
) -> dict[str, Any]:
    """Raise the alt hotels tab. Booking must not stay focused.

    After run_app the new tab is usually rightmost. Click the strip,
    focus Chrome, then if see_screen is still Booking navigate this
    tab to the alt URL so the next look cannot be the homepage.
    Leave leftover Booking tabs in the background — do not ctrl+w
    the alt host.
    """
    if look_has_hotel_results(current) or look_is_hotel_alt_host(current):
        current["_hotel_alt"] = True
        return current
    if focus is not None:
        try:
            focus(app="chrome")
        except Exception:
            pass
        nxt = look_again() or current
        if look_has_hotel_results(nxt) or look_is_hotel_alt_host(nxt):
            nxt["_hotel_alt"] = True
            return nxt
        current = nxt
    for xy in reversed(NEW_TAB_FOCUS_CLICKS):
        click(x=xy[0], y=xy[1])
        _pause_after_web_act()
        nxt = look_again() or current
        if look_has_hotel_results(nxt) or look_is_hotel_alt_host(nxt):
            nxt["_hotel_alt"] = True
            return nxt
        current = nxt
    url = hotel_alt_fallback_url(goal) if fallback else hotel_alt_travel_url(goal)
    nxt, _ = _type_query_at(
        OMNIBOX_CLICK,
        url,
        current,
        click=click,
        type_text=type_text,
        keys=keys,
        look_again=look_again,
    )
    nxt["_hotel_alt"] = True
    if fallback:
        nxt["_hotel_alt_fallback"] = True
    return nxt


def _reopen_dated_hotel_search(
    current: dict[str, Any],
    goal: str,
    *,
    click: Callable[..., dict[str, Any]],
    type_text: Callable[..., dict[str, Any]],
    keys: Callable[..., dict[str, Any]],
    look_again: Callable[[], dict[str, Any]],
    open_url: Callable[[str], dict[str, Any]] | None = None,
    focus: Callable[..., dict[str, Any]] | None = None,
    alt: bool = False,
    fill: bool = True,
    fallback: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Homepage bounce after a dated search: run_app the URL, Search, or omnibox.

    Prefer run_app of the dated searchresults.html URL — clicking Search
    with blank dest/dates stays on index, and omnibox type often misses.
    After a confirmed bounce, ``alt`` opens Google /travel/hotels
    immediately. ``fallback`` opens the DuckDuckGo HTML hotels list
    (the URL that paints names+prices when Travel stays blank).
    Skip the dest/dates fill when ``fill`` is false so bounce recovery
    does not burn the ask budget on Booking alone.
    After alt run_app, a Booking look is the wrong tab — focus / click
    the new tab or omnibox-navigate to the alt URL. Do not treat a
    leftover searchresults pending look as the alt page.
    Do not treat an empty dest/dates index as typed-success.
    """
    query = hotel_typed_query(goal)
    if fallback:
        url = hotel_alt_fallback_url(goal)
    elif alt:
        url = hotel_alt_travel_url(goal)
    else:
        url = hotel_travel_url(goal)
    nxt = current
    if open_url is not None:
        opened = open_url(url)
        _pause_after_web_act()
        nxt = look_again() or current
        if current.get("_typed_query"):
            nxt["_typed_query"] = current.get("_typed_query") or query
        nxt["_hotel_reopened"] = True
        if alt or fallback:
            nxt["_hotel_alt"] = True
        if fallback:
            nxt["_hotel_alt_fallback"] = True
        if look_has_hotel_results(nxt):
            return nxt, bool(opened is None or opened.get("ok", True))
        if (alt or fallback) and look_lost_hotel_alt(nxt):
            nxt = _focus_hotel_alt_tab(
                nxt,
                goal,
                click=click,
                type_text=type_text,
                keys=keys,
                look_again=look_again,
                open_url=open_url,
                focus=focus,
                fallback=fallback,
            )
            return nxt, True
        if (alt or fallback) and look_is_hotel_alt_host(nxt):
            return nxt, True
        if not alt and not fallback and look_is_hotel_search_pending(nxt):
            return nxt, bool(opened is None or opened.get("ok", True))
        current = nxt
    if not alt and not fallback and fill:
        nxt, _filled = _fill_travel_search_form(
            current,
            goal,
            click=click,
            type_text=type_text,
            keys=keys,
            look_again=look_again,
        )
        nxt["_hotel_reopened"] = True
        if look_has_hotel_results(nxt) or look_is_hotel_search_pending(nxt):
            return nxt, True
        current = nxt
    nxt, ok = _type_query_at(
        OMNIBOX_CLICK,
        url,
        current,
        click=click,
        type_text=type_text,
        keys=keys,
        look_again=look_again,
    )
    nxt["_hotel_reopened"] = True
    if alt or fallback:
        nxt["_hotel_alt"] = True
    if fallback:
        nxt["_hotel_alt_fallback"] = True
    if ok:
        nxt["_typed_query"] = query
    elif current.get("_typed_query"):
        nxt["_typed_query"] = current["_typed_query"]
    return nxt, ok


def _focus_new_tab(
    current: dict[str, Any],
    *,
    goal: str,
    click: Callable[..., dict[str, Any]],
    keys: Callable[..., dict[str, Any]],
    look_again: Callable[[], dict[str, Any]],
    already_opened: bool = False,
) -> dict[str, Any]:
    """Ctrl+T once, then click/look until New Tab is focused. Never spray tabs.

    keys(ctrl+t) often does not change the focused tab in this Chromium —
    look_again still sees the leftover host. Click the new tab and look
    until the title is New Tab / Untitled, not the leftover host.
    """
    if not already_opened:
        keys(combo="ctrl+t")
        _pause_after_web_act()
        nxt = look_again() or current
        nxt["_opened_new_tab"] = True
        if look_is_focused_new_tab(nxt):
            return nxt
        current = nxt
    current["_opened_new_tab"] = True
    opened = bool(already_opened or current.get("_opened_new_tab"))
    for xy in NEW_TAB_FOCUS_CLICKS:
        if look_is_focused_new_tab(current):
            return current
        stuck_on_wrong = (
            look_is_leftover_for_ask(current, goal)
            or look_is_http_error(current)
            or look_is_captcha(current)
        )
        if not stuck_on_wrong and not (
            opened and look_is_loading_or_blank(current)
        ):
            return current
        click(x=xy[0], y=xy[1])
        _pause_after_web_act()
        nxt = look_again() or current
        nxt["_opened_new_tab"] = True
        current = nxt
    return current


def _type_new_tab_or_omnibox(
    query: str,
    current: dict[str, Any],
    *,
    goal: str,
    click: Callable[..., dict[str, Any]],
    type_text: Callable[..., dict[str, Any]],
    keys: Callable[..., dict[str, Any]],
    look_again: Callable[[], dict[str, Any]],
    already_opened: bool = False,
    require_new_tab: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Leftover tab: one Ctrl+T, focus New Tab, then omnibox-type THIS ask.

    require_new_tab (captcha / sorry): never type until the title is New Tab
    / Untitled. Typing into the leftover sorry omnibox is a fail.
    """
    current = _focus_new_tab(
        current,
        goal=goal,
        click=click,
        keys=keys,
        look_again=look_again,
        already_opened=already_opened,
    )
    if require_new_tab and not look_is_focused_new_tab(current):
        return current, False
    if look_is_leftover_for_ask(current, goal) and not look_is_focused_new_tab(
        current
    ):
        # Do not type into leftover 403 / shop / sorry. Ctrl+T without focus
        # is a fail.
        return current, False
    return _type_query_at(
        OMNIBOX_CLICK,
        query,
        current,
        click=click,
        type_text=type_text,
        keys=keys,
        look_again=look_again,
    )


def continue_web_search(
    looked: dict[str, Any] | None,
    *,
    goal: str,
    click: Callable[..., dict[str, Any]],
    type_text: Callable[..., dict[str, Any]],
    keys: Callable[..., dict[str, Any]],
    look_again: Callable[[], dict[str, Any]],
    scroll: Callable[..., dict[str, Any]] | None = None,
    open_url: Callable[[str], dict[str, Any]] | None = None,
    focus: Callable[..., dict[str, Any]] | None = None,
    max_rounds: int = 3,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Wait until the page is ready, click the field, type, Enter. Never pay.

    Product path after overlays. look_speed=off does not skip this.
    Sleep seconds between looks (not 0.4s) until a loaded page or ``deadline``.
    A blank / Untitled / loading look is not done — look again.     A leftover
    tab from a previous job is not done — Ctrl+T once, focus New Tab, then
    omnibox-type THIS ask, then look again. A sorry / captcha look after
    type is not success — Ctrl+T once, click until New Tab is focused,
    then type THIS ask on DuckDuckGo, Bing, or a weather site. Never type
    into the leftover sorry tab. Never click I'm not a robot. A first
    failed focus is not done — keep clicking; do not give up in under
    ~30s. After a few still-blank looks, type the query into the Chromium
    omnibox.     Never return without type when a query is needed. A homepage
    that never says "search box" still types. Footer looks Home first —
    never (640, 320) on copyright. After a dated Booking search, keep
    looking until a named hotel + stay price. A searchresults bounce
    back to index / list-your-property / Genius homepage re-opens the
    dated Booking URL once, then immediately run_app Google /travel/hotels.
    After that alt opens, focus that tab and keep looking until priced
    names, captcha/sorry, or the budget ends. A Booking homepage look
    after the alt is the wrong tab — refocus / reopen the alt, never
    finalize typed-search. If Google Travel stays blank, open the
    DuckDuckGo HTML hotels list (the URL that paints on this host).
    Do not spend the whole first-attempt budget on Booking alone.
    A shop IP-block / abuse / access-denied look is not typed-success —
    immediately run_app coolblue.nl, then amazon.nl, and keep the same
    cart job.     A Coolblue cookie card that survives the first dismiss
    clicks is the same — fall back to amazon.nl. Never burn the nginx
    180s on Escape / Home. After cookies, a cart / basket job must
    search real products, open a PDP, add two different items, and
    open the basket. Never finalize typed-search on the shop homepage.
    Speak stuck only after those fallbacks fail.
    """
    query = web_search_query(goal)
    if ask_wants_hotel(goal):
        type_query = hotel_typed_query(goal)
    elif ask_wants_shop(goal):
        type_query = shop_typed_query(goal) or query
    else:
        type_query = query
    current = dict(looked or {})
    blob = look_blob(current)
    if ask_wants_payment(goal):
        return current
    if look_is_pay_control(blob, goal) and "hotel" not in blob.lower():
        return current
    if not (query or type_query or "").strip():
        return current
    typed_query = bool(current.get("_typed_query"))
    opened_new_tab = bool(current.get("_opened_new_tab"))
    captcha_retried = bool(current.get("_captcha_retried"))
    hotel_followed = bool(current.get("_hotel_followed"))
    saw_searchresults = bool(current.get("_saw_searchresults"))
    hotel_alt = bool(current.get("_hotel_alt"))
    hotel_alt_fallback = bool(current.get("_hotel_alt_fallback"))
    retailer_tried = list(current.get("_retailer_tried") or [])
    retailer_blocked = bool(current.get("_retailer_blocked"))
    captcha_focus_started: float | None = None
    blank_looks = 0
    overlay_dismisses = 0
    memory_dismisses = 0
    hotel_reopens = int(current.get("_hotel_reopens") or 0)
    hotel_alt_looks = int(current.get("_hotel_alt_looks") or 0)
    if ask_wants_hotel(goal) and (
        look_is_booking_searchresults(current)
        or look_is_hotel_search_pending(current)
        or saw_searchresults
    ):
        # run_app already opened the dated list — keep looking / recover.
        # A later homepage look still carries _saw_searchresults.
        typed_query = True
        saw_searchresults = True
        current["_typed_query"] = type_query or query
        current["_saw_searchresults"] = True
    if deadline is not None:
        limit = 64
    else:
        limit = max(int(max_rounds), BLANK_LOOKS_BEFORE_OMNIBOX)

    def _mark(item: dict[str, Any]) -> dict[str, Any]:
        if typed_query:
            item["_typed_query"] = type_query or query
        if opened_new_tab:
            item["_opened_new_tab"] = True
        if captcha_retried:
            item["_captcha_retried"] = True
        if hotel_followed:
            item["_hotel_followed"] = True
        if saw_searchresults:
            item["_saw_searchresults"] = True
        if hotel_reopens:
            item["_hotel_reopened"] = True
            item["_hotel_reopens"] = hotel_reopens
        if hotel_alt:
            item["_hotel_alt"] = True
            item["_hotel_alt_looks"] = hotel_alt_looks
        if hotel_alt_fallback:
            item["_hotel_alt_fallback"] = True
        if retailer_tried:
            item["_retailer_tried"] = list(retailer_tried)
        if retailer_blocked:
            item["_retailer_blocked"] = True
        for key in (
            "_cart_adds",
            "_cart_searches",
            "_cart_pdps",
            "_cart_opened_basket",
        ):
            val = item.get(key, current.get(key))
            if val:
                item[key] = val
        return item

    def _open_retailer_fallback(*, force: bool = False) -> bool:
        nonlocal current, retailer_tried, typed_query, overlay_dismisses
        if not ask_wants_shop(goal):
            return False
        if not force and not look_is_retailer_block(current):
            return False
        if open_url is None:
            return False
        while True:
            url = next_retailer_fallback_url(current, retailer_tried)
            if not url:
                return False
            opened = open_url(url)
            retailer_tried.append(url)
            if opened and opened.get("ok"):
                break
        _pause_after_web_act()
        nxt = look_again() or current
        nxt["_retailer_tried"] = list(retailer_tried)
        current = nxt
        typed_query = False
        overlay_dismisses = 0
        current["_cart_adds"] = 0
        current["_cart_searches"] = 0
        current["_cart_pdps"] = []
        return True

    for i in range(limit):
        blob = look_blob(current)
        if ask_wants_payment(goal):
            return _mark(current)
        if look_is_pay_control(blob, goal) and "hotel" not in blob.lower():
            return _mark(current)
        if look_has_cart_results(current):
            return _mark(current)
        if ask_wants_shop(goal) and look_is_retailer_block(current):
            # Leave the dead shop immediately. Do not type into the
            # block page. Do not dismiss overlays on a wall.
            if _open_retailer_fallback():
                continue
            if open_url is not None:
                retailer_blocked = True
                current["_retailer_blocked"] = True
                return _mark(current)
        plan = overlay_dismiss_plan(
            current, goal=goal, dismisses=overlay_dismisses
        )
        memory_toast = plan is not None and plan.kind == "memory_saver"
        if memory_toast and memory_dismisses >= MEMORY_SAVER_DISMISS_MAX:
            # Toast already clicked — do not loop No thanks forever.
            plan = None
            memory_toast = False
        if (
            plan is not None
            and plan.kind == "cookie"
            and overlay_dismisses >= OVERLAY_DISMISS_MAX
            and ask_wants_cart(goal)
        ):
            # Cookie still up after Alles accepteren / Weigeren clicks.
            # Do not Home-loop the modal until nginx 504 — open amazon.nl.
            if _open_retailer_fallback(force=True):
                continue
            retailer_blocked = True
            current["_retailer_blocked"] = True
            return _mark(current)
        if (
            plan is not None
            and (memory_toast or overlay_dismisses < OVERLAY_DISMISS_MAX)
            and not (_deadline_passed(deadline) and not typed_query)
        ):
            # Real Sign-in / cookie / Restore / Memory Saver. A Genius
            # homepage banner is not this — overlay_kind skips it so we
            # reach the form. Memory Saver does not consume the modal
            # dismiss budget — it steals focus from the search.
            if memory_toast:
                memory_dismisses += 1
            else:
                overlay_dismisses += 1
            if plan.click is not None:
                click(x=plan.click[0], y=plan.click[1])
            if plan.keys:
                keys(combo=plan.keys)
            _pause_after_web_act()
            current = _mark(look_again() or current)
            continue
        if look_is_captcha(current):
            if captcha_focus_started is None:
                captcha_focus_started = time.monotonic()
            if captcha_retried:
                # Alt URL was typed on a focused New Tab; still sorry — wait,
                # do not speak stuck while a blank New Tab sits unused.
                if _deadline_passed(deadline) or i >= BLANK_LOOKS_BEFORE_OMNIBOX:
                    return _mark(current)
                _pause_for_page_load()
                current = _mark(look_again() or current)
                continue
            already = opened_new_tab or look_has_unfocused_new_tab(current)
            current, alt_typed = _type_new_tab_or_omnibox(
                alt_web_search_typed(query, goal),
                current,
                goal=goal,
                click=click,
                type_text=type_text,
                keys=keys,
                look_again=look_again,
                already_opened=already,
                require_new_tab=True,
            )
            opened_new_tab = True
            if alt_typed:
                typed_query = True
                captcha_retried = True
                continue
            # First failed focus: click again. Do not type into sorry.
            # Do not give up in under ~30s. look_speed=off does not skip.
            waited = time.monotonic() - captcha_focus_started
            min_s = 0.0 if _in_pytest() else CAPTCHA_FOCUS_MIN_S
            if (
                not _in_pytest()
                and _deadline_passed(deadline)
                and waited >= min_s
            ):
                return _mark(current)
            _pause_for_page_load()
            continue
        if look_is_leftover_for_ask(current, goal) and not typed_query:
            if (
                ask_wants_cart(goal)
                and _look_is_search_engine(current)
                and open_url is not None
            ):
                url = shop_home_url(goal)
                if url:
                    opened = open_url(url)
                    if opened and opened.get("ok"):
                        _pause_after_web_act()
                        current = look_again() or current
                        typed_query = False
                        continue
            current, typed_query = _type_new_tab_or_omnibox(
                type_query or query,
                current,
                goal=goal,
                click=click,
                type_text=type_text,
                keys=keys,
                look_again=look_again,
                already_opened=opened_new_tab,
            )
            opened_new_tab = True
            continue
        if look_has_hotel_results(current) and not look_is_travel_search_form(
            current
        ):
            return _mark(current)
        if needs_hotel_followthrough(goal, current, query) and not hotel_followed:
            # First Google SERP / focused-window caption is not done.
            # Type a Booking URL with real dates (or dates on the SERP).
            current, typed_query = _advance_unfinished_hotel(
                current,
                goal,
                type_query or query,
                click=click,
                type_text=type_text,
                keys=keys,
                look_again=look_again,
            )
            hotel_followed = True
            continue
        if look_is_booking_searchresults(current) or look_is_hotel_search_pending(
            current
        ):
            saw_searchresults = True
        if ask_wants_cart(goal) and needs_cart_followthrough(goal, current):
            if _deadline_passed(deadline):
                if int(current.get("_cart_adds") or 0) >= CART_ADD_TARGET:
                    current, _ = _advance_unfinished_cart(
                        current,
                        goal,
                        click=click,
                        type_text=type_text,
                        keys=keys,
                        look_again=look_again,
                        open_url=open_url,
                    )
                return _mark(current)
            current, progressed = _advance_unfinished_cart(
                current,
                goal,
                click=click,
                type_text=type_text,
                keys=keys,
                look_again=look_again,
                open_url=open_url,
            )
            if look_has_cart_results(current):
                return _mark(current)
            if progressed:
                typed_query = True
                continue
            if _deadline_passed(deadline):
                return _mark(current)
            _pause_for_page_load()
            current = _mark(look_again() or current)
            continue
        if not needs_web_query(goal, current, query):
            return _mark(current)

        def _open_hotel_alt(*, fallback: bool = False) -> bool:
            nonlocal current, hotel_alt, typed_query, hotel_alt_looks
            nonlocal hotel_alt_fallback
            if not ask_wants_hotel(goal):
                return False
            if look_has_hotel_results(current):
                return False
            if fallback:
                if hotel_alt_fallback or not hotel_alt:
                    return False
            elif hotel_alt or HOTEL_SEARCH_ALT_MAX <= 0:
                return False
            current, reopened = _reopen_dated_hotel_search(
                current,
                goal,
                click=click,
                type_text=type_text,
                keys=keys,
                look_again=look_again,
                open_url=open_url,
                focus=focus,
                alt=True,
                fill=False,
                fallback=fallback,
            )
            hotel_alt = True
            hotel_alt_looks = 0
            if fallback:
                hotel_alt_fallback = True
            typed_query = typed_query or reopened
            return True

        if typed_query:
            if look_has_hotel_results(current) and not look_is_travel_search_form(
                current
            ):
                return _mark(current)
            if ask_wants_hotel(goal) and not look_has_hotel_results(current):
                # After dest/dates or a searchresults URL, keep looking
                # until named hotel + stay price. Homepage / list-your-
                # property after a searchresults look is a bounce — one
                # Booking reopen, then immediately Google /travel/hotels.
                # After the alt opens, hold that tab. Do not switch back
                # to Booking. Do not return typed-search while Travel is
                # blank. Do not return on deadline before the alt runs.
                on_form = look_is_travel_search_form(current)
                bounced = look_is_booking_bounce(
                    current, saw_searchresults=saw_searchresults
                )
                bounce_confirmed = bool(bounced or saw_searchresults)
                if hotel_alt and not look_has_hotel_results(current):
                    if look_lost_hotel_alt(current):
                        current = _focus_hotel_alt_tab(
                            current,
                            goal,
                            click=click,
                            type_text=type_text,
                            keys=keys,
                            look_again=look_again,
                            open_url=open_url,
                            focus=focus,
                            fallback=hotel_alt_fallback,
                        )
                        hotel_alt_looks = 0
                        if current.get("_hotel_alt_fallback"):
                            hotel_alt_fallback = True
                        continue
                    hotel_alt_looks += 1
                    if look_has_hotel_results(current):
                        return _mark(current)
                    blank_alt = look_is_hotel_alt_host(
                        current
                    ) and not look_has_hotel_results(current)
                    if (
                        blank_alt
                        and not hotel_alt_fallback
                        and hotel_alt_looks >= HOTEL_ALT_BLANK_BEFORE_FALLBACK
                        and _open_hotel_alt(fallback=True)
                    ):
                        continue
                    if (
                        hotel_alt_looks < HOTEL_ALT_LOOKS_MAX
                        or not _deadline_passed(deadline)
                    ):
                        _pause_for_page_load()
                        current = _mark(look_again() or current)
                        continue
                    # Budget ended still blank — never reopen Booking.
                    current["_hotel_bounced"] = True
                    current["_hotel_reopened"] = True
                    return _mark(current)
                if on_form or bounced:
                    if (
                        bounce_confirmed
                        and hotel_reopens >= HOTEL_BOUNCE_BOOKING_BEFORE_ALT
                        and _open_hotel_alt()
                    ):
                        continue
                    if hotel_reopens < HOTEL_SEARCH_REOPEN_MAX:
                        current, reopened = _reopen_dated_hotel_search(
                            current,
                            goal,
                            click=click,
                            type_text=type_text,
                            keys=keys,
                            look_again=look_again,
                            open_url=open_url,
                            focus=focus,
                            alt=False,
                            fill=not bounce_confirmed or open_url is None,
                        )
                        hotel_reopens += 1
                        typed_query = typed_query or reopened
                        if (
                            bounce_confirmed
                            and (
                                look_is_booking_bounce(
                                    current, saw_searchresults=True
                                )
                                or look_is_travel_search_form(current)
                            )
                            and _open_hotel_alt()
                        ):
                            continue
                        continue
                    if _open_hotel_alt():
                        continue
                    current["_hotel_bounced"] = True
                    current["_hotel_reopened"] = True
                    return _mark(current)
                if _deadline_passed(deadline):
                    if bounce_confirmed and _open_hotel_alt():
                        continue
                    return _mark(current)
                _pause_for_page_load()
                current = _mark(look_again() or current)
                continue
            if _deadline_passed(deadline) or i >= BLANK_LOOKS_BEFORE_OMNIBOX:
                if ask_wants_hotel(goal) and saw_searchresults and _open_hotel_alt():
                    continue
                if ask_wants_cart(goal) and needs_cart_followthrough(goal, current):
                    current, progressed = _advance_unfinished_cart(
                        current,
                        goal,
                        click=click,
                        type_text=type_text,
                        keys=keys,
                        look_again=look_again,
                        open_url=open_url,
                    )
                    if look_has_cart_results(current) or progressed:
                        continue
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
            if ask_wants_hotel(goal) and look_is_travel_search_form(current):
                current, typed_query = _fill_travel_search_form(
                    current,
                    goal,
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
                    type_query or query,
                    current,
                    click=click,
                    type_text=type_text,
                    keys=keys,
                    look_again=look_again,
                )
            continue

        if ask_wants_hotel(goal) and look_is_travel_search_form(current):
            current, typed_query = _fill_travel_search_form(
                current,
                goal,
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
                type_query or query,
                current,
                click=click,
                type_text=type_text,
                keys=keys,
                look_again=look_again,
            )
            continue

        blank_looks += 1
        last = i >= limit - 1
        if ask_wants_hotel(goal) and (
            look_is_hotel_search_pending(current)
            or look_is_booking_searchresults(current)
            or look_is_travel_search_form(current)
        ):
            # Do not type dest text into the omnibox and return — that
            # abandons a dated searchresults tab. Wait or reopen.
            if look_is_travel_search_form(current) and not typed_query:
                current, typed_query = _fill_travel_search_form(
                    current,
                    goal,
                    click=click,
                    type_text=type_text,
                    keys=keys,
                    look_again=look_again,
                )
                continue
            typed_query = True
            current["_typed_query"] = type_query or query
            if look_is_booking_searchresults(
                current
            ) or look_is_hotel_search_pending(current):
                saw_searchresults = True
            if _deadline_passed(deadline):
                if saw_searchresults and _open_hotel_alt():
                    continue
                return _mark(current)
            _pause_for_page_load()
            current = _mark(look_again() or current)
            continue
        if (
            blank_looks >= BLANK_LOOKS_BEFORE_OMNIBOX
            or _deadline_passed(deadline)
            or last
        ):
            if ask_wants_cart(goal) and look_is_nl_retailer(current):
                # Stay on the shop. Never omnibox-Google the cart ask.
                xy = search_box_point(current)
                if xy is None and look_is_web_page(current):
                    xy = SEARCH_BOX_CLICK
                if xy is not None:
                    current, typed_query = _type_query_at(
                        xy,
                        type_query or query,
                        current,
                        click=click,
                        type_text=type_text,
                        keys=keys,
                        look_again=look_again,
                    )
                    continue
                return _mark(current)
            current, typed_query = _type_query_at(
                OMNIBOX_CLICK,
                type_query or query,
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
        if look_is_leftover_for_ask(current, goal) and not look_is_focused_new_tab(
            current
        ):
            return _mark(current)
        if ask_wants_cart(goal) and look_is_nl_retailer(current):
            xy = search_box_point(current)
            if xy is None and look_is_web_page(current):
                xy = SEARCH_BOX_CLICK
            if xy is not None:
                current, typed_query = _type_query_at(
                    xy,
                    type_query or query,
                    current,
                    click=click,
                    type_text=type_text,
                    keys=keys,
                    look_again=look_again,
                )
            return _mark(current)
        current, typed_query = _type_query_at(
            OMNIBOX_CLICK,
            type_query or query,
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
    for i in range(max(1, int(max_rounds))):
        plan = overlay_dismiss_plan(current, goal=goal, dismisses=i)
        if plan is None:
            return current
        if plan.click is not None:
            click(x=plan.click[0], y=plan.click[1])
        if plan.keys:
            keys(combo=plan.keys)
        current = look_again() or current
    return current


def alt_web_search_typed(query: str, asked: str = "") -> str:
    """Omnibox text after captcha: DuckDuckGo / Bing / weather, never Google."""
    q = (query or "").strip() or web_search_query(asked)
    encoded = quote_plus(q)
    if ask_topic(asked) == "weather" or re.search(
        r"\b(weather|forecast)\b", q, re.I
    ):
        return f"https://duckduckgo.com/?q={encoded}"
    return f"https://www.bing.com/search?q={encoded}"


def _click_xy(
    xy: tuple[int, int],
    current: dict[str, Any],
    *,
    click: Callable[..., dict[str, Any]],
    look_again: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    clicked = click(x=xy[0], y=xy[1])
    if not _ok_act(clicked):
        return current, False
    _pause_after_web_act()
    return look_again() or current, True


def _advance_unfinished_cart(
    current: dict[str, Any],
    goal: str,
    *,
    click: Callable[..., dict[str, Any]],
    type_text: Callable[..., dict[str, Any]],
    keys: Callable[..., dict[str, Any]],
    look_again: Callable[[], dict[str, Any]],
    open_url: Callable[[str], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Search → PDP → add → other item → basket. Never typed-search-and-quit.

    One action per call. Two different in-stock products, then open the
    basket. Stop before payment — do not click checkout.
    """
    added = int(current.get("_cart_adds") or 0)
    searches = int(current.get("_cart_searches") or 0)
    pdps = list(current.get("_cart_pdps") or [])
    queries = shop_cart_queries(goal)

    def _stamp(item: dict[str, Any]) -> dict[str, Any]:
        item["_cart_adds"] = added
        item["_cart_searches"] = searches
        if pdps:
            item["_cart_pdps"] = list(pdps)
        if current.get("_typed_query"):
            item["_typed_query"] = current.get("_typed_query")
        return item

    if look_has_cart_results(current):
        return _stamp(current), False

    if added >= CART_ADD_TARGET:
        url = shop_basket_url(current, goal)
        if open_url is not None:
            opened = open_url(url)
            if opened and opened.get("ok"):
                _pause_after_web_act()
                nxt = _stamp(look_again() or current)
                nxt["_cart_opened_basket"] = True
                return nxt, True
        nxt, ok = _click_xy(
            basket_icon_point(current),
            current,
            click=click,
            look_again=look_again,
        )
        nxt = _stamp(nxt)
        nxt["_cart_opened_basket"] = True
        return nxt, ok

    if look_is_shop_pdp(current):
        url = str(current.get("url") or "")
        if url and url in pdps:
            q = queries[min(searches, len(queries) - 1)]
            nxt, typed = _type_query_at(
                shop_search_click(current),
                q,
                current,
                click=click,
                type_text=type_text,
                keys=keys,
                look_again=look_again,
            )
            if typed:
                searches += 1
                nxt["_typed_query"] = q
            return _stamp(nxt), typed
        xy = add_to_basket_point(current)
        if xy is None:
            return _stamp(current), False
        nxt, ok = _click_xy(xy, current, click=click, look_again=look_again)
        if ok:
            added += 1
            if url:
                pdps.append(url)
        return _stamp(nxt), ok

    if look_is_shop_search(current):
        xy = product_tile_point(current, index=added)
        if xy is None:
            return _stamp(current), False
        nxt, ok = _click_xy(xy, current, click=click, look_again=look_again)
        return _stamp(nxt), ok

    if look_is_footer(current):
        keys(combo="home")
        _pause_after_web_act()
        current = look_again() or current

    q = queries[min(searches, len(queries) - 1)]
    xy = shop_search_click(current)
    nxt, typed = _type_query_at(
        xy,
        q,
        current,
        click=click,
        type_text=type_text,
        keys=keys,
        look_again=look_again,
    )
    if typed:
        searches += 1
        nxt["_typed_query"] = q
    return _stamp(nxt), typed


def _advance_unfinished_hotel(
    current: dict[str, Any],
    goal: str,
    query: str,
    *,
    click: Callable[..., dict[str, Any]],
    type_text: Callable[..., dict[str, Any]],
    keys: Callable[..., dict[str, Any]],
    look_again: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Leave a hotel-less Google SERP: Booking URL with dates, or type dates."""
    url = hotel_travel_url(goal)
    nxt, typed = _type_query_at(
        OMNIBOX_CLICK,
        url,
        current,
        click=click,
        type_text=type_text,
        keys=keys,
        look_again=look_again,
    )
    if typed:
        nxt["_hotel_followed"] = True
        return nxt, True
    dates = hotel_date_query()
    refined = hotel_typed_query(goal) or f"{query} {dates}".strip()
    xy = search_box_point(current) or OMNIBOX_CLICK
    nxt, typed = _type_query_at(
        xy,
        refined,
        current,
        click=click,
        type_text=type_text,
        keys=keys,
        look_again=look_again,
    )
    if typed:
        nxt["_hotel_followed"] = True
    return nxt, typed


def _clauses_with_search_tokens(text: str) -> str:
    """Drop coaching-only sentences. Keep destination / budget / dates."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    if len(parts) <= 1:
        return text
    kept = [part for part in parts if distinctive_query_tokens(part)]
    return " ".join(kept) if kept else text


def web_search_query(asked: str) -> str:
    """User query tokens only: destination + budget + dates, never coaching.

    'Use the computer' / 'Look, click and type like a person' / Open Chrome
    / dismiss popups / Do not invent / reply with N options are coaching,
    not the search. Any find / search / use-Chrome job.
    """
    raw = (asked or "").strip()
    raw = _COACHING_PHRASE_RE.sub(" ", raw)
    raw = _clauses_with_search_tokens(raw)
    raw = re.sub(
        r"\b(please|can you|could you|on (?:the|your) (?:screen|computer)|"
        r"using chrome|use chrome|in chrome|with chrome|"
        r"use the computer|using the computer)\b",
        " ",
        raw,
        flags=re.I,
    )
    raw = _COACHING_LEFTOVER_RE.sub(" ", raw)
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
    if raw:
        return raw
    # Never fall back to the coaching sentence / Open Chrome.
    if _COACHING_PHRASE_RE.search(asked or "") or _COACHING_LEFTOVER_RE.search(
        asked or ""
    ):
        return ""
    return (asked or "").strip()
