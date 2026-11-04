"""One bounded public turn at a time; model I/O never holds a database transaction."""

import asyncio
import logging
import re
import time

import tiktoken
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .context import build_context
from .conversations import participants, present, save_public_message
from .db import SessionLocal
from .event_schemas import ClockOperation, EventInput
from .events import apply_event, create_event
from .extraction import MAX_ATTEMPTS, enqueue, run_job
from .models import (
    Conversation,
    Event,
    ExtractionJob,
    Message,
    ProviderSettings,
    Simulation,
    SimulationDependency,
    SimulationTurn,
    World,
    WorldClock,
    now,
)
from .provider import ProviderError

log = logging.getLogger("openworld.simulation")
encoding = tiktoken.get_encoding("cl100k_base")


def clock_for(db: Session, world_id: str) -> WorldClock:
    clock = db.get(WorldClock, world_id)
    if clock is None:
        if db.get(World, world_id) is None:
            raise HTTPException(404, "Welt nicht gefunden.")
        try:
            with db.begin_nested():
                clock = WorldClock(id=world_id)
                db.add(clock)
                db.flush()
        except IntegrityError:
            clock = db.get(WorldClock, world_id)
            if clock is None:
                raise
    return clock


def generation_settings(db: Session, model: str = "") -> ProviderSettings:
    original = db.get(ProviderSettings, 1)
    if not original or not (model or original.model):
        raise ProviderError("Bitte zuerst ein Chatmodell konfigurieren.")
    settings = ProviderSettings(
        **{
            column.key: getattr(original, column.key)
            for column in ProviderSettings.__table__.columns
            if column.key != "id"
        }
    )
    if model:
        settings.model = model
    return settings


async def generate_public(
    db: Session,
    conversation: Conversation,
    speaker_id: str,
    provider,
    model: str = "",
    commit: bool = True,
    turn_id: str | None = None,
) -> Message:
    settings = generation_settings(db, model)
    if speaker_id not in {p.id for p in present(db, conversation)}:
        raise HTTPException(409, "Sprecher ist nicht anwesend.")
    context, _ = build_context(
        db,
        conversation,
        settings.context_window,
        settings.max_output_tokens,
        speaker_id=speaker_id,
    )
    if not any(message["role"] == "user" for message in context):
        context.append(
            {
                "role": "user",
                "content": (
                    "[Technische Sprechzugsteuerung, keine Aussage einer Person in der Szene] "
                    "Du bist als ausgewählter Charakter an der Reihe. Beginne das Gespräch."
                ),
            }
        )
        if (
            sum(
                len(encoding.encode(message["content"], disallowed_special=())) + 8
                for message in context
            )
            + settings.max_output_tokens
            > settings.context_window
        ):
            raise ProviderError(
                "Kontext einschließlich Sprechzugsteuerung überschreitet das Limit."
            )
    snapshot = [(person.id, person.revision) for person in participants(db, conversation)]
    world = db.get(World, conversation.world_id)
    if world is None:
        raise HTTPException(409, "Welt nicht mehr vorhanden.")
    world_revision = world.revision
    scene = (conversation.scene, conversation.scene_location_id, conversation.communication)
    clock = db.get(WorldClock, conversation.world_id)
    clock_revision = clock.revision if clock else None
    event_ids = (
        list(
            db.scalars(
                select(Event.id).where(
                    Event.world_id == conversation.world_id,
                    Event.status == "applied",
                )
            )
        )
        if turn_id
        else []
    )
    db.commit()

    async def collect():
        content = ""
        iterator = provider.stream(context, settings)
        try:
            async for chunk in iterator:
                content += chunk
                if (
                    len(content) > settings.max_output_tokens * 16 + 256
                    or len(encoding.encode(content, disallowed_special=()))
                    > settings.max_output_tokens
                ):
                    raise ProviderError("Antwort überschreitet das konfigurierte Ausgabelimit.")
        finally:
            close = getattr(iterator, "aclose", None)
            if close:
                await close()
        return content

    content = await asyncio.wait_for(collect(), timeout=300)
    db.expire_all()
    current_clock = db.get(WorldClock, conversation.world_id)
    if (
        [(p.id, p.revision) for p in participants(db, conversation)] != snapshot
        or world.revision != world_revision
        or (conversation.scene, conversation.scene_location_id, conversation.communication) != scene
        or (current_clock.revision if current_clock else None) != clock_revision
    ):
        raise HTTPException(
            409, "Welt oder Teilnehmer während der Antwort geändert; Antwort verworfen."
        )
    message = save_public_message(db, conversation, content, speaker_id)
    for event_id in event_ids:
        db.add(SimulationDependency(turn_id=turn_id, event_id=event_id))
    if commit:
        db.commit()
    return message


def enqueue_witnesses(
    db: Session,
    conversation: Conversation,
    message: Message,
    simulation_id: str | None = None,
) -> list[ExtractionJob]:
    jobs = []
    own_action = bool(
        re.search(
            r"\*|\d|\b(?:gebe|übergebe|verlasse|reise|betrete|erreiche|beginne|arrive|leave)\b",
            message.content,
            re.I,
        )
    )
    for recipient in participants(db, conversation):
        from .conversations import can_hear

        if not can_hear(db, message, recipient.id):
            continue
        if recipient.id == message.speaker_character_id and not own_action:
            continue
        job = enqueue(db, conversation, message, [message], recipient.id, simulation_id)
        if job:
            jobs.append(job)
    db.flush()
    return jobs


class LimitReached(ProviderError):
    pass


class MeteredProvider:
    def __init__(self, db: Session, simulation_id: str, provider):
        self.db = db
        self.simulation_id = simulation_id
        self.provider = provider

    def reserve(self, messages, settings):
        self.db.expire_all()
        simulation = self.db.get(Simulation, self.simulation_id)
        if not simulation or simulation.status != "running":
            raise asyncio.CancelledError
        cost = (
            sum(len(encoding.encode(m["content"], disallowed_special=())) + 8 for m in messages)
            + settings.max_output_tokens
        )
        if simulation.calls_used >= simulation.max_calls:
            raise LimitReached("Maximale Anzahl Modellaufrufe erreicht.", code="call_limit")
        if simulation.tokens_reserved + cost > simulation.max_tokens:
            raise LimitReached("Geschätztes Tokenbudget ausgeschöpft.", code="token_limit")
        remaining = simulation.timeout_seconds - simulation.seconds_used
        if remaining <= 0:
            raise LimitReached("Zeitlimit erreicht.", code="time_limit")
        simulation.calls_used += 1
        simulation.tokens_reserved += cost
        simulation.updated_at = now()
        self.db.commit()
        return remaining

    def charge_time(self, elapsed: float):
        self.db.rollback()
        simulation = self.db.get(Simulation, self.simulation_id)
        if simulation:
            simulation.seconds_used += elapsed
            simulation.updated_at = now()
            self.db.commit()

    async def stream(self, messages, settings):
        remaining = self.reserve(messages, settings)
        started = time.monotonic()
        try:
            async with asyncio.timeout(remaining):
                async for chunk in self.provider.stream(messages, settings):
                    yield chunk
        finally:
            self.charge_time(time.monotonic() - started)

    async def extract(self, messages, settings):
        remaining = self.reserve(messages, settings)
        started = time.monotonic()
        try:
            return await asyncio.wait_for(
                self.provider.extract(messages, settings),
                timeout=remaining,
            )
        except TimeoutError as exc:
            raise LimitReached("Zeitlimit bei Extraktion erreicht.", code="time_limit") from exc
        finally:
            self.charge_time(time.monotonic() - started)


def recover(db: Session):
    for simulation in db.scalars(select(Simulation).where(Simulation.status == "running")):
        simulation.status = "paused"
        simulation.error = "Backend unterbrochen. Nur nach bewusster Fortsetzung weiterarbeiten."
        simulation.stop_reason = "backend_restart"
        simulation.revision += 1
        simulation.updated_at = now()
    db.commit()


def stop(db: Session, simulation: Simulation, status: str, reason: str, error: str = ""):
    simulation.status = status
    simulation.stop_reason = reason
    simulation.error = error
    simulation.revision += 1
    simulation.updated_at = now()
    db.commit()


async def process_jobs(db: Session, simulation: Simulation, meter: MeteredProvider) -> bool:
    jobs = list(
        db.scalars(
            select(ExtractionJob)
            .where(
                ExtractionJob.simulation_id == simulation.id,
                ExtractionJob.status.in_(["pending", "failed", "running"]),
            )
            .order_by(ExtractionJob.created_at, ExtractionJob.id)
        )
    )
    for job in jobs:
        db.refresh(simulation)
        if simulation.status != "running":
            return False
        if job.status == "failed" and job.attempts < MAX_ATTEMPTS:
            job.status = "pending"
            db.commit()
        await run_job(db, job.id, meter)
        db.refresh(job)
        if job.status not in {"complete", "skipped"}:
            code = job.diagnostics[-1].get("code", "") if job.diagnostics else ""
            limited = code in {"token_limit", "call_limit", "time_limit"}
            stop(
                db,
                simulation,
                "completed" if limited else "paused",
                code if limited else "extraction_failed",
                job.error,
            )
            return False
    return True


async def step(db: Session, simulation_id: str, provider):
    simulation = db.get(Simulation, simulation_id)
    if not simulation or simulation.status != "running":
        return
    conversation = db.get(Conversation, simulation.conversation_id)
    if conversation is None:
        stop(db, simulation, "failed", "missing_conversation", "Gespräch fehlt.")
        return
    meter = MeteredProvider(db, simulation.id, provider)
    try:
        if simulation.completed_rounds >= simulation.max_rounds:
            stop(db, simulation, "completed", "round_limit")
            return
        if simulation.completed_rounds >= simulation.run_until:
            stop(db, simulation, "paused", "step_limit")
            return
        if not await process_jobs(db, simulation, meter):
            return
        people = present(db, conversation)
        if len(people) < 2:
            stop(db, simulation, "completed", "participants_left")
            return
        number = simulation.completed_rounds + 1
        turn = db.scalar(
            select(SimulationTurn).where(
                SimulationTurn.simulation_id == simulation.id,
                SimulationTurn.number == number,
            )
        )
        if not turn:
            speaker = people[simulation.completed_rounds % len(people)]
            turn = SimulationTurn(
                simulation_id=simulation.id,
                number=number,
                character_id=speaker.id,
            )
            db.add(turn)
            db.commit()
        message = db.get(Message, turn.message_id) if turn.message_id else None
        if not message:
            message = await generate_public(
                db,
                conversation,
                turn.character_id,
                meter,
                simulation.model,
                commit=False,
                turn_id=turn.id,
            )
            turn.message_id = message.id
            turn.status = "extracting"
            enqueue_witnesses(db, conversation, message, simulation.id)
            db.commit()
        else:
            enqueue_witnesses(db, conversation, message, simulation.id)
            db.commit()
        if not await process_jobs(db, simulation, meter):
            return
        db.refresh(simulation)
        if simulation.status != "running":
            return
        if simulation.event_mode != "observe" and simulation.minutes_per_round:
            clock = clock_for(db, simulation.world_id)
            event = create_event(
                db,
                simulation.world_id,
                EventInput(
                    event_type="simulation_time",
                    description=f"Simulationsrunde {number}: Zeitfortschritt",
                    operations=[
                        ClockOperation(
                            entity_id=clock.id,
                            revision=clock.revision,
                            elapsed_minutes=clock.elapsed_minutes + simulation.minutes_per_round,
                            minutes_per_day=clock.minutes_per_day,
                            epoch_label=clock.epoch_label,
                        )
                    ],
                ),
            )
            apply_event(db, event, event.revision, "system")
            turn.clock_event_id = event.id
        turn.status = "complete"
        turn.error = ""
        simulation.completed_rounds = number
        simulation.revision += 1
        simulation.updated_at = now()
        if number >= simulation.max_rounds:
            simulation.status, simulation.stop_reason = "completed", "round_limit"
        elif number >= simulation.run_until:
            simulation.status, simulation.stop_reason = "paused", "step_limit"
        db.commit()
    except asyncio.CancelledError:
        db.rollback()
        for job in db.scalars(
            select(ExtractionJob).where(
                ExtractionJob.simulation_id == simulation_id,
                ExtractionJob.status == "running",
            )
        ):
            job.status, job.error = "failed", "Extraktion bewusst unterbrochen."
        db.commit()
        db.refresh(simulation)
        if simulation.status == "running":
            stop(db, simulation, "paused", "interrupted", "Runde unterbrochen; bewusst fortsetzen.")
        raise
    except LimitReached as exc:
        db.rollback()
        db.refresh(simulation)
        stop(db, simulation, "completed", exc.code, str(exc))
    except TimeoutError:
        db.rollback()
        db.refresh(simulation)
        stop(db, simulation, "completed", "time_limit", "Zeitlimit erreicht.")
    except (ProviderError, HTTPException) as exc:
        db.rollback()
        db.refresh(simulation)
        detail = (
            str(exc.detail) if isinstance(exc, HTTPException) else str(exc) or "Zeitlimit erreicht."
        )
        log.warning("Simulation %s paused: %s", simulation.id, detail)
        stop(db, simulation, "paused", "generation_failed", detail)


async def worker(app):
    app.state.simulation_worker_error = ""
    try:
        await worker_loop(app)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Simulation worker failed")
        app.state.simulation_worker_error = (
            "Simulationsdienst ausgefallen. Backend-Protokoll prüfen und neu starten."
        )


async def worker_loop(app):
    with SessionLocal() as db:
        recover(db)
    app.state.simulation_tasks = {}
    app.state.simulation_worker_error = ""
    while True:
        await asyncio.sleep(0.25)
        with SessionLocal() as db:
            simulation = db.scalar(
                select(Simulation)
                .where(
                    Simulation.status == "running",
                )
                .order_by(Simulation.updated_at, Simulation.id)
                .limit(1)
            )
            if not simulation:
                continue
            app.state.active_conversations.add(simulation.conversation_id)
            task = asyncio.create_task(step(db, simulation.id, app.state.provider))
            app.state.simulation_tasks[simulation.id] = task
            try:
                await task
            except asyncio.CancelledError:
                owner = asyncio.current_task()
                if owner and owner.cancelling():
                    raise
            except Exception:
                db.rollback()
                log.exception("Unexpected simulation failure %s", simulation.id)
                db.refresh(simulation)
                stop(
                    db,
                    simulation,
                    "failed",
                    "internal_error",
                    "Interner Simulationsfehler. Backend-Protokoll prüfen.",
                )
            finally:
                app.state.active_conversations.discard(simulation.conversation_id)
                app.state.simulation_tasks.pop(simulation.id, None)
