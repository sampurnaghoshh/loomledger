"""Floor schemas. Field names = contract keys (docs/api-mocks/floor_*.json)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MachineState = Literal["running", "idle", "breakdown", "changeover"]
MachineStage = Literal["spinning", "weaving", "dyeing", "finishing"]


class MachineNow(BaseModel):
    code: str
    name: str
    stage: MachineStage
    state: MachineState
    state_since: datetime | None
    reason: str | None
    current_run: str | None
    current_lot: str | None
    current_order: str | None


class MachineOutput(BaseModel):
    machine_code: str
    machine_name: str
    stage: MachineStage
    runs_completed: int
    meters: float


class FloorOutput(BaseModel):
    day: date
    machines: list[MachineOutput]


class MachineAvailability(BaseModel):
    machine_code: str
    running_h: float
    breakdown_h: float
    availability_pct: float | None      # null when the machine neither ran nor broke down in the window


class FloorAvailability(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: datetime = Field(serialization_alias="from")
    to: datetime
    machines: list[MachineAvailability]


class StateChangeRequest(BaseModel):
    state: MachineState
    reason: str | None = Field(default=None, max_length=200)


class StateChangeResponse(BaseModel):
    machine_code: str
    state: MachineState
    started_at: datetime
