from __future__ import annotations

from urllib.parse import urlparse

import httpx

from app.auth.constants import (
    DEFAULT_XAI_MODELS,
    XAI_API_BASE_URL,
    XAI_API_HOST_ALLOWLIST,
    XAI_CHAT_COMPLETIONS_PATH,
)
from app.auth.provider import TokenProvider
from app.llm.base import ChatResult, LlmStatus, LlmTestResult


class XaiLlmProvider:
    """Legacy xAI / Grok chat completions provider (optional)."""

    name = "xai"

    def __init__(
        self,
        token_provider: TokenProvider,
        *,
        base_url: str = XAI_API_BASE_URL,
        timeout_seconds: float = 600.0,
        default_model: str = "grok-4.5",
        mode: str = "fixed",
    ) -> None:
        self.token_provider = token_provider
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.default_model = default_model
        self.mode = mode
        host = urlparse(self.base_url).hostname or ""
        if host not in XAI_API_HOST_ALLOWLIST:
            raise ValueError(f"Refusing non-allowlisted API host: {host}")

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
    ) -> ChatResult:
        token = await self.token_provider.get_access_token()
        url = f"{self.base_url}{XAI_CHAT_COMPLETIONS_PATH}"
        host = urlparse(url).hostname or ""
        if host not in XAI_API_HOST_ALLOWLIST:
            raise RuntimeError(f"Refusing to send bearer to host {host}")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        base_body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(
                url,
                headers=headers,
                json={**base_body, "response_format": {"type": "json_object"}},
            )
            if resp.status_code >= 400 and "response_format" in (resp.text or "").lower():
                resp = await client.post(url, headers=headers, json=base_body)
            elif resp.status_code == 400:
                resp = await client.post(url, headers=headers, json=base_body)

        if resp.status_code == 401:
            raise RuntimeError(f"xAI API 401 unauthorized: {resp.text[:500]}")
        if not resp.is_success:
            raise RuntimeError(f"xAI API error HTTP {resp.status_code}: {resp.text[:800]}")

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected xAI response shape: {data!r}"[:800]) from exc

        usage = data.get("usage") or {}
        effective = None
        try:
            effective = data["choices"][0]["message"].get("model") or data.get("model")
        except Exception:
            effective = data.get("model")

        return ChatResult(
            content=content if isinstance(content, str) else str(content),
            raw=data,
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            model=effective or model,
            provider=self.name,
        )

    async def status(self) -> LlmStatus:
        auth = await self.token_provider.status()
        return LlmStatus(
            provider=self.name,
            healthy=bool(auth.healthy and not auth.needs_reauth),
            mode=self.mode,
            default_model=self.default_model,
            last_error=auth.last_error,
        )

    async def list_models(self) -> list[str]:
        return list(DEFAULT_XAI_MODELS)

    async def test_connection(self, *, model: str | None = None) -> LlmTestResult:
        import time

        m = model or self.default_model
        started = time.perf_counter()
        try:
            result = await self.chat(
                model=m,
                messages=[
                    {"role": "user", "content": 'Reply with JSON: {"result":"pong","memory":""}'},
                ],
                temperature=0,
            )
            ms = int((time.perf_counter() - started) * 1000)
            return LlmTestResult(
                ok=True,
                provider=self.name,
                message="xAI connection ok",
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
