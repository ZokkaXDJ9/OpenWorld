import asyncio
import json

import pytest
from sqlalchemy import select
from test_events import act, extract, extracted_event, memory, queue_source, state

from app.extraction import enqueue_turn, run_job
from app.models import Conversation, ExtractionJob, ExtractionJobSource, Knowledge, Message
from app.provider import ExtractionResponse, ProviderError


def test_memory_context_has_exactly_one_leading_system_message(eldoria):
    import tiktoken

    from app.context import build_context

    e = eldoria
    e["client"].post(
        "/api" + e["path"] + "/knowledge",
        json={
            "kind": "received",
            "character_id": e["lumia"]["id"],
            "content": "Power hat einen Kristall.",
            "confidence": 50,
        },
    )
    with e["factory"]() as db:
        conversation = db.get(Conversation, e["conversation"]["id"])
        db.add(
            Message(
                conversation_id=conversation.id,
                sequence=1,
                role="user",
                content="Was weißt du über Power?",
            )
        )
        db.commit()
        messages, count = build_context(db, conversation, 16384, 2048)
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "Wissensdaten" in messages[0]["content"]
    assert "Power hat einen Kristall." in messages[0]["content"]
    assert "Ich besitze den geheimen Kristall." not in json.dumps(messages)
    encoding = tiktoken.get_encoding("cl100k_base")
    assert count == sum(len(encoding.encode(m["content"])) + 8 for m in messages)
    assert count + 2048 + 256 <= 16384


def run(e, job_id, provider):
    with e["factory"]() as db:
        asyncio.run(run_job(db, job_id, provider))
    return next(
        row
        for row in e["client"].get("/api" + e["path"] + "/extraction-jobs").json()
        if row["id"] == job_id
    )


def test_independent_settings_and_secret_preservation(eldoria, tmp_path, monkeypatch):
    import app.provider as module
    from app.extraction_settings import resolve_extraction_settings

    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    e = eldoria
    client = e["client"]
    before = client.get("/api/settings/provider").json()
    result = client.put(
        "/api/settings/extraction",
        json={
            "use_chat_connection": False,
            "base_url": "http://localhost:1234/v1",
            "model": "extractor",
            "api_key": "test-extraction-secret",
            "provider_profile": "lmstudio",
            "reasoning_mode": "off",
            "max_output_tokens": 8192,
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["has_api_key"] is True
    assert "test-extraction-secret" not in result.text and "encrypted_key" not in result.text
    assert client.get("/api/settings/provider").json() == before
    with e["factory"]() as db:
        runtime = resolve_extraction_settings(db)
        assert runtime.model == "extractor" and runtime.max_output_tokens == 8192
        assert module.cipher().decrypt(runtime.encrypted_key.encode()).decode() == (
            "test-extraction-secret"
        )
    result = client.put(
        "/api/settings/extraction",
        json={
            "use_chat_connection": True,
            "model": "",
            "auto_retry": False,
        },
    )
    assert result.json()["has_api_key"] is True
    with e["factory"]() as db:
        runtime = resolve_extraction_settings(db)
        assert runtime.model == before["model"] and runtime.base_url == before["base_url"]
        assert runtime.encrypted_key == "" and runtime.max_output_tokens == 4096


@pytest.mark.parametrize(
    "body",
    [
        {"max_output_tokens": 16384, "context_window": 16384},
        {"provider_profile": "compatible", "reasoning_mode": "off"},
        {"provider_profile": "llama_cpp", "reasoning_mode": "low"},
        {"provider_profile": "lmstudio", "structured_output": "json_schema"},
    ],
)
def test_invalid_extraction_configuration_rejected(environment, body):
    client, _, _ = environment
    assert client.put("/api/settings/extraction", json=body).status_code == 422


@pytest.mark.parametrize("failure_kind", ["explicit", "native_inferred"])
def test_retry_changes_budget_reasoning_and_prompt_and_applies_once(eldoria, failure_kind):
    e = eldoria
    e["client"].put(
        "/api/settings/extraction",
        json={
            "provider_profile": "llama_cpp",
            "max_output_tokens": 2048,
        },
    )
    _, job_id = queue_source(e)

    class Provider:
        calls = []

        async def extract(self, messages, settings):
            self.calls.append((messages, settings))
            if len(self.calls) == 1:
                if failure_kind == "native_inferred":
                    return ExtractionResponse(
                        '{"events":[',
                        {
                            "reasoning_tokens": 1992,
                            "token_limit_reached": True,
                            "completion_tokens": 2048,
                            "http_requests": 1,
                        },
                    )
                raise ProviderError(
                    "Abgeschnitten",
                    code="length",
                    diagnostics={
                        "finish_reason": "length",
                        "reasoning_tokens": 1992,
                        "http_requests": 1,
                    },
                )
            return json.dumps({"events": [extracted_event(e)]})

    provider = Provider()
    result = run(e, job_id, provider)
    assert result["status"] == "complete" and result["attempts"] == 2
    assert len(provider.calls) == 2
    assert provider.calls[0][1].max_output_tokens == 2048
    assert provider.calls[1][1].max_output_tokens == 4096
    assert provider.calls[1][1].reasoning_mode == "off"
    assert provider.calls[0][0] != provider.calls[1][0]
    assert len(result["event_ids"]) == 1
    assert result["diagnostics"][0]["reasoning_tokens"] == 1992
    assert result["diagnostics"][1]["trigger"] == "automatic"
    with e["factory"]() as db:
        assert len(list(db.scalars(select(Knowledge).where(Knowledge.kind == "received")))) == 1


@pytest.mark.parametrize("auto_retry,expected", [(True, 2), (False, 1)])
def test_retry_bounded_and_can_be_disabled(eldoria, auto_retry, expected):
    e = eldoria
    e["client"].put("/api/settings/extraction", json={"auto_retry": auto_retry})
    _, job_id = queue_source(e)

    class Provider:
        calls = 0

        async def extract(self, messages, settings):
            self.calls += 1
            return '{"events":['

    provider = Provider()
    result = run(e, job_id, provider)
    assert result["status"] == "failed" and provider.calls == expected
    assert result["attempts"] == expected
    assert e["client"].get("/api" + e["path"] + "/events").json() == []
    if auto_retry:
        retried = e["client"].post("/api" + e["path"] + f"/extraction-jobs/{job_id}/retry")
        assert retried.status_code == 200
        result = run(e, job_id, provider)
        assert result["attempts"] == 3 and provider.calls == 3
        assert (
            e["client"].post("/api" + e["path"] + f"/extraction-jobs/{job_id}/retry").status_code
            == 409
        )


def test_no_automatic_retry_on_network_or_auth_error(eldoria):
    e = eldoria
    _, job_id = queue_source(e)

    class Provider:
        calls = 0

        async def extract(self, messages, settings):
            self.calls += 1
            raise ProviderError("HTTP 401")

    provider = Provider()
    result = run(e, job_id, provider)
    assert result["status"] == "failed" and provider.calls == 1


def test_retry_switch_off_during_request_prevents_another_model_call(eldoria):
    e = eldoria
    _, job_id = queue_source(e)

    class Provider:
        calls = 0

        async def extract(self, messages, settings):
            self.calls += 1
            e["client"].put("/api/settings/extraction", json={"auto_retry": False})
            return '{"events":['

    provider = Provider()
    result = run(e, job_id, provider)
    assert provider.calls == 1 and result["status"] == "failed"
    e["client"].put("/api/settings/extraction", json={"auto_retry": True})
    e["client"].post("/api" + e["path"] + f"/extraction-jobs/{job_id}/retry")

    class StillInvalid:
        calls = 0

        async def extract(self, messages, settings):
            self.calls += 1
            return '{"events":['

    manual = StillInvalid()
    result = run(e, job_id, manual)
    assert manual.calls == 1 and result["attempts"] == 2 and result["status"] == "failed"


def test_fabricated_revision_is_corrected_but_genuine_concurrent_change_is_not(eldoria):
    e = eldoria
    from test_events import act, propose

    assert act(e, propose(e, [state(e, Haltung="offen")]).json(), "approve").status_code == 200
    quote = "Deine Haltung ist ruhig."
    _, job_id = queue_source(e, content=quote)
    operation = state(e, Haltung="ruhig")

    class Provider:
        calls = 0

        async def extract(self, messages, settings):
            self.calls += 1
            if self.calls == 1:
                return json.dumps(
                    {
                        "events": [
                            extracted_event(
                                e,
                                operations=[{**operation, "revision": operation["revision"] + 1}],
                                evidence_quote=quote,
                            )
                        ]
                    }
                )
            assert f"muss {operation['revision']} sein" in messages[0]["content"]
            return json.dumps(
                {
                    "events": [
                        extracted_event(e, operations=[operation], evidence_quote=quote),
                    ]
                }
            )

    provider = Provider()
    result = run(e, job_id, provider)
    assert result["status"] == "complete" and provider.calls == 2
    event = e["client"].get("/api" + e["path"] + "/events").json()[0]
    assert event["status"] == "proposed"

    # A revision that really changed after the snapshot remains a conflict, not a model repair.
    with e["factory"]() as db:
        new_message = Message(
            conversation_id=e["conversation"]["id"],
            role="assistant",
            content="Power hat einen Kristall.",
            sequence=2,
        )
        db.add(new_message)
        db.flush()
        job = enqueue_turn(db, db.get(Conversation, e["conversation"]["id"]), new_message)
        db.commit()
        second_job = job.id

    class RacingProvider:
        calls = 0

        async def extract(self, messages, settings):
            from app.models import Character

            self.calls += 1
            with e["factory"]() as db:
                character = db.get(Character, e["lumia"]["id"])
                character.revision += 1
                db.commit()
            return json.dumps({"events": [extracted_event(e, operations=[operation])]})

    racing = RacingProvider()
    result = run(e, second_job, racing)
    assert result["status"] == "failed" and racing.calls == 1


def test_failed_chat_does_not_queue_an_incomplete_turn(eldoria):
    e = eldoria

    class Provider:
        async def stream(self, messages, settings):
            yield "Unvollständig"
            raise ProviderError("Testabbruch")

    e["client"].app.state.provider = Provider()
    response = e["client"].post(
        f"/api/conversations/{e['conversation']['id']}/messages",
        json={"content": "Power hat einen Kristall."},
    )
    assert "event: error" in response.text and "event: done" not in response.text
    with e["factory"]() as db:
        assert not list(db.scalars(select(ExtractionJob)))


def test_only_completed_turn_is_queued_and_manual_requeue_is_idempotent(eldoria):
    e = eldoria

    class Provider:
        async def stream(self, messages, settings):
            with e["factory"]() as db:
                assert list(db.scalars(select(ExtractionJob))) == []
            yield "Ich höre dir zu."

    old = e["client"].app.state.provider
    e["client"].app.state.provider = Provider()
    try:
        response = e["client"].post(
            f"/api/conversations/{e['conversation']['id']}/messages",
            json={"content": "Power hat einen Kristall."},
        )
        assert "event: done" in response.text
    finally:
        e["client"].app.state.provider = old
    with e["factory"]() as db:
        jobs = list(db.scalars(select(ExtractionJob)))
        assert len(jobs) == 1
        links = list(db.scalars(select(ExtractionJobSource)))
        assert len(links) == 2 and {link.job_id for link in links} == {jobs[0].id}
    queued = e["client"].post(f"/api/conversations/{e['conversation']['id']}/extract").json()
    assert len(queued) == 1 and queued[0]["id"] == jobs[0].id


def test_both_ai_messages_supported_and_assistant_actions_still_require_approval(eldoria):
    e = eldoria
    with e["factory"]() as db:
        first = Message(
            conversation_id=e["conversation"]["id"],
            role="assistant",
            content="Power hat einen Kristall.",
            sequence=1,
            speaker_character_id=e["power"]["id"],
        )
        second = Message(
            conversation_id=e["conversation"]["id"],
            role="assistant",
            content="Lumia nimmt den Kristall wahr.",
            sequence=2,
            speaker_character_id=e["lumia"]["id"],
        )
        db.add_all([first, second])
        db.flush()
        job = enqueue_turn(db, db.get(Conversation, e["conversation"]["id"]), second)
        db.commit()
        job_id, second_id = job.id, second.id
    result = extract(
        e,
        job_id,
        {
            "events": [
                extracted_event(
                    e,
                    source_message_id=second_id,
                    evidence_quote="Lumia nimmt den Kristall wahr.",
                    operations=[memory(e, "Lumia nimmt den Kristall wahr.", kind="memory")],
                )
            ]
        },
    )
    assert result["status"] == "complete"
    event = e["client"].get("/api" + e["path"] + "/events").json()[0]
    assert event["status"] == "proposed" and event["sources"][0]["message_id"] == second_id
    assert act(e, event, "approve").status_code == 200


def test_greeting_turn_skipped_but_information_not_discarded(eldoria):
    e = eldoria
    with e["factory"]() as db:
        conversation = db.get(Conversation, e["conversation"]["id"])
        for sequence, text in [
            (1, "Hallo!"),
            (2, "Hallo!"),
            (3, "Hallo! Power hat einen Kristall."),
        ]:
            message = Message(
                conversation_id=conversation.id, sequence=sequence, role="assistant", content=text
            )
            db.add(message)
            db.flush()
            if sequence > 1:
                job = enqueue_turn(db, conversation, message)
                assert job.status == ("skipped" if sequence == 2 else "pending")
        db.commit()


def test_regeneration_invalidates_user_sourced_event_of_whole_turn(eldoria):
    e = eldoria
    e["client"].post(
        f"/api/conversations/{e['conversation']['id']}/messages",
        json={"content": "Power hat einen Kristall."},
    )
    with e["factory"]() as db:
        job_id = db.scalar(select(ExtractionJob.id))
    result = extract(e, job_id, {"events": [extracted_event(e)]})
    assert result["status"] == "complete"
    response = e["client"].post(f"/api/conversations/{e['conversation']['id']}/regenerate")
    assert "event: done" in response.text
    assert e["client"].get("/api" + e["path"] + "/events").json()[0]["status"] == "invalidated"
    with e["factory"]() as db:
        assert not list(
            db.scalars(
                select(Knowledge).where(Knowledge.kind == "received", Knowledge.status == "active")
            )
        )
