from __future__ import annotations

import time
from typing import Any

import httpx

from app.jarvis.openrouter_leaders import SNAPSHOT_MODEL_IDS
from app.llm.base import ChatResult, LlmStatus, LlmTestResult
from app.llm.openrouter_attribution import openrouter_attribution_headers

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
# OpenRouter Auto Beta — router picks a model per request.
OPENROUTER_AUTO_MODEL = "openrouter/auto"
OPENROUTER_ONLINE_SUFFIX = ":online"
OPENROUTER_WEB_SEARCH_TOOL = {"type": "openrouter:web_search"}

DEFAULT_OPENROUTER_MODELS = (
    OPENROUTER_AUTO_MODEL,
    *SNAPSHOT_MODEL_IDS,
    "anthropic/claude-sonnet-4",
    "openai/gpt-4.1",
    "openai/gpt-4.1-mini",
    "google/gemini-2.5-pro",
    "google/gemini-2.5-flash",
    "x-ai/grok-4",
    "x-ai/grok-3",
    "meta-llama/llama-4-maverick",
    "deepseek/deepseek-chat-v3-0324",
)


class OpenRouterLlmProvider:
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 600.0,
        default_model: str = OPENROUTER_AUTO_MODEL,
        mode: str = "auto",
        site_url: str = "https://aicontrolroom.nl/jarvis/",
        app_title: str = "Jarvis",
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.timeout_seconds = timeout_seconds
        self.default_model = default_model or OPENROUTER_AUTO_MODEL
        self.mode = mode if mode in ("auto", "fixed") else "auto"
        self.site_url = site_url
        self.app_title = app_title

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            **openrouter_attribution_headers(),
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.app_title:
            headers["X-Title"] = self.app_title
            headers["X-OpenRouter-Title"] = self.app_title
        return headers

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
    ) -> ChatResult:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")

        url = f"{OPENROUTER_BASE}/chat/completions"
        request_model, web_search = _request_model(model)
        base_body: dict[str, Any] = {
            "model": request_model,
            "messages": messages,
            "temperature": temperature,
        }
        if web_search:
            # OpenRouter's web-search server tool is incompatible with JSON mode.
            request_body = {**base_body, "tools": [OPENROUTER_WEB_SEARCH_TOOL]}
        else:
            request_body = {
                **base_body,
                "response_format": {"type": "json_object"},
            }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(
                url,
                headers=self._headers(),
                json=request_body,
            )
            text_l = (resp.text or "").lower()
            if (
                not web_search
                and resp.status_code >= 400
                and (
                    "response_format" in text_l
                    or "json_object" in text_l
                    or resp.status_code == 400
                )
            ):
                resp = await client.post(url, headers=self._headers(), json=base_body)

        if resp.status_code == 401:
            raise RuntimeError("OpenRouter 401 unauthorized — check API key")
        if resp.status_code == 402:
            raise RuntimeError("OpenRouter 402 — insufficient credits")
        if not resp.is_success:
            if web_search:
                raise RuntimeError(f"OpenRouter web search HTTP {resp.status_code}")
            raise RuntimeError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:800]}")

        try:
            data = resp.json()
        except ValueError as exc:
            if web_search:
                raise RuntimeError(
                    "Unexpected OpenRouter web search response shape"
                ) from exc
            raise
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            if web_search:
                raise RuntimeError(
                    "Unexpected OpenRouter web search response shape"
                ) from exc
            raise RuntimeError(
                f"Unexpected OpenRouter response shape: {data!r}"[:800]
            ) from exc

        usage = data.get("usage") or {}
        effective = data.get("model") or request_model
        return ChatResult(
            content=content if isinstance(content, str) else str(content),
            raw=data,
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            model=effective,
            provider=self.name,
        )

    async def status(self) -> LlmStatus:
        ok = bool(self.api_key)
        return LlmStatus(
            provider=self.name,
            healthy=ok,
            mode=self.mode,
            default_model=self.default_model,
            last_error=None if ok else "OPENROUTER_API_KEY missing",
        )

    async def list_models(self) -> list[str]:
        if not self.api_key:
            return list(DEFAULT_OPENROUTER_MODELS)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{OPENROUTER_BASE}/models",
                    headers=self._headers(),
                )
            if not resp.is_success:
                return list(DEFAULT_OPENROUTER_MODELS)
            data = resp.json()
            ids = []
            for item in data.get("data") or []:
                mid = item.get("id")
                if isinstance(mid, str) and mid:
                    ids.append(mid)
            # Prefer curated list first, then extras
            curated = [
                m
                for m in DEFAULT_OPENROUTER_MODELS
                if m in ids or m == OPENROUTER_AUTO_MODEL
            ]
            extras = [m for m in ids if m not in curated][:40]
            return curated + extras
        except Exception:
            return list(DEFAULT_OPENROUTER_MODELS)

    async def test_connection(self, *, model: str | None = None) -> LlmTestResult:
        m = model or (
            OPENROUTER_AUTO_MODEL if self.mode == "auto" else self.default_model
        )
        started = time.perf_counter()
        try:
            result = await self.chat(
                model=m,
                messages=[
                    {
                        "role": "user",
                        "content": 'Reply with JSON only: {"result":"pong","memory":""}',
                    }
                ],
                temperature=0,
            )
            ms = int((time.perf_counter() - started) * 1000)
            return LlmTestResult(
                ok=True,
                provider=self.name,
                message="OpenRouter connection ok",
                model=result.model or m,
                latency_ms=ms,
            )
        except Exception as exc:
            ms = int((time.perf_counter() - started) * 1000)
            return LlmTestResult(
                ok=False,
                provider=self.name,
                message=str(exc)[:400],
                model=m,
                latency_ms=ms,
            )


def _request_model(model: str) -> tuple[str, bool]:
    """Translate the stored ``:online`` marker only at the vendor boundary."""

    if not model.endswith(OPENROUTER_ONLINE_SUFFIX):
        return model, False
    request_model = model[: -len(OPENROUTER_ONLINE_SUFFIX)].strip()
    if not request_model:
        raise RuntimeError("OpenRouter web search requires a base model")
    return request_model, True
