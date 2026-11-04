import asyncio

from test_events import extracted_event, queue_source, state
from test_simulation import SceneProvider, control, run, setup

from app.event_schemas import EventInput
from app.events import decide_mode
from app.extraction import run_job
from app.models import EventSettings, Message


def options(e, **values):
    path = "/api" + e["path"] + "/event-settings"
    previous = e["client"].get(path).json()
    result = e["client"].put(
        path,
        json={
            "enabled": previous["enabled"],
            "revision": previous["revision"],
            **values,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_confirmation_floor_does_not_weaken_knowledge_or_protected_facts(eldoria):
    e = eldoria
    rule = e["client"].put(
        "/api" + e["path"] + "/event-rules",
        json={
            "event_type": "*",
            "object_class": "character",
            "mode": "auto",
        },
    )
    assert rule.status_code == 200
    source = Message(
        conversation_id=e["conversation"]["id"], content="Eine Beobachtung.", role="user"
    )
    body = EventInput(
        event_type="experience",
        description="Beobachtung",
        confidence=90,
        operations=[state(e, Energie=5)],
    )
    with e["factory"]() as db:
        assert decide_mode(db, e["world"]["id"], body, source)[0] == "auto"
    options(e, confirm_changes=True)
    with e["factory"]() as db:
        assert decide_mode(db, e["world"]["id"], body, source)[0] == "confirm"
        assert decide_mode(db, e["world"]["id"], body, None)[0] == "auto"
        body = EventInput(
            event_type="experience",
            description="Beobachtung",
            confidence=90,
            operations=[
                {
                    "op": "knowledge",
                    "character_id": e["lumia"]["id"],
                    "kind": "received",
                    "content": source.content,
                    "confidence": 50,
                }
            ],
        )
        assert decide_mode(db, e["world"]["id"], body, source)[0] == "auto"
        body.operations[0].kind = "fact"
        assert decide_mode(db, e["world"]["id"], body, source)[0] == "protected"


def test_disabling_skips_pending_jobs_and_prevents_simulation_extraction(eldoria):
    e = eldoria
    _, job_id = queue_source(e)
    before = e["client"].get("/api" + e["path"] + "/knowledge").json()
    options(e, enabled=False, automation_disabled=True)
    jobs = e["client"].get("/api" + e["path"] + "/extraction-jobs").json()
    assert jobs[0]["id"] == job_id and jobs[0]["status"] == "skipped"
    provider = SceneProvider("Ich besitze einen blauen Kristall.")
    result = run(e, control(e, setup(e, max_rounds=1), "start").json(), provider)
    assert result["completed_rounds"] == 1 and not provider.extractions
    assert result["calls_used"] == 1 and result["clock"]["elapsed_minutes"] == 1
    assert e["client"].get("/api" + e["path"] + "/knowledge").json() == before


def test_disabling_during_an_in_flight_extraction_does_not_apply_its_output(eldoria):
    e = eldoria
    _, job_id = queue_source(e)
    before = e["client"].get("/api" + e["path"] + "/knowledge").json()

    class InFlight:
        async def extract(self, messages, settings):
            import json

            options(e, enabled=False, automation_disabled=True)
            return json.dumps({"events": [extracted_event(e)]})

    with e["factory"]() as db:
        asyncio.run(run_job(db, job_id, InFlight()))
    assert e["client"].get("/api" + e["path"] + "/knowledge").json() == before
    with e["factory"]() as db:
        assert db.get(EventSettings, e["world"]["id"]).automation_disabled


def test_new_simulation_can_explicitly_run_without_additional_memory_calls(eldoria):
    e = eldoria
    provider = SceneProvider("Ich besitze einen blauen Kristall.")
    result = run(
        e, control(e, setup(e, max_rounds=1, recognize_events=False), "start").json(), provider
    )
    assert result["completed_rounds"] == 1 and result["calls_used"] == 1
    assert not result["jobs"] and not provider.extractions
