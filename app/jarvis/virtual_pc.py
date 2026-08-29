"""Detect talk that should use Jarvis's live PC, not a workspace folder."""

from __future__ import annotations

import os
import re
import sys

_VIRTUAL_PC_ACT = re.compile(
    r"\b(show|open|go to|goto|browse|visit|launch|run|start|find(?:\s+me)?|"
    r"look at|look|see|watch|"
    r"install|click|type|close|scroll|press)\b",
    re.I,
)
_VIRTUAL_PC_TARGET = re.compile(
    r"("
    r"\b(gmail|inbox|ibox|mail|outlook|notepad|mousepad|chrome|chromium|"
    r"browser|terminal|calculator|website|site|screen|http|https|"
    r"file|excel|spreadsheet|app|laptop|computer|pc|game|mines|solitaire|"
    r"package)\b"
    r"|[a-z0-9.-]+\.(com|nl|de|org|net|io|co|uk|edu|app)"
    r")",
    re.I,
)
# Follow-ups like "latest news on cnn" / "cnn news" / "news in Turkey".
_SITE_FOLLOWUP_ON = re.compile(
    r"(?:news|headlines)\s+(?:on|from|at|about|in)\s+(?:the\s+)?([a-z0-9][a-z0-9.-]*)",
    re.I,
)
_SITE_FOLLOWUP_WORD = re.compile(
    r"\b([a-z0-9][a-z0-9.-]*)\s+(?:news|headlines)\b",
    re.I,
)
_FOLLOWUP_FILLER = frozenset(
    {
        "latest",
        "breaking",
        "the",
        "a",
        "an",
        "my",
        "some",
        "any",
        "world",
        "local",
        "live",
        "morning",
        "evening",
        "tonight",
        "today",
        "this",
        "that",
    }
)
# Single-label hosts people say without .com. Not a run_app allowlist.
_BARE_SITE = re.compile(
    r"\b(cnn|bbc|reuters|bloomberg|nytimes|npr|espn|ntv)\b",
    re.I,
)
# Token already looks like a host they said (cnn.com). Never used to invent .com.
_SAID_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,24}$")
_NEWS_SITUATION_RE = re.compile(
    r"\b("
    r"(?:latest\s+)?news|headlines|"
    r"what(?:'s|s|\s+is)\s+going\s+on|"
    r"what(?:'s|s|\s+is)\s+happening"
    r")\b",
    re.I,
)
_LINUX_DESKTOP_ACT = re.compile(
    r"\b(click|type|close|scroll|press|dismiss|see_screen|screenshot|"
    r"notepad|chrome|look at|what.?s on|what.?s that popup|"
    r"what do you see|what are you seeing|visible on|the browser|"
    r"i can still see|file manager|thunar|"
    r"the tabs?|this tab|popup|"
    r"gmail|inbox|ibox|mail)\b",
    re.I,
)
# "your computer" / "your screen" / "the browser" on the hosted page.
# Also: they are narrating the Screen pane ("there is no login here").
_OWN_MACHINE_RE = re.compile(
    r"("
    r"\byour (?:own )?(?:computer|screen|desktop|machine|browser)\b|"
    r"\bthis (?:linux\s+)?(?:pc|computer|machine|desktop)\b|"
    r"\blinux pc\b|"
    r"\bon (?:this|the) linux\b|"
    r"\bthe (?:browser|screen)\b|"
    r"\bwhat(?:'s|s|\s+is|\s+do you see|\s+are you seeing).{0,48}(?:screen|browser|computer)\b|"
    r"\bwhat are you seeing\b|"
    r"\bwhat do you see\b|"
    r"\bvisible on\b|"
    r"\b(?:don'?t you |do you )have your own computer\b|"
    r"\bcheck (?:your )?(?:computer|screen|browser)\b|"
    r"\bthere is no\b.{0,60}\b(here|login|on (?:the )?(?:screen|page|browser))\b|"
    r"\bi (?:don'?t|do not|can'?t|cannot) see\b|"
    r"\bi can still see\b|"
    r"\bi still see\b|"
    r"\bstill (?:on the screen|there|open|visible)\b|"
    r"\bno login\b|"
    r"\bread (?:this |the )?(?:page|screen|article)\b|"
    r"^\s*look(?:\s+again)?[\s!.?,]*$"
    r")",
    re.I,
)
_CLOSE_TAB_RE = re.compile(
    r"\bclose\b.{0,24}\btabs?\b|\btabs?\b.{0,24}\bclose\b",
    re.I,
)
# Close every Chrome window — not one Ctrl+W. "close the tab(s)" without
# "all" stays a single-tab / few-tab keys job.
_CLOSE_ALL_RE = re.compile(
    r"("
    r"\bclose\b.{0,40}\b("
    r"all\s+(?:the\s+)?(?:browser\s+|chrome\s+)?(?:tabs?|windows?|apps?)"
    r"|(?:the\s+)?(?:browser|apps?)(?:\s+windows?)?"
    r"|all\s+windows"
    r"|everything"
    r"|all"
    r"|explorer"
    r"|file manager"
    r"|error(?:\s+dialogs?)?"
    r")\b"
    r"|"
    r"\b("
    r"all\s+(?:the\s+)?(?:browser\s+|chrome\s+)?(?:tabs?|windows?|apps?)"
    r"|(?:the\s+)?(?:browser|apps?)"
    r"|explorer"
    r"|file manager"
    r")\b.{0,24}\bclose\b"
    r")",
    re.I,
)
_HOST_DISK_GOAL = re.compile(
    r"\b(free space|disk space|disk free|storage left|how much space|storage free)\b",
    re.I,
)
# Broader use-the-PC phrasing. Not a site allowlist.
_USE_THE_PC_VERB = re.compile(r"\b(install|open|show|run|click|type|close|scroll)\b", re.I)
_USE_THE_PC_NOUN = re.compile(
    r"("
    r"\b(file|excel|spreadsheet|notepad|app|laptop|computer|pc|game|mines|"
    r"solitaire|package)\b"
    r"|[a-z0-9.-]+\.(?:com|nl|de|org|net|io|co|uk|edu|app)\b"
    r"|https?://"
    r")",
    re.I,
)
_SIMPLE_GREET_RE = re.compile(
    r"^\s*(?:hi|hello|hey|yo|howdy|hiya|thanks|thank\s+you|thx|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"what'?s\s+up|whats\s+up|sup|"
    r"can\s+you\s+hear\s+me|are\s+you\s+there|"
    r"merhaba(?:lar)?|selam(?:lar)?|g[uü]nayd[iı]n|"
    r"iyi\s+(?:ak[sş]amlar|g[uü]nler|geceler)|"
    r"nas[iı]ls[iı]n(?:(?:\s+sen)?|\s+jarvis)?|"
    r"te[sş]ekk[uü]r(?:ler)?"
    r")(?:\s+jarvis)?[\s!.?,]*$",
    re.I,
)
_MEMORY_TALK_RE = re.compile(
    r"("
    r"\b("
    r"what did we (?:talk|discuss|speak)|"
    r"what were we (?:talking|discussing)|"
    r"last time we (?:talked|spoke|discussed)|"
    r"yesterday|"
    r"(?:daily[- ]?)?journal|"
    r"memory|"
    r"do you remember|"
    r"remember (?:when|what|yesterday)|"
    r"\d+\s+days?\s+ago"
    r")\b|"
    r"\bd[uü]n\b|"
    r"ne\s+yapt[iı]k|"
    r"ne\s+konu[sş]tuk|"
    r"hat[iı]rl[iı]yor\s+musun"
    r")",
    re.I,
)
_PC_VERB_RE = re.compile(
    r"\b(show|open|go to|goto|browse|visit|launch|run|start|find|install|"
    r"click|type|close|scroll)\b",
    re.I,
)
_HARD_PC_APP_RE = re.compile(
    r"\b(gmail|inbox|ibox|outlook|notepad|mousepad|chrome|chromium|"
    r"excel|spreadsheet)\b",
    re.I,
)
_TLD_RE = re.compile(
    r"[a-z0-9.-]+\.(?:com|nl|de|org|net|io|co|uk|edu|app)\b",
    re.I,
)
_INSTALL_JOB_RE = re.compile(
    r"\b(install|apt(?:-get)?(?:\s+install)?|add(?:\s+a)?\s+package)\b",
    re.I,
)
_DESKTOP_FILE_RE = re.compile(
    r"("
    r"\b[\w.-]+\.(?:csv|xlsx|xls|txt|tsv)\b"
    r"|\b(?:csv|xlsx|xls)\s+file\b"
    r"|\bsample\s+(?:csv|excel|xlsx|file)\b"
    r")",
    re.I,
)
# On-the-screen verbs. News / facts / explain without these stay spoken.
_SCREEN_JOB_VERB_RE = re.compile(
    r"("
    r"\b(show|open|go to|goto|browse|visit|launch|click|close|install|type|look)\b|"
    r"\bon (?:the|your) screen\b|"
    r"\bon screen\b|"
    r"look(?:\s+\w+){0,4}\s+together|"
    r"\bnews\s+together\b"
    r")",
    re.I,
)
# What-do-you-see is a computer look. Never leftover-chat skip. Never Hello.
_LOOK_JOB_RE = re.compile(
    r"("
    r"\bwhat do you see\b|"
    r"\bwhat are you seeing\b|"
    r"\bwhat(?:'s|s|\s+is)\s+(?:on|visible)\b.{0,40}\b(?:screen|browser|computer)\b|"
    r"\bvisible on\b|"
    r"look\s+at(?:\s+the)?\s+(?:your\s+)?(?:screen|browser|computer|page)|"
    r"check\s+(?:your\s+)?(?:computer|screen|browser)|"
    r"^\s*look(?:\s+again)?[\s!.?,]*$"
    r")",
    re.I,
)
_STILL_SEE_RE = re.compile(
    r"("
    r"\bi can still see\b|"
    r"\bi still see\b|"
    r"\bstill (?:on the screen|there|open|visible)\b|"
    r"\bi can see (?:the )?(?:file manager|explorer|thunar|window|error|apps?)\b"
    r")",
    re.I,
)
# Operate the UI — not "what's on the screen" look-and-tell.
_DESKTOP_OPERATE_RE = re.compile(
    r"\b(click|type|close|open|install|press|dismiss|scroll)\b|"
    r"\bi can still see\b|"
    r"\bi still see\b",
    re.I,
)
AFTER_SEE_ACT_TOOLS = frozenset({"click", "type", "keys"})

# Hire / spawn helpers for multi-part legwork. Do not require the words
# hire or spawn_child. "open cnn.com" / hello / math stay out.
# "open the 2 files" is a look, not a hire — needs create/make/write/build
# or an explicit helper ask.
_HIRE_COUNT = r"(?:\d+|ten|nine|eight|seven|six|five|four|three|two|many|several|multiple)"
_HIRE_NOUN = r"(?:html|tetris|games?|files?|pages?|reports?)"
_HIRE_MAKE = r"(?:create|write|build|scaffold|make(?!\s+sure))"
_HIRE_JOB_RE = re.compile(
    r"("
    r"\bhire\b.+\b(children|child|helpers?|agents?|workers?|spawn_child)\b|"
    r"\bspawn_child\b|"
    r"\b(with|use|using)\s+(?:the\s+)?(helpers?|children|agents?|workers?)\b|"
    r"\bdo this\b.+\b(helpers?|children|agents?|workers?)\b|"
    r"\b(children|helpers?|agents?|workers?)\b.+"
    r"\b(write|create|make|build|research|do)\b"
    r")",
    re.I | re.S,
)
_CREATE_MANY_FILES_RE = re.compile(
    rf"("
    rf"\b(each|every)\b.+\b(write|writes|create|creates|make|makes)\b"
    rf".+\b(html|tetris|game|file|page)"
    rf"|"
    rf"\b{_HIRE_MAKE}\b.+\b{_HIRE_COUNT}\b.+\b{_HIRE_NOUN}\b"
    rf"|"
    rf"\b{_HIRE_COUNT}\b.+\b{_HIRE_NOUN}\b.+\b{_HIRE_MAKE}\b"
    rf")",
    re.I | re.S,
)
_PARALLEL_RESEARCH_RE = re.compile(
    rf"("
    rf"\b(?:in\s+)?parallel\b.+\b(research|look\s*up|topics?|questions?|sources?)\b|"
    rf"\bresearch\b.+\b{_HIRE_COUNT}\s+(topics?|questions?|sources?|pages?)\b|"
    rf"\b{_HIRE_COUNT}\s+(topics?|questions?|sources?)\b.+"
    rf"\b(research|in parallel|helpers?)\b"
    rf")",
    re.I | re.S,
)


def goal_is_hire_job(goal: str) -> bool:
    """Multi-part OpenRouter helper job — not a screen look, not hello/math.

    Create-N files/games, parallel research, or an explicit helper ask.
    ``open … on this Linux PC`` alone is run_app, not spawn_child.
    """
    g = (goal or "").strip()
    if not g:
        return False
    if _HIRE_JOB_RE.search(g):
        return True
    if _CREATE_MANY_FILES_RE.search(g):
        return True
    if _PARALLEL_RESEARCH_RE.search(g):
        return True
    return False


def goal_asks_host_disk(goal: str) -> bool:
    return bool(_HOST_DISK_GOAL.search(goal or ""))


def goal_needs_linux_desktop(goal: str) -> bool:
    return bool(_LINUX_DESKTOP_ACT.search(goal or ""))


def _host_from_followup(goal: str) -> str | None:
    g = goal or ""
    on = _SITE_FOLLOWUP_ON.search(g)
    if on:
        host = on.group(1).rstrip(".,);]!?'\"").lower()
        if host and host not in _FOLLOWUP_FILLER:
            return host
    word = _SITE_FOLLOWUP_WORD.search(g)
    if word:
        host = word.group(1).rstrip(".,);]!?'\"").lower()
        if host and host not in _FOLLOWUP_FILLER:
            return host
    return None


def resolve_followup_host(token: str) -> str | None:
    """Host they actually said: a domain or a known bare news word. Never invent."""
    host = (token or "").strip().lower().rstrip(".,);]!?'\"")
    if not host or host in _FOLLOWUP_FILLER:
        return None
    if "." in host and _SAID_DOMAIN_RE.match(host):
        return host
    if _BARE_SITE.fullmatch(host):
        return host
    return None


def host_from_site_followup(goal: str) -> str | None:
    """Host from 'news on X' / 'X news' / 'news in X'. None unless they named one."""
    return resolve_followup_host(_host_from_followup(goal) or "")


def goal_wants_news(goal: str) -> bool:
    """News / headlines / what's going on — words only, not a computer job."""
    return bool(_NEWS_SITUATION_RE.search(goal or ""))


def wants_still_see(goal: str) -> bool:
    """I can still see X — leftover window, not a chat follow-up."""
    return bool(_STILL_SEE_RE.search(goal or ""))


def wants_look_job(goal: str) -> bool:
    """What do you see / what's on the screen — look, do not skip as chat."""
    return bool(_LOOK_JOB_RE.search(goal or ""))


def wants_screen_job(goal: str) -> bool:
    """They want something on HIS screen: show / open / click / close / look."""
    g = goal or ""
    if goal_is_hire_job(g):
        return False
    if wants_look_job(g):
        return True
    if goal_asks_own_machine(g) or wants_close_all(g) or wants_close_tab(g):
        return True
    if wants_still_see(g):
        return True
    if goal_is_install_job(g) or goal_is_desktop_file_job(g):
        return True
    if _SCREEN_JOB_VERB_RE.search(g):
        return True
    low = g.lower()
    if "http://" in low or "https://" in low or _TLD_RE.search(g):
        return True
    return False


def wants_spoken_news(goal: str) -> bool:
    """Tell the news / a fact — no Chrome unless they said show / open / on screen."""
    g = goal or ""
    if not _NEWS_SITUATION_RE.search(g):
        return False
    return not wants_screen_job(g)


_TALK_FOLLOWUP_RE = re.compile(
    r"("
    r"^\s*(?:really|yeah|yes|and)\s*[.?!]*$|"
    r"\bwhat do you think\b|"
    r"\bwhat about (?:that|it|this)\b|"
    r"\bmore (?:on|about) (?:that|it|this)\b|"
    r"\btell me more\b|"
    r"\bmore details\b"
    r")",
    re.I,
)
_STOP_TALK_RE = re.compile(
    r"^\s*(?:please\s+)?stop(?:\s+(?:please|talking|that))?[.!?]*$",
    re.I,
)


def wants_talk_followup(goal: str) -> bool:
    """Really? / what do you think / more on that — last Talk turns, not the desktop."""
    g = (goal or "").strip()
    if wants_screen_job(g) or wants_still_see(g) or wants_close_all(g) or wants_close_tab(g):
        return False
    return bool(_TALK_FOLLOWUP_RE.search(g))


def wants_desktop_operate(goal: str) -> bool:
    """Click / type / close / open / still-see — operate, do not catalog icons."""
    g = goal or ""
    if wants_still_see(g) or wants_close_all(g) or wants_close_tab(g):
        return True
    if goal_is_install_job(g) or goal_is_desktop_file_job(g):
        return True
    return bool(_DESKTOP_OPERATE_RE.search(g))


def after_see_must_act(goal: str) -> bool:
    """After see_screen on an operate job, next tool is click/type/keys/close."""
    if not goal_is_computer_job(goal):
        return False
    return wants_desktop_operate(goal)


def after_see_allows_tool(name: str, goal: str) -> bool:
    """After see_screen on a computer job, click/type/keys are never skipped."""
    if (name or "").strip() not in AFTER_SEE_ACT_TOOLS:
        return False
    return goal_is_computer_job(goal) or wants_desktop_operate(goal)


def wants_chat_only_desktop_skip(goal: str) -> bool:
    """Really? / pasta / math — leftover screen skip. Never close/look/click."""
    g = (goal or "").strip()
    if not g:
        return False
    if wants_look_job(g) or wants_screen_job(g) or wants_still_see(g):
        return False
    if wants_desktop_operate(g):
        return False
    if wants_close_all(g) or wants_close_tab(g) or goal_is_install_job(g):
        return False
    if wants_talk_followup(g) or wants_stop_talk(g):
        return True
    return goal_is_simple_talk(g)


def wants_stop_talk(goal: str) -> bool:
    """Bare stop — just stop. Not 'stop the browser'."""
    return bool(_STOP_TALK_RE.match((goal or "").strip()))


def bare_site_host(goal: str) -> str | None:
    """Single-label host word (cnn, bbc, …) when said without a TLD."""
    match = _BARE_SITE.search(goal or "")
    if not match:
        return None
    return match.group(1).lower()


def goal_is_install_job(goal: str) -> bool:
    """Install / apt / add a package — including a game not already shipped."""
    return bool(_INSTALL_JOB_RE.search(goal or ""))


def goal_is_desktop_file_job(goal: str) -> bool:
    """Open a named/sample csv/xlsx file on Jarvis's desktop."""
    return bool(_DESKTOP_FILE_RE.search(goal or ""))


def _has_hard_pc_job(goal: str) -> bool:
    """Site / shipped app / file-on-the-PC — not hello, memory, or spoken news."""
    g = goal or ""
    if wants_spoken_news(g):
        return False
    low = g.lower()
    if "http://" in low or "https://" in low:
        return True
    if _BARE_SITE.search(g) or host_from_site_followup(g) or _TLD_RE.search(g):
        return True
    if _HARD_PC_APP_RE.search(g):
        return True
    if goal_is_install_job(g) or goal_is_desktop_file_job(g):
        return True
    if _PC_VERB_RE.search(g) and re.search(
        r"\b(file|app|laptop|computer|pc|game)\b", g, re.I
    ):
        return True
    return False


def goal_is_greeting(goal: str) -> bool:
    return bool(_SIMPLE_GREET_RE.fullmatch((goal or "").strip()))


def goal_is_memory_ask(goal: str) -> bool:
    """Yesterday / journal / last time — unless it is also a site/app job."""
    g = goal or ""
    if _has_hard_pc_job(g):
        return False
    if _MEMORY_TALK_RE.search(g):
        return True
    try:
        from app.jarvis.daily_journal import looks_like_day_query

        return bool(looks_like_day_query(g))
    except Exception:
        return False


def goal_asks_own_machine(goal: str) -> bool:
    """True when they mean jarvis-computer (your screen / the browser / own PC)."""
    return bool(
        _OWN_MACHINE_RE.search(goal or "")
        or _CLOSE_TAB_RE.search(goal or "")
        or _CLOSE_ALL_RE.search(goal or "")
    )


def wants_close_tab(goal: str) -> bool:
    """True for close the tab / close the tabs / close this tab."""
    return bool(_CLOSE_TAB_RE.search(goal or ""))


def wants_close_all(goal: str) -> bool:
    """True for close all tabs / close the browser / close all windows."""
    return bool(_CLOSE_ALL_RE.search(goal or ""))


_OPEN_READ_CLICK_CLOSE_RE = re.compile(
    r"\b("
    r"open|go to|goto|browse|visit|read|look|see|watch|click|close|scroll|"
    r"tell(?:\s+me)?|what(?:'s|s|\s+is)\s+on"
    r")\b",
    re.I,
)


def wants_open_read_click_close(goal: str) -> bool:
    """Open / read / click / close — run_app + see_screen is enough on hosted Linux."""
    g = goal or ""
    if wants_spoken_news(g):
        return False
    if wants_close_all(g) or wants_close_tab(g):
        return True
    if goal_asks_own_machine(g):
        return True
    if not _OPEN_READ_CLICK_CLOSE_RE.search(g):
        return False
    if goal_is_install_job(g) or goal_is_desktop_file_job(g):
        return False
    return True


def goal_is_simple_talk(goal: str) -> bool:
    """Hello / memory / spoken news / short chit-chat — do not open the virtual PC."""
    g = (goal or "").strip()
    if not g:
        return False
    if goal_is_hire_job(g):
        return False
    if goal_is_greeting(g):
        return True
    if wants_look_job(g) or wants_still_see(g) or wants_screen_job(g):
        return False
    if goal_asks_own_machine(g):
        return False
    if wants_stop_talk(g) or wants_talk_followup(g):
        return True
    if wants_spoken_news(g):
        return True
    if goal_asks_own_machine(g) or wants_screen_job(g):
        return False
    if _has_hard_pc_job(g):
        return False
    if goal_is_memory_ask(g):
        return True
    if _PC_VERB_RE.search(g) or goal_needs_linux_desktop(g):
        return False
    if goal_is_install_job(g) or goal_is_desktop_file_job(g):
        return False
    # Count Latin + Turkish + digits. ASCII-only \w misses "dün" / "kaç".
    words = re.findall(r"[0-9]+|[^\W\d_]+", g, flags=re.UNICODE)
    return len(g) <= 80 and len(words) <= 12


def goal_is_virtual_pc_job(goal: str) -> bool:
    """Any site or shipped app on Jarvis's live PC — not a local Inbox folder."""
    if goal_is_simple_talk(goal) or goal_is_hire_job(goal):
        return False
    g = goal or ""
    if goal_asks_host_disk(g) and not goal_needs_linux_desktop(g):
        return False
    low = g.lower()
    if "http://" in low or "https://" in low:
        return True
    if goal_asks_own_machine(g) and not goal_asks_host_disk(g):
        return True
    if goal_needs_linux_desktop(g) and not goal_asks_host_disk(g):
        return True
    if wants_spoken_news(g):
        return False
    if host_from_site_followup(g) and wants_screen_job(g):
        return True
    if _BARE_SITE.search(g) and not goal_asks_host_disk(g) and not goal_wants_news(g):
        return True
    if goal_is_install_job(g) or goal_is_desktop_file_job(g):
        return True
    return bool(_VIRTUAL_PC_ACT.search(g) and _VIRTUAL_PC_TARGET.search(g))


def goal_is_computer_job(goal: str) -> bool:
    """Virtual-PC job plus any use-the-PC ask (install/file/excel/laptop/…)."""
    g = goal or ""
    if goal_is_simple_talk(g) or goal_asks_host_disk(g) or goal_is_hire_job(g):
        return False
    if goal_is_virtual_pc_job(g):
        return True
    if goal_asks_own_machine(g):
        return True
    if goal_is_install_job(g) or goal_is_desktop_file_job(g):
        return True
    return bool(_USE_THE_PC_VERB.search(g) and _USE_THE_PC_NOUN.search(g))


def host_is_windows(env: dict[str, str] | None = None) -> bool:
    environ = env if env is not None else os.environ
    pinned = str(environ.get("JARVIS_HOST_OS") or "").strip().lower()
    if pinned in {"windows", "win32", "win"}:
        return True
    if pinned in {"linux", "darwin", "macos"}:
        return False
    return sys.platform == "win32"


def hosted_linux_talk(
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> bool:
    """True on the Linux host that serves public /jarvis/.

    The live VM pins JARVIS_HOST_OS=windows, so that env is not the signal.
    Real win32 (the Windows app) stays False.
    """
    del env  # callers may pass os.environ; do not trust JARVIS_HOST_OS
    plat = sys.platform if platform is None else platform
    return plat != "win32"


def public_talk_uses_jarvis_computer(goal: str, env: dict[str, str] | None = None) -> bool:
    """Hosted Linux talk uses jarvis-computer for show/open/go/find/run."""
    if not hosted_linux_talk(env):
        return False
    return goal_is_virtual_pc_job(goal) or goal_is_computer_job(goal)
