import json

import pytest
import tiktoken
from conftest import create
from sqlalchemy import select

from app.context import ContextTooLarge, build_context
from app.models import Conversation, Knowledge, Message
from app.provider import ProviderError


def send(e, text):
    response = e["client"].post(
        f"/api/conversations/{e['conversation']['id']}/messages",
        json={"content": text},
    )
    assert response.status_code == 200, response.text
    assert "event: done" in response.text, response.text
    return response


def test_eldoria_acceptance_and_persistent_continuation(eldoria):
    e = eldoria
    send(e, "Hallo Lumia.")
    context = json.dumps(e["provider"].contexts[-1], ensure_ascii=False)
    assert "Kristall" not in context
    assert "Shadowfang" not in context
    assert "Glade" in context

    claim = "Power hat einen Kristall gefunden."
    send(e, claim)
    rows = e["client"].get("/api" + e["path"] + "/knowledge").json()
    received = [r for r in rows if r["kind"] == "received" and r["content"] == claim]
    assert len(received) == 1
    assert received[0]["character_id"] == e["lumia"]["id"]
    assert received[0]["source"] == "Benutzeraussage"
    assert received[0]["source_message_id"]
    assert not any(r["kind"] == "received" and r["character_id"] == e["power"]["id"] for r in rows)
    assert next(r for r in rows if r["id"] == e["fact"]["id"]) == e["fact"]
    power = next(
        c
        for c in e["client"].get("/api" + e["path"] + "/characters").json()
        if c["id"] == e["power"]["id"]
    )
    assert power["state"] == {"Inventar": "Geheimer Kristall"}

    next_conversation = create(
        e["client"],
        e["path"] + "/conversations",
        character_id=e["lumia"]["id"],
    )
    e["conversation"] = next_conversation
    send(e, "Erinnerst du dich an Power?")
    context = json.dumps(e["provider"].contexts[-1], ensure_ascii=False)
    assert claim in context
    assert "Benutzeraussage" in context
    assert e["fact"]["content"] not in context
    with e["factory"]() as session:
        memories = list(
            session.scalars(
                select(Knowledge).where(
                    Knowledge.character_id == e["lumia"]["id"],
                )
            )
        )
        assert any(memory.content == claim for memory in memories)


def test_subjective_false_beliefs_and_public_facts(eldoria):
    e = eldoria
    create(
        e["client"],
        e["path"] + "/knowledge",
        kind="belief",
        character_id=e["lumia"]["id"],
        content="Power ist tot.",
        confidence=95,
    )
    create(
        e["client"],
        e["path"] + "/knowledge",
        kind="memory",
        character_id=e["lumia"]["id"],
        content="Ich traf Power gestern.",
        confidence=60,
    )
    create(
        e["client"],
        e["path"] + "/knowledge",
        kind="fact",
        content="Eldoria hat zwei Monde.",
        public=True,
    )
    send(e, "Was weisst du?")
    context = "\n".join(message["content"] for message in e["provider"].contexts[-1])
    assert "Power ist tot." in context and '"kind": "belief"' in context
    assert "Ich traf Power gestern." in context and '"kind": "memory"' in context
    assert "Eldoria hat zwei Monde." in context
    assert e["fact"]["content"] not in context


def test_reverse_relationship_does_not_leak(eldoria):
    e = eldoria
    create(
        e["client"],
        e["path"] + "/relationships",
        source_id=e["power"]["id"],
        target_id=e["lumia"]["id"],
        secret=True,
        description="Ich plane einen Hinterhalt.",
    )
    send(e, "Was haelt Power von dir?")
    assert "Hinterhalt" not in json.dumps(e["provider"].contexts[-1])


def test_chat_edit_removes_descendants_and_updates_provenance(eldoria):
    e = eldoria
    send(e, "Power hat einen Kristall.")
    send(e, "Eine weitere Aussage.")
    path = f"/api/conversations/{e['conversation']['id']}/messages"
    original = e["client"].get(path).json()
    message = original[0]
    assert (
        e["client"]
        .put(
            path + "/" + message["id"],
            json={
                "content": "Power hat einen Apfel.",
            },
        )
        .status_code
        == 409
    )
    response = e["client"].put(
        path + "/" + message["id"],
        json={
            "content": "Power hat einen Apfel.",
            "confirm_discard": True,
        },
    )
    assert response.status_code == 200
    assert len(e["client"].get(path).json()) == 1
    rows = e["client"].get("/api" + e["path"] + "/knowledge").json()
    personal = [r for r in rows if r["character_id"] == e["lumia"]["id"]]
    assert len(personal) == 1
    assert personal[0]["content"] == "Power hat einen Apfel."
    assert any(r["id"] == e["fact"]["id"] for r in rows)
    regenerated = e["client"].post(f"/api/conversations/{e['conversation']['id']}/regenerate")
    assert "event: done" in regenerated.text
    assert len(e["client"].get(path).json()) == 2


def test_regeneration_replaces_only_latest_answer(eldoria):
    e = eldoria
    send(e, "Hallo")
    path = f"/api/conversations/{e['conversation']['id']}"
    old = e["client"].get(path + "/messages").json()
    result = e["client"].post(path + "/regenerate")
    assert "event: done" in result.text
    new = e["client"].get(path + "/messages").json()
    assert len(new) == 2
    assert old[0]["id"] == new[0]["id"]
    assert old[1]["id"] != new[1]["id"]


def test_provider_failure_is_explicit_and_retryable(eldoria):
    from app.main import app

    class Failure:
        async def stream(self, messages, settings):
            yield "Unvollstaendige Antwort"
            raise ProviderError("Verbindung fehlgeschlagen")

    e = eldoria
    app.state.provider = Failure()
    path = f"/api/conversations/{e['conversation']['id']}"
    response = e["client"].post(path + "/messages", json={"content": "Hallo"})
    assert "event: error" in response.text
    assert "event: done" not in response.text
    assert [m["role"] for m in e["client"].get(path + "/messages").json()] == ["user"]
    app.state.provider = e["provider"]
    assert "event: done" in e["client"].post(path + "/regenerate").text


def test_no_provider_needed_for_editors(environment):
    client, _, _ = environment
    world = create(client, "/worlds", name="Offline")
    character = create(client, f"/worlds/{world['id']}/characters", name="Lumia")
    conversation = create(
        client, f"/worlds/{world['id']}/conversations", character_id=character["id"]
    )
    response = client.post(
        f"/api/conversations/{conversation['id']}/messages", json={"content": "Hallo"}
    )
    assert response.status_code == 422
    assert client.get(f"/api/conversations/{conversation['id']}/messages").json() == []


def test_large_context_and_exact_budget(eldoria):
    e = eldoria
    with e["factory"]() as db:
        db.add(
            Knowledge(
                world_id=e["world"]["id"],
                character_id=e["lumia"]["id"],
                kind="memory",
                content="Eldoria Geschichte " * 22000,
                source="Archiv",
            )
        )
        db.commit()
        conversation = db.get(Conversation, e["conversation"]["id"])
        messages, count = build_context(db, conversation, 131072, 2048)
        encoding = tiktoken.get_encoding("cl100k_base")
        assert count == sum(
            len(encoding.encode(m["content"], disallowed_special=())) + 8 for m in messages
        )
        assert 32768 < count <= 131072 - 2048 - 256
        _, larger_count = build_context(db, conversation, 262144, 2048)
        assert larger_count >= count
        smaller, small_count = build_context(db, conversation, 2048, 512)
        assert small_count <= 2048 - 512 - 256
        assert len(smaller) < len(messages)
        db.add(
            Message(
                conversation_id=conversation.id, role="user", content="Wort " * 2000, sequence=1
            )
        )
        db.commit()
        with pytest.raises(ContextTooLarge):
            build_context(db, conversation, 2048, 512)


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "fact", "content": "Falsch", "character_id": "missing"},
        {"kind": "secret", "content": "Geheim"},
        {"kind": "belief", "content": "Falsch", "character_id": "missing", "public": True},
    ],
)
def test_invalid_knowledge_scope(eldoria, data):
    response = eldoria["client"].post("/api" + eldoria["path"] + "/knowledge", json=data)
    assert response.status_code == 422
