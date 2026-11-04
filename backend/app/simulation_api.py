import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .conversations import create_group, participants, present, save_public_message
from .db import get_db
from .event_schemas import ClockOperation, EventInput
from .events import apply_event, create_event
from .extraction_settings import resolve_extraction_settings
from .models import (
    Conversation,
    ConversationParticipant,
    Event,
    ExtractionJob,
    Message,
    Simulation,
    SimulationTurn,
    World,
    now,
)
from .provider import ProviderError
from .serialization import encode
from .simulation import clock_for, enqueue_witnesses, generate_public, generation_settings
from .simulation_schemas import (
    ClockInput,
    GroupInput,
    GroupMessageInput,
    GroupTurnInput,
    Intervention,
    SceneInput,
    SimulationControl,
    SimulationInput,
)

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_db)]


def get_simulation(db: Session, world_id: str, simulation_id: str) -> Simulation:
    simulation = db.get(Simulation, simulation_id)
    if not simulation or simulation.world_id != world_id:
        raise HTTPException(404, "Simulation nicht gefunden.")
    return simulation


def check_revision(simulation: Simulation, revision: int):
    if simulation.revision != revision:
        raise HTTPException(409, "Simulation wurde geändert. Bitte neu laden.")


def simulation_conversation(db: Session, simulation: Simulation) -> Conversation:
    conversation = db.get(Conversation, simulation.conversation_id)
    if conversation is None:
        raise HTTPException(409, "Simulationsgespräch fehlt.")
    return conversation


def detail(db: Session, simulation: Simulation):
    conversation = simulation_conversation(db, simulation)
    result = encode(simulation)
    result["conversation"] = encode(conversation)
    result["participants"] = [{"id": p.id, "name": p.name} for p in participants(db, conversation)]
    result["messages"] = [
        encode(row)
        for row in db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
            )
            .order_by(Message.sequence)
        )
    ]
    result["turns"] = [
        encode(row)
        for row in db.scalars(
            select(SimulationTurn)
            .where(
                SimulationTurn.simulation_id == simulation.id,
            )
            .order_by(SimulationTurn.number)
        )
    ]
    jobs = list(
        db.scalars(
            select(ExtractionJob)
            .where(
                ExtractionJob.simulation_id == simulation.id,
            )
            .order_by(ExtractionJob.created_at, ExtractionJob.id)
        )
    )
    result["jobs"] = [encode(job) for job in jobs]
    result["event_ids"] = sorted(
        {event_id for job in jobs for event_id in job.event_ids}
        | {turn["clock_event_id"] for turn in result["turns"] if turn["clock_event_id"]}
    )
    result["event_counts"] = dict(
        db.execute(
            select(Event.status, func.count())
            .where(Event.world_id == simulation.world_id, Event.id.in_(result["event_ids"]))
            .group_by(Event.status)
        ).all()
    )
    result["events"] = [
        {"id": event.id, "description": event.description, "status": event.status}
        for event in db.scalars(
            select(Event)
            .where(Event.world_id == simulation.world_id, Event.id.in_(result["event_ids"]))
            .order_by(Event.created_at.desc(), Event.id)
            .limit(20)
        )
    ]
    result["clock"] = encode(clock_for(db, simulation.world_id))
    result["token_usage_kind"] = "conservative_estimate"
    result["reported_total_tokens"] = None
    reported = [
        diagnostic["prompt_tokens"] + diagnostic["completion_tokens"]
        for job in jobs
        for diagnostic in job.diagnostics
        if isinstance(diagnostic.get("prompt_tokens"), int)
        and isinstance(diagnostic.get("completion_tokens"), int)
    ]
    result["reported_extraction_tokens"] = sum(reported) if reported else None
    return result


@router.get("/worlds/{world_id}/simulations")
def list_simulations(world_id: str, request: Request, db: DB):
    if getattr(request.app.state, "simulation_worker_error", ""):
        raise HTTPException(503, request.app.state.simulation_worker_error)
    clock_for(db, world_id)
    rows = list(
        db.scalars(
            select(Simulation)
            .where(
                Simulation.world_id == world_id,
            )
            .order_by(Simulation.updated_at.desc(), Simulation.id)
        )
    )
    result = [encode(row) for row in rows]
    db.commit()
    return result


@router.post("/worlds/{world_id}/simulations", status_code=201)
def post_simulation(world_id: str, body: SimulationInput, db: DB):
    clock_for(db, world_id)
    conversation = create_group(
        db,
        world_id,
        body.character_ids,
        body.title,
        body.scene,
        body.location_id,
        body.communication,
        "simulation",
    )
    simulation = Simulation(
        world_id=world_id,
        conversation_id=conversation.id,
        **body.model_dump(exclude={"character_ids", "scene", "location_id", "communication"}),
    )
    db.add(simulation)
    db.commit()
    return detail(db, simulation)


@router.get("/worlds/{world_id}/simulations/{simulation_id}")
def get_detail(world_id: str, simulation_id: str, db: DB):
    result = detail(db, get_simulation(db, world_id, simulation_id))
    db.commit()
    return result


@router.post("/worlds/{world_id}/simulations/{simulation_id}/control/{action}")
async def control(
    world_id: str,
    simulation_id: str,
    action: str,
    body: SimulationControl,
    request: Request,
    db: DB,
):
    simulation = get_simulation(db, world_id, simulation_id)
    check_revision(simulation, body.revision)
    if action in {"start", "resume"}:
        if simulation.conversation_id in request.app.state.active_conversations:
            raise HTTPException(409, "Vorherigen Sprechzug erst vollständig anhalten lassen.")
        if simulation.status not in {"created", "paused", "failed"}:
            raise HTTPException(409, "Diese Simulation kann nicht gestartet werden.")
        if getattr(request.app.state, "simulation_worker_error", ""):
            raise HTTPException(503, request.app.state.simulation_worker_error)
        if db.scalar(
            select(Simulation.id).where(
                Simulation.world_id == world_id,
                Simulation.status == "running",
                Simulation.id != simulation.id,
            )
        ):
            raise HTTPException(409, "In dieser Welt läuft bereits eine Simulation.")
        conversation = simulation_conversation(db, simulation)
        if len(present(db, conversation)) < 2:
            raise HTTPException(409, "Mindestens zwei anwesende Charaktere erforderlich.")
        try:
            generation_settings(db, simulation.model)
            resolve_extraction_settings(db)
        except ProviderError as exc:
            raise HTTPException(422, str(exc)) from exc
        simulation.run_until = min(
            simulation.max_rounds,
            simulation.completed_rounds + (body.steps or simulation.max_rounds),
        )
        if simulation.completed_rounds >= simulation.max_rounds:
            raise HTTPException(409, "Rundenlimit bereits erreicht.")
        simulation.status = "running"
        simulation.error, simulation.stop_reason = "", ""
    elif action == "pause":
        if simulation.status != "running":
            raise HTTPException(409, "Simulation läuft nicht.")
        simulation.status, simulation.stop_reason = "paused", "user_pause"
    elif action == "cancel":
        if simulation.status in {"cancelled", "completed"}:
            raise HTTPException(409, "Simulation ist bereits beendet.")
        simulation.status, simulation.stop_reason = "cancelled", "user_cancel"
    else:
        raise HTTPException(404, "Unbekannte Simulationsaktion.")
    simulation.revision += 1
    simulation.updated_at = now()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Gleichzeitig wurde eine andere Simulation gestartet.") from exc
    task = getattr(request.app.state, "simulation_tasks", {}).get(simulation.id)
    if action in {"pause", "cancel"} and task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return detail(db, simulation)


@router.post("/worlds/{world_id}/simulations/{simulation_id}/interventions", status_code=201)
def intervene(world_id: str, simulation_id: str, body: Intervention, db: DB):
    simulation = get_simulation(db, world_id, simulation_id)
    check_revision(simulation, body.revision)
    if simulation.status not in {"created", "paused"}:
        raise HTTPException(409, "Vor einem Eingriff die Simulation pausieren.")
    conversation = simulation_conversation(db, simulation)
    address = next((p for p in present(db, conversation) if p.id == body.address_id), None)
    if body.address_id and address is None:
        raise HTTPException(422, "Angesprochener Charakter ist nicht anwesend.")
    content = f"An {address.name}: {body.content}" if address else body.content
    message = save_public_message(db, conversation, content, None)
    # Interventions are extracted on the next consciously resumed round.
    enqueue_witnesses(db, conversation, message, simulation.id)
    simulation.revision += 1
    simulation.updated_at = now()
    db.commit()
    return detail(db, simulation)


@router.put("/worlds/{world_id}/simulations/{simulation_id}/scene")
def change_scene(world_id: str, simulation_id: str, body: SceneInput, db: DB):
    simulation = get_simulation(db, world_id, simulation_id)
    check_revision(simulation, body.revision)
    if simulation.status not in {"created", "paused"}:
        raise HTTPException(409, "Szene nur bei angehaltener Simulation ändern.")
    # Reuse the complete same-world and presence validator, then keep the original identity.
    candidate = create_group(
        db,
        world_id,
        body.character_ids,
        "Szenenprüfung",
        body.scene,
        body.location_id,
        body.communication,
    )
    conversation = simulation_conversation(db, simulation)
    conversation.scene, conversation.scene_location_id = body.scene, body.location_id
    conversation.communication = body.communication
    existing = list(
        db.scalars(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation.id,
            )
        )
    )
    for row in existing:
        row.active = row.character_id in body.character_ids
    for position, character_id in enumerate(body.character_ids):
        row = next((p for p in existing if p.character_id == character_id), None)
        if row:
            row.active, row.position = True, position
        else:
            db.add(
                ConversationParticipant(
                    conversation_id=conversation.id,
                    character_id=character_id,
                    position=position,
                )
            )
    db.delete(candidate)
    simulation.revision += 1
    simulation.updated_at = now()
    db.commit()
    return detail(db, simulation)


@router.get("/worlds/{world_id}/clock")
def get_clock(world_id: str, db: DB):
    result = encode(clock_for(db, world_id))
    db.commit()
    return result


@router.put("/worlds/{world_id}/clock")
def put_clock(world_id: str, body: ClockInput, db: DB):
    if db.scalar(
        select(Simulation.id).where(
            Simulation.world_id == world_id,
            Simulation.status == "running",
        )
    ):
        raise HTTPException(409, "Vor manuellen Zeitänderungen die Simulation pausieren.")
    clock = clock_for(db, world_id)
    event = create_event(
        db,
        world_id,
        EventInput(
            event_type="manual_time",
            description="Weltzeit im Editor geändert",
            operations=[ClockOperation(entity_id=clock.id, **body.model_dump())],
        ),
    )
    apply_event(db, event, event.revision, "user")
    db.commit()
    return encode(clock)


@router.get("/worlds/{world_id}/group-conversations")
def list_groups(world_id: str, db: DB):
    if db.get(World, world_id) is None:
        raise HTTPException(404, "Welt nicht gefunden.")
    return [
        encode(row)
        for row in db.scalars(
            select(Conversation)
            .where(
                Conversation.world_id == world_id,
                Conversation.kind == "group",
            )
            .order_by(Conversation.created_at.desc())
        )
    ]


@router.post("/worlds/{world_id}/group-conversations", status_code=201)
def post_group(world_id: str, body: GroupInput, db: DB):
    conversation = create_group(
        db,
        world_id,
        body.character_ids,
        body.title,
        body.scene,
        body.location_id,
        body.communication,
    )
    db.commit()
    return encode(conversation)


def group_idle(db: Session, request: Request, conversation_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.kind != "group":
        raise HTTPException(404, "Gruppengespräch nicht gefunden.")
    if conversation_id in request.app.state.active_conversations:
        raise HTTPException(409, "Antwort zuerst abschließen lassen.")
    return conversation


@router.get("/group-conversations/{conversation_id}")
def get_group(conversation_id: str, db: DB):
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.kind != "group":
        raise HTTPException(404, "Gruppengespräch nicht gefunden.")
    return {
        **encode(conversation),
        "participants": [{"id": p.id, "name": p.name} for p in participants(db, conversation)],
    }


@router.post("/group-conversations/{conversation_id}/messages", status_code=201)
def group_message(conversation_id: str, body: GroupMessageInput, request: Request, db: DB):
    conversation = group_idle(db, request, conversation_id)
    message = save_public_message(db, conversation, body.content, None)
    enqueue_witnesses(db, conversation, message)
    db.commit()
    return encode(message)


@router.post("/group-conversations/{conversation_id}/turn")
async def group_turn(conversation_id: str, body: GroupTurnInput, request: Request, db: DB):
    conversation = group_idle(db, request, conversation_id)
    request.app.state.active_conversations.add(conversation_id)
    try:
        message = await generate_public(
            db, conversation, body.speaker_id, request.app.state.provider
        )
        enqueue_witnesses(db, conversation, message)
        db.commit()
        return encode(message)
    except (ProviderError, TimeoutError) as exc:
        db.rollback()
        raise HTTPException(502, str(exc) or "KI-Zeitlimit erreicht.") from exc
    finally:
        request.app.state.active_conversations.discard(conversation_id)
