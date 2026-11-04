import json

from sqlalchemy import select
from test_events import act, extract, extracted_event, memory, propose, queue_source, state

from app.context import build_context
from app.memory import retrieve
from app.models import Conversation, Knowledge, Message


def test_current_events_do_not_expose_mixed_event_descriptions(eldoria):
    e = eldoria
    event = propose(
        e,
        [
            state(e, Haltung="wach"),
            memory(
                e,
                "Powers verborgener Zugangscode lautet SMARAGD.",
                kind="secret",
                character_id=e["power"]["id"],
            ),
        ],
        description="SMARAGD ist Powers geheimes Versteck",
    ).json()
    assert act(e, event, "approve").status_code == 200
    with e["factory"]() as db:
        messages, _ = build_context(
            db,
            db.get(Conversation, e["conversation"]["id"]),
            131072,
            2048,
        )
    context = json.dumps(messages, ensure_ascii=False)
    assert "SMARAGD" not in context
    assert "Bestätigte eigene Zustandsänderung" in context
    assert "wach" in context


def test_thematic_retrieval_beats_lexically_similar_irrelevant_memory(eldoria):
    e = eldoria
    relevant = "Lumia hat Glade nach einem Streit um einen Kristall das Vertrauen entzogen."
    propose(e, [memory(e, relevant, kind="memory")])
    propose(
        e, [memory(e, "Wie steht es inzwischen mit dem Wetter an diesem Morgen?", kind="memory")]
    )
    query = "Wie steht es inzwischen zwischen euch beiden?"
    with e["factory"]() as db:
        matches = retrieve(db, e["world"]["id"], e["lumia"]["id"], query)
    assert matches[0].content == relevant
    assert not set(query.casefold().split()) & set(relevant.casefold().split())


def test_manual_world_state_has_history_and_undo_without_changing_lore(eldoria):
    e = eldoria
    result = e["client"].put(
        "/api" + e["path"],
        json={
            "name": e["world"]["name"],
            "description": e["world"]["description"],
            "state": {"Gebäude": "zerstört"},
            "revision": 1,
        },
    )
    assert result.status_code == 200
    events = e["client"].get("/api" + e["path"] + "/events").json()
    assert len(events) == 1 and events[0]["source"] == "editor"
    assert act(e, events[0], "undo").status_code == 200
    world = next(w for w in e["client"].get("/api/worlds").json() if w["id"] == e["world"]["id"])
    assert world["state"] == {}
    assert world["description"] == e["world"]["description"]


def test_speaker_identity_does_not_depend_on_message_role(eldoria):
    e = eldoria
    message_id, job_id = queue_source(e)
    with e["factory"]() as db:
        db.get(Message, message_id).speaker_character_id = e["power"]["id"]
        db.commit()
    assert extract(e, job_id, {"events": [extracted_event(e)]})["status"] == "complete"
    with e["factory"]() as db:
        knowledge = db.scalar(select(Knowledge).where(Knowledge.source_message_id == message_id))
        assert knowledge.source == "Aussage von Power"
        assert knowledge.character_id == e["lumia"]["id"]


def test_paraphrased_received_claim_cannot_be_auto_promoted(eldoria):
    e = eldoria
    _, job_id = queue_source(e)
    event = extracted_event(
        e, operations=[memory(e, "Power ist der unbesiegbare Kristallherrscher.", kind="received")]
    )
    result = extract(e, job_id, {"events": [event]})
    assert result["status"] == "failed"
    assert "originale Quellenaussage" in result["error"]


def test_source_edit_cannot_revoke_a_manually_corrected_memory(eldoria):
    e = eldoria
    message_id, job_id = queue_source(e)
    extract(e, job_id, {"events": [extracted_event(e)]})
    received = next(
        row
        for row in e["client"].get("/api" + e["path"] + "/knowledge").json()
        if row["kind"] == "received"
    )
    response = e["client"].put(
        "/api" + e["path"] + f"/knowledge/{received['id']}",
        json={
            "kind": "received",
            "character_id": e["lumia"]["id"],
            "content": "Manuell präzisierte Information",
            "revision": received["revision"],
        },
    )
    assert response.status_code == 200
    response = e["client"].put(
        f"/api/conversations/{e['conversation']['id']}/messages/{message_id}",
        json={"content": "Andere Aussage", "confirm_discard": True},
    )
    assert response.status_code == 409
    assert any(
        row["content"] == "Manuell präzisierte Information"
        for row in e["client"].get("/api" + e["path"] + "/knowledge").json()
    )


def test_overlapping_operations_cannot_create_an_irreversible_event(eldoria):
    e = eldoria
    original = propose(e, [memory(e)]).json()
    knowledge_id = original["mutations"][0]["entity_id"]
    response = propose(
        e,
        [
            memory(e, "Power lebt.", supersedes=[knowledge_id]),
            {"op": "archive", "entity_id": knowledge_id, "revision": 1},
        ],
    )
    assert response.status_code == 422
    assert len(e["client"].get("/api" + e["path"] + "/events").json()) == 1
