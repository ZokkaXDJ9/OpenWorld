import asyncio
import json

import pytest
from conftest import create
from sqlalchemy import select
from test_events import act

from app.models import Character, Knowledge, Simulation, SimulationTurn, WorldClock
from app.provider import ProviderError
from app.simulation import recover, step


class SceneProvider:
    def __init__(self, content="Guten Tag."):
        self.content = content
        self.contexts = []
        self.extractions = []

    async def stream(self, messages, settings):
        assert any(message["role"] == "user" for message in messages)
        self.contexts.append(messages)
        yield self.content

    async def extract(self, messages, settings):
        self.extractions.append(messages)
        data = json.loads(messages[1]["content"])
        message = data["source"]
        if "Kristall" not in message["content"]:
            return '{"events":[]}'
        return json.dumps(
            {
                "events": [
                    {
                        "event_type": "knowledge_acquired",
                        "description": "Gehörte Aussage",
                        "confidence": 95,
                        "evidence_quote": message["content"],
                        "source_message_id": message["id"],
                        "operations": [
                            {
                                "op": "knowledge",
                                "character_id": data["recipient_id"],
                                "kind": "received",
                                "content": message["content"],
                                "confidence": 50,
                            }
                        ],
                    }
                ]
            }
        )


def setup(e, **fields):
    with e["factory"]() as db:
        power = db.get(Character, e["power"]["id"])
        power.location_id = e["glade"]["id"]
        power.revision += 1
        db.commit()
    return create(
        e["client"],
        e["path"] + "/simulations",
        title="Begegnung",
        character_ids=[e["power"]["id"], e["lumia"]["id"]],
        location_id=e["glade"]["id"],
        max_rounds=fields.pop("max_rounds", 2),
        **fields,
    )


def control(e, simulation, action, **fields):
    return e["client"].post(
        "/api" + e["path"] + f"/simulations/{simulation['id']}/control/{action}",
        json={"revision": simulation["revision"], **fields},
    )


def run(e, simulation, provider):
    with e["factory"]() as db:
        asyncio.run(step(db, simulation["id"], provider))
    return e["client"].get("/api" + e["path"] + f"/simulations/{simulation['id']}").json()


def test_two_autonomous_speakers_and_separate_private_contexts(eldoria):
    e = eldoria
    simulation = control(e, setup(e), "start").json()
    provider = SceneProvider()
    first = run(e, simulation, provider)
    final = run(e, first, provider)
    assert final["status"] == "completed" and final["completed_rounds"] == 2
    assert [m["speaker_character_id"] for m in final["messages"]] == [
        e["power"]["id"],
        e["lumia"]["id"],
    ]
    assert all(m["speaker_type"] == "character" for m in final["messages"])
    assert "Mein geheimer Kristall" in json.dumps(provider.contexts[0], ensure_ascii=False)
    assert "Mein geheimer Kristall" not in json.dumps(provider.contexts[1], ensure_ascii=False)
    assert "Ich besitze den geheimen Kristall." not in json.dumps(provider.contexts[1])
    assert final["clock"]["elapsed_minutes"] == 2
    assert final["event_counts"]["applied"] == 2
    assert sum(final["event_counts"].values()) == len(final["event_ids"])


def test_ai_claim_is_received_by_listener_not_objective_fact_and_next_turn_remembers(eldoria):
    e = eldoria
    simulation = control(e, setup(e), "start").json()
    provider = SceneProvider("Ich besitze einen blauen Kristall.")
    first = run(e, simulation, provider)
    assert first["completed_rounds"] == 1, first
    with e["factory"]() as db:
        learned = list(
            db.scalars(
                select(Knowledge).where(
                    Knowledge.character_id == e["lumia"]["id"],
                    Knowledge.origin == "event",
                )
            )
        )
        assert len(learned) == 1 and learned[0].kind == "received"
        assert (
            learned[0].confidence == 50
            and learned[0].source_message_id == first["messages"][0]["id"]
        )
        assert learned[0].source == "Aussage von Power"
        assert len(list(db.scalars(select(Knowledge).where(Knowledge.kind == "fact")))) == 1
    final = run(e, first, provider)
    assert "blauen Kristall" in json.dumps(provider.contexts[1])
    assert final["completed_rounds"] == 2


def test_pause_intervention_single_step_and_resume_are_persistent(eldoria):
    e = eldoria
    simulation = control(e, setup(e, max_rounds=4), "start", steps=1).json()
    paused = run(e, simulation, SceneProvider())
    assert paused["status"] == "paused" and paused["completed_rounds"] == 1
    response = e["client"].post(
        "/api" + e["path"] + f"/simulations/{paused['id']}/interventions",
        json={"revision": paused["revision"], "content": "Besprecht den Markt."},
    )
    assert response.status_code == 201, response.text
    intervened = response.json()
    assert intervened["messages"][-1]["speaker_type"] == "human"
    resumed = control(e, intervened, "resume", steps=1).json()
    provider = SceneProvider()
    after = run(e, resumed, provider)
    assert after["completed_rounds"] == 2 and after["status"] == "paused"
    assert "Besprecht den Markt" in json.dumps(provider.contexts)


@pytest.mark.parametrize(
    "limit,expected",
    [
        ({"max_calls": 1}, "call_limit"),
        ({"max_tokens": 1024}, "token_limit"),
    ],
)
def test_resources_stop_without_starting_extra_calls(eldoria, limit, expected):
    e = eldoria
    simulation = control(e, setup(e, **limit), "start").json()
    provider = SceneProvider("Eine konkrete Aussage.")
    final = run(e, simulation, provider)
    assert final["status"] == "completed" and final["stop_reason"] == expected, final
    count = len(provider.contexts) + len(provider.extractions)
    assert count <= limit.get("max_calls", 100)
    run(e, final, provider)
    assert len(provider.contexts) + len(provider.extractions) == count


def test_restart_is_paused_and_saved_message_is_not_regenerated(eldoria):
    e = eldoria
    simulation = control(e, setup(e), "start").json()

    class Broken(SceneProvider):
        async def extract(self, messages, settings):
            raise ProviderError("Testabbruch")

    provider = Broken("Eine konkrete Aussage.")
    failed = run(e, simulation, provider)
    assert failed["status"] == "paused" and len(failed["messages"]) == 1
    with e["factory"]() as db:
        row = db.get(Simulation, simulation["id"])
        row.status = "running"
        db.commit()
        recover(db)
    recovered = e["client"].get("/api" + e["path"] + f"/simulations/{simulation['id']}").json()
    assert recovered["status"] == "paused" and recovered["stop_reason"] == "backend_restart"
    healthy = SceneProvider()
    final = run(e, control(e, recovered, "resume").json(), healthy)
    assert final["completed_rounds"] == 1 and len(final["messages"]) == 1
    assert not healthy.contexts


def test_only_one_running_simulation_per_world_and_cancel_prevents_calls(eldoria):
    e = eldoria
    first, second = setup(e), setup(e)
    first = control(e, first, "start").json()
    assert control(e, second, "start").status_code == 409
    cancelled = control(e, first, "cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    provider = SceneProvider()
    run(e, first, provider)
    assert not provider.contexts


def test_observe_mode_does_not_change_knowledge_clock_or_state(eldoria):
    e = eldoria
    simulation = control(e, setup(e, event_mode="observe"), "start").json()
    result = run(e, simulation, SceneProvider("Ich besitze einen Kristall."))
    assert result["clock"]["elapsed_minutes"] == 0
    with e["factory"]() as db:
        assert not list(db.scalars(select(Knowledge).where(Knowledge.origin == "event")))
    events = e["client"].get("/api" + e["path"] + "/events").json()
    assert events and all(event["status"] == "protected" for event in events)
    assert act(e, events[0], "approve").status_code == 409


def test_completed_round_blocks_undo_of_earlier_observed_world_change(eldoria):
    e = eldoria
    simulation = control(e, setup(e), "start").json()
    first = run(e, simulation, SceneProvider())
    with e["factory"]() as db:
        turn = db.scalar(
            select(SimulationTurn).where(
                SimulationTurn.simulation_id == first["id"],
                SimulationTurn.number == 1,
            )
        )
        event_id = turn.clock_event_id
    run(e, first, SceneProvider())
    event = e["client"].get("/api" + e["path"] + f"/events/{event_id}").json()
    result = act(e, event, "undo")
    assert result.status_code == 409 and "Simulationsrunden" in result.json()["detail"]


def test_latest_time_change_can_be_undone_and_clock_is_not_system_time(eldoria):
    e = eldoria
    simulation = control(e, setup(e), "start", steps=1).json()
    result = run(e, simulation, SceneProvider())
    with e["factory"]() as db:
        turn = db.scalar(select(SimulationTurn).where(SimulationTurn.simulation_id == result["id"]))
        event_id = turn.clock_event_id
    event = e["client"].get("/api" + e["path"] + f"/events/{event_id}").json()
    assert act(e, event, "undo").status_code == 200
    with e["factory"]() as db:
        assert db.get(WorldClock, e["world"]["id"]).elapsed_minutes == 0


def test_generation_failure_preserves_history_and_never_automatically_retries(eldoria):
    e = eldoria
    simulation = control(e, setup(e), "start").json()

    class Broken(SceneProvider):
        async def stream(self, messages, settings):
            self.contexts.append(messages)
            yield "Unvollständig"
            raise ProviderError("Verbindung unterbrochen")

    provider = Broken()
    result = run(e, simulation, provider)
    assert result["status"] == "paused" and result["messages"] == []
    assert len(provider.contexts) == 1 and result["calls_used"] == 1


def test_simulation_history_cannot_be_edited_through_legacy_chat_routes(eldoria):
    e = eldoria
    simulation = control(e, setup(e), "start").json()
    result = run(e, simulation, SceneProvider())
    message = result["messages"][0]
    response = e["client"].put(
        f"/api/conversations/{result['conversation_id']}/messages/{message['id']}",
        json={"content": "Manipuliert", "confirm_discard": True},
    )
    assert response.status_code == 409


def test_paused_scene_change_preserves_identity_without_retroactive_hearing(eldoria):
    e = eldoria
    simulation = control(e, setup(e), "start", steps=1).json()
    paused = run(e, simulation, SceneProvider("Alter vertraulicher Gesprächsinhalt."))
    newcomer = create(
        e["client"],
        e["path"] + "/characters",
        name="Ari",
        location_id=e["glade"]["id"],
        travel_status="present",
    )
    response = e["client"].put(
        "/api" + e["path"] + f"/simulations/{paused['id']}/scene",
        json={
            "revision": paused["revision"],
            "scene": "Ein neuer Gesprächspartner kommt hinzu.",
            "location_id": e["glade"]["id"],
            "communication": "in_person",
            "character_ids": [e["lumia"]["id"], newcomer["id"]],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["conversation_id"] == paused["conversation_id"]
    provider = SceneProvider()
    resumed = control(e, response.json(), "resume", steps=1).json()
    result = run(e, resumed, provider)
    assert result["completed_rounds"] == 2
    assert result["messages"][-1]["speaker_character_id"] == newcomer["id"]
    assert "Alter vertraulicher Gesprächsinhalt" not in json.dumps(provider.contexts[0])
