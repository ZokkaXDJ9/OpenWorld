import json
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, inspect, select, update
from sqlalchemy.orm import Session

from .context import ContextTooLarge, build_context
from .db import get_db
from .models import (
    Character,
    Conversation,
    Knowledge,
    Location,
    Message,
    ProviderSettings,
    Relationship,
    World,
)
from .provider import OpenAIProvider, ProviderError, encrypt_key
from .schemas import (
    CharacterInput,
    ConversationInput,
    EditMessageInput,
    KnowledgeInput,
    LocationInput,
    LocationTreeInput,
    ProviderInput,
    RelationshipInput,
    SendInput,
    WorldInput,
)

app = FastAPI(title="OpenWorld", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "OPENWORLD_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(","),
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)
app.state.provider = OpenAIProvider()
app.state.active_conversations = set()
log = logging.getLogger("openworld")
DB = Annotated[Session, Depends(get_db)]


class Resource(str, Enum):
    locations = "locations"
    characters = "characters"
    relationships = "relationships"
    knowledge = "knowledge"


RESOURCES = {
    Resource.locations: (Location, LocationInput),
    Resource.characters: (Character, CharacterInput),
    Resource.relationships: (Relationship, RelationshipInput),
    Resource.knowledge: (Knowledge, KnowledgeInput),
}
RESOURCE_BODY = {
    "requestBody": {
        "required": True,
        "description": "Eingabemodell passend zum resource-Pfad; PUT benötigt revision.",
        "content": {
            "application/json": {
                "schema": {
                    "anyOf": [
                        {
                            key: value
                            for key, value in schema.model_json_schema(
                                ref_template="#/components/schemas/{model}"
                            ).items()
                            if key != "$defs"
                        }
                        for _, schema in RESOURCES.values()
                    ]
                }
            }
        },
    }
}


def encode(row) -> dict:
    return jsonable_encoder(
        {
            column.key: (
                value.replace(tzinfo=UTC)
                if isinstance(value, datetime) and value.tzinfo is None
                else value
            )
            for column in inspect(type(row)).columns
            for value in [getattr(row, column.key)]
        }
    )


def require(db: Session, model, item_id: str, world_id: str | None = None):
    item = db.get(model, item_id)
    if item is None or (world_id and item.world_id != world_id):
        raise HTTPException(404, "Objekt nicht gefunden")
    return item


def assert_idle(request: Request, conversation_id: str):
    if conversation_id in request.app.state.active_conversations:
        raise HTTPException(409, "In diesem Gespräch läuft bereits eine Antwort")


def validate_references(db: Session, world_id: str, data: dict, item_id: str | None = None):
    for key in ("location_id", "destination_id", "parent_id"):
        if data.get(key):
            require(db, Location, data[key], world_id)
    parent_id = data.get("parent_id")
    while parent_id:
        if parent_id == item_id:
            raise HTTPException(422, "Ortsstruktur darf keinen Zyklus enthalten")
        parent_id = require(db, Location, parent_id, world_id).parent_id
    for key in ("source_id", "target_id", "character_id"):
        if data.get(key):
            require(db, Character, data[key], world_id)
    if data.get("source_id") and data.get("source_id") == data.get("target_id"):
        raise HTTPException(422, "Beziehung benötigt zwei verschiedene Charaktere")
    for attribute in data.get("attributes", []):
        if attribute["type"] == "reference":
            reference = attribute["value"]
            if not any(
                (row := db.get(model, reference)) is not None and row.world_id == world_id
                for model in (Location, Character, Relationship, Knowledge)
            ):
                raise HTTPException(
                    422, "Attributreferenz muss auf ein Objekt derselben Welt zeigen"
                )


def ensure_unreferenced(db: Session, world_id: str, removed_ids: set[str]):
    for model in (World, Location, Character, Relationship):
        condition = model.id == world_id if model is World else model.world_id == world_id
        for owner in db.scalars(select(model).where(condition)):
            if owner.id in removed_ids:
                continue
            if any(
                a["type"] == "reference" and a["value"] in removed_ids for a in owner.attributes
            ):
                raise HTTPException(
                    409, "Objekt oder abhängiger Eintrag wird von einem Feld verwendet"
                )


def sourced_knowledge_ids(db: Session, message_ids) -> set[str]:
    return set(db.scalars(select(Knowledge.id).where(Knowledge.source_message_id.in_(message_ids))))


def update_row(db: Session, item, data: dict):
    revision = data.pop("revision", None)
    if revision is None:
        raise HTTPException(422, "Revision für Bearbeitung erforderlich")
    model = type(item)
    result = db.execute(
        update(model)
        .where(
            model.id == item.id,
            model.revision == revision,
        )
        .values(**data, revision=revision + 1)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Objekt wurde inzwischen geändert. Bitte neu laden.")


def write(db: Session, item, data: dict):
    update_row(db, item, data)
    db.commit()
    db.refresh(item)
    return encode(item)


@app.get("/api/health")
def health():
    return {"status": "ok", "phase": 1}


@app.get("/api/worlds")
def worlds(db: DB):
    return [encode(row) for row in db.scalars(select(World).order_by(World.name))]


@app.post("/api/worlds", status_code=201)
def create_world(body: WorldInput, db: DB):
    data = body.model_dump(exclude={"revision"})
    world = World(**data)
    db.add(world)
    db.flush()
    validate_references(db, world.id, data)
    db.commit()
    return encode(world)


@app.put("/api/worlds/{world_id}")
def edit_world(world_id: str, body: WorldInput, db: DB):
    world = require(db, World, world_id)
    data = body.model_dump()
    validate_references(db, world_id, data)
    return write(db, world, data)


@app.delete("/api/worlds/{world_id}", status_code=204)
async def delete_world(world_id: str, db: DB, request: Request, revision: int = Query(ge=1)):
    world = require(db, World, world_id)
    if world.revision != revision:
        raise HTTPException(409, "Welt wurde inzwischen geändert")
    for conversation in db.scalars(select(Conversation).where(Conversation.world_id == world_id)):
        assert_idle(request, conversation.id)
    for model in (Conversation, Knowledge, Relationship, Character):
        db.execute(delete(model).where(model.world_id == world_id))
    locations = list(db.scalars(select(Location).where(Location.world_id == world_id)))
    # Remove leaves first because parent references intentionally restrict deletion.
    while locations:
        parents = {location.parent_id for location in locations}
        leaves = [location for location in locations if location.id not in parents]
        if not leaves:
            raise HTTPException(409, "Ungültige zyklische Ortsstruktur")
        for location in leaves:
            db.delete(location)
            locations.remove(location)
        db.flush()
    db.delete(world)
    db.commit()


@app.get("/api/worlds/{world_id}/conversations")
def conversations(world_id: str, db: DB):
    require(db, World, world_id)
    return [
        encode(row)
        for row in db.scalars(
            select(Conversation)
            .where(
                Conversation.world_id == world_id,
            )
            .order_by(Conversation.created_at.desc())
        )
    ]


@app.post("/api/worlds/{world_id}/conversations", status_code=201)
def create_conversation(world_id: str, body: ConversationInput, db: DB):
    require(db, World, world_id)
    require(db, Character, body.character_id, world_id)
    row = Conversation(world_id=world_id, **body.model_dump())
    db.add(row)
    db.commit()
    return encode(row)


def ordered_locations(db: Session, world_id: str) -> list[Location]:
    return list(
        db.scalars(
            select(Location)
            .where(Location.world_id == world_id)
            .order_by(Location.sort_order, Location.id)
        )
    )


def next_location_order(db: Session, world_id: str, parent_id: str | None) -> int:
    last = db.scalar(
        select(func.max(Location.sort_order)).where(
            Location.world_id == world_id, Location.parent_id == parent_id
        )
    )
    return 0 if last is None else last + 1


@app.put("/api/worlds/{world_id}/location-tree")
def edit_location_tree(world_id: str, body: LocationTreeInput, db: DB):
    require(db, World, world_id)
    rows = {row.id: row for row in ordered_locations(db, world_id)}
    parents = {item.id: item.parent_id for item in body.locations}
    if rows.keys() != parents.keys():
        raise HTTPException(409, "Weltstruktur wurde inzwischen geändert. Bitte neu laden.")
    for item in body.locations:
        visited = {item.id}
        parent_id = item.parent_id
        while parent_id:
            if parent_id not in rows:
                raise HTTPException(422, "Elternort muss zur selben Welt gehören")
            if parent_id in visited:
                raise HTTPException(422, "Ortsstruktur darf keinen Zyklus enthalten")
            visited.add(parent_id)
            parent_id = parents[parent_id]
    # One transaction protects the complete snapshot, including unchanged locations.
    for item in body.locations:
        update_row(db, rows[item.id], item.model_dump(exclude={"id"}))
    if {row.id for row in ordered_locations(db, world_id)} != rows.keys():
        db.rollback()
        raise HTTPException(409, "Weltstruktur wurde inzwischen geändert. Bitte neu laden.")
    db.commit()
    return [encode(row) for row in ordered_locations(db, world_id)]


@app.get("/api/worlds/{world_id}/{resource}")
def list_resources(world_id: str, resource: Resource, db: DB):
    require(db, World, world_id)
    if resource is Resource.locations:
        return [encode(row) for row in ordered_locations(db, world_id)]
    model, _ = RESOURCES[resource]
    return [encode(row) for row in db.scalars(select(model).where(model.world_id == world_id))]


async def parse_resource(request: Request, schema) -> dict:
    from pydantic import ValidationError

    try:
        return schema.model_validate(await request.json()).model_dump()
    except ValidationError as exc:
        raise HTTPException(
            422,
            jsonable_encoder(
                exc.errors(),
                custom_encoder={
                    ValueError: str,
                },
            ),
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Ungültiges JSON") from exc


@app.post("/api/worlds/{world_id}/{resource}", status_code=201, openapi_extra=RESOURCE_BODY)
async def create_resource(world_id: str, resource: Resource, request: Request, db: DB):
    require(db, World, world_id)
    model, schema = RESOURCES[resource]
    data = await parse_resource(request, schema)
    data.pop("revision")
    validate_references(db, world_id, data)
    if model is Location:
        data["sort_order"] = next_location_order(db, world_id, data["parent_id"])
    row = model(world_id=world_id, **data)
    db.add(row)
    db.commit()
    return encode(row)


@app.put("/api/worlds/{world_id}/{resource}/{item_id}", openapi_extra=RESOURCE_BODY)
async def edit_resource(
    world_id: str,
    resource: Resource,
    item_id: str,
    request: Request,
    db: DB,
):
    model, schema = RESOURCES[resource]
    row = require(db, model, item_id, world_id)
    data = await parse_resource(request, schema)
    if model is Knowledge and row.source_message_id and data["kind"] == "fact":
        raise HTTPException(
            422,
            "Chatwissen nicht direkt in Weltfakten umwandeln. Einen separaten Weltfakt anlegen.",
        )
    validate_references(db, world_id, data, item_id)
    if model is Location and data["parent_id"] != row.parent_id:
        data["sort_order"] = next_location_order(db, world_id, data["parent_id"])
    return write(db, row, data)


@app.delete("/api/worlds/{world_id}/{resource}/{item_id}", status_code=204)
async def delete_resource(
    world_id: str,
    resource: Resource,
    item_id: str,
    request: Request,
    db: DB,
    revision: int = Query(ge=1),
):
    model, _ = RESOURCES[resource]
    row = require(db, model, item_id, world_id)
    if row.revision != revision:
        raise HTTPException(409, "Objekt wurde inzwischen geändert")
    if model is Location:
        if db.scalar(select(Location.id).where(Location.parent_id == item_id)) or db.scalar(
            select(Character.id).where(
                (Character.location_id == item_id) | (Character.destination_id == item_id)
            )
        ):
            raise HTTPException(409, "Ort besitzt Unterorte oder wird von Charakteren verwendet")
    removed_ids = {item_id}
    if model is Character:
        removed_ids.update(
            db.scalars(
                select(Relationship.id).where(
                    (Relationship.source_id == item_id) | (Relationship.target_id == item_id)
                )
            )
        )
        removed_ids.update(
            db.scalars(select(Knowledge.id).where(Knowledge.character_id == item_id))
        )
        for conversation in db.scalars(
            select(Conversation).where(
                Conversation.character_id == item_id,
            )
        ):
            assert_idle(request, conversation.id)
            removed_ids.update(
                sourced_knowledge_ids(
                    db, select(Message.id).where(Message.conversation_id == conversation.id)
                )
            )
    ensure_unreferenced(db, world_id, removed_ids)
    db.delete(row)
    db.commit()


def settings(db: Session) -> ProviderSettings:
    row = db.get(ProviderSettings, 1)
    if row is None:
        row = ProviderSettings(id=1)
        db.add(row)
        db.commit()
    return row


def public_settings(row: ProviderSettings) -> dict:
    data = encode(row)
    data["has_api_key"] = bool(data.pop("encrypted_key"))
    return data


@app.get("/api/settings/provider")
def get_settings(db: DB):
    return public_settings(settings(db))


@app.put("/api/settings/provider")
def put_settings(body: ProviderInput, db: DB):
    row = settings(db)
    for key, value in body.model_dump(exclude={"api_key", "clear_key"}).items():
        setattr(row, key, value)
    if body.api_key:
        row.encrypted_key = encrypt_key(body.api_key)
    elif body.clear_key:
        row.encrypted_key = ""
    db.commit()
    return public_settings(row)


@app.get("/api/conversations/{conversation_id}/messages")
def messages(conversation_id: str, db: DB):
    require(db, Conversation, conversation_id)
    return [
        encode(row)
        for row in db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
            )
            .order_by(Message.sequence)
        )
    ]


@app.delete("/api/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, request: Request, db: DB):
    assert_idle(request, conversation_id)
    conversation = require(db, Conversation, conversation_id)
    ensure_unreferenced(
        db,
        conversation.world_id,
        sourced_knowledge_ids(
            db, select(Message.id).where(Message.conversation_id == conversation_id)
        ),
    )
    db.delete(conversation)
    db.commit()


@app.put("/api/conversations/{conversation_id}/messages/{message_id}")
async def edit_message(
    conversation_id: str,
    message_id: str,
    body: EditMessageInput,
    request: Request,
    db: DB,
):
    assert_idle(request, conversation_id)
    conversation = require(db, Conversation, conversation_id)
    message = require(db, Message, message_id)
    if message.conversation_id != conversation_id or message.role != "user":
        raise HTTPException(422, "Nur eigene Nachrichten dieses Gesprächs sind bearbeitbar")
    if not body.confirm_discard:
        raise HTTPException(409, "Nachfolgende Nachrichten und ihre Erinnerungen werden entfernt")
    ensure_unreferenced(
        db,
        conversation.world_id,
        sourced_knowledge_ids(
            db,
            select(Message.id).where(
                Message.conversation_id == conversation_id, Message.sequence >= message.sequence
            ),
        ),
    )
    db.execute(
        delete(Message).where(
            Message.conversation_id == conversation_id,
            Message.sequence > message.sequence,
        )
    )
    db.execute(delete(Knowledge).where(Knowledge.source_message_id == message.id))
    message.content = body.content
    db.add(
        Knowledge(
            world_id=conversation.world_id,
            character_id=conversation.character_id,
            kind="received",
            content=body.content,
            source="Benutzeraussage",
            confidence=50,
            source_message_id=message.id,
        )
    )
    db.commit()
    return encode(message)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def response_stream(
    conversation: Conversation,
    request: Request,
    db: Session,
    replace_message: Message | None = None,
) -> StreamingResponse:
    provider_settings = settings(db)
    if not provider_settings.model:
        raise HTTPException(422, "Bitte zuerst einen KI-Anbieter und ein Modell konfigurieren")
    try:
        context, token_count = build_context(
            db,
            conversation,
            provider_settings.context_window,
            provider_settings.max_output_tokens,
            exclude_message_id=replace_message.id if replace_message else None,
        )
    except ContextTooLarge as exc:
        raise HTTPException(422, str(exc)) from exc
    last_sequence = (
        db.scalar(
            select(Message.sequence)
            .where(
                Message.conversation_id == conversation.id,
            )
            .order_by(Message.sequence.desc())
            .limit(1)
        )
        or 0
    )

    async def generate() -> AsyncIterator[str]:
        content = ""
        try:
            yield sse("context", {"input_tokens": token_count})
            async for chunk in request.app.state.provider.stream(context, provider_settings):
                content += chunk
                yield sse("delta", {"text": chunk})
            if not content.strip():
                raise ProviderError("KI-Anbieter hat eine leere Antwort geliefert")
            if replace_message:
                db.delete(replace_message)
                db.flush()
            assistant = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=content,
                sequence=replace_message.sequence if replace_message else last_sequence + 1,
            )
            db.add(assistant)
            db.commit()
            yield sse("done", {"message": encode(assistant)})
        except ProviderError as exc:
            log.warning("Provider failed in conversation %s: %s", conversation.id, exc)
            yield sse("error", {"message": str(exc)})
        except Exception:
            db.rollback()
            log.exception("Chat failed in conversation %s", conversation.id)
            yield sse("error", {"message": "Interner Chatfehler. Bitte Backend-Protokoll prüfen."})
        finally:
            request.app.state.active_conversations.discard(conversation.id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, body: SendInput, request: Request, db: DB):
    assert_idle(request, conversation_id)
    conversation = require(db, Conversation, conversation_id)
    if not settings(db).model:
        raise HTTPException(422, "Bitte zuerst einen KI-Anbieter und ein Modell konfigurieren")
    sequence = (
        db.scalar(
            select(Message.sequence)
            .where(
                Message.conversation_id == conversation_id,
            )
            .order_by(Message.sequence.desc())
            .limit(1)
        )
        or 0
    )
    message = Message(
        conversation_id=conversation_id,
        role="user",
        content=body.content,
        sequence=sequence + 1,
    )
    db.add(message)
    db.flush()
    db.add(
        Knowledge(
            world_id=conversation.world_id,
            character_id=conversation.character_id,
            kind="received",
            content=body.content,
            source="Benutzeraussage",
            confidence=50,
            source_message_id=message.id,
        )
    )
    response = response_stream(conversation, request, db)
    db.commit()
    request.app.state.active_conversations.add(conversation.id)
    return response


@app.post("/api/conversations/{conversation_id}/regenerate")
async def regenerate(conversation_id: str, request: Request, db: DB):
    assert_idle(request, conversation_id)
    conversation = require(db, Conversation, conversation_id)
    last = db.scalar(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
        )
        .order_by(Message.sequence.desc())
        .limit(1)
    )
    if last is None:
        raise HTTPException(422, "Noch keine Nachricht vorhanden")
    response = response_stream(
        conversation,
        request,
        db,
        replace_message=last if last.role == "assistant" else None,
    )
    db.commit()
    request.app.state.active_conversations.add(conversation.id)
    return response


frontend_dir = os.environ.get("OPENWORLD_FRONTEND_DIR")
if frontend_dir:
    frontend_path = Path(frontend_dir)
    if not (frontend_path / "index.html").is_file():
        raise RuntimeError(
            "Frontend-Build fehlt. Zuerst npm run build im frontend-Ordner ausführen."
        )
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
