import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import httpx
from cryptography.fernet import Fernet, InvalidToken

from .db import DATA_DIR
from .event_schemas import ExtractionOutput
from .models import ProviderSettings

if TYPE_CHECKING:
    from .extraction_settings import ExtractionRuntime


class ProviderError(Exception):
    def __init__(self, message: str, *, code: str = "provider", diagnostics: dict | None = None):
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics or {}


def response_error(status: int, detail: str = "") -> ProviderError:
    lowered = detail.lower()
    diagnostics = {"http_status": status}
    if status in {401, 403}:
        return ProviderError(
            "Der API-Schlüssel wurde abgelehnt. Prüfe Schlüssel und Modellberechtigung.",
            code="authentication",
            diagnostics=diagnostics,
        )
    if status == 429:
        return ProviderError(
            "Der Anbieter begrenzt die Anfragen oder das Guthaben reicht nicht aus. "
            "Prüfe dein API-Guthaben oder versuche es später erneut.",
            code="rate_limit",
            diagnostics=diagnostics,
        )
    if status in {400, 422}:
        for parameter in (
            "reasoning_effort",
            "chat_template_kwargs",
            "think",
            "temperature",
            "max_completion_tokens",
            "max_tokens",
        ):
            if parameter in lowered and any(
                word in lowered
                for word in (
                    "unsupported",
                    "not support",
                    "unknown",
                    "unrecognized",
                    "not allowed",
                )
            ):
                return ProviderError(
                    "Das Modell unterstützt eine angeforderte Einstellung nicht.",
                    code="unsupported_parameter",
                    diagnostics={**diagnostics, "parameter": parameter},
                )
    if status == 404 or any(
        word in lowered for word in ("not loaded", "no model", "model not found")
    ):
        return ProviderError(
            "Das ausgewählte Modell ist nicht verfügbar. Lade es im KI-Programm und "
            "wähle es in der Einrichtung erneut aus.",
            code="model_unavailable",
            diagnostics=diagnostics,
        )
    return ProviderError(
        "Der KI-Server konnte die Anfrage nicht ausführen. Prüfe im KI-Programm, "
        "ob das Chatmodell geladen und der Server aktiviert ist.",
        code="server",
        diagnostics=diagnostics,
    )


@dataclass(frozen=True)
class ExtractionResponse:
    content: str
    diagnostics: dict


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


def decrypt_key(value: str) -> str:
    try:
        return cipher().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise ProviderError(
            "Der gespeicherte API-Schlüssel kann nicht gelesen werden. "
            "Öffne die KI-Einrichtung und gib den Schlüssel erneut ein.",
            code="stored_key",
        ) from exc


class OpenAIProvider:
    async def extract(
        self, messages: list[dict[str, str]], settings: "ExtractionRuntime"
    ) -> ExtractionResponse:
        headers = {"Content-Type": "application/json"}
        if settings.encrypted_key:
            headers["Authorization"] = "Bearer " + decrypt_key(settings.encrypted_key)
        profile = settings.provider_profile
        mode = settings.reasoning_mode
        schema = ExtractionOutput.model_json_schema()
        payload: dict = {
            "model": settings.model,
            "messages": messages,
            "stream": False,
            "max_tokens": settings.max_output_tokens,
            "temperature": settings.temperature,
        }
        format_type = settings.structured_output
        if format_type == "auto":
            format_type = "json_object" if profile == "compatible" else "json_schema"
        if format_type == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "events", "schema": schema},
            }
        elif format_type == "json_object":
            payload["response_format"] = {"type": "json_object"}
        if profile == "openai":
            payload["max_completion_tokens"] = payload.pop("max_tokens")
            if mode != "default":
                payload["reasoning_effort"] = "none" if mode == "off" else mode
                payload.pop("temperature")
        elif profile == "llama_cpp" and mode != "default":
            payload["chat_template_kwargs"] = {"enable_thinking": mode != "off"}
        url = f"{settings.base_url}/chat/completions"
        if profile == "lmstudio":
            url = settings.base_url.removesuffix("/v1") + "/api/v1/chat"
            payload: dict = {
                "model": settings.model,
                "system_prompt": "\n\n".join(
                    m["content"] for m in messages if m["role"] == "system"
                ),
                "input": "\n\n".join(m["content"] for m in messages if m["role"] != "system"),
                "stream": False,
                "store": False,
                "integrations": [],
                "max_output_tokens": settings.max_output_tokens,
                "temperature": settings.temperature,
                "context_length": settings.context_window,
            }
            if mode != "default":
                payload["reasoning"] = mode
            format_type = "prompt_json"
        elif profile == "ollama":
            url = settings.base_url.removesuffix("/v1") + "/api/chat"
            payload = {
                "model": settings.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_predict": settings.max_output_tokens,
                    "num_ctx": settings.context_window,
                    "temperature": settings.temperature,
                },
            }
            if mode != "default":
                payload["think"] = False if mode == "off" else True if mode == "on" else mode
            if format_type != "text":
                payload["format"] = schema if format_type == "json_schema" else "json"
        if settings.omit_temperature:
            if profile == "ollama":
                payload["options"].pop("temperature", None)
            else:
                payload.pop("temperature", None)
        diagnostics = {
            "model": settings.model,
            "profile": profile,
            "reasoning_mode": mode,
            "format": format_type,
            "max_output_tokens": settings.max_output_tokens,
            "http_requests": 0,
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(settings.timeout_seconds, connect=15)
            ) as client:
                diagnostics["http_requests"] += 1
                response = await client.post(url, headers=headers, json=payload)
                if (
                    "response_format" in payload
                    and settings.structured_output == "auto"
                    and response.status_code in {400, 422}
                    and any(
                        marker in response.text.casefold()
                        for marker in (
                            "response_format",
                            "json_object",
                            "json_schema",
                            "structured output",
                        )
                    )
                ):
                    payload.pop("response_format")
                    diagnostics["format"] = "text_fallback"
                    diagnostics["format_fallback_status"] = response.status_code
                    diagnostics["http_requests"] += 1
                    response = await client.post(url, headers=headers, json=payload)
                if response.status_code != 200:
                    raise ProviderError(
                        f"Ereignisextraktion: Anbieter antwortet mit HTTP {response.status_code}. "
                        "Verbindung, Modell und Anbieterprofil prüfen.",
                        diagnostics={**diagnostics, "http_status": response.status_code},
                    )
                try:
                    body = response.json()
                    if profile == "lmstudio":
                        content = "\n".join(
                            item["content"] for item in body["output"] if item["type"] == "message"
                        )
                        usage = body.get("stats") or {}
                        finish = body.get("stop_reason")
                        counts = {
                            "prompt_tokens": usage.get("input_tokens"),
                            "completion_tokens": usage.get("total_output_tokens"),
                            "reasoning_tokens": usage.get("reasoning_output_tokens"),
                        }
                    elif profile == "ollama":
                        content = body["message"]["content"]
                        finish = body.get("done_reason")
                        counts = {
                            "prompt_tokens": body.get("prompt_eval_count"),
                            "completion_tokens": body.get("eval_count"),
                        }
                    else:
                        choice = body["choices"][0]
                        content = choice["message"]["content"]
                        finish = choice.get("finish_reason")
                        usage = body.get("usage") or {}
                        counts = {
                            "prompt_tokens": usage.get("prompt_tokens"),
                            "completion_tokens": usage.get("completion_tokens"),
                            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get(
                                "reasoning_tokens"
                            ),
                        }
                    diagnostics.update(
                        {
                            key: value
                            for key, value in counts.items()
                            if isinstance(value, int) and not isinstance(value, bool)
                        }
                    )
                    diagnostics["finish_reason"] = finish if isinstance(finish, str) else None
                    if diagnostics.get("completion_tokens", -1) >= settings.max_output_tokens:
                        diagnostics["token_limit_reached"] = True
                    if mode == "off" and diagnostics.get("reasoning_tokens", 0) > 0:
                        diagnostics["warning"] = "Reasoning-Abschaltung wurde nicht eingehalten."
                except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
                    raise ProviderError(
                        "Ungültiges Antwortformat der Ereignisextraktion.",
                        code="invalid_output",
                        diagnostics=diagnostics,
                    ) from exc
                if finish in {"length", "max_tokens"}:
                    raise ProviderError(
                        "Extraktionsausgabe am Tokenlimit abgeschnitten.",
                        code="length",
                        diagnostics=diagnostics,
                    )
                if not isinstance(content, str) or not content.strip():
                    raise ProviderError(
                        "Ereignisextraktion hat keinen JSON-Text geliefert. "
                        "Reasoning-Profil und Ausgabebudget prüfen.",
                        code="empty",
                        diagnostics=diagnostics,
                    )
                return ExtractionResponse(content, diagnostics)
        except httpx.HTTPError as exc:
            raise ProviderError(
                "Ereignisextraktion: Anbieter nicht erreichbar/Zeitlimit.",
                diagnostics=diagnostics,
            ) from exc

    async def stream(
        self, messages: list[dict[str, str]], settings: ProviderSettings
    ) -> AsyncIterator[str]:
        headers = {"Content-Type": "application/json"}
        if settings.encrypted_key:
            headers["Authorization"] = "Bearer " + decrypt_key(settings.encrypted_key)
        payload = {
            "model": settings.model,
            "messages": messages,
            "stream": True,
            "max_tokens": settings.max_output_tokens,
            "temperature": settings.temperature,
        }
        if settings.reasoning_profile == "openai":
            payload["max_completion_tokens"] = payload.pop("max_tokens")
        if settings.reasoning_mode not in {None, "default"}:
            if settings.reasoning_profile in {"openai", "lmstudio"}:
                payload["reasoning_effort"] = (
                    "none" if settings.reasoning_mode == "off" else settings.reasoning_mode
                )
                if settings.reasoning_profile == "openai":
                    payload.pop("temperature")
            elif settings.reasoning_profile == "llama_cpp":
                payload["chat_template_kwargs"] = {
                    "enable_thinking": settings.reasoning_mode != "off"
                }
        url = f"{settings.base_url}/chat/completions"
        native = settings.reasoning_profile == "ollama"
        if native:
            url = settings.base_url.removesuffix("/v1") + "/api/chat"
            payload = {
                "model": settings.model,
                "messages": messages,
                "stream": True,
                "options": {
                    "num_ctx": settings.context_window,
                    "num_predict": settings.max_output_tokens,
                    "temperature": settings.temperature,
                },
            }
            if settings.reasoning_mode != "default":
                payload["think"] = settings.reasoning_mode == "on"
        if (settings.setup_state or {}).get("omit_temperature"):
            if native:
                payload["options"].pop("temperature", None)
            else:
                payload.pop("temperature", None)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        await response.aread()
                        raise response_error(response.status_code, response.text[:2000])
                    finished = False
                    async for line in response.aiter_lines():
                        if native:
                            if not line.strip():
                                continue
                            try:
                                packet = json.loads(line)
                                if packet.get("error"):
                                    raise response_error(400, str(packet["error"]))
                                content = packet.get("message", {}).get("content", "")
                                if not isinstance(content, str):
                                    raise ProviderError("Die KI liefert ungültigen Antworttext.")
                                if content:
                                    yield content
                                if packet.get("done") is True:
                                    finished = True
                            except (ValueError, AttributeError, TypeError) as exc:
                                raise ProviderError(
                                    "Die Antwort von Ollama ist unvollständig."
                                ) from exc
                            continue
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
                        raise ProviderError(
                            "Die Verbindung wurde während der Antwort unterbrochen. "
                            "Prüfe den KI-Server und versuche es erneut.",
                            code="connection",
                        )
        except httpx.HTTPError as exc:
            raise ProviderError(
                "Der KI-Server ist nicht erreichbar oder antwortet nicht rechtzeitig. "
                "Starte dein KI-Programm und aktiviere dessen Server.",
                code="connection",
            ) from exc
