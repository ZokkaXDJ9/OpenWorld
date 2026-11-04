from typing import Literal

from pydantic import Field

from .schemas import StrictModel


class GroupInput(StrictModel):
    title: str = Field(default="Begegnung", min_length=1, max_length=200)
    character_ids: list[str] = Field(min_length=2, max_length=12)
    scene: str = Field(default="", max_length=10000)
    location_id: str
    communication: Literal["in_person", "remote"] = "in_person"


class SimulationInput(GroupInput):
    recognize_events: bool = True
    max_rounds: int = Field(default=20, ge=1, le=500)
    max_calls: int = Field(default=100, ge=1, le=2000)
    max_tokens: int = Field(default=250000, ge=1024, le=10000000)
    timeout_seconds: int = Field(default=600, ge=5, le=7200)
    minutes_per_round: int = Field(default=1, ge=0, le=1440)
    event_mode: Literal["observe", "rules", "confirm"] = "rules"
    model: str = Field(default="", max_length=200)


class SimulationControl(StrictModel):
    revision: int = Field(ge=1)
    steps: int | None = Field(default=None, ge=1, le=500)


class Intervention(StrictModel):
    revision: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=10000)
    address_id: str | None = None


class SceneInput(StrictModel):
    revision: int = Field(ge=1)
    scene: str = Field(max_length=10000)
    location_id: str
    character_ids: list[str] = Field(min_length=2, max_length=12)
    communication: Literal["in_person", "remote"] = "in_person"


class ClockInput(StrictModel):
    revision: int = Field(ge=1)
    elapsed_minutes: int = Field(ge=0, le=1000000000)
    minutes_per_day: int = Field(default=1440, ge=60, le=100000)
    epoch_label: str = Field(default="Tag 1", min_length=1, max_length=200)


class GroupTurnInput(StrictModel):
    speaker_id: str


class GroupMessageInput(StrictModel):
    content: str = Field(min_length=1, max_length=10000)
