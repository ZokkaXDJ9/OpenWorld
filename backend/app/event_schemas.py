from datetime import datetime
from math import isfinite
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from .schemas import Attribute, KnowledgeKind, StrictModel

Mode = Literal["auto", "confirm", "protected"]
ObjectClass = Literal["knowledge", "character", "relationship", "location", "world", "*"]
StateValue = str | float | bool | list[str]


class KnowledgeOperation(StrictModel):
    op: Literal["knowledge"] = "knowledge"
    character_id: str | None = None
    subject_id: str | None = None
    kind: KnowledgeKind = "received"
    content: str = Field(min_length=1, max_length=100000)
    confidence: int = Field(default=50, ge=0, le=100)
    importance: int = Field(default=50, ge=0, le=100)
    emotion: str = Field(default="", max_length=200)
    source: str = Field(default="Editor", max_length=200)
    supersedes: list[str] = Field(default_factory=list, max_length=20)
    contradicts: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def scope(self) -> Self:
        if (self.kind == "fact") != (self.character_id is None):
            raise ValueError("Weltfakten und persönliches Wissen müssen getrennt bleiben")
        if not self.content.strip():
            raise ValueError("Wissensinhalt darf nicht leer sein")
        if len(set(self.supersedes)) != len(self.supersedes):
            raise ValueError("Doppelte Wissenskorrektur")
        return self


class StateOperation(StrictModel):
    op: Literal["state"] = "state"
    entity_type: Literal["character", "location", "world"]
    entity_id: str
    revision: int = Field(ge=1)
    values: dict[str, StateValue] = Field(min_length=1, max_length=30)
    value_quotes: dict[str, str] = Field(default_factory=dict, max_length=30)

    @field_validator("values")
    @classmethod
    def finite_values(cls, value: dict[str, StateValue]) -> dict[str, StateValue]:
        if any(isinstance(item, float) and not isfinite(item) for item in value.values()):
            raise ValueError("Zustandswerte müssen endliche Zahlen sein")
        return value


class RelationshipValue(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    value: StateValue


class RelationshipOperation(StrictModel):
    op: Literal["relationship"] = "relationship"
    entity_id: str
    revision: int = Field(ge=1)
    target_id: str | None = Field(default=None, max_length=36)
    attribute_quotes: dict[str, str] = Field(
        default_factory=dict,
        max_length=100,
        description=(
            "Bei einem Attribut weglassen oder {}: evidence_quote wird verwendet. "
            "Nur bei mehreren Attributen: Schlüssel exakt attributes[].name; Wert jeweils "
            "ein unveränderter wörtlicher Ausschnitt aus evidence_quote, keine Paraphrase."
        ),
    )
    attributes: list[Attribute | RelationshipValue] = Field(min_length=1, max_length=100)

    @field_validator("attributes")
    @classmethod
    def unique(
        cls, value: list[Attribute | RelationshipValue]
    ) -> list[Attribute | RelationshipValue]:
        if len({a.name.casefold() for a in value}) != len(value):
            raise ValueError("Doppelte Beziehungsattribute")
        if any(isinstance(a.value, float) and not isfinite(a.value) for a in value):
            raise ValueError("Beziehungswerte müssen endliche Zahlen sein")
        return value


class LocationOperation(StrictModel):
    op: Literal["location"] = "location"
    entity_id: str
    revision: int = Field(ge=1)
    location_id: str | None = None
    destination_id: str | None = None
    travel_status: Literal["present", "traveling", "unknown"]

    @model_validator(mode="after")
    def location(self) -> Self:
        if self.travel_status == "present" and not self.location_id:
            raise ValueError("Anwesende Charaktere benötigen einen Ort")
        if self.travel_status == "unknown" and (self.location_id or self.destination_id):
            raise ValueError("Unbekannter Standort darf keine Ortsreferenz besitzen")
        return self


class ArchiveOperation(StrictModel):
    op: Literal["archive"] = "archive"
    entity_id: str
    revision: int = Field(ge=1)


class TransferOperation(StrictModel):
    op: Literal["transfer"] = "transfer"
    entity_id: str
    revision: int = Field(ge=1)
    target_id: str
    target_revision: int = Field(ge=1)
    item: str = Field(min_length=1, max_length=200)


class ClockOperation(StrictModel):
    op: Literal["clock"] = "clock"
    entity_id: str
    revision: int = Field(ge=1)
    elapsed_minutes: int = Field(ge=0, le=1000000000)
    minutes_per_day: int = Field(default=1440, ge=60, le=100000)
    epoch_label: str = Field(default="Tag 1", min_length=1, max_length=200)


Operation = Annotated[
    KnowledgeOperation
    | StateOperation
    | RelationshipOperation
    | LocationOperation
    | ArchiveOperation
    | TransferOperation
    | ClockOperation,
    Field(discriminator="op"),
]


class EventInput(StrictModel):
    recipient_id: str | None = Field(default=None, max_length=36)
    source_message_id: str | None = Field(default=None, max_length=36)
    event_type: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1, max_length=10000)
    occurred_at: datetime | None = None
    participant_ids: list[str] = Field(default_factory=list, max_length=50)
    location_id: str | None = None
    confidence: int = Field(default=50, ge=0, le=100)
    evidence_quote: str = Field(default="", max_length=100000)
    operations: list[Operation] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def dates_and_ids(self) -> Self:
        if self.occurred_at and self.occurred_at.tzinfo is None:
            raise ValueError("Ereigniszeit benötigt eine Zeitzone")
        if len(set(self.participant_ids)) != len(self.participant_ids):
            raise ValueError("Doppelte Beteiligte")
        return self


class ExtractionOutput(StrictModel):
    events: list[EventInput] = Field(max_length=20)


class EventAction(StrictModel):
    revision: int = Field(ge=1)


class RuleInput(StrictModel):
    event_type: str = Field(default="*", min_length=1, max_length=100)
    object_class: ObjectClass = "*"
    mode: Mode
    revision: int | None = Field(default=None, ge=1)


class EventSettingsInput(StrictModel):
    enabled: bool
    revision: int = Field(ge=1)
