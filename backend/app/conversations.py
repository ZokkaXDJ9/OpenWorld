import re

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Character,
    Conversation,
    ConversationParticipant,
    Location,
    Message,
    MessageAudience,
    WorldClock,
)


def participants(db: Session, conversation: Conversation) -> list[Character]:
    if conversation.kind == "single":
        character = db.get(Character, conversation.character_id)
        return [character] if character else []
    return list(
        db.scalars(
            select(Character)
            .join(ConversationParticipant, ConversationParticipant.character_id == Character.id)
            .where(
                ConversationParticipant.conversation_id == conversation.id,
                ConversationParticipant.active.is_(True),
            )
            .order_by(ConversationParticipant.position, Character.id)
        )
    )


def present(db: Session, conversation: Conversation) -> list[Character]:
    people = participants(db, conversation)
    if conversation.communication == "in_person":
        return [
            p
            for p in people
            if p.location_id == conversation.scene_location_id and p.travel_status == "present"
        ]
    return people


def create_group(
    db: Session,
    world_id: str,
    character_ids: list[str],
    title: str,
    scene: str,
    location_id: str,
    communication: str = "in_person",
    kind: str = "group",
) -> Conversation:
    if len(set(character_ids)) != len(character_ids) or not 2 <= len(character_ids) <= 12:
        raise HTTPException(422, "Zwei bis zwölf unterschiedliche Charaktere auswählen.")
    location = db.get(Location, location_id)
    if not location or location.world_id != world_id:
        raise HTTPException(422, "Szenenort fehlt oder gehört zu einer anderen Welt.")
    people = [db.get(Character, character_id) for character_id in character_ids]
    if any(p is None or p.world_id != world_id for p in people):
        raise HTTPException(422, "Alle Teilnehmer müssen zur gewählten Welt gehören.")
    if communication == "in_person" and any(
        p.location_id != location_id or p.travel_status != "present" for p in people if p
    ):
        raise HTTPException(
            422, "Für ein persönliches Gespräch müssen alle Teilnehmer am Szenenort sein."
        )
    conversation = Conversation(
        world_id=world_id,
        character_id=character_ids[0],
        title=title,
        scene=scene,
        scene_location_id=location_id,
        communication=communication,
        kind=kind,
    )
    db.add(conversation)
    db.flush()
    for position, character_id in enumerate(character_ids):
        db.add(
            ConversationParticipant(
                conversation_id=conversation.id,
                character_id=character_id,
                position=position,
            )
        )
    db.flush()
    return conversation


def can_hear(db: Session, message: Message, character_id: str) -> bool:
    conversation = db.get(Conversation, message.conversation_id)
    if not conversation:
        return False
    if conversation.kind == "single":
        return conversation.character_id == character_id
    return db.get(MessageAudience, (message.id, character_id)) is not None


def save_public_message(
    db: Session,
    conversation: Conversation,
    content: str,
    speaker_id: str | None,
) -> Message:
    if not content.strip() or re.search(r"</?(?:think|analysis|reasoning)>", content, re.I):
        raise HTTPException(422, "Keine leeren Antworten oder internen Denktexte veröffentlichen.")
    listeners = present(db, conversation)
    if speaker_id and speaker_id not in {person.id for person in listeners}:
        raise HTTPException(409, "Sprecher ist nicht in dieser Szene anwesend.")
    sequence = (
        db.scalar(
            select(func.max(Message.sequence)).where(
                Message.conversation_id == conversation.id,
            )
        )
        or 0
    )
    message = Message(
        conversation_id=conversation.id,
        content=content,
        sequence=sequence + 1,
        role="assistant" if speaker_id else "user",
        speaker_character_id=speaker_id,
        speaker_type="character" if speaker_id else "human",
        world_minute=(
            clock.elapsed_minutes if (clock := db.get(WorldClock, conversation.world_id)) else 0
        ),
    )
    db.add(message)
    db.flush()
    for person in listeners:
        db.add(MessageAudience(message_id=message.id, character_id=person.id))
    db.flush()
    return message
