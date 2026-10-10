"""Finance schemas. Field names = contract keys (finance_mass_balance.json, finance_roll_costs_*.json)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BalanceTotals(BaseModel):
    received_kg: float
    issued_kg: float
    fabric_kg: float
    waste_kg: float
    wip_kg: float
    unaccounted_kg: float
    unaccounted_pct: float | None        # null when nothing was issued in the window


class MachineUnaccounted(BaseModel):
    machine_code: str
    machine_name: str
    runs: int
    issued_kg: float
    unaccounted_kg: float
    unaccounted_pct: float | None


class MassBalance(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: datetime | None = Field(serialization_alias="from")    # null = all time
    to: datetime | None
    first_run_at: datetime | None         # earliest weaving run in the window; null when there are none
    totals: BalanceTotals
    by_machine: list[MachineUnaccounted]  # worst first


class RollCost(BaseModel):
    lot_code: str
    qty_m: float
    material: float
    machine: float
    labour: float
    chemicals: float
    total: float
    cost_per_m: float
    custody: Literal["consumed", "at_customer", "wip", "rejected", "rework", "passed_in_store", "awaiting_qc"]
    status: Literal["active", "wip", "consumed", "dispatched", "quarantined", "recalled"]
