"""OpenRouter marketplace attribution for Jarvis.

These headers create the public app page on https://openrouter.ai/apps.
HTTP-Referer is required. Title and categories are merged by OpenRouter.
"""

from __future__ import annotations

OPENROUTER_APP_URL = "https://aicontrolroom.nl/jarvis/"
OPENROUTER_APP_TITLE = "Jarvis"
OPENROUTER_APP_CATEGORIES = "personal-agent,general-chat"


def openrouter_attribution_headers() -> dict[str, str]:
    return {
        "HTTP-Referer": OPENROUTER_APP_URL,
        "X-Title": OPENROUTER_APP_TITLE,
        "X-OpenRouter-Title": OPENROUTER_APP_TITLE,
        "X-OpenRouter-Categories": OPENROUTER_APP_CATEGORIES,
    }
