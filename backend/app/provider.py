import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx
from cryptography.fernet import Fernet

from .db import DATA_DIR
from .models import ProviderSettings


class ProviderError(Exception):
    pass


class LLMProvider(Protocol):
    def stream(
        self, messages: list[dict[str, str]], settings: ProviderSettings
    ) -> AsyncIterator[str]: ...


def cipher() -> Fernet:
    path = DATA_DIR / "provider.key"
    if not path.exists():
        try:
            with path.open("xb") as file:
                file.write(Fernet.generate_key())
            path.chmod(0o600)
        except FileExistsError:
            pass
    return Fernet(path.read_bytes())


def encrypt_key(key: str) -> str:
    return cipher().encrypt(key.encode()).decode()


class OpenAIProvider:
    async def stream(
        self, messages: list[dict[str, str]], settings: ProviderSettings
    ) -> AsyncIterator[str]:
        headers = {"Content-Type": "application/json"}
        if settings.encrypted_key:
            headers["Authorization"] = (
                "Bearer " + cipher().decrypt(settings.encrypted_key.encode()).decode()
            )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
                async with client.stream(
                    "POST",
                    f"{settings.base_url}/chat/completions",
                    headers=headers,
                    json={
                        "model": settings.model,
                        "messages": messages,
                        "stream": True,
                        "max_tokens": settings.max_output_tokens,
                        "temperature": settings.temperature,
                    },
                ) as response:
                    if response.status_code != 200:
                        raise ProviderError(
                            f"KI-Anbieter antwortet mit HTTP {response.status_code}. "
                            "Bitte URL, Modell und Zugangsdaten prüfen."
                        )
                    finished = False
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            finished = True
                            break
                        try:
                            payload = json.loads(data)
                            if payload.get("error"):
                                raise ProviderError("KI-Anbieter meldet einen Streaming-Fehler.")
                            choices = payload.get("choices", [])
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {}).get("content")
                            if delta is not None:
                                if not isinstance(delta, str):
                                    raise ProviderError("KI-Anbieter liefert ungültigen Text.")
                                yield delta
                            if choices[0].get("finish_reason") is not None:
                                finished = True
                        except (ValueError, AttributeError, TypeError, IndexError) as exc:
                            raise ProviderError(
                                "Ungültiges Streaming-Format des KI-Anbieters."
                            ) from exc
                    if not finished:
                        raise ProviderError("KI-Stream wurde ohne Abschluss unterbrochen.")
        except httpx.HTTPError as exc:
            raise ProviderError(
                "KI-Anbieter nicht erreichbar oder Zeitlimit überschritten."
            ) from exc
