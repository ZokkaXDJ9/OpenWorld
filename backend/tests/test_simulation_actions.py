import asyncio
import json

import pytest
from conftest import create
from sqlalchemy import select
from test_events import act
from test_simulation import SceneProvider, control, run, setup

from app.models import Character, ExtractionJob, Message, Simulation
from app.simulation import step


class ActionProvider(SceneProvider):
    def __init__(self, content, operation):
        super().__init__(content)
        self.operation = operation

    async def extract(self, messages, settings):
        self.extractions.append(messages)
        data = json.loads(messages[1]["content"])
        if data["source"]["speaker_character_id"] != data["recipient_id"]:
            return '{"events":[]}'
        return json.dumps(
            {
                "events": [
                    {
                        "event_type": "action_observed",
                        "description": "Ausgeführte Handlung",
                        "confidence": 95,
                        "source_message_id": data["source"]["id"],
                        "evidence_quote": data["source"]["content"],
                        "operations": [self.operation(data)],
                    }
                ]
            }
        )


def automatic(e):
    response = e["client"].put(
        "/api" + e["path"] + "/event-rules",
        json={
            "event_type": "action_observed",
            "object_class": "character",
            "mode": "auto",
        },
    )
    assert response.status_code == 200


@pytest.mark.parametrize("item,valid", [("Kristall", True), ("Gold", False)])
def test_transfer_conserves_existing_inventory_and_impossible_transfer_changes_nothing(
    eldoria, item, valid
):
    e = eldoria
    simulation = setup(e, max_rounds=1)
    with e["factory"]() as db:
        db.get(Character, e["power"]["id"]).state = {"Inventar": ["Kristall"]}
        db.get(Character, e["lumia"]["id"]).state = {"Inventar": []}
        db.commit()
    automatic(e)

    def operation(data):
        target = next(row for row in data["heard_participants"] if row["id"] == e["lumia"]["id"])
        return {
            "op": "transfer",
            "entity_id": data["recipient_id"],
            "revision": data["recipient_state"]["revision"],
            "target_id": target["id"],
            "target_revision": target["revision"],
            "item": item,
        }

    result = run(
        e,
        control(e, simulation, "start").json(),
        ActionProvider(
            f"*Ich übergebe Lumia den {item}.*",
            operation,
        ),
    )
    with e["factory"]() as db:
        source = db.get(Character, e["power"]["id"])
        target = db.get(Character, e["lumia"]["id"])
        assert source.state["Inventar"] == ([] if valid else ["Kristall"])
        assert target.state["Inventar"] == (["Kristall"] if valid else [])
    assert result["status"] == ("completed" if valid else "paused"), result
    if valid:
        event = next(
            event
            for event in e["client"].get("/api" + e["path"] + "/events").json()
            if event["event_type"] == "action_observed"
        )
        assert act(e, event, "undo").status_code == 200
        with e["factory"]() as db:
            assert db.get(Character, e["power"]["id"]).state["Inventar"] == ["Kristall"]
            assert db.get(Character, e["lumia"]["id"]).state["Inventar"] == []


@pytest.mark.parametrize("arrive,valid", [(False, True), (True, False)])
def test_validated_departure_and_no_teleport_between_distant_places(eldoria, arrive, valid):
    e = eldoria
    simulation = setup(e, max_rounds=1)
    automatic(e)

    def operation(data):
        return {
            "op": "location",
            "entity_id": data["recipient_id"],
            "revision": data["recipient_state"]["revision"],
            "location_id": e["shadowfang"]["id"] if arrive else e["glade"]["id"],
            "destination_id": None if arrive else e["shadowfang"]["id"],
            "travel_status": "present" if arrive else "traveling",
        }

    result = run(
        e,
        control(e, simulation, "start").json(),
        ActionProvider(
            "*Ich erreiche Shadowfang.*"
            if arrive
            else "*Ich beginne meine Reise nach Shadowfang.*",
            operation,
        ),
    )
    assert result["status"] == ("completed" if valid else "paused"), result
    with e["factory"]() as db:
        actor = db.get(Character, e["power"]["id"])
        assert actor.location_id == e["glade"]["id"]
        assert actor.travel_status == ("traveling" if valid else "present")


def test_intervention_is_extracted_before_next_generation(eldoria):
    e = eldoria
    paused = setup(e, max_rounds=1)
    response = e["client"].post(
        "/api" + e["path"] + f"/simulations/{paused['id']}/interventions",
        json={"revision": paused["revision"], "content": "Ein Kristall liegt am Markt."},
    )
    assert response.status_code == 201
    provider = SceneProvider()
    result = run(e, control(e, response.json(), "start").json(), provider)
    assert result["completed_rounds"] == 1
    with e["factory"]() as db:
        human = db.scalar(
            select(Message).where(
                Message.conversation_id == result["conversation_id"],
                Message.role == "user",
            )
        )
        jobs = list(db.scalars(select(ExtractionJob).where(ExtractionJob.message_id == human.id)))
        assert len(jobs) == 2 and all(job.status == "complete" for job in jobs)
    assert len(provider.extractions) >= 2
    assert "Ein Kristall liegt am Markt." in json.dumps(provider.contexts[0])


def test_in_flight_cancellation_does_not_save_partial_public_output(eldoria):
    e = eldoria
    simulation = control(e, setup(e), "start").json()

    async def exercise():
        entered = asyncio.Event()

        class Waiting(SceneProvider):
            async def stream(self, messages, settings):
                yield "Angefangener Satz"
                entered.set()
                await asyncio.sleep(60)

        with e["factory"]() as db:
            task = asyncio.create_task(step(db, simulation["id"], Waiting()))
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            db.expire_all()
            row = db.get(Simulation, simulation["id"])
            assert row.status == "paused" and row.calls_used == 1
            assert not list(
                db.scalars(select(Message).where(Message.conversation_id == row.conversation_id))
            )

    asyncio.run(exercise())


def test_time_limit_marks_completion_and_no_job_stays_running(eldoria):
    e = eldoria
    simulation = control(e, setup(e, timeout_seconds=5), "start").json()
    with e["factory"]() as db:
        db.get(Simulation, simulation["id"]).seconds_used = 4.999
        db.commit()

    class Slow(SceneProvider):
        async def stream(self, messages, settings):
            await asyncio.sleep(1)
            yield "Zu spät"

    result = run(e, simulation, Slow())
    assert result["status"] == "completed" and result["stop_reason"] == "time_limit"
    assert not result["messages"]
    assert all(job["status"] != "running" for job in result["jobs"])


def test_world_with_simulation_and_dependencies_can_be_deleted_explicitly(eldoria):
    e = eldoria
    simulation = control(e, setup(e), "start").json()
    first = run(e, simulation, SceneProvider())
    run(e, first, SceneProvider())
    response = e["client"].delete("/api" + e["path"], params={"revision": e["world"]["revision"]})
    assert response.status_code == 204, response.text


@pytest.mark.parametrize("shadow", [False, True])
def test_group_relationship_uses_existing_direction_and_rejects_shadow_state(eldoria, shadow):
    e = eldoria
    simulation = setup(e, max_rounds=1)
    relationship = create(
        e["client"],
        e["path"] + "/relationships",
        source_id=e["power"]["id"],
        target_id=e["lumia"]["id"],
        attributes=[{"name": "Haltung", "type": "text", "value": "skeptisch"}],
    )
    reverse = create(
        e["client"],
        e["path"] + "/relationships",
        source_id=e["lumia"]["id"],
        target_id=e["power"]["id"],
        attributes=[{"name": "Haltung", "type": "text", "value": "neutral"}],
    )

    def operation(data):
        if shadow:
            return {
                "op": "state",
                "entity_type": "character",
                "entity_id": data["recipient_id"],
                "revision": data["recipient_state"]["revision"],
                "values": {"trust_lumia": 80},
            }
        return {
            "op": "relationship",
            "entity_id": relationship["id"],
            "revision": 1,
            "target_id": e["lumia"]["id"],
            "attributes": [{"name": "Haltung", "value": "freundlich"}],
            "attribute_quotes": {"Haltung": "Powers Haltung zu Lumia: freundlich."},
        }

    result = run(
        e,
        control(e, simulation, "start").json(),
        ActionProvider(
            "*Powers Haltung zu Lumia: freundlich.*",
            operation,
        ),
    )
    if shadow:
        assert result["status"] == "paused"
    else:
        assert result["status"] == "completed", result
        event = next(
            event
            for event in e["client"].get("/api" + e["path"] + "/events").json()
            if event["event_type"] == "action_observed"
        )
        assert event["status"] == "proposed"
        assert act(e, event, "approve").status_code == 200
    with e["factory"]() as db:
        from app.models import Relationship

        assert db.get(Relationship, relationship["id"]).attributes[0]["value"] == (
            "skeptisch" if shadow else "freundlich"
        )
        assert db.get(Relationship, reverse["id"]).attributes[0]["value"] == "neutral"
        assert "trust_lumia" not in db.get(Character, e["power"]["id"]).state
