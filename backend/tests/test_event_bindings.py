from copy import deepcopy

import pytest
from conftest import create
from sqlalchemy import select
from test_events import act, extract, extracted_event, memory, queue_source, state

from app.models import Character, EventProposal

QUOTE = "Dein Vertrauen zu Power steigt von 45 auf 60."


def relation(e, **fields):
    return create(
        e["client"],
        e["path"] + "/relationships",
        source_id=e["lumia"]["id"],
        target_id=e["power"]["id"],
        attributes=[
            {
                "name": "Vertrauen",
                "type": "number",
                "value": 45,
                "minimum": 0,
                "maximum": 100,
            }
        ],
        **fields,
    )


def operation(row, **fields):
    return {
        "op": "relationship",
        "entity_id": row["id"],
        "target_id": row["target_id"],
        "revision": row["revision"],
        "attributes": [{**row["attributes"][0], "value": 60}],
        **fields,
    }


def run(e, ops, quote=QUOTE, **fields):
    message_id, job_id = queue_source(e, content=quote)
    event = extracted_event(
        e, event_type="trust_changed", evidence_quote=quote, operations=ops, **fields
    )
    return message_id, extract(e, job_id, {"events": [event]})


def characters(e):
    return e["client"].get("/api" + e["path"] + "/characters").json()


def assert_unchanged(e):
    assert next(c for c in characters(e) if c["id"] == e["lumia"]["id"])["state"] == {}
    rows = e["client"].get("/api" + e["path"] + "/relationships").json()
    assert all(row["attributes"][0]["value"] == 45 for row in rows)
    assert e["client"].get("/api" + e["path"] + "/events").json() == []


@pytest.mark.parametrize(
    "key",
    ["trust_power", "Vertrauen_Power", "powerTrust", "Vertrauen zu Power", "xyz_123"],
)
def test_qwen_shadow_state_is_rejected_atomically_even_with_other_valid_operations(eldoria, key):
    e = eldoria
    relation(e)
    before = e["client"].get("/api" + e["path"] + "/knowledge").json()
    _, job = run(e, [memory(e, QUOTE, kind="received"), state(e, **{key: 60})])
    assert job["status"] == "failed" and job["attempts"] == 2
    assert "Beziehungsattribut" in job["error"]
    assert e["client"].get("/api" + e["path"] + "/knowledge").json() == before
    assert_unchanged(e)


@pytest.mark.parametrize(
    "quote",
    [
        "Dein Vertrauen zu Power steigt etwas.",
        "Dein Vertrauen zu Power steigt nicht auf 60.",
        "Dein Vertrauen zu Power soll auf 60 steigen.",
        "Dein Vertrauen zu Power steigt auf 60?",
        "Dein Vertrauen zu Power steigt von 40 auf 60.",
        "Dein Vertrauen zu Power steigt von 45 auf 600.",
        "Dein Vertrauen zu Power steigt auf 60,5.",
        "Dein Vertrauen zu Power steigt von 45 auf 60 und Mut auf 70.",
        "Powers Vertrauen zu Lumia steigt von 45 auf 60.",
        "Powers Vertrauen zu Power steigt von 45 auf 60.",
    ],
)
def test_numeric_inference_mismatch_negation_intent_and_wrong_view_are_rejected(eldoria, quote):
    e = eldoria
    row = relation(e)
    _, job = run(e, [operation(row)], quote)
    assert job["status"] == "failed", job
    assert_unchanged(e)


@pytest.mark.parametrize("fault", ["target", "missing_target", "attribute", "definition", "entity"])
def test_structural_target_or_attribute_mismatch_is_rejected(eldoria, fault):
    e = eldoria
    row = relation(e)
    op = operation(row)
    if fault == "target":
        op["target_id"] = e["lumia"]["id"]
    elif fault == "missing_target":
        del op["target_id"]
    elif fault == "attribute":
        op["attributes"][0]["name"] = "Zuneigung"
    elif fault == "definition":
        op["attributes"][0]["maximum"] = 200
    else:
        op["entity_id"] = e["power"]["id"]
    _, job = run(e, [op])
    assert job["status"] == "failed", job
    assert_unchanged(e)


@pytest.mark.parametrize("ambiguity", ["names", "relationships"])
def test_ambiguous_names_and_parallel_attributes_require_source_relationship_id(eldoria, ambiguity):
    e = eldoria
    row = relation(e)
    if ambiguity == "names":
        create(e["client"], e["path"] + "/characters", name="Power")
    else:
        relation(e, kind="Rivale")
    _, job = run(e, [operation(row)])
    assert job["status"] == "failed" and "Mehrdeutige" in job["error"]
    assert_unchanged(e)
    e["conversation"] = create(
        e["client"],
        e["path"] + "/conversations",
        character_id=e["lumia"]["id"],
    )
    _, job = run(e, [operation(row)], f"{row['id']} Vertrauen: 60.")
    assert job["status"] == "complete", job


@pytest.mark.parametrize(
    "quote_template",
    [
        "Dein Vertrauen zu Power steigt von 45 auf 60.",
        "Lumias Vertrauen zu Power: 60.",
        "{id} Vertrauen: 60.",
    ],
)
def test_existing_relationship_requires_confirmation_and_preserves_audit_and_undo(
    eldoria,
    quote_template,
):
    e = eldoria
    row = relation(e)
    quote = quote_template.format(id=row["id"])
    _, job = run(e, [operation(row, attribute_quotes={"Vertrauen": quote})], quote)
    assert job["status"] == "complete", job
    event = e["client"].get("/api" + e["path"] + "/events").json()[0]
    assert event["status"] == "proposed"
    assert e["client"].get("/api" + e["path"] + "/relationships").json()[0] == row
    applied = act(e, event, "approve")
    assert applied.status_code == 200, applied.text
    assert applied.json()["mutations"][0]["after"]["attributes"][0]["value"] == 60
    undone = act(e, applied.json(), "undo")
    assert undone.status_code == 200, undone.text
    current = e["client"].get("/api" + e["path"] + "/relationships").json()[0]
    assert current["attributes"] == row["attributes"]
    assert next(c for c in characters(e) if c["id"] == e["lumia"]["id"])["state"] == {}
    assert [entry["action"] for entry in undone.json()["audit"]] == [
        "proposed",
        "applied",
        "mutation_reverted",
        "undone",
    ]


def test_proposal_edit_and_legacy_approval_cannot_bypass_binding(eldoria):
    e = eldoria
    row = relation(e)
    _, job = run(e, [operation(row)])
    assert job["status"] == "complete", job
    event = e["client"].get("/api" + e["path"] + "/events").json()[0]
    body = {
        "event_type": "trust_changed",
        "description": "Korrektur",
        "operations": [state(e, trust_power=60)],
    }
    edited = e["client"].put(
        "/api" + e["path"] + f"/events/{event['id']}?revision={event['revision']}",
        json=body,
    )
    assert edited.status_code == 422
    body["operations"] = [operation(row)]
    body["operations"][0]["attributes"][0]["value"] = 55
    edited = e["client"].put(
        "/api" + e["path"] + f"/events/{event['id']}?revision={event['revision']}",
        json=body,
    )
    assert edited.status_code == 422
    # Simulate a pre-upgrade unsafe open proposal, not a bypass exposed through the API.
    with e["factory"]() as db:
        proposal = db.scalar(select(EventProposal).where(EventProposal.event_id == event["id"]))
        proposal.operations = [state(e, trust_power=60)]
        db.commit()
    approved = act(e, event, "approve")
    assert approved.status_code == 422
    assert e["client"].get("/api" + e["path"] + "/relationships").json()[0] == row
    assert next(c for c in characters(e) if c["id"] == e["lumia"]["id"])["state"] == {}


@pytest.mark.parametrize("value", [60, "60"])
def test_existing_shadow_key_still_cannot_take_a_relationship_change(eldoria, value):
    e = eldoria
    relation(e)
    with e["factory"]() as db:
        db.get(Character, e["lumia"]["id"]).state = {"trust_power": value}
        db.commit()
    _, job = run(e, [state(e, trust_power=value)])
    assert job["status"] == "failed" and "Beziehungsattribut" in job["error"]


@pytest.mark.parametrize("value", [60, "60", True])
def test_numeric_state_values_need_grounding_and_cannot_change_type(eldoria, value):
    e = eldoria
    with e["factory"]() as db:
        db.get(Character, e["lumia"]["id"]).state = {"Mut": 45}
        db.commit()
    _, job = run(e, [state(e, Mut=value)], "Dein Mut steigt etwas.")
    assert job["status"] == "failed", job
    assert next(c for c in characters(e) if c["id"] == e["lumia"]["id"])["state"] == {"Mut": 45}


@pytest.mark.parametrize("key", ["Mut", "Maß"])
def test_legitimate_existing_state_slot_remains_editable(eldoria, key):
    e = eldoria
    with e["factory"]() as db:
        db.get(Character, e["lumia"]["id"]).state = {key: 45}
        db.commit()
    _, job = run(e, [state(e, **{key: 60})], f"Dein {key}:60.")
    assert job["status"] == "complete", job
    event = e["client"].get("/api" + e["path"] + "/events").json()[0]
    assert act(e, event, "approve").status_code == 200
    assert next(c for c in characters(e) if c["id"] == e["lumia"]["id"])["state"] == {key: 60}


def test_multiple_existing_state_values_keep_grounding_through_approval_and_undo(eldoria):
    e = eldoria
    before = {"Mut": 45, "Haltung": "offen"}
    with e["factory"]() as db:
        db.get(Character, e["lumia"]["id"]).state = before
        db.commit()
    mut = "Dein Mut steigt von 45 auf 60."
    haltung = "Deine Haltung ist ruhig."
    op = {**state(e, Mut=60, Haltung="ruhig"), "value_quotes": {"Mut": mut, "Haltung": haltung}}
    _, job = run(e, [op], mut + " " + haltung)
    assert job["status"] == "complete", job
    event = e["client"].get("/api" + e["path"] + "/events").json()[0]
    applied = act(e, event, "approve")
    assert applied.status_code == 200, applied.text
    assert next(c for c in characters(e) if c["id"] == e["lumia"]["id"])["state"] == {
        "Mut": 60,
        "Haltung": "ruhig",
    }
    assert act(e, applied.json(), "undo").status_code == 200
    assert next(c for c in characters(e) if c["id"] == e["lumia"]["id"])["state"] == before


def test_explicit_german_decimal_value_remains_numeric(eldoria):
    e = eldoria
    row = relation(e)
    op = operation(row, attributes=[{"name": "Vertrauen", "value": 60.5}])
    _, job = run(e, [op], "Dein Vertrauen zu Power steigt von 45 auf 60,5.")
    assert job["status"] == "complete", job
    event = e["client"].get("/api" + e["path"] + "/events").json()[0]
    assert act(e, event, "approve").status_code == 200


@pytest.mark.parametrize("value", [60, 101, "60", True])
def test_attribute_value_reference_is_resolved_and_validated_against_existing_definition(
    eldoria,
    value,
):
    e = eldoria
    row = relation(e)
    _, job = run(e, [operation(row, attributes=[{"name": "Vertrauen", "value": value}])])
    if type(value) is int and value == 60:
        assert job["status"] == "complete", job
        event = e["client"].get("/api" + e["path"] + "/events").json()[0]
        assert event["proposal"]["operations"][0]["attributes"] == [
            {**row["attributes"][0], "value": 60},
        ]
        applied = act(e, event, "approve")
        assert applied.status_code == 200, applied.text
        assert act(e, applied.json(), "undo").status_code == 200
    else:
        assert job["status"] == "failed", job
        assert_unchanged(e)


def test_unknown_state_slot_cannot_be_created_even_without_a_relationship(eldoria):
    e = eldoria
    _, job = run(e, [state(e, Mut=60)], "Dein Mut steigt auf 60.")
    assert job["status"] == "failed" and "Unbekanntes Zustandsfeld" in job["error"]
    assert_unchanged(e)


@pytest.mark.parametrize("scope", ["incoming", "other_world"])
def test_extraction_cannot_target_incoming_or_cross_world_relationships(eldoria, scope):
    e = eldoria
    if scope == "incoming":
        row = create(
            e["client"],
            e["path"] + "/relationships",
            source_id=e["power"]["id"],
            target_id=e["lumia"]["id"],
            attributes=[
                {
                    "name": "Vertrauen",
                    "type": "number",
                    "value": 45,
                    "minimum": 0,
                    "maximum": 100,
                }
            ],
        )
    else:
        world = create(e["client"], "/worlds", name="Andere Welt")
        path = f"/worlds/{world['id']}"
        source = create(e["client"], path + "/characters", name="Lumia")
        target = create(e["client"], path + "/characters", name="Power")
        row = create(
            e["client"],
            path + "/relationships",
            source_id=source["id"],
            target_id=target["id"],
            attributes=[
                {
                    "name": "Vertrauen",
                    "type": "number",
                    "value": 45,
                    "minimum": 0,
                    "maximum": 100,
                }
            ],
        )
    _, job = run(e, [operation(row)])
    assert job["status"] == "failed", job
    assert_unchanged(e)


def test_multi_attribute_operation_binds_each_number_to_its_own_subquote(eldoria):
    e = eldoria
    row = relation(e)
    current = deepcopy(row)
    current["attributes"].append({**row["attributes"][0], "name": "Respekt", "value": 20})
    current = {
        key: current[key]
        for key in (
            "source_id",
            "target_id",
            "kind",
            "description",
            "attributes",
            "revision",
            "secret",
        )
    }
    response = e["client"].put(
        "/api" + e["path"] + f"/relationships/{row['id']}",
        json=current,
    )
    assert response.status_code == 200, response.text
    row = response.json()
    trust = "Dein Vertrauen zu Power steigt von 45 auf 60."
    respect = "Dein Respekt zu Power steigt von 20 auf 30."
    op = operation(row)
    op["attributes"].append({**row["attributes"][1], "value": 30})
    op["attribute_quotes"] = {"Vertrauen": trust, "Respekt": respect}
    _, job = run(e, [op], trust + " " + respect)
    assert job["status"] == "complete", job
    event = e["client"].get("/api" + e["path"] + "/events").json()[0]
    assert act(e, event, "approve").status_code == 200
