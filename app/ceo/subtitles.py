from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

SubtitleSize = Literal["sm", "md", "lg"]
# Small allowlist — UI i18n labels only (not model language).
SUBTITLE_LANGS = ("en", "nl", "tr", "de", "fr", "es")
SUBTITLE_SIZES = ("sm", "md", "lg")


@dataclass
class SubtitlePrefs:
    enabled: bool = True
    language: str = "en"
    size: str = "md"
    only_while_speaking: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "language": self.language,
            "size": self.size,
            "only_while_speaking": self.only_while_speaking,
            "languages": list(SUBTITLE_LANGS),
            "sizes": list(SUBTITLE_SIZES),
        }


def normalize_subtitle_prefs(
    *,
    enabled: bool | None = None,
    language: str | None = None,
    size: str | None = None,
    only_while_speaking: bool | None = None,
    base: SubtitlePrefs | None = None,
) -> SubtitlePrefs:
    prefs = base or SubtitlePrefs()
    if enabled is not None:
        prefs.enabled = bool(enabled)
    if language is not None:
        lang = (language or "en").strip().lower()
        prefs.language = lang if lang in SUBTITLE_LANGS else "en"
    if size is not None:
        sz = (size or "md").strip().lower()
        prefs.size = sz if sz in SUBTITLE_SIZES else "md"
    if only_while_speaking is not None:
        prefs.only_while_speaking = bool(only_while_speaking)
    return prefs
