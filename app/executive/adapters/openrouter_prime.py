"""In-process OpenRouter-backed Prime runtime adapter.

The pinned Prime RPC adapter (``prime_rpc``) drives an external ``prime-agent``
binary. That binary is not present on a plain application host, so the default
factory falls back to :class:`NullPrimeAgent`, whose ``send_message`` raises and
leaves the public CEO shell with no reply.

This adapter implements the same :class:`PrimeAgentRuntime` port directly
against OpenRouter's chat-completions API so a host with only
``OPENROUTER_API_KEY`` set can serve live executive turns.

Boundary rules kept identical to the RPC adapter:

* The API key never leaves this module — not into argv, logs, health output,
  session metadata, or raised errors.
* Raw provider payloads never cross into the runtime. Only the scalar
  allowlist carried by :class:`GenerationTelemetry` and the assistant text do.
* Cost accounting is taken from OpenRouter's authoritative streamed usage
  receipt (``source="openrouter_stream"``), which is what the bounded and
  public-guest gates require. A turn without a receipt fails closed.
"""

from __future__ import annotations

from app.llm.openrouter_attribution import OPENROUTER_APP_TITLE, OPENROUTER_APP_URL, openrouter_attribution_headers

import asyncio
import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx

from app.executive.adapters.prime import (
    PrimeMessageResult,
    PrimeRuntimeError,
    PrimeSessionInfo,
    PrimeUnavailableError,
)
from app.executive.telemetry import (
    DEFAULT_BOUNDED_TEST_POLICY,
    BoundedTestPolicyV1,
    GenerationTelemetry,
    GenerationTelemetryError,
)

OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_AUTOROUTER_MODEL = "openrouter/auto"

# Upper bound on assistant text accepted from the provider before the runtime's
# own public-text sanitiser runs. Generous enough for a bounded 600-token reply.
_MAX_RAW_TEXT_CHARS = 24_000
_MAX_STREAM_LINES = 20_000


def _redacted(message: str) -> str:
    """Strip anything key-shaped from an operational message."""
    text = str(message or "").strip()
    lowered = text.lower()
    for token in ("sk-or-", "bearer ", "api_key", "apikey", "authorization", "token="):
        if token in lowered:
            return "provider error (redacted)"
    return text[:240]


class OpenRouterPrimeAgent:
    """Live Prime runtime backed directly by OpenRouter chat completions."""

    name = "openrouter-prime"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = OPENROUTER_AUTOROUTER_MODEL,
        policy: BoundedTestPolicyV1 = DEFAULT_BOUNDED_TEST_POLICY,
        timeout_seconds: float = 60.0,
        base_url: str = OPENROUTER_CHAT_COMPLETIONS_URL,
        referer: str = "",
        title: str = "AI Control Room",
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        key = str(api_key or "").strip()
        if (
            not key
            or len(key) > 512
            or any(character.isspace() or ord(character) < 32 for character in key)
        ):
            raise PrimeUnavailableError("OpenRouter credentials are unavailable")
        self._api_key = key
        self._model = str(model or OPENROUTER_AUTOROUTER_MODEL).strip()
        self._policy = policy
        self._timeout_seconds = max(1.0, min(float(timeout_seconds), 300.0))
        self._base_url = base_url
        self._referer = str(referer or "").strip()
        self._title = str(title or "").strip()[:120]
        self._sessions: dict[str, PrimeSessionInfo] = {}
        self._last_error: str | None = None
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=self._timeout_seconds)
        )

    # --- port surface -------------------------------------------------

    async def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "available": True,
            "availability": "ready",
            "adapter": self.name,
            "prime_binary": False,
            "rpc": False,
            "live": True,
            "credentials_configured": True,
            "model_selector": self._model,
            "active_sessions": len(self._sessions),
            "last_error": self._last_error,
            "detail": (
                "In-process OpenRouter executive runtime; authoritative streamed "
                "usage receipts settle every generation"
            ),
        }

    def mark_error(self, message: str) -> None:
        self._last_error = _redacted(message) or None

    async def start_session(
        self,
        *,
        role_name: str,
        parent_session_id: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PrimeSessionInfo:
        info = PrimeSessionInfo(
            session_id=f"or-{uuid.uuid4()}",
            role_name=role_name,
            parent_session_id=parent_session_id,
            model=model or self._model,
            metadata=dict(metadata or {}),
            status="active",
        )
        self._sessions[info.session_id] = info
        return info

    async def stop_session(self, session_id: str, *, reason: str = "stopped") -> None:
        info = self._sessions.pop(session_id, None)
        if info is not None:
            info.status = reason or "stopped"

    async def list_sessions(self) -> list[PrimeSessionInfo]:
        return list(self._sessions.values())

    async def send_message(
        self, session_id: str, *, message: str
    ) -> PrimeMessageResult:
        session = self._sessions.get(session_id)
        if session is None or session.status != "active":
            raise PrimeUnavailableError("Executive session is unavailable")
        text = str(message or "").strip()
        if not text:
            raise PrimeRuntimeError("Executive prompt is required")

        # Each call is a single self-contained prompt. The runtime already
        # embeds any transcript it wants replayed, so the adapter keeps no
        # history of its own — that keeps token usage inside the prospective
        # per-generation reservation the bounded policy is built on.
        payload = self._build_payload(text)
        reply, receipt = await self._stream_completion(payload)

        try:
            generation = GenerationTelemetry.build(
                generation_id=receipt.get("id"),
                selected_model=receipt.get("model") or self._model,
                input_tokens=receipt.get("prompt_tokens"),
                output_tokens=receipt.get("completion_tokens"),
                total_tokens=receipt.get("total_tokens"),
                actual_cost_usd=receipt.get("cost"),
                source="openrouter_stream",
            )
        except GenerationTelemetryError as exc:
            # Fail closed: an unsettled generation must not look free.
            self.mark_error(str(exc))
            raise PrimeRuntimeError(
                "Authoritative generation accounting is unavailable"
            ) from exc

        return PrimeMessageResult(
            message_id=str(uuid.uuid4()),
            session_id=session_id,
            text=reply,
            safety_filtered=False,
            generation=generation,
        )

    async def close(self) -> None:
        self._sessions.clear()

    # --- internals ----------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            **openrouter_attribution_headers(),
        }
        if self._referer:
            headers["HTTP-Referer"] = self._referer
        if self._title:
            headers["X-Title"] = self._title
            headers["X-OpenRouter-Title"] = self._title
        return headers

    def _build_payload(self, prompt: str) -> dict[str, Any]:
        policy = self._policy
        return {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": int(policy.max_output_tokens_per_generation),
            "stream": True,
            # Authoritative owner-charge accounting on the final stream chunk.
            "usage": {"include": True},
            "provider": {
                # Cheapest compliant provider, no silent fallback to a pricier
                # one, and hard per-million price ceilings from the policy.
                "sort": "price",
                "allow_fallbacks": False,
                "max_price": {
                    "prompt": float(policy.max_prompt_price_usd_per_million),
                    "completion": float(policy.max_completion_price_usd_per_million),
                },
            },
        }

    async def _stream_completion(
        self, payload: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        chunks: list[str] = []
        receipt: dict[str, Any] = {}
        try:
            client = self._client_factory()
            async with client:
                async with client.stream(
                    "POST",
                    self._base_url,
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    if response.status_code in (401, 403):
                        raise PrimeUnavailableError(
                            "OpenRouter credentials were rejected"
                        )
                    if response.status_code == 429:
                        raise PrimeUnavailableError("OpenRouter rate limit reached")
                    if response.status_code >= 400:
                        raise PrimeRuntimeError(
                            f"OpenRouter request failed ({response.status_code})"
                        )
                    seen = 0
                    async for raw_line in response.aiter_lines():
                        seen += 1
                        if seen > _MAX_STREAM_LINES:
                            raise PrimeRuntimeError("OpenRouter stream was too long")
                        line = raw_line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        self._absorb_event(event, chunks, receipt)
        except (PrimeRuntimeError, PrimeUnavailableError):
            raise
        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            raise PrimeRuntimeError("OpenRouter request timed out") from exc
        except httpx.HTTPError as exc:
            self.mark_error(type(exc).__name__)
            raise PrimeUnavailableError("OpenRouter is unreachable") from exc

        reply = "".join(chunks).strip()[:_MAX_RAW_TEXT_CHARS]
        if not reply:
            raise PrimeRuntimeError("OpenRouter returned no assistant text")
        return reply, receipt

    @staticmethod
    def _absorb_event(
        event: Any, chunks: list[str], receipt: dict[str, Any]
    ) -> None:
        """Pull text deltas and the usage receipt out of one stream event."""
        if not isinstance(event, dict):
            return
        if isinstance(event.get("id"), str):
            receipt["id"] = event["id"]
        if isinstance(event.get("model"), str):
            receipt["model"] = event["model"]
        for choice in event.get("choices") or ():
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str):
                    chunks.append(content)
        usage = event.get("usage")
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    receipt[key] = value
            cost = usage.get("cost")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                receipt["cost"] = cost


def build_openrouter_prime_agent(
    *,
    api_key: str,
    model: str = OPENROUTER_AUTOROUTER_MODEL,
    referer: str = "",
) -> OpenRouterPrimeAgent | None:
    """Return a live adapter, or ``None`` when no usable credential is set."""
    key = str(api_key or "").strip()
    if not key:
        return None
    try:
        return OpenRouterPrimeAgent(api_key=key, model=model, referer=referer or OPENROUTER_APP_URL, title=OPENROUTER_APP_TITLE)
    except PrimeUnavailableError:
        return None
