from datetime import date
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KnowledgeKind = Literal[
    "fact", "knowledge", "belief", "suspicion", "rumor", "secret", "memory", "received"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Attribute(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["text", "number", "boolean", "select", "multiselect", "date", "reference"]
    value: str | float | bool | list[str]
    options: list[str] = Field(default_factory=list, max_length=100)
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def check_value(self) -> Self:
        value = self.value
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Minimum darf Maximum nicht überschreiten")
        if self.type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Zahlenfeld erwartet eine Zahl")
            if self.minimum is not None and value < self.minimum:
                raise ValueError("Wert unter Minimum")
            if self.maximum is not None and value > self.maximum:
                raise ValueError("Wert über Maximum")
        elif self.type == "boolean":
            if not isinstance(value, bool):
                raise ValueError("Boolean-Feld erwartet true/false")
        elif self.type == "multiselect":
            if not isinstance(value, list) or any(item not in self.options for item in value):
                raise ValueError("Ungültige Mehrfachauswahl")
        else:
            if not isinstance(value, str):
                raise ValueError("Dieses Feld erwartet Text")
            if self.type == "select" and value not in self.options:
                raise ValueError("Ungültige Auswahl")
            if self.type == "date":
                date.fromisoformat(value)
        return self


class ObjectInput(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=100000)
    attributes: list[Attribute] = Field(default_factory=list, max_length=100)
    state: dict[str, str | float | bool | list[str]] = Field(default_factory=dict)
    revision: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name darf nicht leer sein")
        return value.strip()

    @field_validator("attributes")
    @classmethod
    def unique_names(cls, value: list[Attribute]) -> list[Attribute]:
        if len({a.name.casefold() for a in value}) != len(value):
            raise ValueError("Attributnamen müssen eindeutig sein")
        return value


class WorldInput(ObjectInput):
    pass


class LocationInput(ObjectInput):
    parent_id: str | None = None
    kind: str = Field(default="Ort", min_length=1, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=100)


class LocationTreeItemInput(StrictModel):
    id: str = Field(min_length=1, max_length=36)
    parent_id: str | None = None
    sort_order: int = Field(ge=0)
    revision: int = Field(ge=1)


class LocationTreeInput(StrictModel):
    locations: list[LocationTreeItemInput]

    @model_validator(mode="after")
    def check_order(self) -> Self:
        if len({item.id for item in self.locations}) != len(self.locations):
            raise ValueError("Orte dürfen nicht mehrfach in der Weltstruktur vorkommen")
        groups: dict[str | None, list[int]] = {}
        for item in self.locations:
            groups.setdefault(item.parent_id, []).append(item.sort_order)
        for orders in groups.values():
            if sorted(orders) != list(range(len(orders))):
                raise ValueError("Ortsreihenfolge muss je Elternort eindeutig und lückenlos sein")
        return self


class CharacterInput(ObjectInput):
    profile: dict[str, str] = Field(default_factory=dict)
    location_id: str | None = None
    destination_id: str | None = None
    travel_status: Literal["present", "traveling", "unknown"] = "unknown"

    @model_validator(mode="after")
    def check_location(self) -> Self:
        if self.travel_status == "present" and not self.location_id:
            raise ValueError("Anwesende Charaktere benötigen einen Aufenthaltsort")
        if self.travel_status == "unknown" and (self.location_id or self.destination_id):
            raise ValueError("Unbekannter Standort darf keine Ortsreferenzen besitzen")
        return self


class RelationshipInput(StrictModel):
    source_id: str
    target_id: str
    kind: str = Field(default="Bekanntschaft", min_length=1, max_length=100)
    description: str = Field(default="", max_length=100000)
    attributes: list[Attribute] = Field(default_factory=list, max_length=100)
    secret: bool = False
    revision: int | None = Field(default=None, ge=1)


class KnowledgeInput(StrictModel):
    character_id: str | None = None
    kind: KnowledgeKind
    content: str = Field(min_length=1, max_length=100000)
    source: str = Field(default="Editor", max_length=200)
    confidence: int = Field(default=100, ge=0, le=100)
    public: bool = False
    revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_scope(self) -> Self:
        if self.kind == "fact" and self.character_id:
            raise ValueError("Objektive Fakten gehören zur Welt")
        if self.kind != "fact" and not self.character_id:
            raise ValueError("Persönliches Wissen benötigt einen Charakter")
        if self.public and self.kind != "fact":
            raise ValueError("Nur objektive Fakten können öffentlich sein")
        return self


class ConversationInput(StrictModel):
    character_id: str
    title: str = Field(default="Neues Gespräch", min_length=1, max_length=200)


class SendInput(StrictModel):
    content: str = Field(min_length=1, max_length=100000)

    @field_validator("content")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Nachricht darf nicht leer sein")
        return value


class EditMessageInput(SendInput):
    confirm_discard: bool = False


class ConnectionInput(StrictModel):
    base_url: str = Field(max_length=2000)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=10000)
    clear_key: bool = False
    context_window: int = Field(default=131072, ge=1024)
    max_output_tokens: int = Field(default=2048, ge=1)
    temperature: float = Field(default=0.7, ge=0, le=2)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("Base-URL muss eine HTTP(S)-Adresse sein")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Base-URL darf keine Zugangsdaten, Query oder Fragment enthalten")
        return value.rstrip("/")

    @model_validator(mode="after")
    def budget(self) -> Self:
        if self.max_output_tokens + 256 >= self.context_window:
            raise ValueError("Kontextfenster muss Platz für Eingabe und Ausgabe bieten")
        if self.clear_key and self.api_key:
            raise ValueError("Schlüssel nicht gleichzeitig setzen und löschen")
        return self


class ProviderInput(ConnectionInput):
    reasoning_profile: Literal["default", "openai", "llama_cpp", "lmstudio", "ollama"] = "default"
    reasoning_mode: Literal["default", "off", "on", "low", "medium", "high"] = "default"

    @model_validator(mode="after")
    def reasoning_options(self) -> Self:
        allowed = {
            "default": {"default"},
            "lmstudio": {"default", "off"},
            "llama_cpp": {"default", "off", "on"},
            "openai": {"default", "off", "low", "medium", "high"},
            "ollama": {"default", "off", "on"},
        }
        if self.reasoning_mode not in allowed[self.reasoning_profile]:
            raise ValueError("Reasoning-Modus passt nicht zum gewählten Chat-Anbieterprofil")
        return self


class ExtractionProviderInput(ConnectionInput):
    use_chat_connection: bool = True
    base_url: str = Field(default="http://localhost:1234/v1", max_length=2000)
    model: str = Field(default="", max_length=200)
    context_window: int = Field(default=16384, ge=1024)
    max_output_tokens: int = Field(default=4096, ge=1, le=65536)
    temperature: float = Field(default=0, ge=0, le=2)
    timeout_seconds: int = Field(default=300, ge=15, le=1800)
    provider_profile: Literal["compatible", "openai", "llama_cpp", "ollama", "lmstudio"] = (
        "compatible"
    )
    reasoning_mode: Literal["default", "off", "on", "low", "medium", "high"] = "default"
    structured_output: Literal["auto", "json_schema", "json_object", "text"] = "auto"
    auto_retry: bool = True

    @model_validator(mode="after")
    def profile_options(self) -> Self:
        if self.provider_profile == "compatible" and self.reasoning_mode != "default":
            raise ValueError("Für Reasoning-Steuerung ein passendes Anbieterprofil wählen")
        if self.provider_profile == "openai" and self.reasoning_mode == "on":
            raise ValueError("OpenAI benötigt off, low, medium oder high")
        if self.provider_profile == "llama_cpp" and self.reasoning_mode not in {
            "default",
            "off",
            "on",
        }:
            raise ValueError("llama.cpp unterstützt hier nur default, off oder on")
        if self.provider_profile == "lmstudio" and self.structured_output not in {"auto", "text"}:
            raise ValueError("LM Studio mit Reasoning-Steuerung nutzt natives JSON per Prompt")
        return self


class ProviderDiscoveryInput(ProviderInput):
    model: str = Field(default="", max_length=200)
    kind: Literal["lmstudio", "ollama", "openai", "compatible"] = "compatible"
    automatic: bool = False
    allow_compatibility_retry: bool = False
    manual_model: bool = False


class SetupInput(StrictModel):
    provider: ProviderInput
    kind: Literal["lmstudio", "ollama", "openai", "compatible"]
    configure_memories: bool = True
    verification_token: str = Field(min_length=1, max_length=100)
