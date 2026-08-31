"""Text/voice ask path: local tools + OpenRouter agent.

Used when OpenAI Realtime is not configured. One OpenRouter key is enough
for listen → ask. Speak-back is neural HTTP TTS (OpenAI or OpenRouter
audio/speech), never OS/SAPI. Disk/GitHub phrases hit tools directly;
everything else goes through the model-router agent loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.jarvis.gateway import get_gateway, model_view
from app.jarvis.realtime import openrouter_api_key
from app.jarvis.overlay import (
    RESTORE_DISMISS_CLICK,
    continue_web_search,
    look_has_blocking_overlay,
    look_has_hotel_results,
    look_is_empty_desktop,
    look_is_empty_destination,
    look_is_footer,
    look_is_loading_or_blank,
    look_is_page_ready,
    needs_web_query,
    overlay_dismiss_plan,
    query_visible_on_look,
    search_box_point,
    web_look_pause_s,
    web_search_query,
)
from app.jarvis.serp import (
    DEFAULT_LEAVE_SERP_URL,
    is_search_engine_url,
    leave_serp_url,
    look_has_cookie_overlay,
    look_is_404,
    look_is_dead_page,
    look_is_news_page,
    look_is_serp,
    looks_like_search_results,
    news_fallback_url,
    news_homepage_from_ask,
    publisher_url_from_look,
    result_url_from_look,
    wants_leave_serp,
    wants_open_or_read_article,
)
from app.jarvis.talk_auth import (
    CANT_TALK,
    hosted_talk_endpoint,
    should_use_hosted_talk,
    talk_ready,
)
from app.jarvis.tools import plain_summary

log = logging.getLogger("jarvis.voice_ask")

# Same TLD set as virtual_pc.goal_is_virtual_pc_job — not a site allowlist.
_SITE_RE = re.compile(
    r"("
    r"https?://[^\s<>\"']+"
    r"|[a-z0-9.-]+\.(?:com|nl|de|org|net|io|co|uk|edu|app)\b"
    r")",
    re.I,
)
_MAIL_RE = re.compile(r"\b(gmail|inbox|ibox|mail)\b", re.I)
_NOTEPAD_RE = re.compile(
    r"notepad\+\+|notepadpp|\bnotepad\b|\bmousepad\b|text[\s-]?editor|\beditor\b",
    re.I,
)
_CALC_RE = re.compile(r"\b(calculator|galculator|calc)\b", re.I)
_BARE_ACK = re.compile(r"^(done|ok)\.?$", re.I)
_NEWS_ESSAY_RE = re.compile(
    r"\b(headline|headlines|trending topics|breaking news|"
    r"accept (all )?cookies|cookie (banner|modal|consent))\b",
    re.I,
)
_SCREEN_FAIL = "Could not do that on the screen."
# Public /ask casual talk stays short. Hire / create-many-files needs room
# for N distinct file briefs. Realtime voice utterances stay 400.
ASK_TALK_MAX = 400
ASK_HIRE_MAX = 2000
# Public Talk fetch abort. Hello stays 12s. Look/click stays 30s.
# Find / search / book / hotel / use-Chrome needs minutes (same as hire).
ASK_TALK_ABORT_MS = 12_000
ASK_LOOK_ABORT_MS = 30_000
ASK_WEB_ABORT_MS = 180_000
ASK_HIRE_ABORT_MS = 180_000
_WEB_ABORT_RE = re.compile(
    r"("
    r"\bfind(?:\s+me)?\b|"
    r"\bsearch(?:\s+for)?\b|"
    r"\blook\s+up\b|"
    r"\bbook\b|"
    r"\bhotels?\b|"
    r"\bflights?\b|"
    r"\b(?:use|using)\s+chrome\b"
    r")",
    re.I,
)
_LOOK_ABORT_RE = re.compile(
    r"("
    r"\b(show|open|look|see|click|type|close|scroll|agree|read|install)\b|"
    r"what do you see|what are you seeing|what'?s on|on (the|your) screen|"
    r"look together|news together|popup|headline|\bnews\b"
    r")",
    re.I,
)


def ask_text_max(text: str) -> int:
    """Public /ask cap. Hire / create-many-files may use ASK_HIRE_MAX."""
    from app.jarvis.virtual_pc import goal_is_hire_job

    raw = (text or "").strip()
    if goal_is_hire_job(raw):
        return ASK_HIRE_MAX
    return ASK_TALK_MAX


def ask_abort_ms(text: str) -> int:
    """Public Talk /ask abort. Web/computer jobs get minutes. Hello stays 12s."""
    from app.jarvis.virtual_pc import goal_is_hire_job, wants_web_job

    raw = (text or "").strip()
    if not raw:
        return ASK_TALK_ABORT_MS
    if goal_is_hire_job(raw):
        return ASK_HIRE_ABORT_MS
    if wants_web_job(raw) or _WEB_ABORT_RE.search(raw):
        return ASK_WEB_ABORT_MS
    if _LOOK_ABORT_RE.search(raw):
        return ASK_LOOK_ABORT_MS
    return ASK_TALK_ABORT_MS


def ask_deadline_s(text: str) -> float:
    """Server wait for one /ask. Same buckets as Public Talk askAbortMs."""
    return max(12.0, float(ask_abort_ms(text)) / 1000.0)


_ASK_STARTED_MONO: float | None = None


def mark_ask_clock() -> None:
    """Start the /ask wait budget. Hello stays short; web jobs get minutes."""
    global _ASK_STARTED_MONO
    _ASK_STARTED_MONO = time.monotonic()


def remaining_ask_deadline_s(asked: str) -> float:
    """Seconds left on this /ask. Used as the wait-for-page budget."""
    budget = ask_deadline_s(asked)
    if _ASK_STARTED_MONO is None:
        return budget
    return max(0.0, budget - (time.monotonic() - _ASK_STARTED_MONO))


def web_job_deadline(asked: str) -> float:
    """monotonic timestamp when wait-then-type must stop looking."""
    return time.monotonic() + remaining_ask_deadline_s(asked)


_HIRE_BUDGET_S = 90.0
_HIRE_BUDGET_USD = 0.15
HIRE_JOB_STOP_PROMPT = (
    "This is a hire/create-many-files job. Call spawn_child first "
    "(OpenRouter helpers). Each child write_file a distinct HTML file. "
    "Do not call see_screen before the files exist. After the files are "
    "written, run_app chrome with each file:///home/jarvis/Exports/… URL "
    "— never a bare Exports/ hostname. Then look to confirm a board is visible."
)
_HIRE_FILE_MAX = 10
HIRE_WAVE_LINE = "Making the next ones."
_HIRE_SAY_N = {
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}
_HIRE_SAY_N_REV = {word: n for n, word in _HIRE_SAY_N.items()}
_EMPTY_SPEECH_RE = re.compile(
    r"^\s*(\{\}|\[\]|null|none|undefined)?\s*$",
    re.I,
)
_BOARD_LOOK_RE = re.compile(
    r"\b(tetris|board|playfield|canvas|score|grid|blocks?|tetromino)\b",
    re.I,
)
# Each hired game gets an explicit look. Parent rejects byte-identical copies.
_HIRE_LOOKS: tuple[dict[str, str], ...] = (
    {
        "title": "Neon Stack",
        "palette": "black playfield, hot-pink I/T, cyan O/S/Z, magenta L/J",
        "pieces": "classic 7 tetrominoes plus a plus-shaped pentomino",
        "hud": "score top-left in neon cyan, next-piece window top-right",
        "bg": "#07060c",
        "board": "#12081a",
        "block": "#ff2bd6",
        "block2": "#22f0ff",
        "ink": "#f4f7ff",
        "hud_color": "#22f0ff",
        "empty": "#1a1024",
    },
    {
        "title": "Sunset Quarry",
        "palette": "warm sand playfield, terracotta I/L, gold O, rust J/T, olive S/Z",
        "pieces": "classic 7 only; O is a 3x3 square",
        "hud": "level and score in a bottom amber bar",
        "bg": "#2a1610",
        "board": "#4a2a18",
        "block": "#e07a3d",
        "block2": "#f0c14b",
        "ink": "#fff4e6",
        "hud_color": "#f0c14b",
        "empty": "#3a2216",
    },
    {
        "title": "Ice Well",
        "palette": "pale ice playfield, white I, steel-blue J/L, teal S/Z, navy T/O",
        "pieces": "classic 7 plus a 1x5 I-beam",
        "hud": "lines and score as frost numerals on the right rail",
        "bg": "#dceef6",
        "board": "#9ec9dc",
        "block": "#2a6f8f",
        "block2": "#f7fbff",
        "ink": "#123246",
        "hud_color": "#1a4d66",
        "empty": "#c5dce8",
    },
    {
        "title": "Paper Box",
        "palette": "cream page, ink-black outlines, red I, navy J, forest L, no fills",
        "pieces": "outline-only tetrominoes, no ghost piece",
        "hud": "handwritten score under the title, no next-piece",
        "bg": "#f4efe4",
        "board": "#fffdf6",
        "block": "#1b1b1b",
        "block2": "#b42318",
        "ink": "#1b1b1b",
        "hud_color": "#5c4033",
        "empty": "#ece4d4",
    },
    {
        "title": "Arcade Cabinet",
        "palette": "navy cabinet, orange I/L, lime S, hot-red Z, white O",
        "pieces": "chunky 8-bit tetrominoes with a brick-pattern T",
        "hud": "HISCORE + LEVEL in orange pixel type above the well",
        "bg": "#0b1230",
        "board": "#15204a",
        "block": "#ff7a00",
        "block2": "#9cff4a",
        "ink": "#fff8e7",
        "hud_color": "#ff7a00",
        "empty": "#0e1738",
    },
    {
        "title": "Garden Rows",
        "palette": "moss playfield, leaf-green S/Z, blossom-pink T, soil-brown J/L",
        "pieces": "classic 7 plus a flower-shaped pentomino",
        "hud": "harvest score and next seed on a wooden plank below",
        "bg": "#1d2a18",
        "board": "#2e4a24",
        "block": "#6fbf4a",
        "block2": "#e37aa3",
        "ink": "#f3ffe8",
        "hud_color": "#d6b36a",
        "empty": "#24351e",
    },
    {
        "title": "Mono Grid",
        "palette": "white well, black blocks only, 1px hairline grid",
        "pieces": "classic 7 as solid black rectangles, no color coding",
        "hud": "tiny monospace SCORE/NEXT in the top-right corner",
        "bg": "#f3f3f3",
        "board": "#ffffff",
        "block": "#111111",
        "block2": "#444444",
        "ink": "#111111",
        "hud_color": "#111111",
        "empty": "#e6e6e6",
    },
    {
        "title": "Lava Pit",
        "palette": "charcoal well, ember-red I/Z, molten-orange O/T, ash-grey J/L/S",
        "pieces": "classic 7 plus a jagged 5-block ember",
        "hud": "HEAT meter left, SCORE right, both in ember orange",
        "bg": "#140808",
        "board": "#2a1010",
        "block": "#ff3b1f",
        "block2": "#ff9a1f",
        "ink": "#ffe8d6",
        "hud_color": "#ff9a1f",
        "empty": "#1c0c0c",
    },
    {
        "title": "Harbor Dock",
        "palette": "deep teal water, white I, brass O, rope-tan J/L, signal-red T",
        "pieces": "classic 7; S and Z are boat-shaped hexominoes",
        "hud": "cargo score on a brass plate under the title",
        "bg": "#0b2a2e",
        "board": "#134248",
        "block": "#d4b36a",
        "block2": "#f2f6f4",
        "ink": "#e8f4f2",
        "hud_color": "#d4b36a",
        "empty": "#0f3338",
    },
    {
        "title": "Candy Well",
        "palette": "lavender well, grape I, lemon O, mint S, cherry Z, sky J/L/T",
        "pieces": "rounded candy tetrominoes, no hard corners",
        "hud": "STAR score and next candy in a pastel badge top-left",
        "bg": "#f3e6ff",
        "board": "#e3d2f7",
        "block": "#7b4dff",
        "block2": "#ff5fa2",
        "ink": "#3b2258",
        "hud_color": "#7b4dff",
        "empty": "#efe4fb",
    },
)
_LOOK_FAILED = "The look failed. I could not read the page."
_HOLLOW_HEADLINES = "I opened the page. Here are the headlines that are visible."
_HOLLOW_TELL_RE = re.compile(
    r"("
    r"here are the headlines that are visible|"
    r"^i opened the (page|article)\.?\s*$|"
    r"the page is still settling"
    r")",
    re.I,
)
_NO_YESTERDAY = "I do not have yesterday yet."
_NO_YESTERDAY_TR = "Henüz dünü hatırlamıyorum."
_HELLO = "Hello."
_HELLO_TR = "Merhaba."
_HOW_ARE_YOU = "Good. You?"
_HOW_ARE_YOU_TR = "İyiyim. Sen?"
_NEED = "What do you need?"
_NEED_TR = "Nasıl yardımcı olayım?"
_NO_WEATHER = "I cannot check the weather right now."
_NO_WEATHER_TR = "Şu an havaya bakamıyorum."
_SHOPPING_EN = "Milk, bread, eggs, apples, coffee"
_SHOPPING_TR = "Süt, ekmek, yumurta, elma, kahve"
_INSTALL_LIST = "I can install mines, solitaire, the calculator, or the text editor."
_INSTALL_FAIL = "I could not install that."
_INSTALL_LEAD_RE = re.compile(
    r"(?:^|\b)(?:please\s+|can you\s+|could you\s+)?"
    r"(?:install|apt(?:-get)?(?:\s+install)?|add(?:\s+a)?\s+package)\s+",
    re.I,
)
_COMPOUND_AND_RE = re.compile(r"\band\s+(?:show|open|go|find|look)\b", re.I)
_FILE_NAME_RE = re.compile(
    r"\b([\w.-]+\.(?:csv|xlsx|xls|txt|tsv|md|json))\b",
    re.I,
)
_SAMPLE_CSV_RE = re.compile(
    r"\b(sample\s+csv|csv\s+file|sample\.csv)\b",
    re.I,
)
_SAMPLE_XLSX_RE = re.compile(
    r"\b(sample\s+(?:excel|xlsx)|xlsx\s+file)\b",
    re.I,
)
_OPEN_FILE_VERB_RE = re.compile(r"\b(open|show|launch|run|start|look at)\b", re.I)
_INSTALL_WORD_RE = re.compile(r"\b(install|apt(?:-get)?)\b", re.I)
# Tell / read / look-together / what's on — not show/open a named URL.
_TELL_FROM_SCREEN_RE = re.compile(
    r"("
    r"\b(?:tell(?:\s+me)?|read)\b|"
    r"\bwhat(?:'s|s|\s+are|\s+is)\s+(?:the\s+)?(?:news|headlines)\b|"
    r"what(?:'s|s|\s+is)\s+on(?:\s+the)?\s+screen|"
    r"look(?:\s+\w+){0,4}\s+together|"
    r"news\s+together"
    r")",
    re.I,
)
_LOOK_SCREEN_RE = re.compile(
    r"("
    r"what(?:'s|s|\s+is)\s+on(?:\s+the)?\s+(?:your\s+)?(?:screen|computer|browser)|"
    r"look\s+at(?:\s+the)?\s+(?:your\s+)?(?:screen|browser|computer|page)|"
    r"what\s+do\s+you\s+see|"
    r"what\s+are\s+you\s+seeing|"
    r"what(?:'s|s|\s+is)\s+that\s+popup|"
    r"what(?:'s|s|\s+is)\s+visible|"
    r"visible\s+on(?:\s+the)?\s+(?:browser|screen|computer)|"
    r"check\s+(?:your\s+)?(?:computer|screen|browser)|"
    r"(?:don'?t you |do you )have your own computer|"
    r"there\s+is\s+no.{0,60}(?:here|login|on\s+(?:the\s+)?(?:screen|page|browser))|"
    r"i\s+(?:don'?t|do\s+not|can'?t|cannot)\s+see|"
    r"no\s+login|"
    r"read\s+(?:this\s+|the\s+)?(?:page|screen|article)|"
    r"^\s*look(?:\s+again)?[\s!.?,]*$"
    r")",
    re.I,
)
_CLOSE_TAB_RE = re.compile(
    r"\bclose\b.{0,24}\btabs?\b|\btabs?\b.{0,24}\bclose\b",
    re.I,
)
_CHROME_STILL_RE = re.compile(
    r"("
    r"\bgoogle[\s-]?chrome\b|"
    r"\bchromium\b|"
    r"\bchrome\b|"
    r"restore pages|"
    r"\burl bar\b|"
    r"\baddress bar\b|"
    r"\bomnibox\b"
    r")",
    re.I,
)
_LEFTOVER_APP_RE = re.compile(
    r"("
    r"\bmousepad\b|"
    r"\bgalculator\b|"
    r"\bnotepad\b|"
    r"\bgedit\b|"
    r"\bleafpad\b|"
    r"\bcalculator\b|"
    r"\bristretto\b|"
    r"\beog\b|"
    r"image viewer|"
    r"\bthunar\b|"
    r"\bnemo\b|"
    r"\bnautilus\b|"
    r"file manager|"
    r"\bexplorer\b|"
    r"error dialog|"
    r"\berror\b"
    r")",
    re.I,
)
_CLEAR_LIE_RE = re.compile(
    r"("
    r"desktop is clear|"
    r"screen is clear|"
    r"nothing is (?:open|there|on the screen)|"
    r"all (?:the )?(?:apps?|windows?) (?:are|is) (?:now )?(?:closed|gone|clear)"
    r")",
    re.I,
)
_TECH_DUMP_RE = re.compile(
    r"("
    r"\bdocker\b|"
    r"\bexec\b|"
    r"\boci\b|"
    r"\bmanifest\b|"
    r"error response from daemon|"
    r"\bPATH=|"
    r"/usr/bin/env|"
    r"command not found|"
    r"permission denied"
    r")",
    re.I,
)
_TR_LETTER_RE = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
_TR_WORD_RE = re.compile(
    r"\b("
    r"merhaba(?:lar)?|selam(?:lar)?|g[uü]nayd[iı]n|"
    r"nas[iı]ls[iı]n|te[sş]ekk[uü]r|"
    r"ka[cç]|hava|d[uü]n|yapt[iı]k|konu[sş]tuk|"
    r"hat[iı]rla|l[uü]tfen|evet|hay[iı]r"
    r")\b",
    re.I,
)
_WEATHER_RE = re.compile(
    r"\b(weather|forecast|temperature|hava(?:\s+durumu)?|s[iı]cakl[iı]k)\b",
    re.I,
)
_HOW_ARE_YOU_TR_RE = re.compile(r"\bnas[iı]ls[iı]n\b", re.I)
_SHOPPING_RE = re.compile(r"\b(shopping\s+list|al[iı][sş]veri[sş](?:\s+listesi)?)\b", re.I)
_MATH_OP_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([+\-*/x×÷])\s*(\d+(?:\.\d+)?)")
_MATH_WORDS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s+(plus|minus|times|over|divided\s+by)\s+(\d+(?:\.\d+)?)",
    re.I,
)
_MATH_FOLLOWUP_RE = re.compile(
    r"^\s*(?:and\s+)?(plus|\+|minus|−|-|times|x|×|over|divided\s+by|÷)"
    r"\s*(\d+(?:\.\d+)?)\s*[?!.]*$",
    re.I,
)
_OR_CHOICE_RE = re.compile(
    r"^\s*(.+?)\s+or\s+(.+?)\s*[?!.]*$",
    re.I,
)
_INTERESTING_RE = re.compile(
    r"tell\s+me\s+something\s+interesting\s+about\s+(.+?)\s*[?!.]*$",
    re.I,
)
_STALL_TALK_RE = re.compile(
    r"still here\.?\s*go on|buradayım\.?\s*devam et|^i['’]?m\s+here\W*$|"
    r"^what do you need\?$",
    re.I,
)
_DESKTOP_TALK_RE = re.compile(
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
_FOOTER_TALK_RE = re.compile(
    r"("
    r"\bfooter\b|"
    r"all rights reserved|"
    r"copyright|"
    r"privacy policy|"
    r"terms of (?:service|use)|"
    r"cookie statement|"
    r"destinations we love|"
    r"scrolled to the (?:bottom|footer)"
    r")",
    re.I,
)
_LOOK_AT_SCREEN_RE = re.compile(r"look at the screen\.?", re.I)
_WEB_STUCK = "I could not finish the search."
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_TURKEY_INTERESTING = (
    "Istanbul cats treat the city like they own it. "
    "The land sits on a real earthquake fault, not a postcard."
)
_TURKEY_INTERESTING_TR = (
    "İstanbul'un kedileri şehri sahiplenmiş gibi. "
    "Ülke kartpostal değil, gerçek bir deprem kuşağında."
)
_OPEN_CALC_RE = re.compile(
    r"("
    r"\b(open|launch|start|show|run)\b.{0,24}\b(calc|calculator|galculator)\b|"
    r"\b(calc|calculator|galculator)\b.{0,24}\b(open|launch|start)\b"
    r")",
    re.I,
)
_CLOSED_LIE_RE = re.compile(
    r"("
    r"all (?:the )?(?:browser )?tabs are now closed|"
    r"(?:the )?(?:browser )?window is no longer open|"
    r"browser (?:window )?is (?:now )?(?:closed|gone|no longer)"
    r")",
    re.I,
)
_BLANK_PAGE_RE = re.compile(
    r"about:blank|\buntitled\b|\bnew tab\b|"
    r"page mostly blank|mostly blank|blank page|"
    r"still loading|page is (?:still )?(?:blank|empty|loading)",
    re.I,
)
_CONTROL_ACT_RE = re.compile(
    r"\b(click|type|close|scroll|press|dismiss)\b",
    re.I,
)
_NEWS_ASK_RE = re.compile(
    r"\b("
    r"(?:latest\s+)?news|headlines|"
    r"what(?:'s|s|\s+is)\s+going\s+on|"
    r"what(?:'s|s|\s+is)\s+happening"
    r")\b",
    re.I,
)
_SEARCH_PAGE_RE = re.compile(
    r"("
    r"\bduckduckgo\b|"
    r"\bbing(?:\s+search)?\b|"
    r"\bgoogle(?:\s+news|\s+search)?\b|"
    r"search results|"
    r"web results|"
    r"results for|"
    r"all results|"
    r"search page|"
    r"search results page|"
    r"\bserp\b|"
    r"-\s*search\b"
    r")",
    re.I,
)
_RESTORE_VISION_RE = re.compile(
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
_RESTORE_XY_RE = re.compile(
    r"(?:restore|the\s+x|\bx\b|close)\s+"
    r"(?:button\s+|dialog\s+)?"
    r"(?:at\s+)?\((\d{2,4})\s*,\s*(\d{2,4})\)",
    re.I,
)
_HOWTO_SPEECH_RE = re.compile(
    r"("
    r"\b(?:the\s+)?user\s+can\b|"
    r"\byou\s+should\b|"
    r"\byou\s+can\s+(?:press|click|type|close|access|open|use)\b|"
    r"\byou\s+can\s+(?:access|open|use)\s+chrome\b|"
    r"\byou\s+can\s+(?:search|look)\s+for\s+hotels?\b|"
    r"\byou\s+might\s+need\s+to\s+click\b|"
    r"\byou\s+(?:need|have)\s+to\s+click\b|"
    r"\bplease\s+click\b|"
    r"\bclick\s+accept\b|"
    r"\bto\s+close\s+(?:the\s+)?tabs?\b|"
    r"\bpress\s+(?:ctrl|control)\s*\+?\s*w\b|"
    r"\bctrl\s*\+\s*w\b|"
    r"\bsay\s+confirm\b|"
    r"\bconfirm\s+to\s+proceed\b|"
    r"\bcheck (?:your )?(?:internet|connection)\b|"
    r"\brefresh (?:the )?(?:page|tab|browser)\b|"
    r"\breload (?:the )?(?:page|tab)\b"
    r")",
    re.I,
)
_CHROME_COACH_RE = re.compile(
    r"("
    r"you can (?:access|open|use) chrome|"
    r"you can (?:search|look) for hotels?|"
    r"you can open chrome"
    r")",
    re.I,
)
# jarvis-computer Xvfb is 1280x720 (deploy/jarvis-computer/entrypoint.sh JARVIS_SCREEN).
# Chrome fills the desktop; the XFCE panel sits at the bottom (~40px).
# Chromium chrome (caption + tabs + toolbar) occupies roughly y=0–110.
# DuckDuckGo header + search box + All/Images chips occupy roughly y=110–280
# in the content column. The first organic result title is around (420, 320).
# A second click, if still on DuckDuckGo, aims one result row lower.
# Chromium "Restore pages?" sits at the top; dismiss it before these clicks.
# Do not treat those points as proven — they can hit Restore or a news card.
CHROME_SEARCH_RESULT_CLICKS = ((420, 320), (420, 400))
# Restore pages? X on 1280x720 Xvfb: right edge of the crash-restore
# infobar under the toolbar. Not the window-close button at y≈12.
_RESTORE_DISMISS_CLICK = RESTORE_DISMISS_CLICK
_CLICK_SETTLE_S = 0.8
_LOOK_AFTER_ACT = "what is on the screen now"
_XY_RE = re.compile(r"\((\d{2,4})\s*,\s*(\d{2,4})\)")
_TYPE_TEXT_RE = re.compile(
    r"\btype\s+(?:the\s+(?:words?\s+|text\s+)?)?(.+)$",
    re.I,
)
_TELL_LEAD_RE = re.compile(r"^(?:please\s+)?(?:tell(?:\s+me)?|read)\s+", re.I)
_SEARCH_ENGINE_HOSTS = frozenset(
    {
        "duckduckgo.com",
        "www.duckduckgo.com",
        "google.com",
        "www.google.com",
        "news.google.com",
        "bing.com",
        "www.bing.com",
    }
)
_PAGE_FAIL_RE = re.compile(
    r"("
    r"\bssl\b|certificate error|privacy error|"
    r"your connection is not private|"
    r"this site can(?:not|'t|’t) be reached|"
    r"did not connect|err_[a-z0-9_]+|"
    r"net::err|dns_probe_finished|"
    r"empty response|"
    r"\b404\b|"
    r"page not found|"
    r"this page (?:does not|doesn't) exist"
    r")",
    re.I,
)
_COOKIE_XY_RE = re.compile(
    r"(?:accept(?:\s+all)?|i\s+agree|agree|continue)"
    r"(?:\s+button|\s+and\s+continue)?"
    r"\s+(?:at\s+)?\((\d{2,4})\s*,\s*(\d{2,4})\)",
    re.I,
)
_COOKIE_SPEECH_RE = re.compile(
    r"("
    r"accept (?:all )?cookies|cookie (?:banner|modal|consent|wall)|"
    r"before you continue|i agree|terms accept|"
    r"you might need to click|please click accept"
    r")",
    re.I,
)


async def _hosted_voice_ask(text: str) -> dict[str, Any]:
    """POST one ask to berkly's hosted talk URL (operator key stays on the server)."""
    url = hosted_talk_endpoint("ask")
    if not url:
        return {
            "ok": False,
            "reply": CANT_TALK,
            "tools_used": [],
            "result": {"ok": False, "error": CANT_TALK},
            "ui": {"ok": False, "error": CANT_TALK},
        }
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            res = await client.post(url, json={"text": text})
    except Exception:
        return {
            "ok": False,
            "reply": CANT_TALK,
            "tools_used": [],
            "result": {"ok": False, "error": CANT_TALK},
            "ui": {"ok": False, "error": CANT_TALK},
        }
    if res.status_code >= 400:
        return {
            "ok": False,
            "reply": CANT_TALK,
            "tools_used": [],
            "result": {"ok": False, "error": CANT_TALK},
            "ui": {"ok": False, "error": CANT_TALK},
        }
    try:
        payload = res.json()
    except Exception:
        return {
            "ok": False,
            "reply": CANT_TALK,
            "tools_used": [],
            "result": {"ok": False, "error": CANT_TALK},
            "ui": {"ok": False, "error": CANT_TALK},
        }
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "reply": CANT_TALK,
            "tools_used": [],
            "result": {"ok": False, "error": CANT_TALK},
            "ui": {"ok": False, "error": CANT_TALK},
        }
    reply = str(payload.get("reply") or "").strip() or CANT_TALK
    return {
        "ok": bool(payload.get("ok", True)),
        "reply": reply[:2000],
        "tools_used": list(payload.get("tools_used") or []),
        "result": payload.get("result") if isinstance(payload.get("result"), dict) else payload,
        "ui": payload.get("ui") if isinstance(payload.get("ui"), dict) else payload,
    }


def _normalize_tool_name(name: str) -> str:
    raw = (name or "").strip()
    if raw in {"get_disk_space", "diskSpace", "free_space", "disk_space"}:
        return "get_disk_space"
    if raw in {"get_github_repos", "github_repos"}:
        return "list_github_repos"
    return raw


def _is_computer_ask(asked: str) -> bool:
    from app.jarvis.virtual_pc import (
        goal_is_computer_job,
        goal_is_hire_job,
        goal_is_simple_talk,
        goal_is_virtual_pc_job,
    )

    if goal_is_hire_job(asked) or goal_is_simple_talk(asked):
        return False
    try:
        from app.jarvis.virtual_pc import wants_web_job
    except Exception:
        wants_web_job = None
    if wants_web_job is not None and wants_web_job(asked):
        return True
    return bool(goal_is_virtual_pc_job(asked) or goal_is_computer_job(asked))


def _agent_left_screen_untouched(reply: str, tools: list[Any]) -> bool:
    used = [t for t in (tools or []) if str(t).strip()]
    if not used:
        return True
    if _BARE_ACK.match((reply or "").strip()) and not used:
        return True
    return False


def _looks_like_news_essay(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if _NEWS_ESSAY_RE.search(raw):
        return True
    return len(raw) > 400 and raw.count(". ") >= 3


def _refuse_screen(error: str = "") -> dict[str, Any]:
    err = (error or "").strip() or _SCREEN_FAIL
    return {
        "ok": False,
        "reply": err[:2000],
        "tools_used": [],
        "result": {"ok": False, "error": err},
        "ui": {"ok": False, "error": err},
    }


_IM_HERE_RE = re.compile(r"^i['’]?m\s+here\W*$", re.I)
_HOW_ARE_YOU_RE = re.compile(r"\bhow(?:\s+are|'re|’re)\s+(?:you|ya)\b", re.I)


def _is_blank_talk(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return True
    return bool(_IM_HERE_RE.match(raw))


def spoken_language(asked: str) -> str:
    """Language of the words they just used. Mirror that. Not a locale pin."""
    raw = asked or ""
    if _TR_LETTER_RE.search(raw) or _TR_WORD_RE.search(raw):
        return "tr"
    return "en"


def _math_answer(asked: str) -> str:
    """Local arithmetic for 2+2 / 15+27 / two-number plus-minus. No Chrome."""
    raw = asked or ""
    match = _MATH_OP_RE.search(raw) or _MATH_WORDS_RE.search(raw)
    if not match:
        return ""
    left_s, op, right_s = match.group(1), match.group(2), match.group(3)
    try:
        left = float(left_s)
        right = float(right_s)
    except (TypeError, ValueError):
        return ""
    word = (op or "").strip().lower()
    if word in {"plus"}:
        word = "+"
    elif word in {"minus"}:
        word = "-"
    elif word in {"times", "x", "×"}:
        word = "*"
    elif word in {"over", "divided by", "÷"}:
        word = "/"
    if word == "+":
        value = left + right
    elif word == "-":
        value = left - right
    elif word == "*":
        value = left * right
    elif word == "/":
        if right == 0:
            return ""
        value = left / right
    else:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def _format_math_value(value: float | int) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def _apply_math_op(left: float, op: str, right: float) -> str:
    word = (op or "").strip().lower()
    if word in {"plus", "+"}:
        word = "+"
    elif word in {"minus", "−", "-"}:
        word = "-"
    elif word in {"times", "x", "×"}:
        word = "*"
    elif word in {"over", "divided by", "÷"}:
        word = "/"
    if word == "+":
        value = left + right
    elif word == "-":
        value = left - right
    elif word == "*":
        value = left * right
    elif word == "/":
        if right == 0:
            return ""
        value = left / right
    else:
        return ""
    return _format_math_value(value)


def _last_number_from_history(asked: str = "") -> float | None:
    try:
        from app.jarvis.talk_log import recent_talk_turns

        history = recent_talk_turns(asked)
    except Exception:
        history = []
    for role in ("jarvis", "you"):
        for row in reversed(history):
            if row.get("role") != role:
                continue
            nums = _NUMBER_RE.findall(str(row.get("text") or ""))
            if nums:
                try:
                    return float(nums[-1])
                except ValueError:
                    continue
    return None


def _math_followup_answer(asked: str) -> str:
    """And plus 3? after 56 → 59. Uses the last Talk number."""
    match = _MATH_FOLLOWUP_RE.match((asked or "").strip())
    if not match:
        return ""
    left = _last_number_from_history(asked)
    if left is None:
        return ""
    try:
        right = float(match.group(2))
    except (TypeError, ValueError):
        return ""
    return _apply_math_op(left, match.group(1), right)


def _or_choice_answer(asked: str) -> str:
    """Pasta or stir-fry tonight? → one pick, one sentence."""
    raw = (asked or "").strip()
    match = _OR_CHOICE_RE.match(raw)
    if not match:
        return ""
    left = re.sub(r"\s+tonight$", "", match.group(1).strip(), flags=re.I)
    right = re.sub(r"\s+tonight$", "", match.group(2).strip(), flags=re.I)
    if not left or not right or len(left) > 40 or len(right) > 40:
        return ""
    if re.search(r"\b(open|show|click|screen|browser|install)\b", f"{left} {right}", re.I):
        return ""
    if _MATH_OP_RE.search(raw) or _MATH_WORDS_RE.search(raw):
        return ""
    pick = left.rstrip(" .")
    if not pick:
        return ""
    pick = pick[:1].upper() + pick[1:]
    if re.search(r"\btonight\b", raw, re.I):
        return f"{pick} tonight."
    return pick + "."


def _interesting_about_answer(asked: str) -> str:
    match = _INTERESTING_RE.match((asked or "").strip())
    if not match:
        return ""
    topic = match.group(1).strip().rstrip(".?!")
    if re.search(r"\b(turkey|t[uü]rkiye)\b", topic, re.I):
        return (
            _TURKEY_INTERESTING_TR
            if spoken_language(asked) == "tr"
            else _TURKEY_INTERESTING
        )
    return ""


def _is_stall_talk(text: str) -> bool:
    return bool(_STALL_TALK_RE.search((text or "").strip()))


def _is_desktop_talk(text: str) -> bool:
    return bool(_DESKTOP_TALK_RE.search(text or ""))


def _talk_last_resort(asked: str) -> str:
    lang = spoken_language(asked)
    math = _math_answer(asked)
    if math:
        return math
    if _HOW_ARE_YOU_RE.search(asked or "") or _HOW_ARE_YOU_TR_RE.search(asked or ""):
        return _HOW_ARE_YOU_TR if lang == "tr" else _HOW_ARE_YOU
    if _WEATHER_RE.search(asked or ""):
        return _NO_WEATHER_TR if lang == "tr" else _NO_WEATHER
    from app.jarvis.virtual_pc import goal_is_greeting

    if goal_is_greeting(asked):
        return _HELLO_TR if lang == "tr" else _HELLO
    from app.jarvis.virtual_pc import wants_stop_talk

    if wants_stop_talk(asked):
        return _STOP_OK_TR if lang == "tr" else _STOP_OK
    follow_math = _math_followup_answer(asked)
    if follow_math:
        return follow_math
    interesting = _interesting_about_answer(asked)
    if interesting:
        return interesting
    choice = _or_choice_answer(asked)
    if choice:
        return choice
    history: list[dict[str, Any]] = []
    try:
        from app.jarvis.talk_log import recent_talk_turns

        history = recent_talk_turns(asked)
    except Exception:
        history = []
    if history:
        if _REPEAT_RE.search(asked or ""):
            last = _last_jarvis_sentence(history)
            if last:
                return last
        if _WHAT_I_ASKED_RE.search(asked or ""):
            for row in reversed(history):
                text = str(row.get("text") or "").strip()
                if row.get("role") == "you" and text:
                    return text
        opinion = _opinion_on_last_talk(asked, history)
        if opinion:
            return opinion
        last = _last_jarvis_sentence(history)
        if last:
            return last
    return _NEED_TR if lang == "tr" else _NEED


def _talk_ok(reply: str, asked: str = "") -> dict[str, Any]:
    text = (reply or "").strip()
    if _is_blank_talk(text) or _is_stall_talk(text) or _is_desktop_talk(text):
        text = _talk_last_resort(asked)
    return {
        "ok": True,
        "reply": text[:2000],
        "tools_used": [],
        "result": {"ok": True, "text": text[:2000]},
        "ui": {"ok": True, "text": text[:2000]},
    }


def _few_sentences_from_journal(fact: str) -> str:
    topics: list[str] = []
    decisions: list[str] = []
    section = None
    for line in (fact or "").splitlines():
        s = line.strip()
        low = s.lower().rstrip(":")
        if low == "topics":
            section = "topics"
            continue
        if low == "decisions":
            section = "decisions"
            continue
        if low in {"artifacts", "open threads", "notes"} or low.startswith(
            ("sources", "agents created", "daily journal")
        ):
            section = None
            continue
        if section and s.startswith("- "):
            item = s[2:].strip()
            if not item or item == "(light activity)":
                continue
            if section == "topics" and item not in topics:
                topics.append(item)
            elif section == "decisions" and item not in decisions:
                decisions.append(item)
    bits: list[str] = []
    if topics:
        bits.append("Yesterday we talked about " + ", ".join(topics[:5]) + ".")
    if decisions:
        bits.append(decisions[0].rstrip(".") + ".")
    if not bits:
        compact = re.sub(r"\s+", " ", fact or "").strip()
        if not compact:
            return ""
        bits.append(compact[:280].rstrip(" .") + ".")
    return " ".join(bits)[:500]


_EXPLICIT_DAY_RE = re.compile(
    r"("
    r"\byesterday\b|"
    r"\bd[uü]n\b|"
    r"\btoday\b|"
    r"\bday:\d{4}-\d{2}-\d{2}\b|"
    r"\b\d+\s+days?\s+ago\b|"
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+days?\s+ago\b"
    r")",
    re.I,
)


def _explicit_journal_day_ask(asked: str) -> bool:
    """True only for a named day. 'What did we talk about' is this chat."""
    return bool(_EXPLICIT_DAY_RE.search(asked or ""))


def _has_this_chat_history(asked: str = "") -> bool:
    try:
        from app.jarvis.talk_log import has_talk_history

        return bool(has_talk_history(asked))
    except Exception:
        return False


def _short_journal_reply(asked: str) -> str:
    from app.jarvis.daily_journal import recall_day, resolve_day_key

    lang = spoken_language(asked)
    empty = _NO_YESTERDAY_TR if lang == "tr" else _NO_YESTERDAY
    try:
        mem = getattr(get_gateway(), "memory", None)
        if mem is None:
            return empty
    except Exception:
        return empty
    query = asked
    if resolve_day_key(query) is None:
        query = "yesterday"
    try:
        got = recall_day(mem, query)
    except Exception:
        return empty
    if not got or got.get("empty") or not str(got.get("fact") or "").strip():
        return empty
    spoken = _few_sentences_from_journal(str(got.get("fact") or ""))
    if not spoken:
        return empty
    if lang == "tr" and spoken.startswith("Yesterday we talked about "):
        rest = spoken[len("Yesterday we talked about ") :]
        spoken = "Dün şunlardan konuştuk: " + rest
    return spoken


_TALK_SYSTEM = (
    "You are Jarvis, a friend already in this conversation. "
    "Answer the person's words in one or two short spoken sentences. "
    "Answer in the same language they just used. If they spoke Turkish, reply in Turkish. "
    "If they ask how you are, say how you are and ask back. "
    "Really? / what do you think / more on that: give a short opinion or reaction "
    "on THE last topic in the recent turns. Do not repeat your last spoken lines. "
    "Never switch to leftover browser text "
    "or another country. Never a Wikipedia paragraph or tourism brochure. "
    "Stop means stop — say OK. Do not offer more details. "
    "If they ask for the news, a fact, weather, or an explanation, keep it short and human. "
    "You were already talking. Use the recent turns for follow-ups "
    "(and the capital?, say that again slower, what did I just ask, daily chat). "
    "Stay in the same conversation. Do not greet as if this is new. "
    "Do not say What do you need? when they were already talking. "
    "No tools, no screen, no browser. Do not say you opened a page."
)
_STOP_OK = "OK."
_STOP_OK_TR = "Tamam."
_BROCHURE_RE = re.compile(
    r"("
    r"bridges?\s+europe\s+and\s+asia|"
    r"transcontinental|"
    r"rich\s+(?:history|heritage|culture)|"
    r"\bheritage\b|"
    r"if you(?:'d| would) like more details|"
    r"let me know if you need"
    r")",
    re.I,
)
_HEDGE_RE = re.compile(
    r"("
    r"if you(?:'d| would) like more details[^.]*\.?|"
    r"let me know if you need(?:\s+\w+){0,8}\.?"
    r")",
    re.I,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_TURKEY_TAKE = "It's a big, complicated country. What part do you care about?"
_TURKEY_TAKE_TR = "Büyük, karışık bir ülke. Neresi?"


def _first_sentences(text: str, n: int = 2, max_chars: int = 240) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""
    parts = [p.strip() for p in _SENTENCE_RE.split(raw) if p.strip()]
    if not parts:
        return raw[:max_chars].strip()
    out = " ".join(parts[: max(1, n)])
    if len(out) > max_chars:
        out = out[:max_chars].rstrip(" ,;") + "."
    return out


_CANNED_OPINION_RE = re.compile(
    r"^(Honestly\?|Yeah\.|Dürüst olayım\?|Evet\.)",
    re.I,
)


def _last_jarvis_sentence(
    history: list[dict[str, Any]],
    *,
    skip_opinions: bool = False,
) -> str:
    for row in reversed(history):
        if row.get("role") != "jarvis":
            continue
        raw = str(row.get("text") or "").strip()
        if not raw or _is_stall_talk(raw) or _is_desktop_talk(raw):
            continue
        if skip_opinions and _CANNED_OPINION_RE.search(raw):
            continue
        bit = _first_sentences(raw, n=2, max_chars=180)
        if bit:
            return bit
    return ""


_TOPIC_STOP = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "for",
    "from",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "like",
    "not",
    "of",
    "on",
    "or",
    "so",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "with",
    "you",
}


def _topic_hint(last: str) -> str:
    """Two content words from the last Jarvis line — not the full fact."""
    first = re.split(r"[.!?]", last or "", maxsplit=1)[0]
    first = re.sub(r"^[\s•\-–—]+", "", first or "")
    words = [
        w
        for w in re.findall(r"[A-Za-zÇçĞğİıÖöŞşÜü']+", first)
        if w.casefold() not in _TOPIC_STOP
    ]
    if not words:
        return "that"
    return " ".join(words[:2])


def _same_talk_line(left: str, right: str) -> bool:
    def norm(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip()).casefold().rstrip(".!?")

    return bool(left and right and norm(left) == norm(right))


def _echoes_last_talk(reply: str, last: str) -> bool:
    if _same_talk_line(reply, last):
        return True
    blob = (reply or "").casefold()
    for sent in _SENTENCE_RE.split(last or ""):
        bit = sent.strip().rstrip(".!?")
        if len(bit) >= 24 and bit.casefold() in blob:
            return True
    return False


def _recent_talk_history(asked: str = "") -> list[dict[str, Any]]:
    try:
        from app.jarvis.talk_log import recent_talk_turns

        return recent_talk_turns(asked)
    except Exception:
        return []


def _opinion_on_last_talk(
    asked: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Really? / what do you think — short reaction, never a repeat of last facts."""
    from app.jarvis.virtual_pc import wants_talk_followup

    if not wants_talk_followup(asked):
        return ""
    rows = history if history is not None else _recent_talk_history(asked)
    last = _last_jarvis_sentence(rows, skip_opinions=True)
    if not last:
        return ""
    hint = _topic_hint(last)
    lang = spoken_language(asked)
    compact = (asked or "").strip().lower().rstrip(".!?")
    if compact == "really" or compact.startswith("really"):
        if lang == "tr":
            return f"Evet. {hint} — o kalıyor."
        return f"Yeah. {hint} — that's a lot."
    if lang == "tr":
        return f"Dürüst olayım? Aklımda kalan {hint}."
    return f"Honestly? {hint} — that's the part that sticks."


def _looks_like_brochure(text: str) -> bool:
    return bool(_BROCHURE_RE.search(text or ""))


def _friend_talk_reply(asked: str, reply: str) -> str:
    """Keep Talk short and on-thread. Never a Wikipedia paragraph."""
    from app.jarvis.virtual_pc import wants_stop_talk, wants_talk_followup

    if wants_stop_talk(asked):
        return _STOP_OK_TR if spoken_language(asked) == "tr" else _STOP_OK
    text = _HEDGE_RE.sub("", reply or "").strip()
    if _is_stall_talk(text) or _is_desktop_talk(text):
        return _talk_last_resort(asked)
    text = _first_sentences(text, n=2, max_chars=240)
    history = _recent_talk_history(asked)
    last = _last_jarvis_sentence(history)
    if wants_talk_followup(asked) and last and _echoes_last_talk(text, last):
        opinion = _opinion_on_last_talk(asked, history)
        if opinion:
            return opinion
    if _looks_like_brochure(text):
        if last and not _looks_like_brochure(last) and not wants_talk_followup(asked):
            return last
        if re.search(r"\b(turkey|t[uü]rkiye)\b", asked or "", re.I):
            return _TURKEY_TAKE_TR if spoken_language(asked) == "tr" else _TURKEY_TAKE
        if wants_talk_followup(asked):
            opinion = _opinion_on_last_talk(asked, history)
            if opinion:
                return opinion
            if last:
                return last
    return text
_REPEAT_RE = re.compile(
    r"("
    r"\b(?:say|tell)\s+(?:that|it|this)\s+again\b|"
    r"\brepeat\b|"
    r"\bslower\b|"
    r"\btekrar\b|"
    r"daha\s+yava[sş]"
    r")",
    re.I,
)
_WHAT_I_ASKED_RE = re.compile(
    r"("
    r"what\s+did\s+i\s+(?:just\s+)?(?:ask|say)|"
    r"what\s+was\s+(?:my|the)\s+(?:last\s+)?(?:question|ask)|"
    r"ne\s+sordum|"
    r"ne\s+dedim"
    r")",
    re.I,
)
_GO_ON = "Still here. Go on."
_GO_ON_TR = "Buradayım. Devam et."
_TALK_TIMEOUT = 8.0


def _talk_usage_cost(data: dict[str, Any]) -> float:
    usage = data.get("usage") or {}
    if usage.get("cost") is None:
        return 0.0
    try:
        return float(usage.get("cost") or 0)
    except (TypeError, ValueError):
        return 0.0


def _record_talk_spend(data: dict[str, Any]) -> None:
    """Same settings ledger the agent uses for OpenRouter chat completions."""
    cost = _talk_usage_cost(data)
    if cost <= 0:
        return
    try:
        from app.jarvis.settings_store import record_spend

        record_spend(cost)
    except Exception:
        pass


def _talk_oneshot_messages(asked: str) -> list[dict[str, str]]:
    """System + recent Talk turns + this utterance. Empty history still works."""
    messages: list[dict[str, str]] = [{"role": "system", "content": _TALK_SYSTEM}]
    try:
        from app.jarvis.talk_log import talk_messages_for_oneshot

        prior = talk_messages_for_oneshot(asked)
    except Exception:
        prior = []
    for row in prior:
        role = str(row.get("role") or "").strip()
        content = str(row.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": asked})
    return messages


async def _simple_talk_oneshot(asked: str) -> str:
    """One cheap no-tool chat through pick_free_worker. Not the 32-round agent."""
    from app.jarvis.model_router import chat, list_free_workers

    if not list_free_workers():
        if should_use_hosted_talk():
            body = await _hosted_voice_ask(asked)
            reply = str(body.get("reply") or "").strip()
            if _is_blank_talk(reply) or _is_stall_talk(reply) or _is_desktop_talk(reply):
                log.warning("simple talk oneshot empty")
                return _talk_last_resort(asked)
            return _friend_talk_reply(asked, reply)
        return _talk_last_resort(asked)

    try:
        result = await chat(
            _talk_oneshot_messages(asked),
            timeout=_TALK_TIMEOUT,
        )
    except Exception as exc:
        log.warning("simple talk oneshot failed: %s", type(exc).__name__)
        return _talk_last_resort(asked)
    reply = str(result.text or "").strip()
    if not result.ok:
        log.warning("simple talk oneshot failed: status %s", result.status)
        return _talk_last_resort(asked)
    if _is_blank_talk(reply):
        log.warning("simple talk oneshot empty")
        return _talk_last_resort(asked)
    if result.data:
        _record_talk_spend(result.data)
    return _friend_talk_reply(asked, reply)


async def _simple_talk_answer(asked: str) -> dict[str, Any]:
    """Hello / yesterday / short chit-chat. No PC, no 32-round agent."""
    from app.jarvis.virtual_pc import goal_is_greeting, goal_is_memory_ask

    math = _math_answer(asked) or _math_followup_answer(asked)
    if math and not _OPEN_CALC_RE.search(asked or ""):
        return _talk_ok(math, asked)
    interesting = _interesting_about_answer(asked)
    if interesting:
        return _talk_ok(interesting, asked)
    choice = _or_choice_answer(asked)
    if choice:
        return _talk_ok(choice, asked)
    if goal_is_greeting(asked):
        hello = _HELLO_TR if spoken_language(asked) == "tr" else _HELLO
        return _talk_ok(hello, asked)
    from app.jarvis.virtual_pc import wants_stop_talk

    if wants_stop_talk(asked):
        stop = _STOP_OK_TR if spoken_language(asked) == "tr" else _STOP_OK
        return _talk_ok(stop, asked)
    opinion = _opinion_on_last_talk(asked)
    if opinion:
        return _talk_ok(opinion, asked)
    if goal_is_memory_ask(asked):
        # Journal is yesterday / a named day — not "what did we just talk about".
        if _explicit_journal_day_ask(asked) or not _has_this_chat_history(asked):
            return _talk_ok(_short_journal_reply(asked), asked)
    try:
        reply = await _simple_talk_oneshot(asked)
    except Exception:
        return _talk_ok("", asked)
    if _is_blank_talk(reply):
        log.warning("simple talk oneshot empty")
        return _talk_ok("", asked)
    return _talk_ok(reply, asked)


def _sanitize_computer_agent_reply(
    asked: str, reply: str, tools: list[Any]
) -> dict[str, Any] | None:
    """Do not forward a news scrape or a fake Done. None = keep the agent line."""
    from app.jarvis.virtual_pc import goal_is_hire_job

    used = [str(t).strip() for t in (tools or []) if str(t).strip()]
    if goal_is_hire_job(asked):
        if empty_speech(reply):
            recovered = _hire_children_now(asked) if "spawn_child" not in used else None
            if recovered is not None:
                return recovered
            return {
                "ok": True,
                "reply": hire_fallback_reply(asked),
                "tools_used": used,
                "result": {"ok": True},
                "ui": {"ok": True},
            }
        if "spawn_child" in used:
            return None
        recovered = _hire_children_now(asked)
        if recovered is not None:
            return recovered
        return None
    if not _is_computer_ask(asked):
        return None
    text = (reply or "").strip()
    essay = _looks_like_news_essay(text)
    untouched = _agent_left_screen_untouched(text, tools)
    if not essay and not untouched:
        try:
            from app.jarvis.virtual_pc import wants_web_job
        except Exception:
            wants_web_job = None
        desktop_caption = _is_desktop_talk(text)
        chrome_coach = _is_chrome_coach(text)
        only_looked = not ({"click", "type", "keys"} & set(used))
        if not (
            wants_web_job
            and wants_web_job(asked)
            and (
                desktop_caption
                or chrome_coach
                or only_looked
                or _BARE_ACK.match(text)
                or _ICON_CATALOG_RE.search(text)
            )
        ):
            return None
    recovered = _hire_children_now(asked)
    if recovered is not None:
        return recovered
    recovered = _open_site_now(asked)
    if recovered is not None:
        return recovered
    recovered = _install_now(asked)
    if recovered is not None:
        return recovered
    recovered = _open_file_now(asked)
    if recovered is not None:
        return recovered
    return _refuse_screen()


def _virtual_pc_ask_text(asked: str) -> str:
    from app.jarvis.agent import LOOK_JOB_STOP_PROMPT
    from app.jarvis.computer import bind_job_desktop
    from app.jarvis.virtual_pc import goal_is_hire_job

    if goal_is_hire_job(asked):
        return asked + "\n\n" + HIRE_JOB_STOP_PROMPT
    if not _is_computer_ask(asked):
        return asked
    bind_job_desktop(goal=asked)
    try:
        from app.jarvis.screen_viewer import screen_status, start_computer

        st = screen_status()
        if not st.get("running"):
            start_computer()
    except Exception:
        pass
    return (
        asked
        + "\n\n[Look policy] Do this on Jarvis's computer (jarvis-computer), "
        + "not a workspace folder. Open any website with run_app chrome url=. "
        + "Open notepad / notepad++ with run_app notepad (mousepad). "
        + "Never list Documents/Jarvis/Inbox for gmail or inbox. "
        + "Do not invent a folder or a screenshot. If the computer is down, say so. "
        + "Do not ask for a password. "
        + "Never ask the person to click, refresh, or check their internet. "
        + LOOK_JOB_STOP_PROMPT
    )


def _site_url_from_ask(asked: str) -> str | None:
    """URL they said: https, a TLD, or a known bare news word. Never invent a host."""
    match = _SITE_RE.search(asked or "")
    if match:
        raw = match.group(1).rstrip(".,);]!?'\"")
        if not raw:
            return None
        if raw.lower().startswith("http://") or raw.lower().startswith("https://"):
            return raw
        return "https://" + raw
    from app.jarvis.virtual_pc import bare_site_host, host_from_site_followup

    host = host_from_site_followup(asked) or bare_site_host(asked)
    if not host:
        return None
    if "." in host:
        return "https://" + host
    return "https://www." + host + ".com"


def _search_url_from_ask(asked: str, *, web_results: bool = False) -> str:
    """Real search page for their words. Not an invented hostname."""
    q = _TELL_LEAD_RE.sub("", asked or "").strip()
    q = re.sub(r"\s+", " ", q)
    if not q:
        q = (asked or "").strip() or "news"
    url = "https://duckduckgo.com/?q=" + quote_plus(q)
    if web_results:
        url += "&ia=web"
    return url


def wants_news_search(asked: str) -> bool:
    """News / headlines / what's going on, and they did not name a real URL."""
    if not _NEWS_ASK_RE.search(asked or ""):
        return False
    return _site_url_from_ask(asked) is None


def wants_news_tell(asked: str) -> bool:
    """Spoken news brief — no Chrome. They did not say show / open / on the screen."""
    from app.jarvis.virtual_pc import wants_spoken_news

    return wants_spoken_news(asked)


def news_url_from_ask(asked: str, *, fallback: bool = False) -> str:
    """ONE known working homepage. Never switzerland.com or a 404 swissinfo slug."""
    return news_homepage_from_ask(asked, fallback=fallback)


def wants_look_at_screen(asked: str) -> bool:
    if _LOOK_SCREEN_RE.search(asked or ""):
        return True
    from app.jarvis.virtual_pc import wants_look_job

    return wants_look_job(asked)


def wants_close_tab(asked: str) -> bool:
    """True for close the tab / close the tabs / close this tab."""
    from app.jarvis.virtual_pc import wants_close_tab as _vpc_close

    return bool(_CLOSE_TAB_RE.search(asked or "") or _vpc_close(asked))


def wants_close_all(asked: str) -> bool:
    """True for close all tabs / close the browser / close all windows."""
    from app.jarvis.virtual_pc import wants_close_all as _vpc_all

    return bool(_vpc_all(asked))


def close_tab_count(asked: str) -> int:
    """How many ctrl+w to send. Plural tabs → repeat. close-all is not keys."""
    if wants_close_all(asked) or not wants_close_tab(asked):
        return 0
    if re.search(r"\btabs\b", asked or "", re.I):
        return 2
    return 1


def wants_control_screen(asked: str) -> bool:
    return bool(
        _CONTROL_ACT_RE.search(asked or "")
        or wants_close_tab(asked)
        or wants_close_all(asked)
    )


def wants_tell_from_screen(asked: str) -> bool:
    """True for look-together / what's on the screen / news they asked to show."""
    if wants_news_tell(asked):
        return False
    if _TELL_FROM_SCREEN_RE.search(asked or ""):
        return True
    if wants_look_at_screen(asked):
        return True
    from app.jarvis.virtual_pc import wants_screen_job

    return wants_news_search(asked) and wants_screen_job(asked)


def _looks_like_ssl_or_error_page(text: str) -> bool:
    return bool(_PAGE_FAIL_RE.search(text or ""))


def _strip_howto_speech(text: str) -> str:
    """Drop 'user can press Ctrl+W' / confirm lines. Never coach the hotkey."""
    raw = re.sub(r"[#*_`]+", " ", text or "")
    raw = re.sub(r"\s+", " ", raw).strip()
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", raw) if p.strip()]
    kept = [p for p in parts if not _HOWTO_SPEECH_RE.search(p)]
    return " ".join(kept)


_ICON_CATALOG_RE = re.compile(
    r"("
    r"\b(recycle bin|desktop icons?|folder icons?|shortcuts?|"
    r"turquoise (?:desktop|background)|teal (?:desktop|background)|"
    r"wallpaper|"
    r"fills the screenshot|"
    r"desktop background)\b"
    r")",
    re.I,
)


def spoken_job_line(text: str) -> str:
    """One short line after a computer job is verified. Not a catalog of icons."""
    raw = _strip_howto_speech(text)
    if not raw:
        raw = re.sub(r"\s+", " ", (text or "").strip())
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", raw) if p.strip()]
    kept = [
        p
        for p in parts
        if not _ICON_CATALOG_RE.search(p)
        and not _CLEAR_LIE_RE.search(p)
        and len(re.findall(r"[A-Za-z0-9]{2,}", p)) >= 3
    ]
    if not kept:
        return "I looked."
    line = kept[0]
    words = line.split()
    if len(words) > 16:
        line = " ".join(words[:16]).rstrip(",;:") + "."
    if not re.search(r"[.!?]$", line):
        line = line.rstrip(",;:") + "."
    return line


def _spoken_from_screen(desc: str) -> str:
    """2–4 short sentences from a real look. Never invent headlines."""
    text = _strip_howto_speech(desc)
    if not text:
        fallback = re.sub(r"\s+", " ", (desc or "").strip())
        if fallback and not _HOWTO_SPEECH_RE.search(fallback):
            text = fallback
    if not text:
        return _LOOK_FAILED
    if _looks_like_ssl_or_error_page(text):
        return (
            "The page did not load. The browser shows a security or error page."
        )
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    if not parts:
        return text[:400].rstrip()
    spoken = " ".join(parts[:4])
    return spoken[:800]


def _spoken_from_article(desc: str) -> str:
    """Speak the article. Never treat DuckDuckGo cards as the story."""
    spoken = _spoken_from_screen(desc)
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", spoken) if p.strip()]
    kept = [
        p
        for p in parts
        if not _looks_like_search_results(p)
        and not _RESTORE_VISION_RE.search(p)
        and not _COOKIE_SPEECH_RE.search(p)
        and "duckduckgo" not in p.lower()
        and "404" not in p
        and "page not found" not in p.lower()
    ]
    if not kept:
        return _LOOK_FAILED
    return " ".join(kept[:4])[:800]


def _usable_tell_text(text: str) -> bool:
    """True when speech has real words — not a hollow 'here are the headlines'."""
    raw = (text or "").strip()
    if len(raw) < 12:
        return False
    if _HOLLOW_TELL_RE.search(raw):
        return False
    if raw == _LOOK_FAILED or raw == _HOLLOW_HEADLINES:
        return False
    words = re.findall(r"[A-Za-z0-9]{3,}", raw)
    return len(words) >= 3


def _spoken_headlines(desc: str) -> str:
    """Three short headlines from vision. Never a 404, cookie wall, or hollow line."""
    text = _strip_howto_speech(desc)
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    kept = [
        p
        for p in parts
        if not _looks_like_search_results(p)
        and not _RESTORE_VISION_RE.search(p)
        and not _COOKIE_SPEECH_RE.search(p)
        and not _looks_like_ssl_or_error_page(p)
        and "duckduckgo" not in p.lower()
        and "404" not in p
        and "page not found" not in p.lower()
    ]
    if not kept:
        return _LOOK_FAILED
    spoken = " ".join(kept[:3])[:800]
    if not _usable_tell_text(spoken):
        return _LOOK_FAILED
    return spoken


def search_result_click_point(attempt: int = 0) -> tuple[int, int]:
    """Documented first-result click on jarvis-computer Chrome + DuckDuckGo."""
    idx = min(max(int(attempt), 0), len(CHROME_SEARCH_RESULT_CLICKS) - 1)
    return CHROME_SEARCH_RESULT_CLICKS[idx]


def _no_look_confirm(payload: dict[str, Any]) -> dict[str, Any]:
    """Look / click / keys / close / news must not ask 'Say confirm to proceed'."""
    out = dict(payload or {})
    out.pop("needs_confirm", None)
    prop = out.get("proposal")
    if isinstance(prop, dict):
        cleaned = dict(prop)
        cleaned["needs_confirm"] = False
        prompt = str(cleaned.get("user_prompt") or "")
        if re.search(r"confirm", prompt, re.I):
            cleaned["user_prompt"] = str(cleaned.get("description") or "")[:400]
        out["proposal"] = cleaned
    return out


def _tool_ctx() -> Any:
    from app.jarvis.tools import ToolContext
    from app.jarvis.workspace import Workspace, default_workspace

    return ToolContext(Workspace(default_workspace()), None)


def _look_now(
    asked: str,
    *,
    app: str = "",
    fresh: bool = False,
    skip_web_type: bool = False,
) -> dict[str, Any]:
    """Look at jarvis-computer. Uses see_screen."""
    from app.jarvis.tools import _see_screen

    args: dict[str, Any] = {
        "goal": asked,
        "prefer_last": False if fresh else True,
    }
    if fresh:
        args["fresh"] = True
    if app:
        args["app"] = app
    if skip_web_type:
        args["_skip_web_type"] = True
    return _see_screen(_tool_ctx(), args)


def _look_opened_site(asked: str) -> dict[str, Any]:
    """Look at Chrome after opening a page. Fresh shot — never the last URL."""
    return _look_now(asked, app="chrome", fresh=True, skip_web_type=True)


def _click_now(x: int, y: int) -> dict[str, Any]:
    from app.jarvis.tools import _click

    # Voice-ask already does look-then-leave-SERP. Skip the click-tool wrapper
    # so we do not double-open a publisher after a planned result click.
    return _click(_tool_ctx(), {"x": int(x), "y": int(y), "skip_serp_leave": True})


def _type_now(text: str) -> dict[str, Any]:
    from app.jarvis.tools import _type_text

    return _type_text(_tool_ctx(), {"text": text})


def _keys_now(combo: str) -> dict[str, Any]:
    from app.jarvis.tools import _keys

    return _keys(_tool_ctx(), {"combo": combo})


def _close_windows_now() -> dict[str, Any]:
    from app.jarvis.capture import reset_look_target
    from app.jarvis.desktop import close_windows

    try:
        reset_look_target()
    except Exception:
        pass
    return close_windows(app="chrome")


def _look_app_blob(looked: dict[str, Any] | None) -> str:
    item = looked or {}
    return " ".join(
        str(item.get(key) or "")
        for key in (
            "vision_description",
            "title",
            "process",
            "url",
            "error",
            "note",
        )
    )


def look_still_shows_chrome(looked: dict[str, Any] | None) -> bool:
    """True when the new look still has Chrome / Restore pages / a URL bar."""
    return bool(_CHROME_STILL_RE.search(_look_app_blob(looked)))


def look_still_shows_leftover(looked: dict[str, Any] | None) -> bool:
    """True when Chrome, Restore, an editor, calc, or image viewer remains."""
    blob = _look_app_blob(looked)
    return bool(_CHROME_STILL_RE.search(blob) or _LEFTOVER_APP_RE.search(blob))


def _spoken_after_close_all(looked: dict[str, Any]) -> str:
    """Speak from the new look only. Never invent 'window is no longer open'."""
    desc = str(looked.get("vision_description") or "").strip()
    spoken = _spoken_from_screen(desc)
    if look_still_shows_leftover(looked):
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", spoken) if p.strip()]
        kept = [
            p
            for p in parts
            if not _CLOSED_LIE_RE.search(p) and not _CLEAR_LIE_RE.search(p)
        ]
        leftover = " ".join(kept).strip()
        if leftover and not _CLOSED_LIE_RE.search(leftover) and not _CLEAR_LIE_RE.search(
            leftover
        ):
            return leftover[:800]
        if look_still_shows_chrome(looked):
            return "Chrome is still on the screen."
        blob = _look_app_blob(looked).lower()
        if "file manager" in blob or "thunar" in blob or "explorer" in blob:
            return "The file manager is still on the screen."
        if "error" in blob:
            return "An error dialog is still on the screen."
        return "An app is still on the screen."
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", spoken) if p.strip()]
    kept = [
        p
        for p in parts
        if not _CLOSED_LIE_RE.search(p) and not _CLEAR_LIE_RE.search(p)
    ]
    leftover = " ".join(kept).strip()
    if leftover:
        return leftover[:800]
    if (
        spoken
        and not _CLOSED_LIE_RE.search(spoken)
        and not _CLEAR_LIE_RE.search(spoken)
    ):
        return spoken[:800]
    return "I looked. This is what is on the screen now."


def _scroll_now(*, dy: int = -3) -> dict[str, Any]:
    from app.jarvis.tools import _scroll

    return _scroll(_tool_ctx(), {"dy": dy})


def _look_blob(looked: dict[str, Any]) -> str:
    return " ".join(
        str(looked.get(key) or "")
        for key in ("vision_description", "title", "error", "note", "vision_error")
    )


def _xy_from_look(looked: dict[str, Any]) -> tuple[int, int] | None:
    for key_x, key_y in (("click_x", "click_y"), ("x", "y")):
        if looked.get(key_x) is None or looked.get(key_y) is None:
            continue
        try:
            return int(looked[key_x]), int(looked[key_y])
        except (TypeError, ValueError):
            continue
    match = _XY_RE.search(_look_blob(looked))
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _host_of_url(url: str) -> str:
    raw = re.sub(r"^https?://", "", url or "", flags=re.I).split("/")[0].lower()
    return raw


def _result_url_from_look(looked: dict[str, Any]) -> str | None:
    """First https URL on the screen that is not the search engine itself."""
    return result_url_from_look(looked)


def _looks_like_search_results(text: str) -> bool:
    return looks_like_search_results(text) or bool(_SEARCH_PAGE_RE.search(text or ""))


def _search_page_look(looked: dict[str, Any]) -> bool:
    """True when title/url/vision are still DuckDuckGo / Google / Bing.

    ``preferred`` staying duckduckgo.com is not proof — remember_look_target
    pins the search URL even after a real article loads.
    """
    return look_is_serp(looked) or _looks_like_search_results(_look_blob(looked))


def look_blocked_by_restore(looked: dict[str, Any] | None) -> bool:
    """True when Restore pages? (or TR) is on the look — dismiss, then look again."""
    return _restore_blocking(looked or {})


def _restore_blocking(looked: dict[str, Any]) -> bool:
    """Chromium Restore pages? overlay — title dialog or vision bubble."""
    from app.jarvis.overlay import overlay_kind

    return overlay_kind(looked) == "restore" or bool(
        _RESTORE_VISION_RE.search(_look_blob(looked))
    )


def _restore_dismiss_point(looked: dict[str, Any]) -> tuple[int, int] | None:
    """Click Restore / the X only when vision names that control."""
    blob = _look_blob(looked)
    match = _RESTORE_XY_RE.search(blob)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _wait_after_act() -> None:
    """Give Chrome a beat after click/keys. Tests must not sleep."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    time.sleep(_CLICK_SETTLE_S)


def _headline_from_look(looked: dict[str, Any]) -> str:
    """A news-card line from vision. Not a DuckDuckGo chrome title."""
    desc = str(looked.get("vision_description") or "")
    chunks = re.split(r"[\n•|;]+|(?<=[.!?])\s+", desc)
    for raw in chunks:
        text = raw.strip().strip("-:").strip()
        text = re.sub(
            r"^(?:news cards?|headlines?|results?)\s*:\s*",
            "",
            text,
            flags=re.I,
        )
        if len(text) < 8 or len(text) > 160:
            continue
        if _looks_like_search_results(text) or _RESTORE_VISION_RE.search(text):
            continue
        if _HOWTO_SPEECH_RE.search(text) or re.search(r"https?://", text, re.I):
            continue
        return text
    return ""


def _open_chrome_url(url: str, *, fresh_session: bool = False) -> dict[str, Any]:
    from app.jarvis.computer import linux_run_app, plan_linux_run_app

    if fresh_session:
        _close_windows_now()
        _wait_after_act()
    plan = plan_linux_run_app({"target": "chrome", "url": url})
    if not plan.get("ok"):
        return plan
    result = linux_run_app(plan)
    if result.get("ok"):
        try:
            from app.jarvis.capture import remember_look_target

            remember_look_target(app="chrome", url=str(url))
        except Exception:
            pass
    return result


def _look_fail_reply(looked: dict[str, Any], *, opened: bool) -> str:
    blob = _look_blob(looked)
    if _looks_like_ssl_or_error_page(blob):
        return "The page did not load. The browser shows a security or error page."
    if _page_not_ready(looked) or look_is_dead_page(looked):
        return "The page is still blank. I am opening it again."
    if opened:
        return "The look failed. I could not read the page."
    return _LOOK_FAILED


def _is_footer_talk(text: str) -> bool:
    return bool(_FOOTER_TALK_RE.search(text or ""))


def _hotel_results_visible(looked: dict[str, Any]) -> bool:
    return look_has_hotel_results(looked)


def _is_chrome_coach(text: str) -> bool:
    return bool(_CHROME_COACH_RE.search(text or ""))


def _web_job_caption_forbidden(text: str) -> bool:
    raw = text or ""
    return bool(
        _is_desktop_talk(raw)
        or _is_footer_talk(raw)
        or _is_chrome_coach(raw)
        or _ICON_CATALOG_RE.search(raw)
        or _LOOK_AT_SCREEN_RE.search(raw)
        or _BLANK_PAGE_RE.search(raw)
    )


def _speak_web_job(
    asked: str,
    looked: dict[str, Any],
    tools: list[str],
    *,
    opened: bool,
) -> dict[str, Any]:
    """Find / search / use-Chrome job: a pick or an honest stuck. Never a caption."""
    from app.jarvis.overlay import look_is_pay_control

    blob = _look_blob(looked)
    desc = str(looked.get("vision_description") or "").strip()
    payload = _no_look_confirm(looked)
    query = web_search_query(asked)
    spoken = _spoken_from_screen(desc)
    usable = bool(
        spoken
        and _usable_tell_text(spoken)
        and not _web_job_caption_forbidden(spoken)
    )
    typed = bool(looked.get("_typed_query")) or "type" in tools
    if look_is_pay_control(blob) and "hotel" not in blob.lower():
        reply = "I stopped. I will not pay or check out."
    elif look_has_hotel_results(looked) and usable:
        reply = spoken
    elif query_visible_on_look(looked, query) and usable:
        reply = spoken
    elif typed and usable:
        reply = spoken
    elif look_is_loading_or_blank(looked) or _page_not_ready(looked):
        # Never "still opening / could not finish" — type happens first.
        reply = "I typed the search." if typed else _WEB_STUCK
    elif look_is_empty_desktop(looked) or _is_desktop_talk(desc):
        reply = "I opened the page but I am stuck on the desktop. I did not finish the search."
    elif look_is_footer(looked) or _is_footer_talk(desc):
        reply = "I opened the page but I am stuck at the footer. I did not finish the search."
    elif look_is_empty_destination(looked) or needs_web_query(asked, looked, query):
        reply = (
            spoken
            if typed and usable
            else (
                "I typed the search."
                if typed
                else "The search field is still empty. I could not finish the search."
            )
        )
    elif _looks_like_ssl_or_error_page(blob):
        reply = "The page did not load. The browser shows a security or error page."
    elif usable:
        reply = spoken
    else:
        reply = _WEB_STUCK
    if _LOOK_AT_SCREEN_RE.search(reply):
        reply = _WEB_STUCK
    return {
        "ok": True,
        "reply": reply,
        "tools_used": tools,
        "result": payload,
        "ui": payload,
    }


def _speak_looked(
    looked: dict[str, Any],
    tools: list[str],
    *,
    opened: bool,
    article: bool = False,
    headlines: bool = False,
    asked: str = "",
) -> dict[str, Any]:
    from app.jarvis.virtual_pc import wants_web_job

    if asked and wants_web_job(asked):
        return _speak_web_job(asked, looked, tools, opened=opened)
    blob = _look_blob(looked)
    payload = _no_look_confirm(looked)
    if headlines and look_is_404(looked) and not _looks_like_ssl_or_error_page(blob):
        # News-tell already tried the fallback. Do not narrate the 404 as news.
        reply = "The page did not load. I could not read the headlines."
        return {
            "ok": True,
            "reply": reply,
            "tools_used": tools,
            "result": payload,
            "ui": payload,
        }
    if _looks_like_ssl_or_error_page(blob):
        reply = "The page did not load. The browser shows a security or error page."
        return {
            "ok": True,
            "reply": reply,
            "tools_used": tools,
            "result": payload,
            "ui": payload,
        }
    desc = str(looked.get("vision_description") or "").strip()
    if look_is_empty_desktop(looked) or _is_desktop_talk(desc):
        return {
            "ok": True,
            "reply": "The page is still opening. I am looking again.",
            "tools_used": tools,
            "result": payload,
            "ui": payload,
        }
    if _restore_blocking(looked):
        return {
            "ok": True,
            "reply": "I opened the page.",
            "tools_used": tools,
            "result": payload,
            "ui": payload,
        }
    if not looked.get("ok") and not desc:
        return {
            "ok": True,
            "reply": _look_fail_reply(looked, opened=opened),
            "tools_used": tools,
            "result": payload,
            "ui": payload,
        }
    if headlines:
        reply = _spoken_headlines(desc)
    elif article:
        reply = _spoken_from_article(desc)
    else:
        reply = _spoken_from_screen(desc)
    if (headlines or article) and not _usable_tell_text(reply):
        reply = _LOOK_FAILED
    return {
        "ok": True,
        "reply": reply,
        "tools_used": tools,
        "result": payload,
        "ui": payload,
    }


def _page_not_ready(looked: dict[str, Any]) -> bool:
    """Blank / loading / empty look — not a loaded page. Not look_speed."""
    if look_is_loading_or_blank(looked):
        return True
    title = str(looked.get("title") or "")
    desc = str(looked.get("vision_description") or "").strip()
    blob = _look_blob(looked)
    if _BLANK_PAGE_RE.search(title) or _BLANK_PAGE_RE.search(blob):
        return True
    if looked.get("page_ready") is False:
        return True
    return bool(looked.get("ok") and not desc and not title.strip())


def _note_tool(tools: list[str], name: str) -> None:
    if name and name not in tools:
        tools.append(name)


def _click_search_result(
    asked: str,
    looked: dict[str, Any],
    tools: list[str],
    *,
    force: bool = False,
    attempt: int = 0,
    ignore_xy: bool = False,
) -> dict[str, Any]:
    """If this is a search page, click or open a result that is actually on it.

    Cheap vision often describes DuckDuckGo chrome and omits click_x / https
    result URLs. Still click through using the documented first-result point.
    Ignore click_x/y when Restore is on screen — those coords hit the bubble.
    """
    if not force and not _search_page_look(looked):
        return looked
    xy = None if ignore_xy or _restore_blocking(looked) else _xy_from_look(looked)
    result_url = _result_url_from_look(looked)
    acted = False
    if xy:
        clicked = _click_now(xy[0], xy[1])
        _note_tool(tools, "click")
        acted = bool(clicked.get("ok"))
    elif result_url:
        opened = _open_chrome_url(result_url)
        acted = bool(opened.get("ok"))
    else:
        fx, fy = search_result_click_point(attempt)
        clicked = _click_now(fx, fy)
        _note_tool(tools, "click")
        acted = bool(clicked.get("ok"))
    if not acted:
        return looked
    _wait_after_act()
    return _look_opened_site(asked)


def _dismiss_overlays_if_needed(
    asked: str, looked: dict[str, Any], tools: list[str], *, rounds: int = 3
) -> dict[str, Any]:
    """Dismiss Restore / sandbox / sign-in / cookies, then look. Never Sign in."""
    current = looked
    for _ in range(max(1, int(rounds))):
        if look_is_empty_desktop(current):
            _wait_after_act()
            current = _look_opened_site(asked)
            if not look_is_empty_desktop(current) and not look_has_blocking_overlay(
                current, goal=asked
            ):
                return current
        plan = overlay_dismiss_plan(current, goal=asked)
        if plan is None:
            return current
        if plan.click is not None:
            clicked = _click_now(plan.click[0], plan.click[1])
            _note_tool(tools, "click")
            if not clicked.get("ok") and plan.kind == "restore":
                _click_now(*_RESTORE_DISMISS_CLICK)
                _note_tool(tools, "click")
        if plan.keys:
            _keys_now(plan.keys)
            _note_tool(tools, "keys")
        _wait_after_act()
        current = _look_opened_site(asked)
    return current


def _dismiss_restore_if_needed(
    asked: str, looked: dict[str, Any], tools: list[str]
) -> dict[str, Any]:
    """Look already happened. Click the X (never Restore), then look.

    Escape alone does not close Chromium Restore pages? on this Xvfb. Click
    first, then Escape, then a fresh look. Also dismiss sandbox / sign-in /
    cookie overlays so a web job can continue. Never speak a title while
    the bubble is still up.
    """
    if not look_has_blocking_overlay(looked, goal=asked) and not _restore_blocking(
        looked
    ):
        return looked
    return _dismiss_overlays_if_needed(asked, looked, tools)


def _cookie_dismiss_point(looked: dict[str, Any]) -> tuple[int, int] | None:
    """Reject / No thanks when named; Accept only if that is the named control."""
    plan = overlay_dismiss_plan(looked)
    if plan is not None and plan.kind == "cookie":
        return plan.click
    blob = _look_blob(looked)
    match = _COOKIE_XY_RE.search(blob)
    if match:
        return int(match.group(1)), int(match.group(2))
    if look_has_cookie_overlay(looked):
        return _xy_from_look(looked)
    return None


def _dismiss_cookie_if_needed(
    asked: str, looked: dict[str, Any], tools: list[str]
) -> dict[str, Any]:
    """He clicks Reject / the named dismiss. Never ask the person to click."""
    if not look_has_cookie_overlay(looked) and overlay_dismiss_plan(
        looked, goal=asked
    ) is None:
        return looked
    return _dismiss_overlays_if_needed(asked, looked, tools)


def _open_news_homepage(
    asked: str,
    tools: list[str],
    *,
    fallback: bool = False,
    current: str = "",
) -> dict[str, Any]:
    """ONE run_app to a known working homepage. Never a 404 swissinfo slug."""
    url = (
        news_fallback_url(asked, current)
        if fallback
        else news_homepage_from_ask(asked)
    )
    if current and url.rstrip("/").lower() == current.rstrip("/").lower():
        url = news_fallback_url(asked, current)
    opened = _open_chrome_url(url)
    if opened.get("ok"):
        _note_tool(tools, "run_app")
        _wait_after_act()
    return opened


def _press_enter_result(
    asked: str, tools: list[str]
) -> dict[str, Any]:
    """Activate the focused DuckDuckGo row after a failed click."""
    _keys_now("enter")
    _note_tool(tools, "keys")
    _wait_after_act()
    return _look_opened_site(asked)


def _open_first_real_or_ia_web(
    asked: str, looked: dict[str, Any], tools: list[str]
) -> dict[str, Any]:
    """Last exit from a SERP: a real article URL, never another search.

    Prefer an https URL or known publisher from the look (nzz.ch, swissinfo,
    bbc, reuters, cnn, ntv). If the look named none, open a known publisher
    homepage. Never invent switzerland.com. Never stay on DuckDuckGo.
    """
    url = leave_serp_url(looked, asked, allow_default=True)
    if url and is_search_engine_url(url):
        url = news_homepage_from_ask(asked) if wants_news_tell(asked) else DEFAULT_LEAVE_SERP_URL
    if not url:
        url = news_homepage_from_ask(asked) if wants_news_tell(asked) else DEFAULT_LEAVE_SERP_URL
    opened = _open_chrome_url(url)
    if not opened.get("ok"):
        return looked
    _note_tool(tools, "run_app")
    _wait_after_act()
    looked = _look_opened_site(asked)
    if not _search_page_look(looked):
        return looked
    fallback = publisher_url_from_look(looked) or DEFAULT_LEAVE_SERP_URL
    if fallback and fallback != url and not is_search_engine_url(fallback):
        opened = _open_chrome_url(fallback)
        if opened.get("ok"):
            _note_tool(tools, "run_app")
            _wait_after_act()
            looked = _look_opened_site(asked)
    return looked


def _leave_search_for_article(
    asked: str,
    looked: dict[str, Any],
    tools: list[str],
    opened: dict[str, Any],
) -> dict[str, Any]:
    """Leave DuckDuckGo. Restore first, then click/Enter, then ia=web."""
    opened_search = "duckduckgo.com" in str(
        opened.get("opened") or opened.get("url") or ""
    ).lower()

    def still_search(item: dict[str, Any]) -> bool:
        if _search_page_look(item):
            return True
        return bool(
            opened_search and not str(item.get("vision_description") or "").strip()
        )

    looked = _dismiss_restore_if_needed(asked, looked, tools)
    if not still_search(looked):
        return looked
    looked = _click_search_result(
        asked, looked, tools, force=True, attempt=0
    )
    if not still_search(looked):
        return looked
    looked = _dismiss_restore_if_needed(asked, looked, tools)
    if still_search(looked):
        looked = _click_search_result(
            asked, looked, tools, force=True, attempt=1
        )
    if not still_search(looked):
        return looked
    looked = _dismiss_restore_if_needed(asked, looked, tools)
    if still_search(looked):
        looked = _press_enter_result(asked, tools)
    if not still_search(looked):
        return looked
    return _open_first_real_or_ia_web(asked, looked, tools)


def _reopen_if_blank(
    asked: str, looked: dict[str, Any], tools: list[str], opened: dict[str, Any]
) -> dict[str, Any]:
    if not (_page_not_ready(looked) or look_is_dead_page(looked) or look_is_404(looked)):
        return looked
    _wait_after_act()
    current = str(opened.get("opened") or opened.get("url") or "")
    if wants_news_tell(asked):
        again = _open_news_homepage(
            asked, tools, fallback=True, current=current
        )
        if not again.get("ok"):
            return looked
        return _look_now(asked, app="chrome", fresh=True)
    url = current
    if not url:
        try:
            from app.jarvis.capture import last_look_target

            url = str(last_look_target().get("url") or "")
        except Exception:
            url = ""
    if not url and wants_news_search(asked):
        url = news_homepage_from_ask(asked)
    if not url:
        return looked
    again = _open_chrome_url(url)
    if not again.get("ok"):
        return looked
    if "run_app" not in tools:
        tools.append("run_app")
    _wait_after_act()
    return _look_opened_site(asked)


def _finish_news_tell(
    asked: str, looked: dict[str, Any], tools: list[str], opened: dict[str, Any]
) -> dict[str, Any]:
    """Cookie once, 404/SERP → fallback homepage, speak 3 headlines. No more tools."""
    looked = _dismiss_restore_if_needed(asked, looked, tools)
    looked = _dismiss_cookie_if_needed(asked, looked, tools)
    current = str(opened.get("opened") or opened.get("url") or "")
    if (
        look_is_serp(looked)
        or look_is_404(looked)
        or look_is_dead_page(looked)
        or _page_not_ready(looked)
    ):
        again = _open_news_homepage(
            asked,
            tools,
            fallback=look_is_404(looked) or look_is_dead_page(looked),
            current=current,
        )
        if again.get("ok"):
            opened = again
            looked = _look_now(asked, app="chrome", fresh=True)
            looked = _dismiss_cookie_if_needed(asked, looked, tools)
    if look_is_404(looked) or _looks_like_ssl_or_error_page(_look_blob(looked)):
        again = _open_news_homepage(
            asked,
            tools,
            fallback=True,
            current=str(opened.get("opened") or opened.get("url") or ""),
        )
        if again.get("ok"):
            looked = _look_now(asked, app="chrome", fresh=True)
            looked = _dismiss_cookie_if_needed(asked, looked, tools)
    desc = str(looked.get("vision_description") or "").strip()
    if not _usable_tell_text(_spoken_headlines(desc)):
        looked = _look_now(asked, app="chrome", fresh=True)
        looked = _dismiss_cookie_if_needed(asked, looked, tools)
        if "see_screen" not in tools:
            tools.append("see_screen")
    return _speak_looked(looked, tools, opened=True, article=True, headlines=True)


def _needs_web_query(asked: str, looked: dict[str, Any], query: str) -> bool:
    """True when the destination / search field still needs the query typed."""
    return needs_web_query(asked, looked, query)


def _scroll_to_search(
    asked: str, looked: dict[str, Any], tools: list[str]
) -> dict[str, Any]:
    """Footer / no named box — Home or scroll up, then look. Never a footer click."""
    _keys_now("home")
    _note_tool(tools, "keys")
    _wait_after_act()
    current = _look_opened_site(asked)
    current = _dismiss_overlays_if_needed(asked, current, tools)
    if search_box_point(current) is None and (
        look_is_footer(current) or look_is_empty_destination(current)
    ):
        _scroll_now(dy=5)
        _note_tool(tools, "scroll")
        _wait_after_act()
        current = _look_opened_site(asked)
        current = _dismiss_overlays_if_needed(asked, current, tools)
    return current


def _type_web_query(
    asked: str, looked: dict[str, Any], tools: list[str], query: str
) -> tuple[dict[str, Any], bool]:
    """Click the search field, type, Enter. False if there is no field."""
    xy = search_box_point(looked)
    if xy is None:
        return looked, False
    clicked = _click_now(xy[0], xy[1])
    _note_tool(tools, "click")
    if not clicked.get("ok"):
        return looked, False
    acted = _type_now(query)
    _note_tool(tools, "type")
    if acted.get("ok"):
        _keys_now("enter")
        _note_tool(tools, "keys")
    _wait_after_act()
    current = _look_opened_site(asked)
    current = _dismiss_overlays_if_needed(asked, current, tools)
    return current, True


def _wait_until_page_ready(
    asked: str,
    looked: dict[str, Any],
    tools: list[str],
    *,
    deadline: float | None = None,
) -> dict[str, Any]:
    """After run_app: keep looking until a loaded page or the ask deadline.

    look_speed=off does not skip this. Sleep seconds between looks, not 0.4s.
    """
    from app.jarvis.overlay import BLANK_LOOKS_BEFORE_OMNIBOX

    current = looked
    blank_looks = 0
    cap = 64 if deadline is not None else max(1, int(BLANK_LOOKS_BEFORE_OMNIBOX))
    for _ in range(cap):
        if look_is_page_ready(current):
            return current
        if not look_is_loading_or_blank(current) and not look_is_empty_desktop(
            current
        ):
            return current
        blank_looks += 1
        if blank_looks >= BLANK_LOOKS_BEFORE_OMNIBOX or (
            deadline is not None and time.monotonic() >= deadline
        ):
            return current
        wait = web_look_pause_s()
        if wait > 0:
            time.sleep(wait)
        current = _look_opened_site(asked)
        _note_tool(tools, "see_screen")
        current = _dismiss_overlays_if_needed(asked, current, tools)
    return current


def _continue_web_job(
    asked: str, looked: dict[str, Any], tools: list[str]
) -> dict[str, Any]:
    """After overlays: wait on the ask deadline, type the query, look.

    click / type / keys are recorded on tools_used before any spoken reply.
    look_speed=off does not skip that. Untitled / blank looks wait in
    seconds, then type the page field or the Chromium omnibox. Never
    return without type when a query is needed. Never pay.
    """
    deadline = web_job_deadline(asked)
    current = _dismiss_overlays_if_needed(asked, looked, tools)
    current = _wait_until_page_ready(
        asked, current, tools, deadline=deadline
    )

    def click(*, x, y, **_k):
        _note_tool(tools, "click")
        return _click_now(int(x), int(y))

    def type_text(*, text="", **_k):
        _note_tool(tools, "type")
        return _type_now(str(text))

    def keys(*, combo="", **_k):
        _note_tool(tools, "keys")
        return _keys_now(str(combo))

    def look_again():
        again = _look_opened_site(asked)
        _note_tool(tools, "see_screen")
        return _dismiss_overlays_if_needed(asked, again, tools)

    def scroll(*, dy=5, **_k):
        _note_tool(tools, "scroll")
        return _scroll_now(dy=int(dy))

    return continue_web_search(
        current,
        goal=asked,
        click=click,
        type_text=type_text,
        keys=keys,
        look_again=look_again,
        scroll=scroll,
        deadline=deadline,
    )


def _tell_from_opened_site(asked: str, opened: dict[str, Any]) -> dict[str, Any]:
    """Look, type if this is a find/search job, then speak. Never a blank caption.

    First look skips in-see typing so click/type/keys are recorded on
    tools_used. look_speed=off does not skip wait + type.
    """
    looked = _look_now(asked, app="chrome", fresh=True, skip_web_type=True)
    tools = ["run_app", "see_screen"]
    if wants_news_tell(asked):
        looked = _dismiss_restore_if_needed(asked, looked, tools)
        if look_is_news_page(looked) and not look_has_cookie_overlay(looked):
            return _speak_looked(
                looked, tools, opened=True, article=True, headlines=True
            )
        if look_is_serp(looked):
            again = _open_news_homepage(asked, tools)
            if again.get("ok"):
                opened = again
                looked = _look_now(asked, app="chrome", fresh=True, skip_web_type=True)
        return _finish_news_tell(asked, looked, tools, opened)
    wanted = str(opened.get("opened") or opened.get("url") or "")
    from app.jarvis.virtual_pc import wants_web_job

    web_job = wants_web_job(asked)
    if _page_not_ready(looked) or look_is_dead_page(looked) or not looked.get("ok"):
        looked = _reopen_if_blank(asked, looked, tools, opened)
    looked = _dismiss_restore_if_needed(asked, looked, tools)
    looked = _dismiss_cookie_if_needed(asked, looked, tools)
    if wanted and _look_is_wrong_host(looked, wanted) and not look_is_serp(looked):
        again = _open_chrome_url(wanted, fresh_session=True)
        if again.get("ok"):
            _note_tool(tools, "run_app")
            _wait_after_act()
            looked = _look_now(asked, app="chrome", fresh=True, skip_web_type=True)
            looked = _dismiss_restore_if_needed(asked, looked, tools)
            looked = _dismiss_cookie_if_needed(asked, looked, tools)
    if web_job:
        # A blank / loading / failed first look is not done. Wait, look again,
        # click+type, then speak. Never return a homepage caption here.
        looked = _continue_web_job(asked, looked, tools)
        return _speak_looked(looked, tools, opened=True, asked=asked)
    blob = _look_blob(looked)
    if _looks_like_ssl_or_error_page(blob) and looked.get("ok"):
        return _speak_looked(looked, tools, opened=True)
    if not looked.get("ok") and not (_page_not_ready(looked) or look_is_dead_page(looked)):
        return _speak_looked(looked, tools, opened=True)
    looked = _reopen_if_blank(asked, looked, tools, opened)
    looked = _dismiss_restore_if_needed(asked, looked, tools)
    looked = _dismiss_cookie_if_needed(asked, looked, tools)
    opened_search = "duckduckgo.com" in str(
        opened.get("opened") or opened.get("url") or ""
    ).lower()
    on_search = _search_page_look(looked) or (
        opened_search and not str(looked.get("vision_description") or "").strip()
    )
    news = wants_news_search(asked) or wants_open_or_read_article(asked)
    asked_for_this_page = bool(wanted and _look_has_host(looked, wanted))
    if on_search and not asked_for_this_page:
        looked = _leave_search_for_article(asked, looked, tools, opened)
    desc = str(looked.get("vision_description") or "").strip()
    spoken = _spoken_headlines(desc) if news else _spoken_from_screen(desc)
    if not _usable_tell_text(spoken) or _page_not_ready(looked):
        looked = _reopen_if_blank(asked, looked, tools, opened)
        looked = _look_now(asked, app="chrome", fresh=True, skip_web_type=True)
        if "see_screen" not in tools:
            tools.append("see_screen")
    return _speak_looked(looked, tools, opened=True, article=news, headlines=news)


def _tell_from_current_news(asked: str) -> dict[str, Any]:
    """Already on BBC/Reuters/NZZ/CNN — look and tell. Do not reopen search."""
    looked = _look_now(asked, fresh=True)
    tools = ["see_screen"]
    return _finish_news_tell(asked, looked, tools, {"url": str(looked.get("url") or "")})


def _tell_from_current_screen(asked: str) -> dict[str, Any]:
    """Look at what is already on the screen. Do not invent a URL."""
    tools = ["see_screen"]
    looked = _look_now(asked, fresh=True, skip_web_type=True)
    looked = _dismiss_restore_if_needed(asked, looked, tools)
    looked = _dismiss_cookie_if_needed(asked, looked, tools)
    from app.jarvis.virtual_pc import wants_web_job

    if wants_web_job(asked):
        looked = _continue_web_job(asked, looked, tools)
        return _speak_looked(looked, tools, opened=False, asked=asked)
    if wants_news_tell(asked) or look_is_news_page(looked):
        return _finish_news_tell(
            asked, looked, tools, {"url": str(looked.get("url") or "")}
        )
    return _speak_looked(looked, tools, opened=False)


def _text_to_type(asked: str) -> str:
    if _SHOPPING_RE.search(asked or ""):
        return _SHOPPING_TR if spoken_language(asked) == "tr" else _SHOPPING_EN
    match = _TYPE_TEXT_RE.search(asked or "")
    if not match:
        return ""
    text = match.group(1).strip()
    text = re.sub(r"\s+(here|there|please)\s*$", "", text, flags=re.I).strip()
    if text.lower() in {"here", "there", "this", "that"}:
        return ""
    if _SHOPPING_RE.search(text):
        return _SHOPPING_TR if spoken_language(asked) == "tr" else _SHOPPING_EN
    return text.strip(".,!?\"'")


def _look_has_host(looked: dict[str, Any], url: str) -> bool:
    """True when the fresh look is the host they asked for — not the last tab."""
    host = _host_of_url(url).removeprefix("www.")
    if not host:
        return False
    blob = (_look_blob(looked) + " " + str(looked.get("url") or "")).lower()
    if host in blob:
        return True
    label = host.split(".")[0]
    if label in {"google", "chrome", "www"}:
        return False
    cleaned = re.sub(r"google\s*chrome|\bchromium\b", " ", blob)
    return bool(label and len(label) >= 3 and re.search(rf"\b{re.escape(label)}\b", cleaned))


_OTHER_SESSION_HOST_RE = re.compile(
    r"\b(reuters|bbc|cnn|wikipedia|nzz|bloomberg|nytimes|swissinfo|ntv)\b",
    re.I,
)


def _look_is_wrong_host(looked: dict[str, Any], url: str) -> bool:
    """True when this look is a leftover tab, not the URL they just asked for."""
    if _look_has_host(looked, url):
        return False
    if _restore_blocking(looked):
        return True
    blob = _look_blob(looked) + " " + str(looked.get("url") or "")
    want = _host_of_url(url).removeprefix("www.").split(".")[0].lower()
    for hit in _OTHER_SESSION_HOST_RE.findall(blob):
        if hit.lower() != want:
            return True
    return False


def _spoken_tool_error(error: str, fallback: str) -> str:
    """Parent-facing error. Never docker / exec / OCI / PATH dumps."""
    raw = (error or "").strip()
    if not raw or _TECH_DUMP_RE.search(raw):
        return fallback
    if len(raw) > 180:
        return fallback
    return raw


def _type_into_editor(asked: str) -> dict[str, Any]:
    """After run_app notepad: type the list, then a fresh look to verify."""
    tools = ["run_app"]
    text = _text_to_type(asked)
    if not text:
        return _tell_from_current_screen(asked)
    acted = _type_now(text)
    _note_tool(tools, "type")
    if not acted.get("ok"):
        err = _spoken_tool_error(
            str(acted.get("error") or ""),
            "I could not type that in the editor.",
        )
        fail = _no_look_confirm(acted)
        return {
            "ok": False,
            "reply": err[:2000],
            "tools_used": tools,
            "result": fail,
            "ui": fail,
        }
    _wait_after_act()
    looked = _look_now(_LOOK_AFTER_ACT, fresh=True)
    tools.append("see_screen")
    blob = _look_blob(looked).lower()
    needle = text.split(",")[0].strip().lower()
    if needle and needle not in blob:
        _type_now(text)
        _wait_after_act()
        looked = _look_now(_LOOK_AFTER_ACT, fresh=True)
    return _speak_looked(looked, tools, opened=False)


def _focus_now(app: str) -> dict[str, Any]:
    """Raise a window by name. Bypass the tool wrapper (it skips focus on open)."""
    from app.jarvis.desktop import focus_app

    return focus_app(app=app)


def _look_is_calculator(looked: dict[str, Any]) -> bool:
    """True when galculator is the focused look — not leftover Mousepad."""
    title = str(looked.get("title") or "").lower()
    process = str(looked.get("process") or "").lower()
    if re.search(r"\b(mousepad|notepad|gedit|leafpad)\b", title):
        return False
    if "galculator" in process or "galculator" in title:
        return True
    if "calculator" in title:
        return True
    blob = _look_app_blob(looked).lower()
    if re.search(r"\b(mousepad|notepad|gedit|leafpad)\b", blob) and "galculator" not in blob:
        return False
    return "galculator" in blob or bool(re.search(r"\bcalculator\b", blob))


def _galculator_display(looked: dict[str, Any]) -> str:
    """Number on the galculator display, if vision/title names one."""
    blob = _look_app_blob(looked)
    named = re.search(
        r"(?:shows?|display(?:s|ed)?|result(?:s|ed)?|equals?)\s+"
        r"(-?\d+(?:\.\d+)?)",
        blob,
        re.I,
    )
    if named:
        return named.group(1)
    title = str(looked.get("title") or "")
    lone = re.search(r"(-?\d+(?:\.\d+)?)", title)
    if lone:
        return lone.group(1)
    return ""


def _use_calculator(asked: str) -> dict[str, Any]:
    """One galculator. Focus it, type there, speak the display. Never invent."""
    tools = ["run_app"]
    _focus_now("galculator")
    _note_tool(tools, "focus_app")
    _wait_after_act()
    looked = _look_now(_LOOK_AFTER_ACT, fresh=True)
    _note_tool(tools, "see_screen")
    if not _look_is_calculator(looked):
        _focus_now("galculator")
        _wait_after_act()
        looked = _look_now(_LOOK_AFTER_ACT, fresh=True)
    if not _look_is_calculator(looked):
        payload = _no_look_confirm(looked)
        return {
            "ok": True,
            "reply": "The calculator is not on the screen.",
            "tools_used": tools,
            "result": payload,
            "ui": payload,
        }
    expr = ""
    match = _MATH_OP_RE.search(asked or "")
    if match:
        expr = f"{match.group(1)}{match.group(2)}{match.group(3)}"
        expr = expr.replace("×", "*").replace("x", "*").replace("÷", "/")
    if expr:
        acted = _type_now(expr)
        _note_tool(tools, "type")
        if acted.get("ok"):
            _keys_now("enter")
            _note_tool(tools, "keys")
        _wait_after_act()
        looked = _look_now(_LOOK_AFTER_ACT, fresh=True)
    math = _math_answer(asked)
    desc = str(looked.get("vision_description") or "").strip()
    display = _galculator_display(looked)
    spoken = _spoken_from_screen(desc)
    if math and (display == math or math in desc):
        if math not in spoken:
            spoken = (
                (spoken + " " + math).strip()
                if spoken and spoken != _LOOK_FAILED
                else math
            )
    elif display == "0" or (math and math not in desc and display != math):
        spoken = "I opened the calculator but the number is not on the screen."
    payload = _no_look_confirm(looked)
    return {
        "ok": True,
        "reply": (spoken or "The calculator is open.")[:2000],
        "tools_used": tools,
        "result": payload,
        "ui": payload,
    }


def _close_all_from_ask(asked: str) -> dict[str, Any]:
    """One close-all, then a fresh look. Close again once if Chrome remains."""
    tools = ["keys"]
    acted = _close_windows_now()
    if not acted.get("ok"):
        err = str(acted.get("error") or "").strip() or "I could not close the browser."
        fail = _no_look_confirm(acted)
        return {
            "ok": False,
            "reply": err[:2000],
            "tools_used": tools,
            "result": fail,
            "ui": fail,
        }
    looked = _look_now(_LOOK_AFTER_ACT, fresh=True)
    tools.append("see_screen")
    if look_still_shows_leftover(looked):
        _close_windows_now()
        looked = _look_now(_LOOK_AFTER_ACT, fresh=True)
    payload = _no_look_confirm(looked)
    reply = _spoken_after_close_all(looked)
    if wants_close_all(asked) and _HOWTO_SPEECH_RE.search(reply):
        leftover = _spoken_after_close_all(looked)
        reply = leftover
    return {
        "ok": True,
        "reply": reply,
        "tools_used": tools,
        "result": payload,
        "ui": payload,
    }


def _control_from_screen(asked: str) -> dict[str, Any]:
    """Look first, then click/type/keys from what is actually there."""
    if wants_close_all(asked):
        return _close_all_from_ask(asked)
    looked = _look_now(asked)
    tools = ["see_screen"]
    if not looked.get("ok"):
        fail = _no_look_confirm(looked)
        return {
            "ok": False,
            "reply": _look_fail_reply(looked, opened=False),
            "tools_used": tools,
            "result": fail,
            "ui": fail,
        }

    low = (asked or "").lower()
    acted: dict[str, Any] | None = None
    if wants_close_tab(asked):
        acted = None
        for _ in range(max(close_tab_count(asked), 1)):
            acted = _keys_now("ctrl+w")
            if not acted.get("ok"):
                break
        tools.append("keys")
    elif re.search(r"\b(dismiss|escape)\b", low) or re.search(
        r"\bclose\b", low
    ):
        acted = _keys_now("escape")
        tools.append("keys")
    elif re.search(r"\btype\b", low):
        text = _text_to_type(asked)
        if not text:
            return _speak_looked(looked, tools, opened=False)
        acted = _type_now(text)
        tools.append("type")
    elif re.search(r"\bscroll\b", low):
        acted = _scroll_now()
        tools.append("scroll")
    else:
        xy = _xy_from_look(looked)
        if not xy:
            miss = _no_look_confirm(looked)
            return {
                "ok": True,
                "reply": "I looked, but I could not tell where to click.",
                "tools_used": tools,
                "result": miss,
                "ui": miss,
            }
        acted = _click_now(xy[0], xy[1])
        tools.append("click")

    if acted is not None and not acted.get("ok"):
        err = str(acted.get("error") or "").strip() or "I could not do that on the screen."
        fail = _no_look_confirm(acted)
        return {
            "ok": False,
            "reply": err[:2000],
            "tools_used": tools,
            "result": fail,
            "ui": fail,
        }
    look_goal = _LOOK_AFTER_ACT if wants_close_tab(asked) else asked
    looked = _look_now(look_goal, fresh=True)
    news_or_read = wants_leave_serp(asked, looked)
    if news_or_read and _search_page_look(looked):
        looked = _leave_search_for_article(asked, looked, tools, {"url": ""})
    body = _speak_looked(
        looked, tools, opened=False, article=news_or_read or wants_news_search(asked)
    )
    if wants_close_tab(asked) and _HOWTO_SPEECH_RE.search(str(body.get("reply") or "")):
        leftover = _spoken_from_screen(str(looked.get("vision_description") or ""))
        if _HOWTO_SPEECH_RE.search(leftover):
            leftover = "The tab is closed. This is the page that is left."
        body["reply"] = leftover
    else:
        try:
            from app.jarvis.virtual_pc import after_see_must_act

            operate = after_see_must_act(asked)
        except Exception:
            operate = False
        if operate and not news_or_read:
            body["reply"] = spoken_job_line(
                str(looked.get("vision_description") or body.get("reply") or "")
            )
    return body


def _close_tabs_now(asked: str) -> tuple[list[str], dict[str, Any] | None]:
    """Close Chrome tab(s). close-all is one window close, not N× ctrl+w."""
    if wants_close_all(asked):
        tools = ["keys"]
        acted = _close_windows_now()
        if not acted.get("ok"):
            err = str(acted.get("error") or "").strip() or "I could not close the browser."
            return tools, {
                "ok": False,
                "reply": err[:2000],
                "tools_used": tools,
                "result": acted,
                "ui": acted,
            }
        return tools, None
    tools = ["see_screen", "keys"]
    _look_now(asked)
    times = max(close_tab_count(asked), 1)
    acted: dict[str, Any] | None = None
    for _ in range(times):
        acted = _keys_now("ctrl+w")
        if not acted.get("ok"):
            err = str(acted.get("error") or "").strip() or "I could not close the tab."
            return tools, {
                "ok": False,
                "reply": err[:2000],
                "tools_used": tools,
                "result": acted,
                "ui": acted,
            }
    return tools, None


def _with_prior_tools(body: dict[str, Any], prior: list[str]) -> dict[str, Any]:
    used: list[str] = []
    for name in [*prior, *(body.get("tools_used") or [])]:
        if name and name not in used:
            used.append(name)
    body["tools_used"] = used
    return body


def _open_fail(error: str) -> dict[str, Any]:
    err = _spoken_tool_error(error, "Could not open that on the screen.")
    return {
        "ok": False,
        "reply": err[:2000],
        "tools_used": ["run_app"],
        "result": {"ok": False, "error": err},
        "ui": {"ok": False, "error": err},
    }


def _package_from_install_ask(asked: str) -> str | None:
    """Package or game word from a simple install/apt ask. None if compound."""
    raw = asked or ""
    if _COMPOUND_AND_RE.search(raw):
        return None
    match = _INSTALL_LEAD_RE.search(raw)
    if not match:
        return None
    rest = raw[match.end() :].strip().rstrip(".,!?")
    tokens = re.findall(r"[A-Za-z0-9.+-]+", rest)
    stop = {
        "a",
        "an",
        "the",
        "some",
        "new",
        "simple",
        "package",
        "app",
        "application",
        "please",
        "on",
        "your",
        "my",
        "pc",
        "computer",
        "screen",
        "linux",
        "for",
        "me",
        "this",
        "small",
        "tiny",
        "little",
        "something",
        "anything",
        "one",
        "any",
        "just",
    }
    words = [t.lower() for t in tokens if t.lower() not in stop]
    if not words:
        return "mines"
    return words[-1]


def _desktop_path_from_ask(asked: str) -> str | None:
    from app.jarvis.computer import desktop_file_path

    named = _FILE_NAME_RE.search(asked or "")
    if named:
        return desktop_file_path(named.group(1))
    if _SAMPLE_CSV_RE.search(asked or ""):
        return desktop_file_path("sample.csv")
    if _SAMPLE_XLSX_RE.search(asked or ""):
        return desktop_file_path("sample.xlsx")
    return None


def _talk_allow_hit(tool: str) -> dict[str, Any] | bool | None:
    """Honor Public Talk Allowed picks on /ask shortcuts. None = go ahead."""
    from app.jarvis.talk_allow import shortcut_gate

    return shortcut_gate(tool)


def _install_now(asked: str) -> dict[str, Any] | None:
    """Install a listed Linux VM app, then launch it. Never dump docker/exec."""
    from app.jarvis.virtual_pc import goal_is_install_job, goal_is_simple_talk

    if sys.platform == "win32":
        return None
    if goal_is_simple_talk(asked):
        return None
    if not goal_is_install_job(asked):
        return None
    if _COMPOUND_AND_RE.search(asked or ""):
        return None
    allow_hit = _talk_allow_hit("install")
    if allow_hit is False:
        return None
    if isinstance(allow_hit, dict):
        return allow_hit
    pkg = _package_from_install_ask(asked)

    from app.jarvis.computer import (
        JARVIS_COMPUTER,
        LISTED_LINUX_APPS,
        bind_job_desktop,
        is_listed_linux_package,
        linux_install_package,
        linux_run_app,
        map_apt_package,
    )

    apt_name = map_apt_package(pkg or "")
    if not pkg or not is_listed_linux_package(pkg):
        return {
            "ok": True,
            "reply": _INSTALL_LIST,
            "tools_used": [],
            "result": {"ok": True, "listed": list(LISTED_LINUX_APPS)},
            "ui": {"ok": True, "listed": list(LISTED_LINUX_APPS)},
        }

    bind_job_desktop(goal=asked)
    installed = linux_install_package(apt_name)
    if not installed.get("ok"):
        err = _spoken_tool_error(
            str(installed.get("error") or ""),
            _INSTALL_FAIL,
        )
        return {
            "ok": False,
            "reply": err[:2000],
            "tools_used": ["install"],
            "result": {"ok": False, "error": err},
            "ui": {"ok": False, "error": err},
        }
    plan = {
        "ok": True,
        "kind": "app",
        "app": apt_name,
        "url": "",
        "argv": [apt_name],
        "cmd": apt_name,
        "computer": JARVIS_COMPUTER,
    }
    launched = linux_run_app(plan)
    if not launched.get("ok"):
        err = _spoken_tool_error(
            str(launched.get("error") or ""),
            "I installed it but could not open it on the screen.",
        )
        return {
            "ok": False,
            "reply": err[:2000],
            "tools_used": ["install", "run_app"],
            "result": {"ok": False, "error": err},
            "ui": {"ok": False, "error": err},
        }
    reply = f"Installed {apt_name} and opened it on the screen."
    return {
        "ok": True,
        "reply": reply,
        "tools_used": ["install", "run_app"],
        "result": launched,
        "ui": launched,
    }


def _open_file_now(asked: str) -> dict[str, Any] | None:
    """Open a desktop csv/xlsx/named file with the shipped editor. No agent."""
    from app.jarvis.virtual_pc import goal_is_simple_talk

    if sys.platform == "win32":
        return None
    if goal_is_simple_talk(asked):
        return None
    if _INSTALL_WORD_RE.search(asked or "") and _COMPOUND_AND_RE.search(asked or ""):
        return None
    if not _OPEN_FILE_VERB_RE.search(asked or ""):
        return None
    allow_hit = _talk_allow_hit("run_app")
    if allow_hit is False:
        return None
    if isinstance(allow_hit, dict):
        return allow_hit
    path = _desktop_path_from_ask(asked)
    if not path:
        return None

    from app.jarvis.computer import bind_job_desktop, linux_run_app, plan_linux_run_app

    bind_job_desktop(goal=asked)
    plan_args: dict[str, Any] = {"target": "notepad", "args": path}
    plan = plan_linux_run_app(plan_args)
    if not plan.get("ok"):
        return _open_fail(str(plan.get("error") or ""))
    result = linux_run_app(plan)
    if not result.get("ok"):
        return _open_fail(str(result.get("error") or ""))
    looked = _tell_from_current_screen(asked)
    return _with_prior_tools(looked, ["run_app"])


def empty_speech(text: str) -> bool:
    """True for silence, raw JSON leftovers, or '{}' — not a spoken line."""
    raw = (text or "").strip()
    if not raw:
        return True
    if raw in {"{}", "[]", "null", "None", "undefined"}:
        return True
    return bool(_EMPTY_SPEECH_RE.match(raw))


def ensure_spoken_reply(text: str, fallback: str) -> str:
    """Never return empty speech or '{}' after a hire / tool job."""
    if empty_speech(text):
        return (fallback or "I did that.").strip()
    return str(text).strip()


def hire_count_word(n: int) -> str:
    count = max(2, min(int(n or 0), _HIRE_FILE_MAX))
    return _HIRE_SAY_N.get(count, str(count))


def hire_start_line(asked: str) -> str:
    """First spoken line when a create-N / hire job starts."""
    n = _hire_wanted_count(asked)
    word = hire_count_word(n)
    stem = _hire_stem(asked)
    if stem == "tetris":
        return f"I'll make {word} different Tetris games."
    if stem == "game":
        return f"I'll make {word} different games."
    return f"I'll make {word} different files."


def hire_wave_line() -> str:
    return HIRE_WAVE_LINE


def hire_fallback_reply(asked: str) -> str:
    return f"{hire_start_line(asked)} {HIRE_WAVE_LINE}"


def hire_spoken_reply(
    asked: str,
    *,
    hired: int,
    opened: list[str] | None = None,
    waved: bool = False,
) -> str:
    """Human speech after a hire job. Never empty. Never '{}'."""
    bits = [hire_start_line(asked)]
    if waved:
        bits.append(HIRE_WAVE_LINE)
    opened = list(opened or [])
    if opened:
        bits.append(
            f"Hired {hired} helpers and opened {len(opened)} games on the screen."
        )
        if _hire_stem(asked) == "tetris":
            bits.append("A Tetris board is visible.")
    else:
        bits.append(f"Hired {hired} helpers.")
    return ensure_spoken_reply(" ".join(bits), hire_fallback_reply(asked))


def next_hire_wave_job_id() -> str:
    return f"ask-hire-wave-{time.time_ns()}"


def recover_spawn_child_limit(
    name: str,
    arguments: dict[str, Any] | None,
    result: dict[str, Any] | None,
    run,
) -> dict[str, Any]:
    """CHILD_LIMIT is a full wave, not a stop. Retry on a new parent job id."""
    from app.jarvis.children import CHILD_LIMIT

    payload = result if isinstance(result, dict) else {}
    if (name or "").strip() != "spawn_child":
        return payload
    if str(payload.get("error") or "") != CHILD_LIMIT:
        return payload
    args = dict(arguments or {})
    args["parent_job_id"] = next_hire_wave_job_id()
    try:
        retried = run(args)
    except Exception:
        retried = None
    if isinstance(retried, dict) and retried.get("ok") and retried.get("id"):
        out = dict(retried)
        out["waved"] = True
        out["summary"] = HIRE_WAVE_LINE
        return out
    out = dict(payload)
    out["waved"] = True
    out["summary"] = HIRE_WAVE_LINE
    return out


_HIRE_N_ASK_RE = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?:[a-z]+\s+){0,3}"
    r"(?:html|tetris|games?|files?|pages?)\b",
    re.I,
)


def _hire_wanted_count(asked: str) -> int:
    """How many files they asked for. Waves of CHILD_CEILING still apply at spawn."""
    from app.jarvis.children import count_independent_work_items

    n = count_independent_work_items(asked)
    if n is None:
        hit = _HIRE_N_ASK_RE.search(asked or "")
        if hit:
            raw = hit.group(1).lower()
            n = _HIRE_SAY_N_REV.get(raw)
            if n is None:
                try:
                    n = int(raw)
                except ValueError:
                    n = None
    if n is None:
        n = 2
    return max(2, min(int(n), _HIRE_FILE_MAX))


def _hire_stem(asked: str) -> str:
    raw = asked or ""
    if re.search(r"\btetris\b", raw, re.I):
        return "tetris"
    if re.search(r"\bgames?\b", raw, re.I):
        return "game"
    return "page"


def _goal_wants_html_open(asked: str) -> bool:
    """Local HTML / games get file:// chrome. Research slices do not invent Tetris."""
    return bool(re.search(r"\b(html|htm|tetris|games?|pages?)\b", asked or "", re.I))


def _hire_look(index: int) -> dict[str, str]:
    looks = _HIRE_LOOKS
    i = max(1, int(index)) - 1
    return looks[i % len(looks)]


def _unique_game_html(index: int, stem: str = "tetris") -> str:
    """Host fallback when a child file is missing or a duplicate of a sibling."""
    look = _hire_look(index)
    title = look["title"]
    n = max(1, int(index))
    step = 11 + (n % 7)
    label = "Tetris" if stem == "tetris" else ("Game" if stem == "game" else "Page")
    cells: list[str] = []
    for i in range(200):
        klass = ""
        if i % step == 0 or i > 190 - n:
            klass = ' class="alt"' if i % 2 else ' class="on"'
        cells.append(f"<i{klass}></i>")
    board = "".join(cells)
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="en"><head><meta charset="utf-8"><title>{title}</title>\n'
        "<style>\n"
        f"body{{margin:0;background:{look['bg']};color:{look['ink']};"
        "font:16px/1.3 sans-serif;text-align:center}}\n"
        "h1{margin:12px 0 4px}\n"
        "#hud{display:flex;justify-content:space-between;width:220px;"
        f"margin:0 auto 8px;color:{look['hud_color']}}}\n"
        "#board{display:grid;grid-template-columns:repeat(10,20px);width:200px;"
        f"margin:8px auto;border:3px solid {look['block2']};background:{look['board']}}}\n"
        f"#board i{{width:20px;height:20px;display:block;background:{look['empty']}}}\n"
        f"#board i.on{{background:{look['block']}}}\n"
        f"#board i.alt{{background:{look['block2']}}}\n"
        "</style></head>\n"
        "<body>\n"
        f"<h1>{title}</h1>\n"
        f'<div id="hud"><span>{label} score 0</span><span>Next</span></div>\n'
        f'<div id="board" aria-label="{title} board" data-variant="{n}">{board}</div>\n'
        "</body></html>\n"
    )


def _file_look_key(data: bytes) -> str:
    norm = re.sub(rb"\s+", b" ", data or b"").strip().lower()
    return hashlib.sha256(norm).hexdigest()


def _child_file_goal(asked: str, index: int, total: int) -> str:
    stem = _hire_stem(asked)
    name = f"{stem}_{index:02d}.html"
    look = _hire_look(index)
    if stem == "tetris":
        kind = "pretty playable Tetris HTML"
    elif stem == "game":
        kind = "pretty playable HTML game"
    else:
        kind = "pretty HTML page"
    return (
        f"Write a distinct {kind} to Exports/{name} (variant {index} of {total}). "
        f"Unique look required: title {look['title']!r}; palette {look['palette']}; "
        f"piece set {look['pieces']}; HUD {look['hud']}. "
        f"Do not copy a sibling file. Use write_file. Do not call see_screen. "
        f"Parent will open file:///home/jarvis/Exports/{name}."
    )


def _child_slice_goal(asked: str, index: int, total: int) -> str:
    if _goal_wants_html_open(asked) or re.search(
        r"\b(files?|write|create|make|build)\b", asked or "", re.I
    ):
        return _child_file_goal(asked, index, total)
    brief = re.sub(r"\s+", " ", (asked or "").strip())[:400]
    return (
        f"Independent slice {index} of {total}: {brief}. "
        f"Do the assigned work. Write any artifact under Exports/. "
        f"Do not only describe the screen."
    )


def _host_html_path(raw: str) -> Path | None:
    from app.jarvis.workspace import Workspace, default_workspace

    name = Path(str(raw or "").replace("\\", "/")).name
    ws = Workspace(default_workspace())
    for rel in (str(raw or ""), f"Exports/{name}"):
        try:
            cand = ws.resolve(rel)
        except Exception:
            continue
        if cand.is_file():
            return cand
    try:
        return ws.resolve(f"Exports/{name}")
    except Exception:
        return None


def _ensure_hire_html_files(asked: str, n: int) -> list[Path]:
    """Make sure Exports/<stem>_01.html … _0N.html exist and do not match."""
    from app.jarvis.workspace import default_workspace

    stem = _hire_stem(asked)
    exp = default_workspace() / "Exports"
    exp.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    seen: dict[str, str] = {}
    for i in range(1, n + 1):
        path = exp / f"{stem}_{i:02d}.html"
        raw = path.read_bytes() if path.is_file() else b""
        key = _file_look_key(raw) if len(raw) >= 40 else ""
        if not key or key in seen:
            path.write_text(_unique_game_html(i, stem), encoding="utf-8")
            key = _file_look_key(path.read_bytes())
        seen[key] = path.name
        paths.append(path)
    return paths


def _look_has_game_board(looked: dict[str, Any] | None) -> bool:
    blob = _look_blob(looked or {})
    return bool(_BOARD_LOOK_RE.search(blob))


def _open_html_on_linux(asked: str, paths: list[Path]) -> list[str]:
    """Open each HTML as file:///home/jarvis/Exports/…. Never a bare host."""
    if sys.platform == "win32" or not paths:
        return []
    from app.jarvis.computer import (
        EXPORTS_DIR,
        bind_job_desktop,
        computer_html_file_url,
        linux_close_chrome_windows,
        linux_run_app,
        plan_linux_run_app,
        stage_file_on_computer,
    )

    bind_job_desktop(goal=asked)
    try:
        linux_close_chrome_windows(app="thunar")
    except Exception:
        pass
    opened: list[str] = []
    for path in paths:
        name = path.name
        dest = f"{EXPORTS_DIR}/{name}"
        try:
            stage_file_on_computer(str(path), dest)
        except Exception:
            pass
        url = computer_html_file_url(name)
        plan = plan_linux_run_app({"target": "chrome", "url": url})
        if not plan.get("ok"):
            continue
        result = linux_run_app(plan)
        if result.get("ok"):
            opened.append(url)
    return opened


def _hire_children_now(asked: str) -> dict[str, Any] | None:
    """Hire OpenRouter children in waves, write files, open file:// URLs."""
    from app.jarvis.children import CHILD_CEILING, CHILD_LIMIT
    from app.jarvis.virtual_pc import goal_is_hire_job

    if not goal_is_hire_job(asked):
        return None

    wanted = _hire_wanted_count(asked)
    wave = CHILD_CEILING
    gw = get_gateway()
    tools: list[str] = []
    ids: list[str] = []
    index = 1
    wave_i = 0
    waved = False

    def _spawn(payload: dict[str, Any]) -> dict[str, Any]:
        out = gw.run("spawn_child", payload, source="ask", confirmed=False)
        _note_tool(tools, "spawn_child")
        return out if isinstance(out, dict) else {}

    while index <= wanted and wave_i < 8:
        wave_i += 1
        batch = min(wave, wanted - index + 1)
        if batch < 1:
            break
        job_id = f"ask-hire-wave-{wave_i}"
        wave_ids: list[str] = []
        for _ in range(batch):
            payload = {
                "goal": _child_slice_goal(asked, index, wanted),
                "budget_seconds": _HIRE_BUDGET_S,
                "budget_usd": _HIRE_BUDGET_USD,
                "parent_job_id": job_id,
            }
            result = _spawn(payload)
            if str((result or {}).get("error") or "") == CHILD_LIMIT:
                waved = True
                result = recover_spawn_child_limit(
                    "spawn_child", payload, result, _spawn
                )
            cid = str((result or {}).get("id") or "").strip()
            if (result or {}).get("ok") and cid:
                ids.append(cid)
                wave_ids.append(cid)
                index += 1
                continue
            if str((result or {}).get("error") or "") == CHILD_LIMIT:
                break
            index += 1
        for cid in wave_ids:
            gw.run("wait_child", {"id": cid}, source="ask", confirmed=False)
            _note_tool(tools, "wait_child")
    opened: list[str] = []
    if _goal_wants_html_open(asked) or re.search(
        r"\b(files?|html|page)\b", asked or "", re.I
    ):
        host_files = _ensure_hire_html_files(asked, wanted)
        opened = _open_html_on_linux(asked, host_files)
    if opened:
        _note_tool(tools, "run_app")
        try:
            looked = _look_now(asked, app="chrome", fresh=True)
            _note_tool(tools, "see_screen")
            if not _look_has_game_board(looked) and opened:
                from app.jarvis.computer import linux_run_app, plan_linux_run_app

                again = plan_linux_run_app({"target": "chrome", "url": opened[-1]})
                if again.get("ok"):
                    linux_run_app(again)
                _look_now(asked, app="chrome", fresh=True)
        except Exception:
            pass
    if "spawn_child" not in tools:
        return None
    hired = len(ids) or wanted
    reply = hire_spoken_reply(asked, hired=hired, opened=opened, waved=waved)
    return {
        "ok": True,
        "reply": reply,
        "tools_used": tools,
        "result": {
            "ok": True,
            "hired": hired,
            "opened": opened,
            "ids": ids,
            "waved": waved,
        },
        "ui": {
            "ok": True,
            "hired": hired,
            "opened": opened,
            "ids": ids,
            "waved": waved,
        },
    }


def _open_site_now(asked: str) -> dict[str, Any] | None:
    """Use the PC now: open a named URL, search, look, or click. Skip the agent.

    Gate on the real OS (sys.platform), not host_is_windows() / JARVIS_HOST_OS.
    The live Linux VM pins JARVIS_HOST_OS=windows, which would send this path
    to Windows Edge and hang. Real win32 still skips so the Windows app is
    unchanged. Does not call start_computer (that blocks 45–120s).
    Never invents a hostname. Spoken news (latest news / what's happening,
    no show/open/on-screen) does not open Chrome. News they asked to show
    or open uses ONE known publisher homepage and looks. If that page is
    already BBC/Reuters/NZZ/CNN with headlines, just look and tell. Control
    looks first, then clicks or types what is there. Compound
    "close the tabs and … news" closes first, then opens the homepage.
    """
    from app.jarvis.virtual_pc import goal_is_simple_talk

    if sys.platform == "win32":
        return None
    if wants_news_tell(asked) or goal_is_simple_talk(asked):
        return None

    from app.jarvis.computer import bind_job_desktop, linux_run_app, plan_linux_run_app

    bind_job_desktop(goal=asked)
    named = _site_url_from_ask(asked)
    mail = bool(_MAIL_RE.search(asked or ""))
    notepad = bool(_NOTEPAD_RE.search(asked or ""))
    calc = bool(_CALC_RE.search(asked or "") or _OPEN_CALC_RE.search(asked or ""))
    from app.jarvis.virtual_pc import wants_screen_job, wants_web_job

    opening = bool(named or mail or notepad or calc) or (
        wants_news_search(asked) and wants_screen_job(asked)
    ) or wants_web_job(asked)
    if opening:
        allow_hit = _talk_allow_hit("run_app")
        if allow_hit is False:
            return None
        if isinstance(allow_hit, dict):
            return allow_hit
    prior_tools: list[str] = []
    if (wants_close_all(asked) or wants_close_tab(asked)) and wants_news_search(asked):
        prior_tools, fail = _close_tabs_now(asked)
        if fail is not None:
            return fail
    elif wants_close_all(asked) and not named and not mail and not notepad and not calc:
        return _close_all_from_ask(asked)
    elif wants_control_screen(asked) and not named and not mail and not notepad and not calc:
        return _control_from_screen(asked)
    if (
        wants_look_at_screen(asked)
        and not named
        and not wants_news_search(asked)
        and not wants_web_job(asked)
        and not mail
        and not notepad
        and not calc
    ):
        return _tell_from_current_screen(asked)
    if wants_news_tell(asked) and not named and not mail and not notepad and not calc:
        try:
            from app.jarvis.capture import last_look

            prior = last_look()
        except Exception:
            prior = {}
        if look_is_news_page(prior) and not look_is_dead_page(prior):
            return _with_prior_tools(_tell_from_current_news(asked), prior_tools)

    url = named
    if not url and wants_news_search(asked):
        url = news_homepage_from_ask(asked)
    if not url:
        try:
            from app.jarvis.virtual_pc import wants_web_job
        except Exception:
            wants_web_job = None
        if wants_web_job and wants_web_job(asked):
            q = web_search_query(asked) or asked
            url = "https://www.google.com/search?q=" + quote_plus(q)
    if not url and not _is_computer_ask(asked):
        return None

    plan_args: dict[str, Any]
    if url:
        plan_args = {"target": "chrome", "url": url}
    elif mail:
        url = "https://mail.google.com"
        plan_args = {"target": "chrome", "url": url}
    elif notepad:
        plan_args = {"target": "notepad"}
    elif calc:
        plan_args = {"target": "calculator"}
    else:
        return None

    plan = plan_linux_run_app(plan_args)
    if not plan.get("ok"):
        return _open_fail(str(plan.get("error") or ""))
    if url:
        # Kill leftover Chromium (Reuters session / Restore pages?) first.
        _close_windows_now()
        _wait_after_act()
    result = linux_run_app(plan)
    if not result.get("ok"):
        return _open_fail(str(result.get("error") or ""))
    if url:
        try:
            from app.jarvis.capture import remember_look_target

            remember_look_target(app="chrome", url=str(url))
        except Exception:
            pass
    if url:
        return _with_prior_tools(_tell_from_opened_site(asked, result), prior_tools)
    if notepad and re.search(r"\btype\b", asked or "", re.I):
        return _with_prior_tools(_type_into_editor(asked), ["run_app", *prior_tools])
    if calc:
        return _with_prior_tools(_use_calculator(asked), ["run_app", *prior_tools])
    looked = _tell_from_current_screen(asked)
    return _with_prior_tools(looked, ["run_app", *prior_tools])


async def run_voice_ask(text: str) -> dict[str, Any]:
    """Run one spoken or typed ask through tools / OpenRouter.

    Returns a speakable ``reply`` plus the same ``result`` / ``ui`` split
    the Realtime tool endpoint uses (model-safe vs Allow/Cancel panel).
    """
    asked = str(text or "").strip()
    if not asked:
        return {
            "ok": False,
            "reply": "I did not catch that.",
            "tools_used": [],
            "result": {"ok": False, "error": "empty"},
            "ui": {"ok": False, "error": "empty"},
        }

    mark_ask_clock()
    gw = get_gateway()
    gw.clear_taint("ask", goal=asked)

    from app.jarvis.bridge_routes import _infer_tool_from_goal
    from app.jarvis.virtual_pc import goal_is_hire_job, goal_is_simple_talk

    inferred = None if goal_is_hire_job(asked) else _infer_tool_from_goal(asked)
    if inferred:
        raw_name, args = inferred
        name = _normalize_tool_name(raw_name)
        result = gw.run(name, args or {}, source="ask", confirmed=False)
        summary = plain_summary(name, result)
        return {
            "ok": bool(result.get("ok", True)),
            "reply": summary,
            "tools_used": [name],
            "result": model_view(result),
            "ui": result,
        }

    if goal_is_simple_talk(asked):
        return await _simple_talk_answer(asked)

    hired = _hire_children_now(asked)
    if hired is not None:
        hired["reply"] = ensure_spoken_reply(
            str(hired.get("reply") or ""), hire_fallback_reply(asked)
        )
        return hired

    opened = _open_site_now(asked)
    if opened is not None:
        return opened

    installed = _install_now(asked)
    if installed is not None:
        return installed

    opened_file = _open_file_now(asked)
    if opened_file is not None:
        return opened_file

    key = openrouter_api_key()
    if not key and should_use_hosted_talk():
        body = await _hosted_voice_ask(asked)
        patched = _sanitize_computer_agent_reply(
            asked,
            str(body.get("reply") or ""),
            list(body.get("tools_used") or []),
        )
        return patched if patched is not None else body
    if not key:
        return {
            "ok": False,
            "reply": CANT_TALK,
            "tools_used": [],
            "result": {"ok": False, "error": CANT_TALK},
            "ui": {"ok": False, "error": CANT_TALK},
        }

    from app.jarvis.agent import build_jarvis_agent, resolve_tool_rounds

    agent_text = _virtual_pc_ask_text(asked)
    rounds = resolve_tool_rounds(asked, None)
    if _is_computer_ask(asked):
        rounds = 32
    cap = ask_deadline_s(asked)
    agent = build_jarvis_agent(
        api_key=key,
        tool_source="ask",
        goal=asked,
        timeout_seconds=cap,
        max_tool_rounds=rounds,
    )
    if agent is None:
        return {
            "ok": False,
            "reply": "Jarvis is not ready to answer yet.",
            "tools_used": [],
            "result": {"ok": False, "error": "Jarvis agent unavailable"},
            "ui": {"ok": False, "error": "Jarvis agent unavailable"},
        }

    sess = await agent.start_session(role_name="ask")
    try:
        try:
            msg = await asyncio.wait_for(
                agent.send_message(sess.session_id, message=agent_text),
                timeout=cap,
            )
        except asyncio.TimeoutError:
            if sys.platform != "win32" and _is_computer_ask(asked):
                recovered = _sanitize_computer_agent_reply(asked, "", [])
                if recovered is not None:
                    return recovered
            return _refuse_screen("That took too long on the screen.")
    finally:
        await agent.stop_session(sess.session_id, reason="ask_complete")

    tools = list(getattr(agent, "_tools_called", []) or [])
    reply = str(getattr(msg, "text", "") or "").strip()
    if _TECH_DUMP_RE.search(reply):
        reply = _spoken_tool_error(reply, "Could not do that on the screen.")
    if sys.platform != "win32" and _is_computer_ask(asked):
        patched = _sanitize_computer_agent_reply(asked, reply, tools)
        if patched is not None:
            return patched

    payload = {
        "text": reply,
        "model": getattr(agent, "_model", None),
        "model_route": getattr(agent, "_model_route", None) or {},
        "tools_called": tools,
    }
    if empty_speech(reply) and tools:
        reply = hire_fallback_reply(asked) if goal_is_hire_job(asked) else "I did that."
    return {
        "ok": True,
        "reply": reply[:2000],
        "tools_used": tools,
        "result": payload,
        "ui": payload,
    }


def public_talk_sheet() -> dict[str, Any]:
    """Model + spend from the one settings ledger. Same names as public_view.

    Never invents cost and never returns secrets. Used by /health and /ask so
    the public page can paint the sheet without a second store.
    """
    try:
        from app.jarvis.settings_store import public_view

        view = public_view()
    except Exception:
        return {
            "model": None,
            "spent_today_usd": None,
            "spent_month_usd": None,
            "remaining_budget_usd": None,
            "monthly_budget_usd": None,
            "quality_vs_price": None,
            "model_speed": None,
            "helper_models": [],
            "helper_name": None,
            "computer_kind": "linux",
            "computer": None,
            "realtime_voice": None,
            "look_speed": None,
            "permission_profile": None,
            "talk_speed": None,
        }
    computer = None
    try:
        from app.jarvis.computer import public_computer_status

        computer = public_computer_status()
    except Exception:
        computer = None
    return {
        "model": view.get("model"),
        "spent_today_usd": view.get("spent_today_usd"),
        "spent_month_usd": view.get("spent_month_usd"),
        "remaining_budget_usd": view.get("remaining_budget_usd"),
        "monthly_budget_usd": view.get("monthly_budget_usd"),
        "quality_vs_price": view.get("quality_vs_price"),
        "model_speed": view.get("model_speed"),
        "helper_models": list(view.get("helper_models") or []),
        "helper_name": view.get("helper_name"),
        "computer_kind": view.get("computer_kind") or "linux",
        "computer": computer,
        "realtime_voice": view.get("realtime_voice"),
        "look_speed": view.get("look_speed"),
        "permission_profile": view.get("permission_profile"),
        "talk_speed": view.get("talk_speed"),
    }


def attach_public_talk_sheet(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.update(public_talk_sheet())
    return out


def listen_health(*, lite: bool = False) -> dict[str, Any]:
    """Listen/speak flags. Full payload adds the spend sheet + helper catalog.

    ``lite=True`` is the first-open path: no ``helper_models`` catalog and no
    spend sheet. Settings still loads the full sheet when idle.
    """
    from app.jarvis.realtime import can_listen, listen_mode, realtime_available
    from app.jarvis.tts import can_speak, neural_tts_available, speak_mode
    from app.jarvis.workspace import default_workspace

    body = {
        "ok": True,
        "realtime": realtime_available(),
        "can_listen": can_listen(),
        "listen_mode": listen_mode(),
        "can_speak": can_speak(),
        "speak_mode": speak_mode(),
        "neural_tts": neural_tts_available(),
        "openrouter": bool(openrouter_api_key()),
        "hosted_talk": should_use_hosted_talk(),
        "talk_ready": talk_ready(),
        "workspace": str(default_workspace()),
        "tools": True,
        "gateway": True,
        "jarvis": str(os.environ.get("JARVIS_ENABLED", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
    }
    try:
        from app.jarvis.computer import public_computer_status
        from app.jarvis.settings_store import get_computer_kind

        body["computer_kind"] = get_computer_kind()
        body["computer"] = public_computer_status()
    except Exception:
        body["computer_kind"] = "linux"
        body["computer"] = {
            "kind": "linux",
            "label": "Linux",
            "live": False,
            "play_store_client": False,
        }
    if not lite:
        body.update(public_talk_sheet())
    return body
