import asyncio
import json

import pytest
from conftest import create
from sqlalchemy import select

from app.extraction import run_job
from app.memory import retrieve
from app.models import Event, ExtractionJob, Knowledge, Message


def propose(e, operations, **fields):
    return e["client"].post(
        "/api" + e["path"] + "/events",
        json={
            "event_type": "experience",
            "description": "Belegtes Erlebnis",
            "confidence": 90,
            "participant_ids": [e["lumia"]["id"]],
            "operations": operations,
            **fields,
        },
    )


def act(e, event, action):
    return e["client"].post(
        "/api" + e["path"] + f"/events/{event['id']}/{action}",
        json={"revision": event["revision"]},
    )


def memory(e, content="Power ist tot.", **extra):
    return {
        "op": "knowledge",
        "character_id": e["lumia"]["id"],
        "kind": "belief",
        "content": content,
        **extra,
    }


def state(e, **values):
    character = next(
        c
        for c in e["client"].get("/api" + e["path"] + "/characters").json()
        if c["id"] == e["lumia"]["id"]
    )
    return {
        "op": "state",
        "entity_type": "character",
        "entity_id": character["id"],
        "revision": character["revision"],
        "values": values,
    }


def test_secret_and_subjective_information_are_isolated(eldoria):
    e = eldoria
    before = e["client"].get("/api" + e["path"] + "/knowledge").json()
    result = propose(e, [memory(e, "Power besitzt einen Kristall.", kind="received")])
    assert result.status_code == 201, result.text
    assert result.json()["status"] == "applied"
    records = e["client"].get("/api" + e["path"] + "/knowledge").json()
    assert all(record in records for record in before)
    personal = [r for r in records if r["character_id"] == e["lumia"]["id"]]
    assert personal[0]["kind"] == "received"
    assert personal[0]["public"] is False
    assert not any(
        r["kind"] == "received" and r["character_id"] == e["power"]["id"] for r in records
    )


def test_belief_correction_retains_history_links_and_undo(eldoria):
    e = eldoria
    old_event = propose(e, [memory(e)]).json()
    old_id = old_event["mutations"][0]["entity_id"]
    new_event = propose(
        e,
        [
            memory(
                e,
                "Power lebt; ich bin ihm begegnet.",
                supersedes=[old_id],
                confidence=80,
            )
        ],
    ).json()
    assert new_event["status"] == "proposed"
    accepted = act(e, new_event, "approve")
    assert accepted.status_code == 200, accepted.text
    history = (
        e["client"].get("/api" + e["path"] + f"/characters/{e['lumia']['id']}/memories").json()
    )
    assert next(k for k in history if k["id"] == old_id)["status"] == "superseded"
    new = next(k for k in history if k["id"] != old_id)
    assert new["links"][0]["target_id"] == old_id
    assert act(e, old_event, "undo").status_code == 409
    assert act(e, accepted.json(), "undo").status_code == 200
    active = e["client"].get("/api" + e["path"] + "/knowledge").json()
    assert next(k for k in active if k["id"] == old_id)["status"] == "active"
    assert act(e, old_event, "undo").status_code == 200


def test_regeneration_invalidates_old_answer_events_without_duplicate_memories(eldoria):
    e = eldoria
    _, job_id = queue_source(e, role="assistant")
    assert extract(e, job_id, {"events": [extracted_event(e)]})["status"] == "complete"
    event = e["client"].get("/api" + e["path"] + "/events").json()[0]
    assert event["status"] == "proposed"
    assert act(e, event, "approve").status_code == 200
    response = e["client"].post(f"/api/conversations/{e['conversation']['id']}/regenerate")
    assert "event: done" in response.text, response.text
    history = e["client"].get("/api" + e["path"] + "/events").json()
    assert len(history) == 1 and history[0]["status"] == "invalidated"
    assert not any(
        row["kind"] == "received"
        for row in e["client"].get("/api" + e["path"] + "/knowledge").json()
    )


def test_extraction_is_off_by_default_and_smalltalk_is_not_persisted(environment):
    client, factory, _ = environment
    world = create(client, "/worlds", name="Ohne Zusatzanfragen")
    row = client.get(f"/api/worlds/{world['id']}/event-settings").json()
    assert row["enabled"] is False
    assert client.get(f"/api/worlds/{world['id']}/extraction-jobs").json() == []
    with factory() as db:
        assert list(db.scalars(select(ExtractionJob))) == []


def test_relationship_confirmation_changes_only_existing_attribute(eldoria):
    e = eldoria
    relationship = create(
        e["client"],
        e["path"] + "/relationships",
        source_id=e["lumia"]["id"],
        target_id=e["power"]["id"],
        attributes=[
            {"name": "Vertrauen", "type": "number", "value": 45, "minimum": 0, "maximum": 100}
        ],
    )
    new_attribute = {**relationship["attributes"][0], "value": 60}
    event = propose(
        e,
        [
            {
                "op": "relationship",
                "entity_id": relationship["id"],
                "revision": 1,
                "attributes": [new_attribute],
            }
        ],
        event_type="trust_changed",
    ).json()
    assert event["status"] == "proposed"
    assert (
        e["client"].get("/api" + e["path"] + "/relationships").json()[0]["attributes"][0]["value"]
        == 45
    )
    applied = act(e, event, "approve")
    assert applied.status_code == 200, applied.text
    assert applied.json()["mutations"][0]["before"]["attributes"][0]["value"] == 45
    assert (
        e["client"].get("/api" + e["path"] + "/relationships").json()[0]["attributes"][0]["value"]
        == 60
    )
    assert act(e, applied.json(), "undo").status_code == 200


def test_undo_blocks_newer_and_manual_changes_and_logs_itself(eldoria):
    e = eldoria
    first = act(e, propose(e, [state(e, Haltung="ruhig")]).json(), "approve").json()
    second = act(e, propose(e, [state(e, Haltung="wütend")]).json(), "approve").json()
    assert act(e, first, "undo").status_code == 409
    second_undo = act(e, second, "undo")
    assert second_undo.status_code == 200
    undone = act(e, first, "undo")
    assert undone.status_code == 200, undone.text
    assert undone.json()["audit"][-1]["action"] == "undone"
    third = act(e, propose(e, [state(e, Haltung="wach")]).json(), "approve").json()
    operation = state(e)
    character = next(
        c
        for c in e["client"].get("/api" + e["path"] + "/characters").json()
        if c["id"] == e["lumia"]["id"]
    )
    update = e["client"].put(
        "/api" + e["path"] + f"/characters/{character['id']}",
        json={
            "name": character["name"],
            "state": character["state"],
            "location_id": character["location_id"],
            "travel_status": "present",
            "revision": operation["revision"],
        },
    )
    assert update.status_code == 200
    assert act(e, third, "undo").status_code == 409


def test_local_retrieval_without_keyword_overlap_and_no_foreign_secret(eldoria):
    e = eldoria
    event = propose(
        e,
        [
            memory(
                e,
                "Lumia hat Glade nach einem Streit um einen Kristall das Vertrauen entzogen.",
                kind="memory",
                subject_id=e["power"]["id"],
            )
        ],
    ).json()
    assert event["status"] == "applied"
    with e["factory"]() as db:
        rows = retrieve(
            db, e["world"]["id"], e["lumia"]["id"], "Wie steht es inzwischen zwischen euch beiden?"
        )
        assert "Vertrauen entzogen" in rows[0].content
        assert not any(row.character_id == e["power"]["id"] for row in rows)


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "knowledge", "character_id": "missing", "content": "Ungültig"},
        {"op": "knowledge", "kind": "fact", "character_id": "missing", "content": "Ungültig"},
        {
            "op": "state",
            "entity_type": "character",
            "entity_id": "missing",
            "revision": 1,
            "values": {"x": 1},
        },
    ],
)
def test_invalid_references_never_leave_partial_events(eldoria, operation):
    e = eldoria
    result = propose(e, [memory(e, "Darf nicht gespeichert werden."), operation])
    assert result.status_code == 422
    assert e["client"].get("/api" + e["path"] + "/events").json() == []
    with e["factory"]() as db:
        assert (
            db.scalar(select(Knowledge.id).where(Knowledge.character_id == e["lumia"]["id"]))
            is None
        )


def test_protected_facts_cannot_be_enabled_by_rules(eldoria):
    e = eldoria
    e["client"].put(
        "/api" + e["path"] + "/event-rules",
        json={
            "mode": "auto",
            "object_class": "*",
        },
    )
    event = propose(e, [{"op": "knowledge", "kind": "fact", "content": "Die Welt brennt."}]).json()
    assert event["status"] == "protected"
    assert act(e, event, "approve").status_code == 409
    assert act(e, event, "reject").json()["status"] == "rejected"


def test_multi_operation_stale_approval_is_atomic(eldoria):
    e = eldoria
    event = propose(
        e, [memory(e, "Diese Erinnerung darf nicht teilweise erscheinen."), state(e, Mut=60)]
    ).json()
    later = act(e, propose(e, [state(e, Mut=20)]).json(), "approve")
    assert later.status_code == 200
    assert act(e, event, "approve").status_code == 409
    assert not any(
        k["content"].startswith("Diese Erinnerung")
        for k in e["client"].get("/api" + e["path"] + "/knowledge").json()
    )


def enable(e):
    settings = e["client"].get("/api" + e["path"] + "/event-settings").json()
    response = e["client"].put(
        "/api" + e["path"] + "/event-settings",
        json={"enabled": True, "revision": settings["revision"]},
    )
    assert response.status_code == 200


def queue_source(e, content="Power hat einen Kristall.", role="user"):
    with e["factory"]() as db:
        message = Message(
            conversation_id=e["conversation"]["id"],
            content=content,
            role=role,
            sequence=1,
            speaker_character_id=e["lumia"]["id"] if role == "assistant" else None,
        )
        db.add(message)
        db.commit()
        message_id = message.id
    response = e["client"].post(f"/api/conversations/{e['conversation']['id']}/extract")
    assert response.status_code == 200, response.text
    return message_id, response.json()[0]["id"]


def extract(e, job_id, body):
    class Extractor:
        async def extract(self, messages, settings):
            context = json.dumps(messages)
            assert "Ich besitze den geheimen Kristall." not in context
            assert "Mein geheimer Kristall" not in context
            return body if isinstance(body, str) else json.dumps(body)

    with e["factory"]() as db:
        asyncio.run(run_job(db, job_id, Extractor()))
    return e["client"].get("/api" + e["path"] + "/extraction-jobs").json()[0]


def extracted_event(e, **extra):
    return {
        "event_type": "knowledge_acquired",
        "description": "Benutzer berichtet von Power",
        "confidence": 90,
        "evidence_quote": "Power hat einen Kristall.",
        "operations": [memory(e, "Power hat einen Kristall.", kind="received")],
        **extra,
    }


def test_completed_source_extraction_is_idempotent_and_subjective(eldoria):
    e = eldoria
    enable(e)
    _, job_id = queue_source(e)
    result = extract(e, job_id, {"events": [extracted_event(e)]})
    assert result["status"] == "complete", result
    assert len(result["event_ids"]) == 1
    assert extract(e, job_id, "invalid repeated response")["status"] == "complete"
    queued_again = e["client"].post(f"/api/conversations/{e['conversation']['id']}/extract").json()
    assert len(queued_again) == 1 and queued_again[0]["id"] == job_id
    assert len(e["client"].get("/api" + e["path"] + "/events").json()) == 1
    records = e["client"].get("/api" + e["path"] + "/knowledge").json()
    assert len([r for r in records if r["kind"] == "received"]) == 1
    assert next(r for r in records if r["kind"] == "received")["confidence"] == 50


@pytest.mark.parametrize("bad", ["not JSON", '{"events":[', '{"events":[{"bad":1}]}'])
def test_invalid_json_fails_visibly_without_mutations(eldoria, bad):
    e = eldoria
    enable(e)
    _, job_id = queue_source(e)
    assert extract(e, job_id, bad)["status"] == "failed"
    assert e["client"].get("/api" + e["path"] + "/events").json() == []


def test_one_bad_extracted_event_rolls_back_whole_batch(eldoria):
    e = eldoria
    enable(e)
    _, job_id = queue_source(e)
    valid = extracted_event(e)
    invalid = extracted_event(e, operations=[memory(e, character_id=e["power"]["id"])])
    result = extract(e, job_id, {"events": [valid, invalid]})
    assert result["status"] == "failed"
    assert e["client"].get("/api" + e["path"] + "/events").json() == []
    assert not any(
        k["kind"] == "received" for k in e["client"].get("/api" + e["path"] + "/knowledge").json()
    )


def test_question_does_not_auto_create_history_and_empty_extraction_is_valid(eldoria):
    e = eldoria
    enable(e)
    _, job_id = queue_source(e, "Weißt du noch, wie wir uns damals im Wald kennengelernt haben?")
    assert extract(e, job_id, {"events": []})["status"] == "complete"
    assert e["client"].get("/api" + e["path"] + "/events").json() == []


def test_message_edit_invalidates_effects_and_reextracts_new_revision(eldoria):
    e = eldoria
    enable(e)
    message_id, job_id = queue_source(e)
    assert extract(e, job_id, {"events": [extracted_event(e)]})["status"] == "complete"
    response = e["client"].put(
        f"/api/conversations/{e['conversation']['id']}/messages/{message_id}",
        json={"content": "Power hat einen Apfel.", "confirm_discard": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 2
    events = e["client"].get("/api" + e["path"] + "/events").json()
    assert events[0]["status"] == "invalidated"
    assert not any(
        k["kind"] == "received" for k in e["client"].get("/api" + e["path"] + "/knowledge").json()
    )
    with e["factory"]() as db:
        jobs = list(db.scalars(select(ExtractionJob)))
        assert len(jobs) == 2
        assert {job.status for job in jobs} == {"invalidated", "pending"}


def test_source_edit_conflict_preserves_messages_and_independent_changes(eldoria):
    e = eldoria
    enable(e)
    message_id, job_id = queue_source(e)
    operation = state(e, Haltung="ruhig")
    event = extracted_event(e, operations=[operation])
    assert extract(e, job_id, {"events": [event]})["status"] == "complete"
    pending = e["client"].get("/api" + e["path"] + "/events").json()[0]
    assert act(e, pending, "approve").status_code == 200
    assert act(e, propose(e, [state(e, Haltung="wach")]).json(), "approve").status_code == 200
    response = e["client"].put(
        f"/api/conversations/{e['conversation']['id']}/messages/{message_id}",
        json={"content": "Geändert.", "confirm_discard": True},
    )
    assert response.status_code == 409
    assert (
        e["client"]
        .get(f"/api/conversations/{e['conversation']['id']}/messages")
        .json()[0]["content"]
        == "Power hat einen Kristall."
    )


def test_message_deleted_during_extraction_cannot_apply_result(eldoria):
    e = eldoria
    enable(e)
    _, job_id = queue_source(e)

    class RacingProvider:
        async def extract(self, messages, settings):
            response = e["client"].delete(f"/api/conversations/{e['conversation']['id']}")
            assert response.status_code == 204
            return json.dumps({"events": [extracted_event(e)]})

    with e["factory"]() as db:
        asyncio.run(run_job(db, job_id, RacingProvider()))
        assert db.get(ExtractionJob, job_id).status == "invalidated"
        assert list(db.scalars(select(Event))) == []


def test_cross_world_ids_and_evidence_fabrication_are_rejected(eldoria):
    e = eldoria
    foreign = create(e["client"], "/worlds", name="Fremde Welt")
    other = create(e["client"], f"/worlds/{foreign['id']}/characters", name="Andere")
    assert propose(e, [memory(e, subject_id=other["id"])]).status_code == 422
    enable(e)
    _, job_id = queue_source(e)
    assert (
        extract(e, job_id, {"events": [extracted_event(e, evidence_quote="Erfunden")]})["status"]
        == "failed"
    )


def test_archive_is_reversible_and_cannot_be_extracted(eldoria):
    e = eldoria
    created = propose(e, [memory(e)]).json()
    knowledge_id = created["mutations"][0]["entity_id"]
    archive = propose(e, [{"op": "archive", "entity_id": knowledge_id, "revision": 1}]).json()
    applied = act(e, archive, "approve")
    assert applied.status_code == 200, applied.text
    assert act(e, applied.json(), "undo").status_code == 200


def test_event_time_filters_and_rule_revision_conflicts(eldoria):
    e = eldoria
    event = propose(e, [memory(e)], occurred_at="1200-01-01T12:00:00Z").json()
    assert event["occurred_at"].startswith("1200-")
    rows = e["client"].get("/api" + e["path"] + "/events?until_time=1300-01-01T00:00:00Z").json()
    assert len(rows) == 1
    rule = (
        e["client"]
        .put(
            "/api" + e["path"] + "/event-rules",
            json={
                "event_type": "experience",
                "object_class": "knowledge",
                "mode": "confirm",
            },
        )
        .json()
    )
    assert (
        e["client"]
        .put(
            "/api" + e["path"] + "/event-rules",
            json={
                "event_type": "experience",
                "object_class": "knowledge",
                "mode": "auto",
                "revision": rule["revision"] + 1,
            },
        )
        .status_code
        == 409
    )
