import asyncio
import json

import httpx
import pytest

from app.extraction_settings import ExtractionRuntime
from app.models import ProviderSettings
from app.provider import OpenAIProvider, ProviderError


def test_keys_encrypted_and_never_returned(environment, tmp_path, monkeypatch):
    import app.provider as module

    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    client, factory, _ = environment
    key = "test-secret-key"
    response = client.put(
        "/api/settings/provider",
        json={
            "base_url": "http://localhost:1234/v1",
            "model": "local",
            "api_key": key,
            "context_window": 262144,
        },
    )
    assert response.status_code == 200
    assert key not in response.text and "encrypted_key" not in response.text
    assert response.json()["has_api_key"] is True
    with factory() as db:
        settings = db.get(ProviderSettings, 1)
        assert key not in settings.encrypted_key
        assert module.cipher().decrypt(settings.encrypted_key.encode()).decode() == key
    response = client.put(
        "/api/settings/provider",
        json={
            "base_url": "http://localhost:1234/v1",
            "model": "local",
        },
    )
    assert response.json()["has_api_key"] is True
    response = client.put(
        "/api/settings/provider",
        json={
            "base_url": "http://localhost:1234/v1",
            "model": "local",
            "clear_key": True,
        },
    )
    assert response.json()["has_api_key"] is False


@pytest.mark.parametrize("url", ["file:///secret", "http://user:pass@localhost/v1", "invalid"])
def test_invalid_provider_url(environment, url):
    client, _, _ = environment
    assert (
        client.put(
            "/api/settings/provider",
            json={
                "base_url": url,
                "model": "test",
            },
        ).status_code
        == 422
    )


@pytest.mark.parametrize("profile", ["default", "lmstudio", "llama_cpp", "openai"])
def test_real_openai_adapter_request_and_stream(monkeypatch, profile):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"content":"Hallo "}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"Welt"},"finish_reason":"stop"}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(handler),
        ),
    )
    settings = ProviderSettings(
        base_url="http://localhost:11434/v1",
        model="llama3.1",
        encrypted_key="",
        context_window=131072,
        max_output_tokens=2048,
        temperature=0.7,
        reasoning_profile=profile,
        reasoning_mode="default" if profile == "default" else "off",
    )

    async def collect():
        return "".join(
            [
                part
                async for part in OpenAIProvider().stream(
                    [{"role": "user", "content": "Hallo"}],
                    settings,
                )
            ]
        )

    assert asyncio.run(collect()) == "Hallo Welt"
    assert str(captured[0].url) == "http://localhost:11434/v1/chat/completions"
    assert json.loads(captured[0].content)["stream"] is True
    assert json.loads(captured[0].content)["model"] == "llama3.1"
    payload = json.loads(captured[0].content)
    if profile in {"lmstudio", "openai"}:
        assert payload["reasoning_effort"] == "none"
    elif profile == "llama_cpp":
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    else:
        assert "reasoning_effort" not in payload and "chat_template_kwargs" not in payload
    if profile == "openai":
        assert payload["max_completion_tokens"] == 2048 and "max_tokens" not in payload


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401),
        httpx.Response(200, text="data: invalid-json\n\n"),
        httpx.Response(200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'),
    ],
)
def test_adapter_rejects_errors_and_unfinished_stream(monkeypatch, response):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(lambda request: response),
        ),
    )
    settings = ProviderSettings(
        base_url="http://localhost/v1",
        model="test",
        encrypted_key="",
        max_output_tokens=2048,
        temperature=0.7,
    )

    async def collect():
        return [part async for part in OpenAIProvider().stream([], settings)]

    with pytest.raises(ProviderError):
        asyncio.run(collect())


def test_structured_extraction_falls_back_only_for_unsupported_json_format(monkeypatch):
    captured = []

    def handler(request):
        body = json.loads(request.content)
        captured.append(body)
        if "response_format" in body:
            return httpx.Response(400, text="response_format is not supported")
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"events":[]}'}}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    settings = ExtractionRuntime(
        base_url="http://localhost/v1",
        model="test",
        encrypted_key="",
        max_output_tokens=2048,
        context_window=16384,
        temperature=0.7,
    )
    result = asyncio.run(OpenAIProvider().extract([], settings))
    assert result.content == '{"events":[]}'
    assert result.diagnostics["http_requests"] == 2
    assert len(captured) == 2
    assert captured[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in captured[1]


def test_extraction_does_not_retry_authentication_failure(monkeypatch):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(401)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    settings = ExtractionRuntime(
        base_url="http://localhost/v1",
        model="test",
        encrypted_key="",
        max_output_tokens=2048,
        context_window=16384,
    )
    with pytest.raises(ProviderError, match="HTTP 401"):
        asyncio.run(OpenAIProvider().extract([], settings))
    assert len(captured) == 1


@pytest.mark.parametrize(
    ("profile", "path", "response"),
    [
        (
            "lmstudio",
            "/api/v1/chat",
            {
                "output": [{"type": "message", "content": '{"events":[]}'}],
                "stats": {"total_output_tokens": 5, "reasoning_output_tokens": 0},
            },
        ),
        ("ollama", "/api/chat", {"message": {"content": '{"events":[]}'}, "done_reason": "stop"}),
        (
            "llama_cpp",
            "/v1/chat/completions",
            {"choices": [{"message": {"content": '{"events":[]}'}, "finish_reason": "stop"}]},
        ),
        (
            "openai",
            "/v1/chat/completions",
            {"choices": [{"message": {"content": '{"events":[]}'}, "finish_reason": "stop"}]},
        ),
    ],
)
def test_extraction_provider_profiles(monkeypatch, profile, path, response):
    captured = []

    def handler(request):
        assert request.url.path == path
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=response)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handler))
    )
    settings = ExtractionRuntime(
        base_url="http://localhost/v1",
        model="local",
        encrypted_key="",
        context_window=16384,
        max_output_tokens=8192,
        provider_profile=profile,
        reasoning_mode="off",
    )
    result = asyncio.run(
        OpenAIProvider().extract(
            [{"role": "system", "content": "schema"}, {"role": "user", "content": "source"}],
            settings,
        )
    )
    assert result.content == '{"events":[]}'
    payload = captured[0]
    if profile == "lmstudio":
        assert payload["reasoning"] == "off" and payload["store"] is False
        assert payload["integrations"] == [] and payload["input"] == "source"
        assert payload["max_output_tokens"] == 8192
        assert result.diagnostics["reasoning_tokens"] == 0
    elif profile == "ollama":
        assert payload["think"] is False and payload["options"]["num_predict"] == 8192
    elif profile == "llama_cpp":
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        assert payload["max_tokens"] == 8192
    else:
        assert payload["reasoning_effort"] == "none"
        assert payload["max_completion_tokens"] == 8192 and "max_tokens" not in payload


def test_truncated_reasoning_reports_finish_and_usage(monkeypatch):
    original = httpx.AsyncClient
    response = {
        "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
        "usage": {
            "completion_tokens": 2048,
            "completion_tokens_details": {"reasoning_tokens": 1992},
        },
    }
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            **kw, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))
        ),
    )
    runtime = ExtractionRuntime(
        base_url="http://localhost/v1",
        model="local",
        encrypted_key="",
        context_window=16384,
        max_output_tokens=2048,
    )
    with pytest.raises(ProviderError) as caught:
        asyncio.run(OpenAIProvider().extract([], runtime))
    assert caught.value.code == "length"
    assert caught.value.diagnostics["reasoning_tokens"] == 1992
    assert caught.value.diagnostics["finish_reason"] == "length"
