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


class RunProgress(BaseModel):
    machine_code: str
    machine_name: str
    state: MachineState           # at `at`
    run_code: str
    lot_code: str
    order_code: str | None
    started_at: datetime
    planned_m: float
    rated_m_per_hour: float
    planned_hours: float          # planned_m / rated_m_per_hour
    productive_hours: float       # time in 'running' since the run started
    paused_hours: float           # breakdowns / changeovers since the run started
    progress_pct: float           # productive / planned, capped at 100
    est_done_m: float             # estimated metres woven (no metre counter on a loom)
    remaining_hours: float
    over_plan_hours: float        # running past the planned time
    expected_end: datetime | None  # null while the machine is not running
    woven_to_plan_at: datetime | None  # running time reached the plan: due off the loom since then; null = under plan


class FloorProgress(BaseModel):
    at: datetime                  # the moment the progress is computed for (default now)
    runs: list[RunProgress]
