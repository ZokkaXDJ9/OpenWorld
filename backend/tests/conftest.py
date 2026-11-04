import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db, make_engine
from app.extraction import run_job
from app.main import app
from app.models import ExtractionJob


class RecordingProvider:
    def __init__(self):
        self.contexts = []

    async def stream(self, messages, settings):
        self.contexts.append(messages)
        yield "Hallo! "
        yield "Ich bin hier."

    async def extract(self, messages, settings):
        source = json.loads(messages[1]["content"])
        message = source["source"]
        if message["role"] != "user" or not message["content"].startswith("Power hat "):
            return '{"events":[]}'
        return json.dumps(
            {
                "events": [
                    {
                        "event_type": "knowledge_acquired",
                        "description": "Bericht über Power",
                        "confidence": 90,
                        "evidence_quote": message["content"],
                        "operations": [
                            {
                                "op": "knowledge",
                                "character_id": source["recipient_id"],
                                "kind": "received",
                                "content": message["content"],
                                "confidence": 50,
                            }
                        ],
                    }
                ]
            }
        )


def drain_jobs(factory, provider):
    with factory() as db:
        for job_id in list(
            db.scalars(select(ExtractionJob.id).where(ExtractionJob.status == "pending"))
        ):
            asyncio.run(run_job(db, job_id, provider))


@pytest.fixture
def environment(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def override_db():
        with factory() as session:
            yield session

    old_provider = app.state.provider
    provider = RecordingProvider()
    app.state.provider = provider
    app.dependency_overrides[get_db] = override_db
    app.state.active_conversations.clear()
    with TestClient(app) as client:
        yield client, factory, provider
    app.dependency_overrides.clear()
    app.state.provider = old_provider
    app.state.active_conversations.clear()
    engine.dispose()


def create(client, path, **data):
    response = client.post("/api" + path, json=data)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def eldoria(environment):
    client, factory, provider = environment
    world = create(client, "/worlds", name="Eldoria", description="Eine fantastische Welt.")
    path = f"/worlds/{world['id']}"
    shadowfang = create(client, path + "/locations", name="Shadowfang", kind="Region")
    glade = create(client, path + "/locations", name="Glade", kind="Region")
    lumia = create(
        client,
        path + "/characters",
        name="Lumia",
        location_id=glade["id"],
        travel_status="present",
        profile={"Persoenlichkeit": "Neugierig und freundlich"},
    )
    power = create(
        client,
        path + "/characters",
        name="Power",
        location_id=shadowfang["id"],
        travel_status="present",
        profile={"Geheimnisse": "Mein geheimer Kristall"},
        state={"Inventar": "Geheimer Kristall"},
    )
    fact = create(
        client,
        path + "/knowledge",
        kind="fact",
        content="Power besitzt einen geheimen Kristall.",
    )
    create(
        client,
        path + "/knowledge",
        kind="secret",
        character_id=power["id"],
        content="Ich besitze den geheimen Kristall.",
        source="Eigene Beobachtung",
    )
    response = client.put(
        "/api/settings/provider",
        json={
            "base_url": "http://localhost:11434/v1",
            "model": "test-model",
        },
    )
    assert response.status_code == 200
    conversation = create(client, path + "/conversations", character_id=lumia["id"])
    client.put("/api" + path + "/event-settings", json={"enabled": True, "revision": 1})
    return {
        "client": client,
        "factory": factory,
        "provider": provider,
        "world": world,
        "path": path,
        "lumia": lumia,
        "power": power,
        "fact": fact,
        "glade": glade,
        "shadowfang": shadowfang,
        "conversation": conversation,
    }
