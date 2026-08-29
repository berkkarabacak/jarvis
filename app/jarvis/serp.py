"""Search-results pages are not articles. Click-ok is not navigation.

Talk and /ask both need this: after a click, if title/url/vision is still
DuckDuckGo / Google / Bing, the click missed. Leave the SERP with a real
result link or run_app to a publisher URL from the look. Never invent a
country host (switzerland.com). Never treat news-card headlines as the story.
"""

from __future__ import annotations

import re
from typing import Any

# Title / vision still on a search engine results page.
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
# Known publishers. Use only when the look names them, or as a last-resort
# leave-SERP target (never an invented country TLD). Homepages only — never a
# swissinfo article slug that 404s.
_KNOWN_PUBLISHERS: tuple[tuple[str, str], ...] = (
    ("swissinfo.ch", "https://www.swissinfo.ch/eng"),
    ("nzz.ch", "https://www.nzz.ch/"),
    ("n-tv.de", "https://www.n-tv.de/"),
    ("reuters.com", "https://www.reuters.com/"),
    ("bbc.com", "https://www.bbc.com/news"),
    ("cnn.com", "https://www.cnn.com/"),
    ("srf.ch", "https://www.srf.ch/news"),
    ("apnews.com", "https://apnews.com/"),
    ("swissinfo", "https://www.swissinfo.ch/eng"),
    ("reuters", "https://www.reuters.com/"),
    ("bbc", "https://www.bbc.com/news"),
    ("cnn", "https://www.cnn.com/"),
    ("nzz", "https://www.nzz.ch/"),
    ("ntv", "https://www.n-tv.de/"),
    ("srf", "https://www.srf.ch/news"),
)
# Last-resort article host when the SERP named no URL and no publisher.
# Real publisher, not an invented country host.
DEFAULT_LEAVE_SERP_URL = "https://www.reuters.com/"
EUROPE_NEWS_URL = "https://www.bbc.com/news/world/europe"
EUROPE_NEWS_FALLBACK = "https://www.reuters.com/world/europe/"
SWISS_NEWS_URL = "https://www.nzz.ch/"
SWISS_NEWS_FALLBACK = "https://www.swissinfo.ch/eng"
GENERIC_NEWS_URL = "https://www.reuters.com/"
GENERIC_NEWS_FALLBACK = "https://www.bbc.com/news"
# Working news-tell homepages. Region → (primary, fallback).
_NEWS_TELL_HOMEPAGES: dict[str, tuple[str, str]] = {
    "europe": (EUROPE_NEWS_URL, EUROPE_NEWS_FALLBACK),
    "switzerland": (SWISS_NEWS_URL, SWISS_NEWS_FALLBACK),
    "generic": (GENERIC_NEWS_URL, GENERIC_NEWS_FALLBACK),
}
_SWISS_ASK_RE = re.compile(r"\b(switzerland|swiss)\b", re.I)
_EUROPE_ASK_RE = re.compile(r"\b(europe|european)\b", re.I)
_NEWS_PUBLISHER_HOSTS = frozenset(
    {
        "bbc.com",
        "www.bbc.com",
        "reuters.com",
        "www.reuters.com",
        "nzz.ch",
        "www.nzz.ch",
        "cnn.com",
        "www.cnn.com",
        "swissinfo.ch",
        "www.swissinfo.ch",
    }
)
_DEAD_PAGE_RE = re.compile(
    r"("
    r"\b404\b|"
    r"page not found|"
    r"this page (?:does not|doesn't|is not) (?:exist|available)|"
    r"we (?:can(?:not|'t|’t)|could not) find|"
    r"the page you (?:requested|are looking for)|"
    r"about:blank|"
    r"\buntitled\b|"
    r"\bnew tab\b"
    r")",
    re.I,
)
_COOKIE_OVERLAY_RE = re.compile(
    r"("
    r"\baccept(?:\s+all)?(?:\s+(?:and\s+)?continue)?\b|"
    r"\bi\s+agree\b|"
    r"\bagree\s+and\s+continue\b|"
    r"before you continue|"
    r"cookie\s+(?:banner|modal|consent|wall|notice)|"
    r"consent\s+(?:banner|modal|overlay)|"
    r"terms\s+(?:of\s+use\s+)?accept|"
    r"accept\s+(?:all\s+)?cookies"
    r")",
    re.I,
)
_HEADLINE_HINT_RE = re.compile(
    r"\b(headline|headlines|breaking|latest|top stories)\b",
    re.I,
)
_INVENTED_COUNTRY_HOST_RE = re.compile(
    r"("
    r"switzerland\.com|swiss\.com|french\.com|japan\.com|"
    r"brazil\.com|turkish\.com|turkey\.com"
    r")",
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
_OPEN_READ_ARTICLE_RE = re.compile(
    r"("
    r"\bopen\b.{0,48}\b(?:the\s+)?(?:news|article)\b|"
    r"\bread\b.{0,48}\b(?:news|that|this|the|article|it)\b|"
    r"\bclick\s+that\s+and\s+read\b|"
    r"\bclick\s+(?:that|this|it)\b.{0,32}\bread\b"
    r")",
    re.I,
)
_CONTINUE_LEAVE_RE = re.compile(
    r"^\s*("
    r"yes|yeah|yep|ok|okay|go ahead|do it|"
    r"click(?:\s+that)?|read(?:\s+it)?|"
    r"what\??\s*go ahead"
    r")\s*[.!]?\s*$",
    re.I,
)
# jarvis-computer 1280×720: DDG search box / chips sit around y=110–280.
# Clicks here are the search box or "What? Go ahead.", not a result headline.
_SERP_CHROME_Y_MAX = 280
_SERP_CHROME_Y_MIN = 0


def looks_like_search_results(text: str) -> bool:
    return bool(_SEARCH_PAGE_RE.search(text or ""))


def host_of_url(url: str) -> str:
    raw = re.sub(r"^https?://", "", url or "", flags=re.I).split("/")[0].lower()
    return raw


def is_search_engine_host(host: str) -> bool:
    h = (host or "").lower()
    if h.startswith("www."):
        h = h[4:]
    return h in _SEARCH_ENGINE_HOSTS or f"www.{h}" in _SEARCH_ENGINE_HOSTS


def is_search_engine_url(url: str) -> bool:
    return is_search_engine_host(host_of_url(url))


def invented_country_host(url: str) -> bool:
    return bool(_INVENTED_COUNTRY_HOST_RE.search(url or ""))


def look_blob(looked: dict[str, Any] | None) -> str:
    item = looked or {}
    return " ".join(
        str(item.get(key) or "")
        for key in ("vision_description", "title", "error", "note", "vision_error", "url")
    )


def look_is_serp(looked: dict[str, Any] | None) -> bool:
    """True when title/url/vision are still DuckDuckGo / Google / Bing.

    ``preferred`` staying duckduckgo.com is not proof — remember_look_target
    pins the search URL even after a real article loads. Use the current
    title / vision / explicit url field only.
    """
    item = looked or {}
    title = str(item.get("title") or "")
    if looks_like_search_results(title):
        return True
    url = str(item.get("url") or "")
    if url and is_search_engine_url(url):
        return True
    return looks_like_search_results(look_blob(item))


def wants_open_or_read_article(asked: str) -> bool:
    """open the news / click that and read / read that news."""
    return bool(_OPEN_READ_ARTICLE_RE.search(asked or ""))


def wants_continue_leave_serp(asked: str) -> bool:
    """Short yes / go ahead while already on a SERP."""
    return bool(_CONTINUE_LEAVE_RE.search((asked or "").strip()))


def wants_news_words(asked: str) -> bool:
    return bool(_NEWS_ASK_RE.search(asked or ""))


def wants_leave_serp(asked: str, looked: dict[str, Any] | None = None) -> bool:
    """News / read / click-that, or a yes while the last look is still a SERP."""
    if wants_news_words(asked) or wants_open_or_read_article(asked):
        return True
    return bool(look_is_serp(looked) and wants_continue_leave_serp(asked))


def click_hits_serp_chrome(x: Any, y: Any) -> bool:
    """True for the DDG/Google search box / chips / top chrome, not a result row."""
    try:
        yi = int(y)
    except (TypeError, ValueError):
        return False
    return _SERP_CHROME_Y_MIN <= yi <= _SERP_CHROME_Y_MAX


def path_of_url(url: str) -> str:
    raw = re.sub(r"^https?://", "", url or "", flags=re.I)
    if "/" not in raw:
        return "/"
    return "/" + raw.split("/", 1)[1].split("?", 1)[0].split("#", 1)[0]


def is_dead_swissinfo_path(url: str) -> bool:
    """True for a swissinfo article slug that often 404s. Homepages are fine."""
    host = host_of_url(url)
    if "swissinfo.ch" not in host:
        return False
    path = path_of_url(url).rstrip("/").lower()
    if path in {"", "/", "/eng"}:
        return False
    return True


def is_working_news_url(url: str) -> bool:
    """Known publisher homepage or section — not a 404 slug or invented host."""
    raw = (url or "").strip()
    if not raw or invented_country_host(raw) or is_search_engine_url(raw):
        return False
    if is_dead_swissinfo_path(raw):
        return False
    host = host_of_url(raw)
    if host.startswith("www."):
        host = host[4:]
    return f"www.{host}" in _NEWS_PUBLISHER_HOSTS or host in _NEWS_PUBLISHER_HOSTS


def news_region_from_ask(asked: str) -> str:
    """europe / switzerland / generic. Never invent a country host."""
    raw = asked or ""
    if _SWISS_ASK_RE.search(raw):
        return "switzerland"
    if _EUROPE_ASK_RE.search(raw):
        return "europe"
    return "generic"


def news_homepage_from_ask(asked: str, *, fallback: bool = False) -> str:
    """ONE known working homepage for news-tell. Never switzerland.com."""
    region = news_region_from_ask(asked)
    primary, alt = _NEWS_TELL_HOMEPAGES.get(region, _NEWS_TELL_HOMEPAGES["generic"])
    return alt if fallback else primary


def news_fallback_url(asked: str, current: str = "") -> str:
    """If the current page 404s or is blank, the other known homepage."""
    region = news_region_from_ask(asked)
    primary, alt = _NEWS_TELL_HOMEPAGES.get(region, _NEWS_TELL_HOMEPAGES["generic"])
    cur = (current or "").strip().lower().rstrip("/")
    if cur and alt.rstrip("/").lower() != cur:
        if primary.rstrip("/").lower() == cur or primary.lower() in cur:
            return alt
    if cur and primary.rstrip("/").lower() != cur:
        return primary
    return alt


def look_is_404(looked: dict[str, Any] | None) -> bool:
    blob = look_blob(looked)
    title = str((looked or {}).get("title") or "")
    if re.search(r"\b404\b", title) or re.search(r"page not found", title, re.I):
        return True
    return bool(
        re.search(
            r"\b404\b|page not found|this page (?:does not|doesn't) exist",
            blob,
            re.I,
        )
    )


def look_is_dead_page(looked: dict[str, Any] | None) -> bool:
    """404, about:blank, Untitled, empty — not a loaded news page."""
    item = looked or {}
    title = str(item.get("title") or "")
    desc = str(item.get("vision_description") or "").strip()
    blob = look_blob(item)
    if look_is_404(item):
        return True
    if _DEAD_PAGE_RE.search(title) or _DEAD_PAGE_RE.search(blob):
        return True
    return bool(item.get("ok") and not desc and not title.strip())


def look_has_cookie_overlay(looked: dict[str, Any] | None) -> bool:
    return bool(_COOKIE_OVERLAY_RE.search(look_blob(looked)))


def look_is_news_page(looked: dict[str, Any] | None) -> bool:
    """BBC / Reuters / NZZ / CNN / swissinfo with headlines, not a 404/SERP."""
    item = looked or {}
    if not item or look_is_serp(item) or look_is_dead_page(item):
        return False
    url = str(item.get("url") or "")
    blob = look_blob(item)
    host_ok = bool(url and is_working_news_url(url))
    named = bool(
        re.search(
            r"\b(bbc|reuters|nzz|cnn|swissinfo)\b",
            blob,
            re.I,
        )
    )
    if not host_ok and not named:
        return False
    if _HEADLINE_HINT_RE.search(blob):
        return True
    desc = str(item.get("vision_description") or "").strip()
    return bool(desc and len(desc) >= 24)


def result_url_from_look(looked: dict[str, Any] | None) -> str | None:
    """First https URL on the screen that is not the search engine itself."""
    blob = str((looked or {}).get("vision_description") or "") + " " + str(
        (looked or {}).get("title") or ""
    )
    for match in re.finditer(r"https?://[^\s<>\"']+", blob, re.I):
        raw = match.group(0).rstrip(".,);]!?'\"")
        if invented_country_host(raw):
            continue
        if is_search_engine_url(raw):
            continue
        if is_dead_swissinfo_path(raw):
            continue
        return raw
    return None


def publisher_url_from_look(looked: dict[str, Any] | None) -> str | None:
    """Known publisher named in the look. Not an invented country host."""
    blob = look_blob(looked).lower()
    if not blob.strip():
        return None
    for key, url in _KNOWN_PUBLISHERS:
        if " " in key:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", blob):
            if invented_country_host(url) or is_dead_swissinfo_path(url):
                continue
            return url
    return None


def leave_serp_url(
    looked: dict[str, Any] | None,
    asked: str = "",
    *,
    allow_default: bool = True,
) -> str | None:
    """Real article URL to leave a SERP. Prefer vision https, then a named publisher.

    Last resort is a known working homepage for the ask (Europe / Switzerland /
    generic), never switzerland.com, never a 404 swissinfo slug, and never
    another DuckDuckGo search.
    """
    url = result_url_from_look(looked)
    if url and is_working_news_url(url):
        return url
    if url and not invented_country_host(url) and not is_search_engine_url(url):
        if not is_dead_swissinfo_path(url):
            return url
    url = publisher_url_from_look(looked)
    if url and not is_dead_swissinfo_path(url):
        return url
    if allow_default:
        if wants_news_words(asked):
            return news_homepage_from_ask(asked)
        return DEFAULT_LEAVE_SERP_URL
    return None


def click_missed_search(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> bool:
    """True when we were on a SERP and the post-click look is still a SERP."""
    if after is None:
        return look_is_serp(before)
    if not look_is_serp(before) and not look_is_serp(after):
        return False
    return look_is_serp(after)
