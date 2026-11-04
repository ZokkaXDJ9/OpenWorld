import asyncio
import hashlib
import json
import secrets
import time
from typing import Literal

import httpx
from fastapi import HTTPException

from .models import ProviderSettings
from .provider import OpenAIProvider, ProviderError, decrypt_key, encrypt_key
from .schemas import ExtractionProviderInput, ProviderDiscoveryInput, ProviderInput, SetupInput


def connection(body: ProviderInput, stored: ProviderSettings) -> ProviderSettings:
    row = ProviderSettings(
        **body.model_dump(
            include=set(ProviderInput.model_fields) - {"api_key", "clear_key"},
        )
    )
    row.setup_state = {}
    row.encrypted_key = ""
    if body.api_key:
        row.encrypted_key = encrypt_key(body.api_key)
    elif not body.clear_key and body.base_url == stored.base_url:
        row.encrypted_key = stored.encrypted_key
    return row


async def discover(row: ProviderSettings) -> dict:
    request_headers = headers(row)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{row.base_url}/models", headers=request_headers)
    except httpx.RequestError as exc:
        raise HTTPException(
            502,
            "Keine Verbindung zum KI-Programm. Starte LM Studio bzw. Ollama und dessen "
            "lokalen Server. Prüfe anschließend die Serveradresse und versuche es erneut.",
        ) from exc
    if response.status_code in {401, 403}:
        raise HTTPException(
            422, "Zugriff verweigert. Prüfe deinen API-Schlüssel und seine Berechtigungen."
        )
    if response.status_code != 200:
        raise HTTPException(
            502,
            f"Der Server antwortet mit HTTP {response.status_code}. Prüfe die Adresse "
            "(normalerweise mit /v1 am Ende) und ob die OpenAI-kompatible Schnittstelle "
            "aktiviert ist.",
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(
            502, "Die Adresse liefert keine Modellliste. Prüfe die Serveradresse."
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise HTTPException(
            502,
            "Der Server liefert keine OpenAI-kompatible Modellliste. "
            "Nutze bei Bedarf die manuelle Modellauswahl.",
        )
    if any(
        not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip()
        for item in data["data"]
    ):
        raise HTTPException(502, "Die Modellliste enthält ungültige Einträge.")
    models = sorted({item["id"] for item in data["data"]})
    return {
        "models": models,
        "details": [
            {
                "id": item["id"],
                "name": item.get("name") or item["id"],
                "loaded": None,
                "context_window": positive(item.get("context_length"))
                or positive(item.get("max_model_len")),
                "reasoning_off": None,
            }
            for item in data["data"]
        ],
    }


async def test_connection(row: ProviderSettings) -> dict:
    text = ""
    try:
        async with asyncio.timeout(90):
            async for chunk in OpenAIProvider().stream(
                [{"role": "user", "content": "Antworte kurz mit: Verbindung funktioniert."}], row
            ):
                text += chunk
    except TimeoutError as exc:
        raise HTTPException(
            502,
            "Das Modell hat nicht rechtzeitig geantwortet. Warte, bis es fertig geladen ist, "
            "und versuche den Test erneut.",
        ) from exc
    if not text.strip():
        raise HTTPException(
            502,
            "Der Server ist erreichbar, aber das Modell hat keinen Antworttext geliefert. "
            "Lade ein Chatmodell oder prüfe unter Erweitert dessen Antwortbudget und Denkmodus.",
        )
    return {"reply": text.strip()[:200]}


def key(row: ProviderSettings) -> str:
    try:
        return decrypt_key(row.encrypted_key)
    except ProviderError as exc:
        raise HTTPException(422, str(exc)) from exc


def headers(row: ProviderSettings) -> dict:
    if not row.encrypted_key:
        return {}
    return {"Authorization": "Bearer " + key(row)}


async def document(
    client: httpx.AsyncClient,
    url: str,
    row: ProviderSettings,
    optional: bool = False,
    model: str | None = None,
) -> dict:
    try:
        response = (
            await client.post(url, headers=headers(row), json={"model": model})
            if model
            else await client.get(url, headers=headers(row))
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            502,
            "Das KI-Programm ist nicht erreichbar. Starte es und aktiviere seinen lokalen Server.",
        ) from exc
    if optional and response.status_code in {404, 405}:
        return {"metadata_unavailable": True}
    if response.status_code != 200:
        from .provider import response_error

        raise HTTPException(
            502,
            str(response_error(response.status_code, response.text[:2000])),
        )
    try:
        value = response.json()
    except ValueError as exc:
        raise HTTPException(
            502, "Die Serveradresse liefert keine lesbare Modellübersicht."
        ) from exc
    if not isinstance(value, dict):
        raise HTTPException(502, "Die Modellübersicht des Servers ist ungültig.")
    return value


def positive(value) -> int | None:
    return value if type(value) is int and value >= 1024 else None


async def inventory(row: ProviderSettings, kind: str) -> dict:
    if kind not in {"lmstudio", "ollama"}:
        result = await discover(row)
        return {"models": result["details"], "uncertainties": ["readiness", "reasoning_control"]}
    root = row.base_url.removesuffix("/v1")
    async with httpx.AsyncClient(timeout=3) as client:
        if kind == "lmstudio":
            data = await document(client, root + "/api/v1/models", row, optional=True)
            if data.get("metadata_unavailable"):
                result = await discover(row)
                return {
                    "models": result["details"],
                    "uncertainties": ["model_metadata", "readiness"],
                }
            if not isinstance(data.get("models"), list):
                raise HTTPException(
                    502,
                    "LM Studio liefert keine lesbare Modellübersicht. "
                    "Prüfe, ob der lokale Server aktiviert und LM Studio aktuell ist.",
                )
            choices = []
            for item in data["models"]:
                if not isinstance(item, dict) or item.get("type") != "llm":
                    continue
                key = item.get("key")
                if not isinstance(key, str) or not key:
                    raise HTTPException(502, "LM Studio liefert einen ungültigen Modellnamen.")
                capabilities = item.get("capabilities") or {}
                if not isinstance(capabilities, dict):
                    raise HTTPException(502, "Die Modellinformationen von LM Studio sind ungültig.")
                reasoning = capabilities.get("reasoning") or {}
                if not isinstance(reasoning, dict):
                    raise HTTPException(502, "Die Modellinformationen von LM Studio sind ungültig.")
                allowed = reasoning.get("allowed_options", [])
                if not isinstance(allowed, list) or any(not isinstance(v, str) for v in allowed):
                    raise HTTPException(502, "Die Denkmodus-Angaben von LM Studio sind ungültig.")
                off = "off" in allowed if reasoning else None
                instances = item.get("loaded_instances", [])
                if not isinstance(instances, list) or any(
                    not isinstance(instance, dict)
                    or not isinstance(instance.get("id"), str)
                    or not isinstance(instance.get("config", {}), dict)
                    for instance in instances
                ):
                    raise HTTPException(
                        502, "Die geladenen Modelle von LM Studio sind nicht lesbar."
                    )
                for instance in instances or [None]:
                    choices.append(
                        {
                            "id": instance["id"] if instance else key,
                            "name": item.get("display_name") or key,
                            "loaded": bool(instance),
                            "context_window": positive(
                                instance.get("config", {}).get("context_length")
                                if instance
                                else None
                            ),
                            "reasoning_off": off,
                        }
                    )
            return {"models": choices, "uncertainties": []}
        tags = await document(client, root + "/api/tags", row)
        running = await document(client, root + "/api/ps", row)
        if not isinstance(tags.get("models"), list) or not isinstance(running.get("models"), list):
            raise HTTPException(502, "Ollama liefert keine lesbare Modellübersicht.")
        active = {item.get("name"): item for item in running["models"] if isinstance(item, dict)}
        choices = []
        for item in tags["models"]:
            name = item.get("name") if isinstance(item, dict) else None
            if not isinstance(name, str) or not name:
                raise HTTPException(502, "Ollama liefert einen ungültigen Modellnamen.")
            loaded = active.get(name)
            choices.append(
                {
                    "id": name,
                    "name": name,
                    "loaded": loaded is not None,
                    "context_window": positive(loaded.get("context_length")) if loaded else None,
                    "reasoning_off": None,
                }
            )
        return {"models": choices, "uncertainties": ["reasoning_control"]}


async def local_servers() -> dict:
    async def probe(kind: str, port: int):
        row = connection(
            ProviderInput(base_url=f"http://127.0.0.1:{port}/v1", model="probe"),
            ProviderSettings(base_url="", encrypted_key=""),
        )
        try:
            found = await inventory(row, kind)
        except HTTPException as exc:
            return {
                "kind": kind,
                "base_url": row.base_url,
                "reachable": False,
                "models": [],
                "message": str(exc.detail),
            }
        return {"kind": kind, "base_url": row.base_url, "reachable": True, **found}

    return {"servers": await asyncio.gather(probe("lmstudio", 1234), probe("ollama", 11434))}


async def prepare(body: ProviderDiscoveryInput, stored: ProviderSettings):
    row = connection(body, stored)
    capabilities = {
        "kind": body.kind,
        "context_source": "expert",
        "structured_output": "unknown",
        "reasoning_control": "unknown",
        "uncertainties": ["structured_output"],
    }
    if body.automatic:
        try:
            listing = await inventory(row, body.kind)
        except HTTPException:
            if not body.manual_model:
                raise
            listing = {
                "models": [
                    {"id": row.model, "loaded": None, "context_window": None, "reasoning_off": None}
                ],
                "uncertainties": ["model_metadata_unavailable"],
            }
        selected = next((item for item in listing["models"] if item["id"] == body.model), None)
        if selected is None:
            raise HTTPException(
                422, "Das Modell ist nicht mehr verfügbar. Aktualisiere die Modellliste."
            )
        if body.kind == "lmstudio" and selected["loaded"] is False:
            raise HTTPException(
                422,
                "LM Studio ist erreichbar, aber das Modell ist noch nicht geladen. "
                "Lade es in LM Studio und prüfe anschließend erneut.",
            )
        context = selected["context_window"]
        if body.kind == "ollama":
            async with httpx.AsyncClient(timeout=5) as client:
                details = await document(
                    client,
                    row.base_url.removesuffix("/v1") + "/api/show",
                    row,
                    optional=True,
                    model=row.model,
                )
            advertised = details.get("capabilities", [])
            if not isinstance(advertised, list) or any(not isinstance(v, str) for v in advertised):
                raise HTTPException(502, "Die Modellfähigkeiten von Ollama sind nicht lesbar.")
            if "thinking" in advertised:
                selected["reasoning_off"] = True
        row.context_window = context or 4096
        row.max_output_tokens = min(2048, row.context_window // 4)
        row.temperature = 0.7
        row.reasoning_profile = {
            "lmstudio": "lmstudio",
            "ollama": "ollama",
            "openai": "openai",
        }.get(body.kind, "default")
        row.reasoning_mode = "off" if selected["reasoning_off"] else "default"
        capabilities["context_source"] = "server_metadata" if context else "conservative_default"
        capabilities["reasoning_control"] = (
            "off_advertised" if selected["reasoning_off"] else "unknown"
        )
        capabilities["native_reasoning_off"] = bool(selected["reasoning_off"])
        if not context:
            capabilities["uncertainties"].append("runtime_context")
        capabilities["uncertainties"].extend(listing["uncertainties"])
    row.setup_state = capabilities
    return row


def fingerprint(row: ProviderSettings) -> str:
    values = {
        name: getattr(row, name)
        for name in ProviderInput.model_fields
        if name not in {"api_key", "clear_key"}
    }
    values["key"] = hashlib.sha256(key(row).encode()).hexdigest() if row.encrypted_key else ""
    values["omit_temperature"] = bool((row.setup_state or {}).get("omit_temperature"))
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def public_connection(row: ProviderSettings) -> dict:
    return {
        **{
            name: getattr(row, name)
            for name in ProviderInput.model_fields
            if name not in {"api_key", "clear_key"}
        },
        "has_api_key": bool(row.encrypted_key),
    }


def memory_defaults(
    row: ProviderSettings, kind: Literal["lmstudio", "ollama", "openai", "compatible"]
) -> ExtractionProviderInput:
    profile = kind
    if kind in {"openai", "compatible"}:
        profile = "openai" if row.reasoning_profile == "openai" else "compatible"
    return ExtractionProviderInput(
        use_chat_connection=True,
        model="",
        context_window=row.context_window,
        max_output_tokens=min(4096, row.context_window // 2),
        provider_profile=profile,
        reasoning_mode=(
            "off"
            if (row.reasoning_mode == "off" or (row.setup_state or {}).get("native_reasoning_off"))
            and kind in {"lmstudio", "ollama"}
            else "default"
        ),
        structured_output="text",
        auto_retry=False,
    )


async def verify(body: ProviderDiscoveryInput, stored: ProviderSettings, checks: dict) -> dict:
    if not body.model.strip():
        raise HTTPException(422, "Wähle zuerst ein Chatmodell aus.")
    row = await prepare(body, stored)
    attempts = 0
    for attempt in range(2 if body.allow_compatibility_retry else 1):
        attempts += 1
        try:
            result = await test_connection(row)
            break
        except ProviderError as exc:
            parameter = exc.diagnostics.get("parameter")
            if (
                attempt == 0
                and body.allow_compatibility_retry
                and exc.code == "unsupported_parameter"
            ):
                state = dict(row.setup_state or {})
                if parameter == "temperature":
                    state["omit_temperature"] = True
                elif parameter in {"max_tokens", "max_completion_tokens"}:
                    row.reasoning_profile = "openai" if parameter == "max_tokens" else "default"
                    row.reasoning_mode = "default"
                else:
                    row.reasoning_mode = "default"
                    if row.reasoning_profile != "ollama":
                        row.reasoning_profile = "default"
                    state["reasoning_control"] = "unsupported"
                row.setup_state = state
                continue
            message = str(exc)
            if exc.code == "unsupported_parameter" and not body.allow_compatibility_retry:
                message += " Erlaube im Assistenten einen zweiten Verbindungstest, damit "
                message += "OpenWorld die Verbindung passend einstellen kann."
            raise HTTPException(502, message) from exc
    else:
        raise HTTPException(502, "Die KI konnte noch nicht erfolgreich geprüft werden.")
    token = secrets.token_urlsafe(24)
    now = time.time()
    for old in list(checks):
        if checks[old]["expires"] < now:
            del checks[old]
    while len(checks) >= 32:
        del checks[next(iter(checks))]
    checks[token] = {
        "fingerprint": fingerprint(row),
        "kind": body.kind,
        "capabilities": row.setup_state,
        "expires": now + 900,
    }
    return {
        **result,
        "settings": public_connection(row),
        "verification_token": token,
        "attempts": attempts,
    }


def verified_connection(
    body: SetupInput, stored: ProviderSettings, checks: dict
) -> ProviderSettings:
    proof = checks.get(body.verification_token)
    if not proof or proof["expires"] < time.time() or proof["kind"] != body.kind:
        raise HTTPException(
            422, "Bitte teste die Antwort erneut, bevor du die Einrichtung abschließt."
        )
    row = connection(body.provider, stored)
    row.setup_state = proof["capabilities"]
    if fingerprint(row) != proof["fingerprint"]:
        raise HTTPException(
            422, "Die Verbindung wurde seit dem Test verändert. Bitte erneut testen."
        )
    row.setup_state = {
        **row.setup_state,
        "fingerprint": fingerprint(row),
        "checked_at": time.time(),
    }
    return row


async def connection_status(row: ProviderSettings) -> dict:
    if not row.model:
        return {
            "state": "missing",
            "message": "Für Gespräche und Simulationen benötigst du "
            "eine KI-Verbindung. Wir helfen dir bei der Einrichtung.",
        }
    saved = row.setup_state or {}
    kind = saved.get("kind") or {"lmstudio": "lmstudio", "ollama": "ollama"}.get(
        row.reasoning_profile, "compatible"
    )
    try:
        listing = await inventory(row, kind)
    except HTTPException as exc:
        return {"state": "unavailable", "message": str(exc.detail)}
    selected = next((item for item in listing["models"] if item["id"] == row.model), None)
    if selected is None or (kind == "lmstudio" and selected["loaded"] is False):
        return {
            "state": "unavailable",
            "message": "Das gewählte Modell ist nicht einsatzbereit. "
            "Lade es in deinem KI-Programm oder richte eine andere KI ein.",
        }
    checked = saved.get("fingerprint") == fingerprint(row)
    return {
        "state": "ready" if checked else "unchecked",
        "message": (
            "Deine KI-Verbindung wurde erfolgreich getestet."
            if checked
            else "Deine bisherige Verbindung bleibt erhalten. "
            "Du kannst sie mit dem Assistenten prüfen."
        ),
        "checked_at": saved.get("checked_at"),
    }
