from __future__ import annotations

from typing import Any

import pytest

from app.llm.openrouter import OpenRouterLlmProvider


class _Response:
    def __init__(
        self,
        status_code: int,
        *,
        body: dict[str, Any] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict[str, Any]:
        return self._body


class _Client:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _Client:  # noqa: PYI034
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def _install_client(monkeypatch: pytest.MonkeyPatch, client: _Client) -> None:
    monkeypatch.setattr(
        "app.llm.openrouter.httpx.AsyncClient",
        lambda **_kwargs: client,
    )


def _success(*, model: str | None = "openai/gpt-5.2") -> _Response:
    body: dict[str, Any] = {
        "choices": [{"message": {"content": "grounded result"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
    }
    if model is not None:
        body["model"] = model
    return _Response(200, body=body)


@pytest.mark.asyncio
async def test_online_marker_uses_web_search_tool_without_json_mode(monkeypatch):
    client = _Client([_success()])
    _install_client(monkeypatch, client)
    provider = OpenRouterLlmProvider("test-key")
    messages = [{"role": "user", "content": "Latest Turkey news"}]

    result = await provider.chat(
        model="openrouter/auto:online",
        messages=messages,
        temperature=0.1,
    )

    assert len(client.calls) == 1
    payload = client.calls[0]["json"]
    assert payload == {
        "model": "openrouter/auto",
        "messages": messages,
        "temperature": 0.1,
        "tools": [{"type": "openrouter:web_search"}],
    }
    assert "response_format" not in payload
    assert result.model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_online_effective_model_falls_back_to_transport_model(monkeypatch):
    client = _Client([_success(model=None)])
    _install_client(monkeypatch, client)
    provider = OpenRouterLlmProvider("test-key")

    result = await provider.chat(
        model="openrouter/auto:online",
        messages=[{"role": "user", "content": "news"}],
    )

    assert result.model == "openrouter/auto"


@pytest.mark.asyncio
async def test_normal_grok_model_keeps_json_mode_and_existing_fallback(monkeypatch):
    client = _Client(
        [
            _Response(400, text="response_format is unsupported"),
            _success(model="x-ai/grok-4"),
        ]
    )
    _install_client(monkeypatch, client)
    provider = OpenRouterLlmProvider("test-key")
    messages = [{"role": "user", "content": "normal task"}]

    result = await provider.chat(model="x-ai/grok-4", messages=messages)

    assert len(client.calls) == 2
    first = client.calls[0]["json"]
    second = client.calls[1]["json"]
    assert first["model"] == "x-ai/grok-4"
    assert first["response_format"] == {"type": "json_object"}
    assert "tools" not in first
    assert second == {
        "model": "x-ai/grok-4",
        "messages": messages,
        "temperature": 0.2,
    }
    assert result.model == "x-ai/grok-4"


@pytest.mark.asyncio
async def test_online_error_fails_closed_without_body_or_retry(monkeypatch):
    response_text = "upstream rejected request; credential=test-key"
    client = _Client([_Response(400, text=response_text)])
    _install_client(monkeypatch, client)
    provider = OpenRouterLlmProvider("test-key")

    with pytest.raises(RuntimeError, match=r"^OpenRouter web search HTTP 400$") as exc:
        await provider.chat(
            model="openrouter/auto:online",
            messages=[{"role": "user", "content": "news"}],
        )

    assert len(client.calls) == 1
    assert response_text not in str(exc.value)
    assert "test-key" not in str(exc.value)


@pytest.mark.asyncio
async def test_online_success_with_error_shape_fails_closed(monkeypatch):
    private_detail = "credential=test-key"
    client = _Client(
        [
            _Response(
                200,
                body={"error": {"message": private_detail}},
            )
        ]
    )
    _install_client(monkeypatch, client)
    provider = OpenRouterLlmProvider("test-key")

    with pytest.raises(
        RuntimeError,
        match=r"^Unexpected OpenRouter web search response shape$",
    ) as exc:
        await provider.chat(
            model="openrouter/auto:online",
            messages=[{"role": "user", "content": "news"}],
        )

    assert len(client.calls) == 1
    assert private_detail not in str(exc.value)
    assert "test-key" not in str(exc.value)


@pytest.mark.asyncio
async def test_online_marker_requires_base_model(monkeypatch):
    def unexpected_client(**_kwargs: Any) -> None:
        raise AssertionError("network client must not be constructed")

    monkeypatch.setattr("app.llm.openrouter.httpx.AsyncClient", unexpected_client)
    provider = OpenRouterLlmProvider("test-key")

    with pytest.raises(
        RuntimeError,
        match=r"^OpenRouter web search requires a base model$",
    ):
        await provider.chat(
            model=":online",
            messages=[{"role": "user", "content": "news"}],
        )
