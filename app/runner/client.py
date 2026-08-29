"""Backward-compatible re-export. Prefer app.llm providers. """
from __future__ import annotations

from app.llm.base import ChatResult
from app.llm.xai import XaiLlmProvider as GrokClient

__all__ = ["ChatResult", "GrokClient"]
