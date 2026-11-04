import asyncio
import json

import httpx
import pytest

from app.extraction_settings import resolve_extraction_settings
from app.models import ProviderSettings
from app.provider import OpenAIProvider


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )


def server(request):
    path = request.url.path
    if path == "/api/v1/models":
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "type": "llm",
                        "key": "chosen",
                        "display_name": "Testmodell",
                        "loaded_instances": [{"id": "chosen", "config": {"context_length": 8192}}],
                        "max_context_length": 262144,
                        "capabilities": {"reasoning": {"allowed_options": ["off", "on"]}},
                    },
                    {"type": "embedding", "key": "not-a-chat-model"},
                ]
            },
        )
    if path in {"/api/tags", "/api/ps"}:
        return httpx.Response(200, json={"models": [{"name": "chosen", "context_length": 8192}]})
    if path == "/api/show":
        return httpx.Response(200, json={"capabilities": ["completion", "thinking"]})
    if path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": "chosen", "context_length": 8192}]})
    body = json.loads(request.content)
    if path == "/api/chat":
        return httpx.Response(
            200,
            text=json.dumps(
                {
                    "message": {"content": "OK", "thinking": "PRIVATE THINKING"},
                    "done": True,
                }
            )
            + "\n",
        )
    if body.get("stream"):
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )
    return httpx.Response(200, json={"choices": [{"message": {"content": '{"events":[]}'}}]})


def complete(client, **values):
    body = {
        "base_url": "http://local/v1",
        "model": "chosen",
        "kind": "compatible",
        "automatic": True,
        **values,
    }
    response = client.post("/api/settings/provider/test", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    settings = {key: value for key, value in result["settings"].items() if key != "has_api_key"}
    saved = client.post(
        "/api/settings/setup",
        json={
            "provider": settings,
            "kind": body["kind"],
            "verification_token": result["verification_token"],
            "configure_memories": True,
        },
    )
    assert saved.status_code == 200, saved.text
    return result


def test_first_start_does_not_make_inference_calls(environment, monkeypatch):
    client, _, _ = environment
    transport(monkeypatch, lambda request: pytest.fail("No network needed without a connection"))
    assert client.get("/api/settings/provider/status").json()["state"] == "missing"


def test_concurrent_first_start_queries_share_one_settings_row(environment, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import Session

    from app.main import settings

    _, factory, _ = environment
    barrier = Barrier(2)
    original = Session.get

    def simultaneous_get(db, entity, identity, **kwargs):
        row = original(db, entity, identity, **kwargs)
        if entity is ProviderSettings and row is None:
            barrier.wait(timeout=10)
        return row

    monkeypatch.setattr(Session, "get", simultaneous_get)

    def first_start(_):
        with factory() as db:
            row = settings(db)
            return row.id, row.model

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(first_start, range(2))) == [(1, ""), (1, "")]


def test_discovery_is_read_only_and_queries_actual_models(environment, monkeypatch):
    client, _, _ = environment
    before = client.get("/api/settings/provider").json()
    transport(monkeypatch, server)
    result = client.post("/api/settings/provider/models", json={"base_url": "http://local/v1"})
    assert result.status_code == 200 and result.json()["models"] == ["chosen"]
    assert client.get("/api/settings/provider").json() == before


@pytest.mark.parametrize("kind", ["lmstudio", "ollama", "openai", "compatible"])
def test_automatic_setup_uses_metadata_not_theoretical_maxima(environment, monkeypatch, kind):
    client, factory, _ = environment
    captured = []

    def handler(request):
        captured.append(request)
        return server(request)

    transport(monkeypatch, handler)
    result = complete(client, kind=kind)
    assert result["settings"]["context_window"] == 8192
    assert client.get("/api/settings/provider/status").json()["state"] == "ready"
    memory = client.get("/api/settings/extraction").json()
    assert memory["use_chat_connection"] and memory["model"] == ""
    assert memory["provider_profile"] == kind and memory["context_window"] == 8192
    assert memory["structured_output"] == "text" and memory["auto_retry"] is False
    assert memory["reasoning_mode"] == ("off" if kind in {"lmstudio", "ollama"} else "default")
    inference = [r for r in captured if r.method == "POST" and r.url.path != "/api/show"]
    assert len(inference) == 1
    assert "response_format" not in json.loads(inference[0].content)
    assert result["reply"] == "OK" and "PRIVATE THINKING" not in result["reply"]
    with factory() as db:
        stored = db.get(ProviderSettings, 1)
        assert stored.setup_state["structured_output"] == "unknown"
        assert stored.setup_state["context_source"] == "server_metadata"


def test_unknown_capabilities_choose_conservative_defaults(environment, monkeypatch):
    client, factory, _ = environment

    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "chosen"}]})
        return server(request)

    transport(monkeypatch, handler)
    complete(client)
    with factory() as db:
        row = db.get(ProviderSettings, 1)
        assert row.context_window == 8192 and row.max_output_tokens == 2048
        assert "runtime_context" in row.setup_state["uncertainties"]
        assert row.reasoning_mode == "default"


def test_reachable_lmstudio_without_loaded_model_is_explained_without_inference(
    environment, monkeypatch
):
    client, _, _ = environment

    def handler(request):
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "type": "llm",
                        "key": "chosen",
                        "loaded_instances": [],
                        "capabilities": {},
                    }
                ]
            },
        )

    transport(monkeypatch, handler)
    result = client.post(
        "/api/settings/provider/test",
        json={
            "base_url": "http://local/v1",
            "model": "chosen",
            "kind": "lmstudio",
            "automatic": True,
        },
    )
    assert result.status_code == 422 and "noch nicht geladen" in result.json()["detail"]


def test_local_detection_checks_both_servers_without_downloading(environment, monkeypatch):
    client, _, _ = environment
    captured = []

    def handler(request):
        captured.append(request)
        assert request.method == "GET"
        return server(request)

    transport(monkeypatch, handler)
    result = client.get("/api/settings/provider/local").json()
    assert {s["kind"] for s in result["servers"]} == {"lmstudio", "ollama"}
    assert all(s["reachable"] for s in result["servers"])
    assert len(captured) == 3


@pytest.mark.parametrize(
    "status,data,message",
    [
        (401, {}, "API-Schlüssel"),
        (503, {}, "Server"),
        (200, {"unexpected": []}, "Modellliste"),
        (200, {"data": [{}]}, "ungültige Einträge"),
    ],
)
def test_discovery_errors_are_actionable(environment, monkeypatch, status, data, message):
    client, _, _ = environment
    transport(monkeypatch, lambda request: httpx.Response(status, json=data))
    result = client.post("/api/settings/provider/models", json={"base_url": "http://local/v1"})
    assert result.status_code >= 400 and message in result.json()["detail"]


def test_offline_server_gives_start_instructions(environment, monkeypatch):
    client, _, _ = environment

    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    transport(monkeypatch, handler)
    result = client.post("/api/settings/provider/models", json={"base_url": "http://local/v1"})
    assert result.status_code == 502 and "lokalen Server" in result.json()["detail"]


def test_saved_key_is_scoped_and_never_returned(environment, monkeypatch, tmp_path):
    import app.provider as module

    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    client, _, _ = environment
    client.put(
        "/api/settings/provider",
        json={
            "base_url": "http://original/v1",
            "model": "chosen",
            "api_key": "private-key",
        },
    )
    headers = []

    def handler(request):
        headers.append(request.headers.get("Authorization"))
        return server(request)

    transport(monkeypatch, handler)
    for url in ["http://original/v1", "http://other/v1"]:
        result = client.post("/api/settings/provider/models", json={"base_url": url})
        assert result.status_code == 200 and "private-key" not in result.text
    assert headers == ["Bearer private-key", None]
    client.put("/api/settings/provider", json={"base_url": "http://other/v1", "model": "chosen"})
    assert client.get("/api/settings/provider").json()["has_api_key"] is False


def test_unsupported_reasoning_has_only_an_explicitly_permitted_retry(environment, monkeypatch):
    client, _, _ = environment
    calls = []

    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            calls.append(body)
            if "reasoning_effort" in body:
                return httpx.Response(400, text="Unsupported reasoning_effort")
        return server(request)

    transport(monkeypatch, handler)
    body = {"base_url": "http://local/v1", "model": "chosen", "kind": "lmstudio", "automatic": True}
    first = client.post("/api/settings/provider/test", json=body)
    assert first.status_code == 502 and len(calls) == 1
    calls.clear()
    allowed = client.post(
        "/api/settings/provider/test", json={**body, "allow_compatibility_retry": True}
    )
    assert allowed.status_code == 200 and allowed.json()["attempts"] == 2 and len(calls) == 2
    assert allowed.json()["settings"]["reasoning_profile"] == "default"
    assert "reasoning_effort" not in calls[-1]


def test_authentication_failure_never_retries_even_with_permission(environment, monkeypatch):
    client, _, _ = environment
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401)

    transport(monkeypatch, handler)
    result = client.post(
        "/api/settings/provider/test",
        json={
            "base_url": "http://local/v1",
            "model": "chosen",
            "allow_compatibility_retry": True,
        },
    )
    assert result.status_code == 502 and "API-Schlüssel" in result.json()["detail"]
    assert len(calls) == 1


def test_no_structured_output_support_still_allows_validated_memory_extraction(
    environment, monkeypatch
):
    client, factory, _ = environment
    captured = []

    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            captured.append(body)
            assert "response_format" not in body
        return server(request)

    transport(monkeypatch, handler)
    complete(client)
    with factory() as db:
        runtime = resolve_extraction_settings(db)
    output = asyncio.run(
        OpenAIProvider().extract(
            [{"role": "user", "content": "Nur JSON ausgeben."}],
            runtime,
        )
    )
    assert json.loads(output.content) == {"events": []}
    assert len(captured) == 2  # One explicit setup test and one explicit extraction.


def test_finish_requires_exact_verified_connection_and_preserves_expert_settings(
    environment, monkeypatch
):
    client, _, _ = environment
    transport(monkeypatch, server)
    client.put("/api/settings/extraction", json={"model": "custom", "max_output_tokens": 8192})
    before = client.get("/api/settings/extraction").json()
    result = client.post(
        "/api/settings/provider/test",
        json={
            "base_url": "http://local/v1",
            "model": "chosen",
            "context_window": 32768,
            "max_output_tokens": 8192,
            "kind": "compatible",
            "automatic": False,
        },
    ).json()
    settings = {k: v for k, v in result["settings"].items() if k != "has_api_key"}
    body = {
        "provider": settings,
        "kind": "compatible",
        "configure_memories": False,
        "verification_token": result["verification_token"],
    }
    changed = client.post(
        "/api/settings/setup", json={**body, "provider": {**settings, "model": "other"}}
    )
    assert changed.status_code == 422
    assert client.post("/api/settings/setup", json=body).status_code == 200
    assert client.get("/api/settings/extraction").json() == before
    assert client.get("/api/settings/provider").json()["context_window"] == 32768
    assert "setup_state" not in client.get("/api/settings/provider").json()


@pytest.mark.parametrize("kind", ["lmstudio", "ollama"])
def test_malformed_capabilities_are_explained_without_inference(environment, monkeypatch, kind):
    client, _, _ = environment

    def malformed(request):
        response = server(request)
        if request.url.path == "/api/v1/models":
            data = response.json()
            data["models"][0]["capabilities"]["reasoning"]["allowed_options"] = 7
            return httpx.Response(200, json=data)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": 7})
        assert request.url.path in {"/api/tags", "/api/ps"}
        return response

    transport(monkeypatch, malformed)
    result = client.post(
        "/api/settings/provider/test",
        json={
            "base_url": "http://local/v1",
            "model": "chosen",
            "kind": kind,
            "automatic": True,
        },
    )
    assert result.status_code == 502
    assert any(word in result.json()["detail"] for word in ["ungültig", "nicht lesbar"])


@pytest.mark.parametrize(
    "profile,unsupported",
    [
        ("default", "max_tokens"),
        ("openai", "max_completion_tokens"),
    ],
)
def test_budget_compatibility_is_verified_and_used_for_memories(
    environment, monkeypatch, profile, unsupported
):
    client, factory, _ = environment
    requests = []

    def handler(request):
        if request.method == "POST":
            payload = json.loads(request.content)
            requests.append(payload)
            if unsupported in payload:
                return httpx.Response(400, text=f"Unsupported parameter: {unsupported}")
        return server(request)

    transport(monkeypatch, handler)
    result = complete(
        client, automatic=False, reasoning_profile=profile, allow_compatibility_retry=True
    )
    assert result["attempts"] == 2 and len(requests) == 2
    assert unsupported not in requests[-1]
    memory = client.get("/api/settings/extraction").json()
    assert memory["provider_profile"] == ("openai" if unsupported == "max_tokens" else "compatible")
    with factory() as db:
        runtime = resolve_extraction_settings(db)
    output = asyncio.run(
        OpenAIProvider().extract([{"role": "user", "content": "Nur JSON."}], runtime)
    )
    assert json.loads(output.content) == {"events": []}


@pytest.mark.parametrize("kind", ["compatible", "ollama"])
def test_unsupported_temperature_stays_compatible_after_unrelated_expert_edit(
    environment, monkeypatch, kind
):
    client, factory, _ = environment

    def handler(request):
        if request.url.path in {"/api/chat", "/v1/chat/completions"}:
            payload = json.loads(request.content)
            if "temperature" in payload.get("options", payload):
                return httpx.Response(400, text="Unsupported temperature")
        return server(request)

    transport(monkeypatch, handler)
    result = complete(client, kind=kind, allow_compatibility_retry=True)
    assert result["attempts"] == 2
    settings = {k: v for k, v in result["settings"].items() if k != "has_api_key"}
    response = client.put("/api/settings/provider", json={**settings, "max_output_tokens": 512})
    assert response.status_code == 200
    with factory() as db:
        row = db.get(ProviderSettings, 1)
        assert row is not None

        async def answer():
            return "".join(
                [
                    piece
                    async for piece in OpenAIProvider().stream(
                        [{"role": "user", "content": "Hallo"}], row
                    )
                ]
            )

        assert asyncio.run(answer()) == "OK"
        runtime = resolve_extraction_settings(db)
    asyncio.run(OpenAIProvider().extract([{"role": "user", "content": "Nur JSON."}], runtime))


def test_unreadable_saved_key_offers_setup_instead_of_server_error(environment):
    client, factory, _ = environment
    with factory() as db:
        db.add(ProviderSettings(id=1, model="chosen", encrypted_key="broken"))
        db.commit()
    response = client.get("/api/settings/provider/status")
    assert response.status_code == 200 and response.json()["state"] == "unavailable"
    assert "erneut ein" in response.json()["message"]


@pytest.mark.parametrize("metadata_context", [8192, None])
def test_automatic_memory_budget_fits_its_real_prompt_and_binds_the_recipient(
    eldoria, monkeypatch, metadata_context
):
    from test_events import extract, extracted_event, queue_source

    from app.event_schemas import ExtractionOutput
    from app.extraction import extraction_context
    from app.models import Message

    e = eldoria

    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "chosen",
                            "context_length": metadata_context,
                        }
                    ]
                },
            )
        return server(request)

    transport(monkeypatch, handler)
    complete(e["client"])
    message_id, job_id = queue_source(e)
    with e["factory"]() as db:
        runtime = resolve_extraction_settings(db)
        messages = extraction_context(db, db.get(Message, message_id), runtime)
    content = messages[0]["content"]
    schema = json.loads(content[content.index('{"$defs":') :])
    assert (
        schema["$defs"]["KnowledgeOperation"]["properties"]["character_id"]["const"]
        == e["lumia"]["id"]
    )
    assert (
        "const"
        not in ExtractionOutput.model_json_schema()["$defs"]["KnowledgeOperation"]["properties"][
            "character_id"
        ]
    )
    assert runtime.context_window == 8192 and runtime.max_output_tokens == 2048
    wrong = extracted_event(e)
    wrong["operations"][0]["character_id"] = e["power"]["id"]
    result = extract(e, job_id, {"events": [wrong]})
    assert result["status"] == "failed"
    assert "Gesprächsempfängers" in result["error"]


def test_small_runtime_window_has_plain_memory_warning(environment, monkeypatch):
    client, _, _ = environment
    transport(monkeypatch, server)
    result = complete(client, automatic=False, context_window=4096, max_output_tokens=1024)
    assert result["reply"] == "OK"
    assert any("automatische Erinnerungen" in warning for warning in result["warnings"])
