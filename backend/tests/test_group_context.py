import json

import pytest
from fastapi import HTTPException

from app.context import build_context
from app.conversations import create_group, save_public_message
from app.models import Character, ConversationParticipant


def group(e, db):
    power = db.get(Character, e["power"]["id"])
    power.location_id = e["glade"]["id"]
    db.flush()
    return create_group(
        db,
        e["world"]["id"],
        [e["lumia"]["id"], power.id],
        "Begegnung",
        "",
        e["glade"]["id"],
    )


def test_group_context_is_built_for_each_speaker_and_keeps_one_system_message(eldoria):
    e = eldoria
    with e["factory"]() as db:
        conversation = group(e, db)
        save_public_message(db, conversation, "Guten Tag, Lumia.", e["power"]["id"])
        power, _ = build_context(db, conversation, 16384, 2048, speaker_id=e["power"]["id"])
        lumia, _ = build_context(db, conversation, 16384, 2048, speaker_id=e["lumia"]["id"])
        assert "Mein geheimer Kristall" in json.dumps(power, ensure_ascii=False)
        assert "Mein geheimer Kristall" not in json.dumps(lumia, ensure_ascii=False)
        assert "Ich besitze den geheimen Kristall." not in json.dumps(lumia, ensure_ascii=False)
        assert [m["role"] for m in power] == ["system", "assistant"]
        assert [m["role"] for m in lumia] == ["system", "user"]
        assert e["power"]["id"] in lumia[-1]["content"]


def test_only_actually_heard_messages_are_visible_after_joining(eldoria):
    e = eldoria
    with e["factory"]() as db:
        conversation = group(e, db)
        membership = db.get(ConversationParticipant, (conversation.id, e["lumia"]["id"]))
        membership.active = False
        db.flush()
        save_public_message(db, conversation, "Alte private Unterhaltung.", e["power"]["id"])
        membership.active = True
        db.flush()
        save_public_message(db, conversation, "Jetzt darfst du mithören.", e["power"]["id"])
        context, _ = build_context(db, conversation, 16384, 2048, speaker_id=e["lumia"]["id"])
        text = json.dumps(context, ensure_ascii=False)
        assert "Alte private Unterhaltung" not in text
        assert "Jetzt darfst du mithören" in text


def test_absent_characters_cannot_join_an_in_person_scene_without_moving(eldoria):
    e = eldoria
    with e["factory"]() as db:
        with pytest.raises(HTTPException):
            create_group(
                db,
                e["world"]["id"],
                [e["lumia"]["id"], e["power"]["id"]],
                "Begegnung",
                "",
                e["glade"]["id"],
            )
        remote = create_group(
            db,
            e["world"]["id"],
            [e["lumia"]["id"], e["power"]["id"]],
            "Funk",
            "Ausdrücklich definierte Funkverbindung",
            e["glade"]["id"],
            "remote",
        )
        assert remote.communication == "remote"


def test_reasoning_is_never_saved_as_public_dialogue(eldoria):
    e = eldoria
    with e["factory"]() as db:
        conversation = group(e, db)
        with pytest.raises(HTTPException):
            save_public_message(db, conversation, "<think>Geheim</think>Hallo", e["power"]["id"])


def test_scene_context_does_not_describe_departed_members_as_present(eldoria):
    e = eldoria
    with e["factory"]() as db:
        conversation = group(e, db)
        db.get(Character, e["power"]["id"]).travel_status = "traveling"
        db.flush()
        context, _ = build_context(db, conversation, 16384, 2048, speaker_id=e["lumia"]["id"])
        system = context[0]["content"]
        data, _ = json.JSONDecoder().raw_decode(system[system.index("{"):])
        assert data["scene"]["participants"] == [{"id": e["lumia"]["id"], "name": "Lumia"}]
