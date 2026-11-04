from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .db import get_db
from .event_schemas import EventAction, EventInput, EventSettingsInput, RuleInput
from .events import (
    apply_event,
    audit,
    compare_and_set,
    create_event,
    decide_mode,
    entity,
    event_detail,
    preview_operations,
    proposal_for,
    sync_proposal_references,
    undo_event,
    validate_event,
)
from .extraction import MAX_ATTEMPTS, enqueue, event_settings
from .models import (
    Conversation,
    Event,
    EventParticipant,
    EventRule,
    EventSource,
    ExtractionJob,
    Knowledge,
    KnowledgeLink,
    Message,
)
from .serialization import encode

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_db)]


def get_event(db: Session, world_id: str, event_id: str):
    event = db.get(Event, event_id)
    if not event or event.world_id != world_id:
        raise HTTPException(404, "Ereignis nicht gefunden")
    return event


@router.get("/worlds/{world_id}/events")
def events(
    world_id: str,
    db: DB,
    character_id: str | None = None,
    location_id: str | None = None,
    event_type: str | None = None,
    status: str | None = None,
    from_time: datetime | None = None,
    until_time: datetime | None = None,
    conversation_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    entity(db, "world", world_id, world_id)
    query = select(Event).where(Event.world_id == world_id)
    if character_id:
        query = query.where(
            Event.id.in_(
                select(EventParticipant.event_id).where(
                    EventParticipant.character_id == character_id
                )
            )
        )
    if location_id:
        query = query.where(Event.location_id == location_id)
    if event_type:
        query = query.where(Event.event_type == event_type)
    if status:
        query = query.where(Event.status == status)
    if conversation_id:
        query = query.where(
            Event.id.in_(
                select(EventSource.event_id).where(EventSource.conversation_id == conversation_id)
            )
        )
    if from_time:
        query = query.where(Event.occurred_at >= from_time)
    if until_time:
        query = query.where(Event.occurred_at <= until_time)
    if from_time and until_time and from_time > until_time:
        raise HTTPException(422, "Zeitraum: Beginn liegt nach dem Ende")
    return [
        event_detail(db, row)
        for row in db.scalars(
            query.order_by(Event.occurred_at.desc(), Event.created_at.desc(), Event.id)
            .limit(limit)
            .offset(offset)
        )
    ]


@router.post("/worlds/{world_id}/events", status_code=201)
def post_event(world_id: str, body: EventInput, db: DB):
    with db.begin_nested():
        event = create_event(db, world_id, body)
    db.commit()
    return event_detail(db, event)


@router.get("/worlds/{world_id}/events/{event_id}")
def detail(world_id: str, event_id: str, db: DB):
    return event_detail(db, get_event(db, world_id, event_id))


@router.put("/worlds/{world_id}/events/{event_id}")
def edit_proposal(
    world_id: str,
    event_id: str,
    body: EventInput,
    db: DB,
    revision: int = Query(ge=1),
):
    event = get_event(db, world_id, event_id)
    if event.status not in {"proposed", "protected"}:
        raise HTTPException(409, "Nur offene Vorschläge sind bearbeitbar")
    sources = list(db.scalars(select(EventSource).where(EventSource.event_id == event.id)))
    message = db.get(Message, sources[0].message_id) if sources else None
    if sources and (not message or message.revision != sources[0].message_revision):
        raise HTTPException(409, "Quelle wurde inzwischen geändert")
    if sources:
        body = body.model_copy(update={"evidence_quote": sources[0].quote})
    validate_event(db, world_id, body, message)
    mode, reason = decide_mode(db, world_id, body, message)
    with db.begin_nested():
        compare_and_set(
            db,
            event,
            {
                "event_type": body.event_type,
                "description": body.description,
                "confidence": body.confidence,
                "location_id": body.location_id,
                "occurred_at": body.occurred_at or event.occurred_at,
                "status": "protected" if mode == "protected" else "proposed",
            },
            revision,
        )
        proposal = proposal_for(db, event.id)
        old_operations = proposal.operations
        proposal.operations = [operation.model_dump() for operation in body.operations]
        proposal.preview = preview_operations(db, world_id, body)
        proposal.mode, proposal.reason = mode, reason
        sync_proposal_references(db, event, body, message)
        audit(db, event, "edited", "user", before=old_operations, after=proposal.operations)
    db.commit()
    return event_detail(db, event)


@router.post("/worlds/{world_id}/events/{event_id}/{action}")
def event_action(world_id: str, event_id: str, action: str, body: EventAction, db: DB):
    event = get_event(db, world_id, event_id)
    with db.begin_nested():
        if action == "approve":
            apply_event(db, event, body.revision, "user")
        elif action == "undo":
            undo_event(db, event, body.revision)
        elif action == "reject":
            if event.status not in {"proposed", "protected"}:
                raise HTTPException(409, "Nur offene Vorschläge können abgelehnt werden")
            compare_and_set(db, event, {"status": "rejected"}, body.revision)
            audit(db, event, "rejected", "user")
        else:
            raise HTTPException(404, "Unbekannte Ereignisaktion")
    db.commit()
    return event_detail(db, event)


@router.get("/worlds/{world_id}/event-settings")
def get_event_settings(world_id: str, db: DB):
    entity(db, "world", world_id, world_id)
    row = event_settings(db, world_id)
    db.commit()
    return encode(row)


@router.put("/worlds/{world_id}/event-settings")
def put_event_settings(world_id: str, body: EventSettingsInput, db: DB):
    entity(db, "world", world_id, world_id)
    row = event_settings(db, world_id)
    result = db.execute(
        update(type(row))
        .where(type(row).world_id == world_id, type(row).revision == body.revision)
        .values(enabled=body.enabled, revision=body.revision + 1)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Ereigniseinstellungen wurden inzwischen geändert")
    db.commit()
    db.refresh(row)
    return encode(row)


@router.get("/worlds/{world_id}/event-rules")
def rules(world_id: str, db: DB):
    entity(db, "world", world_id, world_id)
    return [
        encode(row) for row in db.scalars(select(EventRule).where(EventRule.world_id == world_id))
    ]


@router.put("/worlds/{world_id}/event-rules")
def put_rule(world_id: str, body: RuleInput, db: DB):
    entity(db, "world", world_id, world_id)
    rule = db.scalar(
        select(EventRule).where(
            EventRule.world_id == world_id,
            EventRule.event_type == body.event_type,
            EventRule.object_class == body.object_class,
        )
    )
    if rule:
        if body.revision is None:
            raise HTTPException(422, "Regelrevision erforderlich")
        compare_and_set(db, rule, {"mode": body.mode}, body.revision)
    else:
        if body.revision is not None:
            raise HTTPException(409, "Regel ist nicht mehr vorhanden")
        rule = EventRule(world_id=world_id, **body.model_dump(exclude={"revision"}))
        db.add(rule)
    db.commit()
    return encode(rule)


@router.get("/worlds/{world_id}/extraction-jobs")
def jobs(
    world_id: str,
    db: DB,
    request: Request,
    conversation_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
):
    if getattr(request.app.state, "event_worker_error", ""):
        raise HTTPException(503, request.app.state.event_worker_error)
    entity(db, "world", world_id, world_id)
    query = select(ExtractionJob).where(ExtractionJob.world_id == world_id)
    if conversation_id:
        query = query.where(ExtractionJob.conversation_id == conversation_id)
    return [
        encode(row)
        for row in db.scalars(
            query.order_by(ExtractionJob.created_at.desc(), ExtractionJob.id).limit(limit)
        )
    ]


@router.post("/worlds/{world_id}/extraction-jobs/{job_id}/retry")
def retry(world_id: str, job_id: str, db: DB):
    job = db.get(ExtractionJob, job_id)
    if not job or job.world_id != world_id:
        raise HTTPException(404, "Extraktionsauftrag nicht gefunden")
    if not event_settings(db, world_id).enabled:
        raise HTTPException(409, "Ereigniserkennung ist deaktiviert")
    if job.status != "failed" or job.attempts >= MAX_ATTEMPTS:
        raise HTTPException(409, "Keine Wiederholung möglich (höchstens drei Versuche)")
    job.status, job.error = "pending", ""
    db.commit()
    return encode(job)


@router.post("/conversations/{conversation_id}/extract")
def extract_conversation(conversation_id: str, request: Request, db: DB):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "Gespräch nicht gefunden")
    if conversation_id in request.app.state.active_conversations:
        raise HTTPException(409, "Antwort zuerst abschließen lassen")
    if not event_settings(db, conversation.world_id).enabled:
        raise HTTPException(409, "Ereigniserkennung zuerst bewusst aktivieren")
    result = {}
    messages = list(db.scalars(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.status == "complete",
        )
        .order_by(Message.sequence)
    ))
    index = 0
    while index < len(messages):
        source = messages[index]
        pair = messages[index:index + 2]
        if len(pair) == 2:
            index += 2
        else:
            pair = [source]
            index += 1
        job = enqueue(db, conversation, pair[-1], pair)
        if job:
            result[job.id] = encode(job)
    db.commit()
    return list(result.values())


@router.get("/worlds/{world_id}/characters/{character_id}/memories")
def memories(world_id: str, character_id: str, db: DB):
    entity(db, "character", character_id, world_id)
    return [
        {
            **encode(row),
            "links": [
                encode(link)
                for link in db.scalars(
                    select(KnowledgeLink).where(
                        (KnowledgeLink.source_id == row.id) | (KnowledgeLink.target_id == row.id)
                    )
                )
            ],
        }
        for row in db.scalars(
            select(Knowledge)
            .where(
                Knowledge.world_id == world_id,
                Knowledge.character_id == character_id,
            )
            .order_by(Knowledge.created_at.desc(), Knowledge.id)
        )
    ]
