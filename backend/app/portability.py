"""Versioned world-only snapshots; provider credentials and runtime configuration stay local."""

import json
import math
from datetime import datetime
from typing import NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, TypeAdapter, ValidationError
from sqlalchemy import Boolean, DateTime, Float, Integer, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models as m
from .event_schemas import Operation, StateValue
from .events import operation_class
from .schemas import (
    Attribute,
    CharacterInput,
    KnowledgeInput,
    LocationInput,
    RelationshipInput,
    StrictModel,
    WorldInput,
)
from .serialization import encode
from .simulation_api import DB
from .simulation_schemas import ClockInput, SimulationInput

router = APIRouter(prefix="/api")
MODELS = (
    m.World,
    m.Location,
    m.Character,
    m.Relationship,
    m.Conversation,
    m.Message,
    m.ConversationParticipant,
    m.MessageAudience,
    m.WorldClock,
    m.Knowledge,
    m.Event,
    m.EventParticipant,
    m.EventSource,
    m.EventTarget,
    m.EventProposal,
    m.EventMutation,
    m.EventAudit,
    m.KnowledgeLink,
    m.EventRule,
    m.EventSettings,
    m.Simulation,
    m.SimulationTurn,
    m.SimulationDependency,
    m.ExtractionJob,
    m.ExtractionJobSource,
)
TABLES = {model.__tablename__: m.Base.metadata.tables[model.__tablename__] for model in MODELS}
ENTITY_TABLES = {
    "world": "worlds",
    "location": "locations",
    "character": "characters",
    "relationship": "relationships",
    "knowledge": "knowledge",
    "clock": "world_clocks",
}
DOMAIN = {
    "worlds": WorldInput,
    "locations": LocationInput,
    "characters": CharacterInput,
    "relationships": RelationshipInput,
    "knowledge": KnowledgeInput,
}


class WorldBundle(StrictModel):
    format: str = Field(pattern=r"^openworld\.world$")
    version: int = Field(ge=1, le=1)
    world_id: str = Field(min_length=1, max_length=36)
    tables: dict[str, list[dict]] = Field(max_length=30)


def bad(detail: str) -> NoReturn:
    raise HTTPException(422, detail)


@router.get("/worlds/{world_id}/export")
def export_world(world_id: str, request: Request, db: DB):
    if not db.get(m.World, world_id):
        raise HTTPException(404, "Welt nicht gefunden.")
    conversations = select(m.Conversation.id).where(m.Conversation.world_id == world_id)
    if (
        db.scalar(
            select(m.Simulation.id).where(
                m.Simulation.world_id == world_id,
                m.Simulation.status == "running",
            )
        )
        or set(db.scalars(conversations)) & request.app.state.active_conversations
    ):
        raise HTTPException(
            409, "Vor dem Export alle Antworten und Simulationen dieser Welt pausieren."
        )
    if db.get_bind().dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN")
    events = select(m.Event.id).where(m.Event.world_id == world_id)
    knowledge = select(m.Knowledge.id).where(m.Knowledge.world_id == world_id)
    messages = select(m.Message.id).where(m.Message.conversation_id.in_(conversations))
    simulations = select(m.Simulation.id).where(m.Simulation.world_id == world_id)
    turns = select(m.SimulationTurn.id).where(m.SimulationTurn.simulation_id.in_(simulations))
    jobs = select(m.ExtractionJob.id).where(m.ExtractionJob.world_id == world_id)
    filters = {
        m.World: m.World.id == world_id,
        m.WorldClock: m.WorldClock.id == world_id,
        m.Message: m.Message.conversation_id.in_(conversations),
        m.MessageAudience: m.MessageAudience.message_id.in_(messages),
        m.ConversationParticipant: m.ConversationParticipant.conversation_id.in_(conversations),
        m.KnowledgeLink: m.KnowledgeLink.source_id.in_(knowledge),
        m.SimulationTurn: m.SimulationTurn.simulation_id.in_(simulations),
        m.SimulationDependency: m.SimulationDependency.turn_id.in_(turns),
        m.ExtractionJobSource: m.ExtractionJobSource.job_id.in_(jobs),
    }
    data = {}
    for model in MODELS:
        condition = filters.get(model)
        if condition is None:
            table = TABLES[model.__tablename__]
            condition = (
                table.c.world_id == world_id
                if "world_id" in table.c
                else table.c.event_id.in_(events)
            )
        rows = [encode(row) for row in db.scalars(select(model).where(condition))]
        for row in rows:
            if model is m.Simulation:
                row["model"] = ""
                row["error"] = (
                    "Exportierte Unterbrechung; Details verbleiben lokal." if row["error"] else ""
                )
            if model is m.ExtractionJob:
                row["diagnostics"] = [
                    {
                        key: value
                        for key, value in diagnostic.items()
                        if key
                        in {
                            "attempt",
                            "trigger",
                            "status",
                            "code",
                            "prompt_tokens",
                            "completion_tokens",
                            "reasoning_tokens",
                            "http_requests",
                        }
                        and isinstance(value, (str, int, float, bool, type(None)))
                    }
                    for diagnostic in row["diagnostics"]
                ]
                row["error"] = "Exportierter Extraktionsfehler." if row["error"] else ""
        data[model.__tablename__] = rows
    return {"format": "openworld.world", "version": 1, "world_id": world_id, "tables": data}


def typed_value(column, value):
    if value is None:
        if not column.nullable:
            bad(f"Pflichtfeld fehlt: {column.table.name}.{column.name}")
        return value
    valid = True
    if isinstance(column.type, Boolean):
        valid = isinstance(value, bool)
    elif isinstance(column.type, Integer):
        valid = type(value) is int
    elif isinstance(column.type, Float):
        valid = type(value) in {int, float} and math.isfinite(value)
    elif isinstance(column.type, String):
        valid = isinstance(value, str) and (
            column.type.length is None or len(value) <= column.type.length
        )
    elif isinstance(column.type, DateTime):
        try:
            value = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            bad("Ungültiger Zeitstempel im Import.")
    if not valid:
        bad(f"Ungültiger Feldtyp: {column.table.name}.{column.name}")
    return value


def validate_tree(rows):
    parents = {row["id"]: row["parent_id"] for row in rows}
    complete = set()
    for item in parents:
        path = set()
        cursor = item
        while cursor and cursor not in complete:
            if cursor in path:
                bad("Zyklische Ortsstruktur im Import.")
            path.add(cursor)
            cursor = parents.get(cursor)
        complete.update(path)


@router.post("/worlds/import", status_code=201)
def import_world(body: WorldBundle, db: DB):
    if set(body.tables) != set(TABLES):
        bad(
            "Unvollständige oder unbekannte Tabellen. "
            "Provider-/Laufzeitkonfiguration ist nicht importierbar."
        )
    if (
        sum(map(len, body.tables.values())) > 100000
        or len(json.dumps(body.model_dump(), ensure_ascii=False)) > 50000000
    ):
        raise HTTPException(413, "Weltexport ist zu groß.")
    if len(body.tables["worlds"]) != 1 or body.tables["worlds"][0].get("id") != body.world_id:
        bad("Export benötigt genau eine konsistent referenzierte Welt.")
    converted = {}
    keys = {}
    try:
        json.dumps(body.model_dump(), allow_nan=False)
        for name, rows in body.tables.items():
            table = TABLES[name]
            columns = set(table.columns.keys())
            if any(set(row) != columns for row in rows):
                bad(f"Unbekannte oder fehlende Felder in {name}.")
            converted[name] = [
                {column.name: typed_value(column, row[column.name]) for column in table.columns}
                for row in rows
            ]
            primary = list(table.primary_key.columns)
            keys[name] = {tuple(row[c.name] for c in primary) for row in rows}
            if len(keys[name]) != len(rows):
                bad(f"Doppelte Identitäten in {name}.")
            if name in DOMAIN:
                schema = DOMAIN[name]
                for row in rows:
                    schema.model_validate(
                        {key: value for key, value in row.items() if key in schema.model_fields}
                    )
        enums = {
            "conversations": {
                "kind": {"single", "group", "simulation"},
                "communication": {"in_person", "remote"},
            },
            "messages": {
                "role": {"user", "assistant"},
                "speaker_type": {"human", "character"},
                "status": {"complete"},
            },
            "simulations": {"status": {"created", "paused", "failed", "completed", "cancelled"}},
            "simulation_turns": {"status": {"generating", "extracting", "complete"}},
            "extraction_jobs": {
                "status": {"pending", "running", "failed", "complete", "skipped", "invalidated"}
            },
            "knowledge": {"status": {"active", "superseded", "revoked", "archived"}},
            "events": {
                "status": {
                    "proposed",
                    "protected",
                    "applied",
                    "rejected",
                    "undone",
                    "invalidated",
                    "recorded",
                }
            },
            "event_rules": {"mode": {"auto", "confirm", "protected"}},
            "event_proposals": {"mode": {"auto", "confirm", "protected"}},
        }
        for name, fields in enums.items():
            for row in body.tables[name]:
                if any(row[key] not in allowed for key, allowed in fields.items()):
                    bad(f"Unbekannter Status oder Modus in {name}.")
        for row in body.tables["world_clocks"]:
            ClockInput.model_validate({key: row[key] for key in ClockInput.model_fields})
        conversations = {row["id"]: row for row in body.tables["conversations"]}
        for row in body.tables["simulations"]:
            conversation = conversations[row["conversation_id"]]
            SimulationInput.model_validate(
                {
                    **{key: row[key] for key in SimulationInput.model_fields if key in row},
                    "scene": conversation["scene"],
                    "location_id": conversation["scene_location_id"],
                    "communication": conversation["communication"],
                    "character_ids": [
                        participant["character_id"]
                        for participant in body.tables["conversation_participants"]
                        if participant["conversation_id"] == conversation["id"]
                        and participant["active"]
                    ],
                }
            )
            if any(
                row[key] < 0
                for key in (
                    "completed_rounds",
                    "run_until",
                    "calls_used",
                    "tokens_reserved",
                    "seconds_used",
                )
            ):
                bad("Negative Simulationszähler.")
            if row["completed_rounds"] > row["max_rounds"] or row["calls_used"] > row["max_calls"]:
                bad("Simulationszähler überschreiten ihre Grenzen.")
        for name, fields in {
            "event_proposals": {"preview": list[dict]},
            "event_audit": {"detail": dict},
            "extraction_jobs": {"event_ids": list[str], "diagnostics": list[dict]},
        }.items():
            for row in body.tables[name]:
                for key, annotation in fields.items():
                    TypeAdapter(annotation).validate_python(row[key], strict=True)
                if name == "event_proposals" and any(
                    not isinstance(change.get("before"), dict)
                    or not isinstance(change.get("after"), dict)
                    for change in row["preview"]
                ):
                    bad("Ungültige Ereignisvorschau.")
        for name, rows in converted.items():
            table = TABLES[name]
            for row in rows:
                if "world_id" in row and row["world_id"] != body.world_id:
                    bad("Import darf keine Daten anderer Welten enthalten.")
                for foreign in table.foreign_keys:
                    value = row[foreign.parent.name]
                    if value is not None and (value,) not in keys[foreign.column.table.name]:
                        bad(f"Fehlende weltinterne Referenz in {name}.{foreign.parent.name}")
        if any(row["status"] == "running" for row in body.tables["simulations"]):
            bad("Laufende Simulationen müssen vor dem Export pausiert werden.")
        event_status = {row["id"]: row["status"] for row in body.tables["events"]}
        for job in body.tables["extraction_jobs"]:
            if any((event_id,) not in keys["events"] for event_id in job["event_ids"]):
                bad("Extraktionsauftrag referenziert ein fehlendes oder fremdes Ereignis.")
        for row in body.tables["event_proposals"]:
            operations = TypeAdapter(list[Operation]).validate_python(row["operations"])
            if event_status[row["event_id"]] not in {"proposed", "protected", "applied"}:
                continue
            for operation in operations:
                values = operation.model_dump()
                for field, referenced_table in {
                    "entity_id": ENTITY_TABLES[operation_class(operation)],
                    "target_id": "characters",
                    "character_id": "characters",
                    "subject_id": "characters",
                    "location_id": "locations",
                    "destination_id": "locations",
                }.items():
                    value = values.get(field)
                    if value is not None and (value,) not in keys[referenced_table]:
                        bad("Offener Ereignisvorschlag referenziert ein fehlendes Weltobjekt.")
                for value in values.get("supersedes", []) + values.get("contradicts", []):
                    if (value,) not in keys["knowledge"]:
                        bad("Wissenskorrektur referenziert ein fehlendes oder fremdes Wissen.")
        for name in ("event_targets", "event_mutations"):
            for row in body.tables[name]:
                table = ENTITY_TABLES.get(row["entity_type"])
                if table is None:
                    bad("Unbekannte Ereignisobjektklasse.")
                if event_status[row["event_id"]] in {"proposed", "protected", "applied"}:
                    if (row["entity_id"],) not in keys[table]:
                        bad("Aktive Ereignisreferenz zeigt auf fehlende oder fremde Daten.")
                if name == "event_mutations":
                    for snapshot in (row["before"], row["after"]):
                        if not isinstance(snapshot, dict) or set(snapshot) - set(
                            TABLES[table].columns.keys()
                        ):
                            bad("Ungültiger Mutationssnapshot.")
                    mutable = {
                        "world": {"state"},
                        "location": {"state"},
                        "character": {"state", "location_id", "destination_id", "travel_status"},
                        "relationship": {"attributes"},
                        "knowledge": {"status"},
                        "clock": {"elapsed_minutes", "minutes_per_day", "epoch_label"},
                    }[row["entity_type"]]
                    created_knowledge = row["entity_type"] == "knowledge" and not row["before"]
                    if set(row["before"]) - mutable or (
                        not created_knowledge and set(row["after"]) - mutable
                    ):
                        bad("Mutationssnapshot darf keine Identitäten oder Weltzuordnung ändern.")
                    for snapshot in (row["before"], row["after"]):
                        for key, value in snapshot.items():
                            column = TABLES[table].c[key]
                            typed_value(column, value)
                            if event_status[row["event_id"]] in {
                                "proposed",
                                "protected",
                                "applied",
                            }:
                                for foreign in column.foreign_keys:
                                    if (
                                        value is not None
                                        and (value,) not in keys[foreign.column.table.name]
                                    ):
                                        bad("Fremde oder fehlende Referenz im Mutationssnapshot.")
                        if "state" in snapshot:
                            TypeAdapter(dict[str, StateValue]).validate_python(
                                snapshot["state"], strict=True
                            )
                        if "attributes" in snapshot:
                            attributes = TypeAdapter(list[Attribute]).validate_python(
                                snapshot["attributes"]
                            )
                            if any(
                                attribute.type == "reference"
                                and not any(
                                    (attribute.value,) in keys[entity_table]
                                    for entity_table in (
                                        "locations",
                                        "characters",
                                        "relationships",
                                        "knowledge",
                                    )
                                )
                                for attribute in attributes
                            ):
                                bad("Mutationssnapshot besitzt eine ungültige Attributreferenz.")
                        if row["entity_type"] == "clock":
                            clock = next(
                                (
                                    clock
                                    for clock in body.tables["world_clocks"]
                                    if clock["id"] == row["entity_id"]
                                ),
                                None,
                            )
                            if clock is None:
                                bad("Mutationssnapshot besitzt keine zugehörige Weltuhr.")
                            ClockInput.model_validate(
                                {
                                    **{key: clock[key] for key in ClockInput.model_fields},
                                    **snapshot,
                                }
                            )
        validate_tree(body.tables["locations"])
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            422, "Ungültiges versioniertes Weltformat oder ungültige Referenzen."
        ) from exc
    try:
        return write_bundle(db, body, converted)
    except IntegrityError as exc:
        raise HTTPException(
            422, "Widersprüchliche Eindeutigkeit oder Referenz. Import verworfen."
        ) from exc


def write_bundle(db: Session, body: WorldBundle, converted: dict):
    with db.begin():
        for name, table in TABLES.items():
            primary = list(table.primary_key.columns)
            for row in converted[name]:
                if db.execute(
                    select(primary[0]).where(*[column == row[column.name] for column in primary])
                ).first():
                    raise HTTPException(
                        409, "Eine importierte Identität existiert bereits. Nichts überschrieben."
                    )
        if db.get_bind().dialect.name == "sqlite":
            db.connection().exec_driver_sql("PRAGMA defer_foreign_keys=ON")
        for table in m.Base.metadata.sorted_tables:
            rows = converted.get(table.name)
            if rows:
                if table.name == "extraction_jobs":
                    for row in rows:
                        if row["status"] in {"pending", "running"}:
                            row["status"] = "failed"
                            row["error"] = "Importierter Auftrag. Nur bewusst erneut starten."
                if table.name == "simulations":
                    for row in rows:
                        row["model"] = ""
                db.execute(table.insert(), rows)
        from .main import validate_references

        for name, schema in DOMAIN.items():
            for row in body.tables[name]:
                validate_references(
                    db,
                    body.world_id,
                    {key: value for key, value in row.items() if key in schema.model_fields},
                )
        if (
            db.get_bind().dialect.name == "sqlite"
            and db.connection().exec_driver_sql("PRAGMA foreign_key_check").first()
        ):
            bad("Referenzprüfung fehlgeschlagen. Import vollständig verworfen.")
    return encode(db.get(m.World, body.world_id))
