"""Validated proposals and reversible world mutations; callers own the transaction."""

import re
from copy import deepcopy
from typing import NoReturn

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .conversations import can_hear
from .event_bindings import (
    reject_relationship_state_aliases,
    relationship_binding,
    state_binding,
)
from .event_schemas import (
    ArchiveOperation,
    ClockOperation,
    EventInput,
    KnowledgeOperation,
    LocationOperation,
    RelationshipOperation,
    RelationshipValue,
    StateOperation,
    TransferOperation,
)
from .models import (
    Character,
    Conversation,
    Event,
    EventAudit,
    EventMutation,
    EventParticipant,
    EventProposal,
    EventRule,
    EventSource,
    EventTarget,
    ExtractionJob,
    ExtractionJobSource,
    Knowledge,
    KnowledgeLink,
    Location,
    Message,
    Relationship,
    Simulation,
    SimulationDependency,
    World,
    WorldClock,
    now,
)
from .schemas import Attribute
from .serialization import encode

ENTITY_MODELS = {
    "world": World,
    "character": Character,
    "location": Location,
    "relationship": Relationship,
    "knowledge": Knowledge,
    "clock": WorldClock,
}


def fail(detail: str, status: int = 422) -> NoReturn:
    raise HTTPException(status, detail)


def entity(db: Session, kind: str, item_id: str, world_id: str):
    row = db.get(ENTITY_MODELS[kind], item_id)
    if row is None or (row.id if kind in {"world", "clock"} else row.world_id) != world_id:
        fail("Ereignisreferenz fehlt oder gehört zu einer anderen Welt")
    return row


def audit(db: Session, event: Event, action: str, actor: str, **detail):
    sequence = db.scalar(
        select(func.max(EventAudit.sequence)).where(EventAudit.event_id == event.id)
    )
    db.add(
        EventAudit(
            event_id=event.id,
            action=action,
            actor=actor,
            detail=detail,
            sequence=0 if sequence is None else sequence + 1,
        )
    )


def compare_and_set(db: Session, row, values: dict, revision: int):
    result = db.execute(
        update(type(row))
        .where(type(row).id == row.id, type(row).revision == revision)
        .values(**values, revision=revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        fail("Abhängige Daten wurden inzwischen geändert. Bitte neu laden.", 409)
    db.refresh(row)


def proposal_for(db: Session, event_id: str) -> EventProposal:
    proposal = db.scalar(select(EventProposal).where(EventProposal.event_id == event_id))
    if proposal is None:
        fail("Änderungsvorschlag fehlt", 404)
    return proposal


def validate_event(db: Session, world_id: str, body: EventInput, message: Message | None):
    entity(db, "world", world_id, world_id)
    for participant in body.participant_ids:
        entity(db, "character", participant, world_id)
    if body.location_id:
        entity(db, "location", body.location_id, world_id)
    conversation = db.get(Conversation, message.conversation_id) if message else None
    recipient_id = body.recipient_id or (conversation.character_id if conversation else None)
    own_speech = bool(message and conversation and message.speaker_character_id == recipient_id)
    if message:
        if not conversation or conversation.world_id != world_id or message.status != "complete":
            fail("Nur gespeicherte vollständige Nachrichten dürfen Ereignisse auslösen")
        if not body.evidence_quote.strip() or body.evidence_quote not in message.content:
            fail("Vorschlag benötigt ein wörtliches Quellenzitat aus der Nachricht")
        if message.speaker_character_id:
            entity(db, "character", message.speaker_character_id, world_id)
        if not recipient_id or not can_hear(db, message, recipient_id):
            fail("Empfänger hat diese Nachricht nicht wahrgenommen")
    seen_targets: set[tuple[str, str]] = set()
    corrected_ids: set[str] = set()
    for operation in body.operations:
        if isinstance(operation, KnowledgeOperation):
            if operation.character_id:
                entity(db, "character", operation.character_id, world_id)
            if operation.subject_id:
                entity(db, "character", operation.subject_id, world_id)
            if conversation:
                if operation.character_id != recipient_id:
                    fail("Extraktion darf nur den Wissensstand des Gesprächsempfängers ändern")
                if operation.kind not in {"received", "memory", "belief", "suspicion", "rumor"}:
                    fail(
                        "Erzählungen dürfen keine objektiven Fakten "
                        "oder verifiziertes Wissen erzeugen"
                    )
                if operation.kind == "received" and operation.confidence > 50:
                    fail("Eine erhaltene Behauptung ist nicht verifiziert; maximal 50 % Vertrauen")
                if (
                    message
                    and operation.kind == "received"
                    and operation.content not in message.content
                ):
                    fail("Erhaltene Informationen müssen die originale Quellenaussage wiedergeben")
            for old_id in operation.supersedes + operation.contradicts:
                old = entity(db, "knowledge", old_id, world_id)
                if old.character_id != operation.character_id or old.kind == "fact":
                    fail("Wissenskorrekturen müssen im selben persönlichen Wissensstand bleiben")
                if old.status != "active":
                    fail("Zu korrigierendes Wissen ist nicht mehr aktuell", 409)
            for old_id in operation.supersedes:
                if old_id in corrected_ids or ("knowledge", old_id) in seen_targets:
                    fail("Ein Wissenseintrag darf nicht zweimal ersetzt werden")
                corrected_ids.add(old_id)
                seen_targets.add(("knowledge", old_id))
        else:
            if conversation and isinstance(operation, ArchiveOperation):
                fail("KI-Extraktion darf keine bestehenden Informationen entfernen")
            kind = (
                operation.entity_type
                if isinstance(operation, StateOperation)
                else "relationship"
                if isinstance(operation, RelationshipOperation)
                else "knowledge"
                if isinstance(operation, ArchiveOperation)
                else "clock"
                if isinstance(operation, ClockOperation)
                else "character"
            )
            target = entity(db, kind, operation.entity_id, world_id)
            key = (kind, target.id)
            if key in seen_targets:
                fail("Mehrere Änderungen desselben Objekts bitte in einer Operation zusammenfassen")
            seen_targets.add(key)
            if target.revision != operation.revision:
                fail("Vorschlag beruht auf einer veralteten Objektrevision", 409)
            if isinstance(operation, ClockOperation) and message:
                fail("Die Weltzeit darf nicht aus einer Modellbehauptung geändert werden")
            if isinstance(operation, TransferOperation):
                receiver = entity(db, "character", operation.target_id, world_id)
                if receiver.id == target.id or receiver.revision != operation.target_revision:
                    fail("Empfänger oder Revision der Übergabe ist ungültig", 409)
                receiver_key = ("character", receiver.id)
                if receiver_key in seen_targets:
                    fail("Übergabe überschneidet sich mit einer weiteren Charakteränderung")
                seen_targets.add(receiver_key)
                transfer_values(target, receiver, operation.item)
                if (
                    target.location_id is None
                    or receiver.location_id != target.location_id
                    or target.travel_status != "present"
                    or receiver.travel_status != "present"
                ):
                    fail("Gegenstände können nur zwischen anwesenden Charakteren übergeben werden")
                if message and (
                    message.speaker_character_id != target.id
                    or not can_hear(db, message, receiver.id)
                    or operation.item not in body.evidence_quote
                    or receiver.name not in body.evidence_quote
                    or not re.search(
                        r"\b(?:gebe|gibt|übergebe|übergibt|gives|hands)\b",
                        body.evidence_quote,
                        re.I,
                    )
                    or re.search(
                        r"\b(?:nicht|will|werde|möchte|soll|would|might)\b",
                        body.evidence_quote,
                        re.I,
                    )
                ):
                    fail("Eine Übergabe benötigt die belegte ausgeführte Handlung des Besitzers")
            if conversation and message:
                if kind == "character" and target.id != recipient_id:
                    fail("Kein Zugriff auf den privaten Zustand anderer Charaktere")
                if kind == "relationship" and target.source_id != recipient_id:
                    fail("Keine Änderung fremder Beziehungseinschätzungen")
                if isinstance(operation, StateOperation):
                    if "Inventar" in operation.values:
                        fail("Inventaränderungen benötigen eine validierte transfer-Operation")
                    if kind == "character":
                        reject_relationship_state_aliases(db, target, body.evidence_quote)
                    state_binding(
                        target,
                        operation.values,
                        body.evidence_quote,
                        own_speech,
                        operation.value_quotes,
                    )
                if isinstance(operation, LocationOperation):
                    if (
                        operation.travel_status == "present"
                        and operation.location_id != target.location_id
                    ):
                        if (
                            target.travel_status != "traveling"
                            or target.destination_id != operation.location_id
                        ):
                            fail("Ankunft benötigt zuvor eine Reise zu genau diesem Zielort")
                    if operation.travel_status == "traveling" and (
                        not operation.destination_id
                        or operation.location_id != target.location_id
                        or operation.destination_id == target.location_id
                    ):
                        fail("Reisebeginn benötigt vorhandenen Ausgangs- und anderen Zielort")
                    if (
                        message.speaker_character_id != target.id
                        or re.search(
                            r"\b(?:will|werde|möchte|soll|nicht|would|might|morgen)\b",
                            body.evidence_quote,
                            re.I,
                        )
                        or not re.search(
                            r"\b(?:verlasse|verlässt|reise|reist|beginne|beginnt|betrete|betritt|"
                            r"erreiche|erreicht|arrive|arrives|leave|leaves|travel|travels)\b",
                            body.evidence_quote,
                            re.I,
                        )
                    ):
                        fail(
                            "Ortsänderung benötigt eine ausgeführte Handlung des aktiven Charakters"
                        )
                    destination_id = operation.destination_id or operation.location_id
                    if destination_id:
                        destination = entity(db, "location", destination_id, world_id)
                        if destination.name.casefold() not in body.evidence_quote.casefold():
                            fail("Zielort ist im Handlungsbeleg nicht genannt")
            if isinstance(operation, RelationshipOperation):
                if operation.target_id is not None and operation.target_id != target.target_id:
                    fail("Zielcharakter passt nicht zur gerichteten Beziehung")
                existing = {attribute["name"]: attribute for attribute in target.attributes}
                if len({name.casefold() for name in existing}) != len(target.attributes):
                    fail("Mehrdeutige Attributdefinitionen in der bestehenden Beziehung")
                resolved: list[Attribute] = []
                for attribute in operation.attributes:
                    old = existing.get(attribute.name)
                    if not old:
                        fail("Beziehungsänderungen benötigen ein bestehendes Attribut")
                    if isinstance(attribute, RelationshipValue):
                        try:
                            attribute = Attribute.model_validate({**old, "value": attribute.value})
                        except ValidationError as exc:
                            reason = exc.errors(include_input=False, include_url=False)[0]["msg"]
                            fail(f"Wert passt nicht zur bestehenden Attributdefinition: {reason}")
                    unchanged = attribute.model_dump(exclude={"value"})
                    old_definition = {key: value for key, value in old.items() if key != "value"}
                    if unchanged != old_definition:
                        fail("Eine Ereignisänderung darf keine Attributdefinition umschreiben")
                    if attribute.type == "reference":
                        fail("Referenzattribute sind keine unterstützte Beziehungsoperation")
                    resolved.append(attribute)
                operation.attributes[:] = resolved
                if conversation and recipient_id:
                    relationship_binding(
                        db,
                        target,
                        entity(db, "character", recipient_id, world_id),
                        operation.target_id,
                        resolved,
                        operation.attribute_quotes,
                        body.evidence_quote,
                        own_speech,
                    )
            if isinstance(operation, LocationOperation):
                for location_id in (operation.location_id, operation.destination_id):
                    if location_id:
                        entity(db, "location", location_id, world_id)
            if isinstance(operation, ArchiveOperation):
                if target.kind == "fact":
                    fail("Weltfakten dürfen nicht über eine Erinnerungsoperation entfernt werden")
                if target.status != "active":
                    fail("Erinnerung ist nicht mehr aktuell", 409)
                assert_not_referenced(db, world_id, target.id)


def operation_class(operation) -> str:
    if isinstance(operation, (KnowledgeOperation, ArchiveOperation)):
        return "knowledge"
    if isinstance(operation, StateOperation):
        return operation.entity_type
    if isinstance(operation, ClockOperation):
        return "clock"
    return "relationship" if isinstance(operation, RelationshipOperation) else "character"


def transfer_values(giver: Character, receiver: Character, item: str) -> tuple[dict, dict]:
    held = giver.state.get("Inventar", [])
    received = receiver.state.get("Inventar", [])
    if (
        not isinstance(held, list)
        or not isinstance(received, list)
        or any(not isinstance(value, str) for value in held + received)
    ):
        fail("Für Übergaben Inventar im Editor als Liste von Gegenstandsnamen anlegen")
    if item not in held:
        fail("Übergabe nicht ausführbar: Der Charakter besitzt diesen Gegenstand nicht")
    remaining = list(held)
    remaining.remove(item)
    return (
        {**giver.state, "Inventar": remaining},
        {**receiver.state, "Inventar": [*received, item]},
    )


def preview_operations(db: Session, world_id: str, body: EventInput) -> list[dict]:
    preview = []
    for operation in body.operations:
        kind = operation_class(operation)
        if isinstance(operation, KnowledgeOperation):
            preview.append(
                {
                    "entity_type": kind,
                    "entity_id": None,
                    "before": {},
                    "after": {"kind": operation.kind, "content": operation.content},
                }
            )
            continue
        row = entity(db, kind, operation.entity_id, world_id)
        if isinstance(operation, TransferOperation):
            receiver = entity(db, "character", operation.target_id, world_id)
            giver_state, receiver_state = transfer_values(row, receiver, operation.item)
            for person, state in ((row, giver_state), (receiver, receiver_state)):
                preview.append(
                    {
                        "entity_type": "character",
                        "entity_id": person.id,
                        "before": {"state": deepcopy(person.state)},
                        "after": {"state": state},
                    }
                )
            continue
        if isinstance(operation, StateOperation):
            after = {"state": {**row.state, **operation.values}}
        elif isinstance(operation, RelationshipOperation):
            replacement = {a.name: a.model_dump() for a in operation.attributes}
            after = {"attributes": [replacement.get(a["name"], a) for a in row.attributes]}
        elif isinstance(operation, ArchiveOperation):
            after = {"status": "archived"}
        else:
            after = operation.model_dump(exclude={"op", "entity_id", "revision"})
        preview.append(
            {
                "entity_type": kind,
                "entity_id": row.id,
                "before": {key: deepcopy(getattr(row, key)) for key in after},
                "after": after,
            }
        )
    return preview


def decide_mode(db: Session, world_id: str, body: EventInput, message: Message | None):
    modes = ["auto"]
    reasons = []
    for operation in body.operations:
        witnessed_claim = bool(
            message
            and body.recipient_id
            and isinstance(operation, KnowledgeOperation)
            and operation.kind == "received"
            and message.speaker_character_id != body.recipient_id
            and operation.content in message.content
        )
        validated_action = bool(
            message
            and body.recipient_id
            and body.recipient_id == message.speaker_character_id
            and isinstance(
                operation,
                (TransferOperation, LocationOperation, StateOperation, RelationshipOperation),
            )
        )
        kind = operation_class(operation)
        protected = kind in {"world", "location"} or (
            isinstance(operation, KnowledgeOperation) and operation.kind == "fact"
        )
        default = (
            "auto"
            if isinstance(operation, KnowledgeOperation)
            and operation.kind in {"received", "memory", "belief", "suspicion", "rumor"}
            and not operation.supersedes
            else "confirm"
        )
        matching = list(
            db.scalars(
                select(EventRule).where(
                    EventRule.world_id == world_id,
                    EventRule.event_type.in_(["*", body.event_type]),
                    EventRule.object_class.in_(["*", kind]),
                )
            )
        )
        matching.sort(
            key=lambda rule: (rule.event_type != "*", rule.object_class != "*"), reverse=True
        )
        mode = matching[0].mode if matching else default
        if protected:
            mode = "protected"
        elif (
            message
            and (
                (message.role != "user" and not witnessed_claim and not validated_action)
                or message.content.rstrip().endswith("?")
                or body.confidence < 60
                or isinstance(operation, KnowledgeOperation)
                and operation.content not in message.content
            )
            and mode == "auto"
        ):
            mode = "confirm"
        modes.append(mode)
        reasons.append(f"{kind}: {mode}")
    simulation = (
        db.scalar(
            select(Simulation).where(
                Simulation.conversation_id == message.conversation_id,
            )
        )
        if message
        else None
    )
    if simulation and simulation.event_mode != "rules":
        mode = "protected" if simulation.event_mode == "observe" else "confirm"
        modes.append(mode)
        reasons.append("Simulationsfreigabe: " + mode)
    return max(modes, key={"auto": 0, "confirm": 1, "protected": 2}.__getitem__), "; ".join(reasons)


def add_target(db: Session, event_id: str, kind: str, item_id: str):
    exists = db.scalar(
        select(EventTarget.id).where(
            EventTarget.event_id == event_id,
            EventTarget.entity_type == kind,
            EventTarget.entity_id == item_id,
        )
    )
    if not exists:
        db.add(EventTarget(event_id=event_id, entity_type=kind, entity_id=item_id))
        db.flush()


def record_change(db: Session, event: Event, kind: str, row, values: dict):
    before = {key: deepcopy(getattr(row, key)) for key in values}
    revision = row.revision
    compare_and_set(db, row, values, revision)
    sequence = (
        db.scalar(
            select(func.count())
            .select_from(EventMutation)
            .where(EventMutation.event_id == event.id)
        )
        or 0
    )
    db.add(
        EventMutation(
            event_id=event.id,
            sequence=sequence,
            entity_type=kind,
            entity_id=row.id,
            before=before,
            after=deepcopy(values),
            revision_before=revision,
            revision_after=row.revision,
        )
    )
    add_target(db, event.id, kind, row.id)


def record_editor_change(db: Session, row, before: dict, after: dict, revision: int):
    kind = next(key for key, model in ENTITY_MODELS.items() if isinstance(row, model))
    world_id = row.id if kind == "world" else row.world_id
    event = Event(
        world_id=world_id,
        event_type="manual_change",
        description="Manuelle Änderung im Editor",
        occurred_at=now(),
        source="editor",
        status="applied",
        confidence=100,
    )
    db.add(event)
    db.flush()
    db.add(
        EventProposal(
            event_id=event.id,
            operations=[],
            mode="confirm",
            reason="Bewusste manuelle Editoraktion",
            preview=[{"entity_type": kind, "entity_id": row.id, "before": before, "after": after}],
        )
    )
    db.add(
        EventMutation(
            event_id=event.id,
            sequence=0,
            entity_type=kind,
            entity_id=row.id,
            before=before,
            after=after,
            revision_before=revision,
            revision_after=revision + 1,
        )
    )
    add_target(db, event.id, kind, row.id)
    participants = (
        {row.id}
        if kind == "character"
        else {row.source_id, row.target_id}
        if kind == "relationship"
        else {row.character_id}
        if kind == "knowledge" and row.character_id
        else set()
    )
    for participant_id in participants:
        db.add(EventParticipant(event_id=event.id, character_id=participant_id))
    audit(db, event, "applied", "user", editor=True)


def apply_event(db: Session, event: Event, revision: int, actor: str):
    if event.status != "proposed":
        fail("Nur offene Vorschläge können übernommen werden", 409)
    proposal = proposal_for(db, event.id)
    if proposal.mode == "protected":
        fail("Geschützte Änderungen sind ausschließlich im manuellen Editor zulässig", 409)
    body = EventInput(
        event_type=event.event_type,
        description=event.description,
        operations=proposal.operations,
        confidence=event.confidence,
    )
    # Validate current references and revisions again, not just extraction-time input.
    validate_event(db, event.world_id, body, None)
    sources = list(db.scalars(select(EventSource).where(EventSource.event_id == event.id)))
    if sources:
        body = body.model_copy(update={"recipient_id": sources[0].recipient_id})
    for source in sources:
        source_message = db.get(Message, source.message_id) if source.message_id else None
        if not source_message or source_message.revision != source.message_revision:
            fail("Die Quelle wurde geändert oder gelöscht", 409)
        source_body = body.model_copy(
            update={
                "evidence_quote": source.quote,
                "recipient_id": source.recipient_id,
            }
        )
        validate_event(db, event.world_id, source_body, source_message)
    current_mode, reason = decide_mode(
        db,
        event.world_id,
        body,
        db.get(Message, sources[0].message_id) if sources else None,
    )
    if current_mode == "protected" or (actor == "auto" and current_mode != "auto"):
        fail("Die aktuellen Regeln erlauben diese Übernahme nicht", 409)
    compare_and_set(db, event, {"status": "applied"}, revision)
    for operation in body.operations:
        if isinstance(operation, KnowledgeOperation):
            source = sources[0] if sources else None
            speaker = (
                db.get(Character, source.speaker_character_id)
                if (source and source.speaker_character_id)
                else None
            )
            row = Knowledge(
                world_id=event.world_id,
                character_id=operation.character_id,
                subject_id=operation.subject_id,
                kind=operation.kind,
                content=operation.content,
                confidence=operation.confidence,
                importance=operation.importance,
                emotion=operation.emotion,
                event_id=event.id,
                occurred_at=event.occurred_at,
                origin="event",
                source_message_id=source.message_id if source else None,
                source=f"Aussage von {speaker.name}"
                if speaker
                else "Benutzeraussage"
                if source and source.role == "user"
                else "Charakteraussage"
                if source
                else operation.source,
                public=False,
            )
            db.add(row)
            db.flush()
            sequence = (
                db.scalar(
                    select(func.count())
                    .select_from(EventMutation)
                    .where(EventMutation.event_id == event.id)
                )
                or 0
            )
            db.add(
                EventMutation(
                    event_id=event.id,
                    sequence=sequence,
                    entity_type="knowledge",
                    entity_id=row.id,
                    before={},
                    after={"status": "active"},
                    revision_before=0,
                    revision_after=1,
                )
            )
            add_target(db, event.id, "knowledge", row.id)
            for old_id in operation.supersedes:
                old = entity(db, "knowledge", old_id, event.world_id)
                record_change(db, event, "knowledge", old, {"status": "superseded"})
                db.add(KnowledgeLink(source_id=row.id, target_id=old_id, relation="supersedes"))
            for old_id in operation.contradicts:
                db.add(KnowledgeLink(source_id=row.id, target_id=old_id, relation="contradicts"))
        else:
            kind = operation_class(operation)
            row = entity(db, kind, operation.entity_id, event.world_id)
            if isinstance(operation, TransferOperation):
                receiver = entity(db, "character", operation.target_id, event.world_id)
                giver_state, receiver_state = transfer_values(row, receiver, operation.item)
                record_change(db, event, "character", row, {"state": giver_state})
                record_change(db, event, "character", receiver, {"state": receiver_state})
                continue
            if isinstance(operation, StateOperation):
                values = {"state": {**row.state, **operation.values}}
            elif isinstance(operation, ArchiveOperation):
                values = {"status": "archived"}
            elif isinstance(operation, RelationshipOperation):
                replacement = {a.name: a.model_dump() for a in operation.attributes}
                values = {"attributes": [replacement.get(a["name"], a) for a in row.attributes]}
            else:
                values = operation.model_dump(exclude={"op", "entity_id", "revision"})
            record_change(db, event, kind, row, values)
    proposal.reason = reason
    audit(db, event, "applied", actor)
    db.flush()
    return event


def create_event(
    db: Session,
    world_id: str,
    body: EventInput,
    message: Message | None = None,
    mode_override: str | None = None,
):
    validate_event(db, world_id, body, message)
    mode, reason = decide_mode(db, world_id, body, message)
    if mode_override in {"confirm", "protected"} and mode != "protected":
        mode = mode_override
        reason = "Simulationsfreigabe: " + mode
    event = Event(
        world_id=world_id,
        event_type=body.event_type,
        description=body.description,
        occurred_at=body.occurred_at or (message.created_at if message else now()),
        source="conversation" if message else "manual",
        world_minute=message.world_minute
        if message
        else (clock.elapsed_minutes if (clock := db.get(WorldClock, world_id)) else None),
        confidence=body.confidence,
        location_id=body.location_id,
        status="protected" if mode == "protected" else "proposed",
    )
    db.add(event)
    db.flush()
    db.add(
        EventProposal(
            event_id=event.id,
            operations=[operation.model_dump() for operation in body.operations],
            preview=preview_operations(db, world_id, body),
            mode=mode,
            reason=reason,
        )
    )
    sync_proposal_references(db, event, body, message)
    if message:
        db.add(
            EventSource(
                recipient_id=body.recipient_id,
                event_id=event.id,
                message_id=message.id,
                message_revision=message.revision,
                conversation_id=message.conversation_id,
                role=message.role,
                quote=body.evidence_quote,
                speaker_character_id=message.speaker_character_id,
            )
        )
    audit(db, event, "proposed", "extractor" if message else "user", mode=mode)
    db.flush()
    if not body.operations:
        compare_and_set(db, event, {"status": "recorded"}, event.revision)
    elif mode == "auto":
        apply_event(db, event, event.revision, "auto")
    return event


def sync_proposal_references(
    db: Session,
    event: Event,
    body: EventInput,
    message: Message | None = None,
):
    db.execute(delete(EventParticipant).where(EventParticipant.event_id == event.id))
    db.execute(delete(EventTarget).where(EventTarget.event_id == event.id))
    participants = set(body.participant_ids)
    if message and message.speaker_character_id:
        participants.add(message.speaker_character_id)
    for operation in body.operations:
        if isinstance(operation, KnowledgeOperation):
            participants.update(filter(None, (operation.character_id, operation.subject_id)))
            for old_id in operation.supersedes + operation.contradicts:
                add_target(db, event.id, "knowledge", old_id)
        else:
            kind = operation_class(operation)
            add_target(db, event.id, kind, operation.entity_id)
            if kind == "character":
                participants.add(operation.entity_id)
                if isinstance(operation, TransferOperation):
                    participants.add(operation.target_id)
                    add_target(db, event.id, "character", operation.target_id)
            elif kind == "relationship":
                relationship = entity(db, kind, operation.entity_id, event.world_id)
                participants.update((relationship.source_id, relationship.target_id))
    for participant_id in participants:
        db.add(EventParticipant(event_id=event.id, character_id=participant_id))


def assert_not_referenced(db: Session, world_id: str, knowledge_id: str):
    for model in (World, Location, Character, Relationship):
        condition = model.id == world_id if model is World else model.world_id == world_id
        for owner in db.scalars(select(model).where(condition)):
            if any(
                a["type"] == "reference" and a["value"] == knowledge_id for a in owner.attributes
            ):
                fail("Erinnerung wird von einem eigenen Feld verwendet; Referenz zuerst lösen", 409)


def undo_event(db: Session, event: Event, revision: int, actor="user"):
    if db.scalar(
        select(SimulationDependency.turn_id).where(
            SimulationDependency.event_id == event.id,
        )
    ):
        fail(
            "Spätere Simulationsrunden nutzten diesen Weltzustand. "
            "Sichere Rückabwicklung nicht möglich.",
            409,
        )
    if event.status != "applied":
        fail("Nur angewendete Ereignisse können rückgängig gemacht werden", 409)
    changes = list(
        db.scalars(
            select(EventMutation)
            .where(EventMutation.event_id == event.id)
            .order_by(EventMutation.sequence.desc())
        )
    )
    for mutation in changes:
        row = entity(db, mutation.entity_type, mutation.entity_id, event.world_id)
        if db.scalar(
            select(EventMutation.id)
            .join(Event)
            .where(
                EventMutation.entity_type == mutation.entity_type,
                EventMutation.entity_id == mutation.entity_id,
                EventMutation.revision_after > mutation.revision_after,
                EventMutation.event_id != event.id,
                EventMutation.reverted.is_(False),
                Event.status == "applied",
            )
        ):
            fail("Rücknahme blockiert: ein neueres angewendetes Ereignis hängt vom Objekt ab", 409)
        for field, kind in (
            ("location_id", "location"),
            ("destination_id", "location"),
            ("character_id", "character"),
            ("subject_id", "character"),
            ("source_id", "character"),
            ("target_id", "character"),
        ):
            reference = mutation.before.get(field)
            if reference and db.get(ENTITY_MODELS[kind], reference) is None:
                fail("Rücknahme blockiert: ein früher referenziertes Objekt wurde entfernt", 409)
        expected_revision = (
            db.scalar(
                select(func.max(EventMutation.revision_after)).where(
                    EventMutation.entity_type == mutation.entity_type,
                    EventMutation.entity_id == mutation.entity_id,
                )
            )
            or mutation.revision_after
        )
        for entry in db.scalars(
            select(EventAudit)
            .join(Event)
            .where(
                Event.world_id == event.world_id,
                EventAudit.action == "mutation_reverted",
            )
        ):
            if entry.detail.get("entity_id") == mutation.entity_id:
                expected_revision = max(expected_revision, entry.detail["revision"])
        if row.revision != expected_revision or any(
            getattr(row, key) != value for key, value in mutation.after.items()
        ):
            fail("Rücknahme blockiert: neuere oder manuelle Änderungen hängen vom Objekt ab", 409)
        if not mutation.before:
            assert_not_referenced(db, event.world_id, row.id)
        if mutation.entity_type == "knowledge":
            linked = db.scalar(
                select(KnowledgeLink.source_id)
                .join(Knowledge, Knowledge.id == KnowledgeLink.source_id)
                .where(
                    KnowledgeLink.target_id == row.id,
                    Knowledge.status == "active",
                    Knowledge.event_id != event.id,
                )
            )
            if linked:
                fail("Rücknahme blockiert: eine neuere Erinnerung bezieht sich darauf", 409)
    compare_and_set(db, event, {"status": "undone"}, revision)
    for mutation in changes:
        row = entity(db, mutation.entity_type, mutation.entity_id, event.world_id)
        before_undo = row.revision
        values = mutation.before or {"status": "revoked", "source_message_id": None}
        compare_and_set(db, row, values, before_undo)
        mutation.reverted = True
        audit(
            db,
            event,
            "mutation_reverted",
            actor,
            entity_id=row.id,
            before=mutation.after,
            after=values,
            revision=row.revision,
        )
    audit(db, event, "undone", actor)
    db.flush()


def invalidate_messages(db: Session, message_ids: list[str]):
    if not message_ids:
        return
    jobs = list(
        db.scalars(
            select(ExtractionJob).where(
                (ExtractionJob.message_id.in_(message_ids))
                | (
                    ExtractionJob.id.in_(
                        select(ExtractionJobSource.job_id).where(
                            ExtractionJobSource.message_id.in_(message_ids)
                        )
                    )
                )
            )
        )
    )
    linked_event_ids = [event_id for job in jobs for event_id in job.event_ids]
    events = list(
        db.scalars(
            select(Event)
            .outerjoin(EventSource)
            .where(EventSource.message_id.in_(message_ids) | Event.id.in_(linked_event_ids))
            .distinct()
            .order_by(Event.created_at.desc(), Event.id.desc())
        )
    )
    for event in events:
        if event.status == "applied":
            undo_event(db, event, event.revision, "source_edit")
        if event.status != "invalidated":
            compare_and_set(db, event, {"status": "invalidated"}, event.revision)
            audit(db, event, "invalidated", "source_edit")
    for job in jobs:
        job.status = "invalidated"
    # Preserve the event history, while Phase-1 cascade semantics remain unchanged.
    for knowledge in db.scalars(
        select(Knowledge).where(
            Knowledge.source_message_id.in_(message_ids), Knowledge.event_id.is_not(None)
        )
    ):
        knowledge.source_message_id = None
    db.flush()


def block_active_target_delete(db: Session, kind: str, item_id: str):
    if db.scalar(
        select(Event.id)
        .join(EventTarget)
        .where(
            EventTarget.entity_type == kind,
            EventTarget.entity_id == item_id,
            Event.status.in_(["applied", "proposed"]),
        )
    ):
        fail("Objekt besitzt Ereignisabhängigkeiten. Änderungen zuerst zurücknehmen/ablehnen.", 409)


def event_detail(db: Session, event: Event) -> dict:
    proposal = proposal_for(db, event.id)
    return {
        **encode(event),
        "proposal": encode(proposal),
        "participants": list(
            db.scalars(
                select(EventParticipant.character_id).where(EventParticipant.event_id == event.id)
            )
        ),
        "sources": [
            encode(row)
            for row in db.scalars(select(EventSource).where(EventSource.event_id == event.id))
        ],
        "targets": [
            encode(row)
            for row in db.scalars(select(EventTarget).where(EventTarget.event_id == event.id))
        ],
        "mutations": [
            encode(row)
            for row in db.scalars(
                select(EventMutation)
                .where(EventMutation.event_id == event.id)
                .order_by(EventMutation.sequence)
            )
        ],
        "audit": [
            encode(row)
            for row in db.scalars(
                select(EventAudit)
                .where(EventAudit.event_id == event.id)
                .order_by(EventAudit.sequence)
            )
        ],
    }
