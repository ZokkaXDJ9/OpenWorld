from conftest import create
from test_knowledge_and_chat import send

from app.main import app
from app.provider import ProviderError


def test_failed_regeneration_preserves_previous_answer(eldoria):
    e = eldoria
    send(e, "Hallo")
    path = f"/api/conversations/{e['conversation']['id']}"
    original = e["client"].get(path + "/messages").json()

    class Failure:
        async def stream(self, messages, settings):
            assert messages[-1]["role"] == "user"
            yield "Teilantwort"
            raise ProviderError("Testfehler")

    app.state.provider = Failure()
    response = e["client"].post(path + "/regenerate")
    assert "event: error" in response.text
    assert e["client"].get(path + "/messages").json() == original
    app.state.provider = e["provider"]


def test_sourced_reference_blocks_chat_deletion_and_edit(eldoria):
    e = eldoria
    send(e, "Hallo")
    knowledge = e["client"].get("/api" + e["path"] + "/knowledge").json()
    sourced = next(k for k in knowledge if k["kind"] == "received")
    create(
        e["client"],
        e["path"] + "/locations",
        name="Archiv",
        attributes=[
            {"name": "Quelle", "type": "reference", "value": sourced["id"]},
        ],
    )
    path = f"/api/conversations/{e['conversation']['id']}"
    assert e["client"].delete(path).status_code == 409
    message = e["client"].get(path + "/messages").json()[0]
    assert (
        e["client"]
        .put(
            path + "/messages/" + message["id"],
            json={
                "content": "Geaendert",
                "confirm_discard": True,
            },
        )
        .status_code
        == 409
    )
    assert (
        e["client"]
        .delete("/api" + e["path"] + "/characters/" + e["lumia"]["id"] + "?revision=1")
        .status_code
        == 409
    )


def test_active_chat_blocks_conflicting_operations(eldoria):
    e = eldoria
    conversation_id = e["conversation"]["id"]
    app.state.active_conversations.add(conversation_id)
    path = f"/api/conversations/{conversation_id}"
    assert e["client"].post(path + "/messages", json={"content": "Hallo"}).status_code == 409
    assert e["client"].post(path + "/regenerate").status_code == 409
    assert e["client"].delete(path).status_code == 409
    assert e["client"].delete("/api" + e["path"] + "?revision=1").status_code == 409
    app.state.active_conversations.clear()


def test_sourced_information_cannot_become_cascade_deleted_world_fact(eldoria):
    e = eldoria
    send(e, "Power hat einen Kristall.")
    sourced = next(
        k
        for k in e["client"].get("/api" + e["path"] + "/knowledge").json()
        if k["kind"] == "received"
    )
    response = e["client"].put(
        "/api" + e["path"] + "/knowledge/" + sourced["id"],
        json={"kind": "fact", "content": sourced["content"], "revision": sourced["revision"]},
    )
    assert response.status_code == 422
