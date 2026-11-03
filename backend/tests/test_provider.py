import asyncio
import json

import httpx
import pytest

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


def test_real_openai_adapter_request_and_stream(monkeypatch):
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
