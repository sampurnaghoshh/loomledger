"""Rolls schemas. Field names = contract keys (roll_passport_*.json, roll_labels.json)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

ROLL_CODE = r"^R-\d{3,}(-G)?$"          # finished roll R-1204 or greige roll R-1212-G
LOT_CODE = r"^[A-Z]{1,3}-\d{3,}(-G)?$"  # any lot: Y-112, R-1204, R-1212-G

Custody = Literal["passed_in_store", "awaiting_qc", "rework", "rejected", "wip", "at_customer", "consumed"]
LotStatus = Literal["active", "wip", "consumed", "dispatched", "quarantined", "recalled"]


class Receipt(BaseModel):
    code: str
    supplier: str
    received_at: datetime


class Run(BaseModel):
    code: str
    stage: Literal["spinning", "weaving", "dyeing", "finishing"]
    machine: str
    shift: str
    operator: str
    started_at: datetime
    ended_at: datetime | None     # null = still on the machine


class LineageStep(BaseModel):
    lot_code: str
    kind: Literal["yarn", "greige", "finished"]
    product: str
    qty: float
    uom: Literal["kg", "m"]
    depth: int                    # 0 = this roll, 1 = its parent, ...
    receipt: Receipt | None       # yarn: bought
    run: Run | None               # fabric: made


class Qc(BaseModel):
    result: Literal["pass", "rework", "reject"]
    defect_type: str | None
    defect_m: float | None
    inspector: str
    inspected_at: datetime


class Cost(BaseModel):
    material: float
    machine: float
    labour: float
    chemicals: float
    total: float
    cost_per_m: float


class PassportOrder(BaseModel):
    code: str
    buyer: str
    status: str
    promised_date: date
    revised_promise_date: date | None


class PassportDispatch(BaseModel):
    code: str
    dispatched_at: datetime
    vehicle_no: str | None
    invoice_code: str | None


class PassportRecall(BaseModel):
    code: str
    root_lot_code: str
    reason: str
    initiated_at: datetime


class RollPassport(BaseModel):
    code: str
    kind: Literal["greige", "finished"]
    status: LotStatus             # quarantined / recalled once a recall froze it
    custody: Custody              # where it is, derived from facts (v_roll_custody)
    qty_m: float
    product_code: str
    product: str
    colour: str | None
    lineage: list[LineageStep]    # oldest first; the roll itself last
    qc: Qc | None
    cost: Cost
    order: PassportOrder | None
    dispatch: PassportDispatch | None
    recall: PassportRecall | None


class Label(BaseModel):
    code: str
    product: str
    qty_m: float
    custody: Custody
    in_scope: bool                # downstream of the root


class RollLabels(BaseModel):
    root: str | None
    rolls: list[Label]


class RollListItem(BaseModel):
    code: str
    kind: Literal["greige", "finished"]
    product: str
    qty_m: float
    status: LotStatus
    custody: Custody
    order_code: str | None
    buyer: str | None
    qc_result: Literal["pass", "rework", "reject"] | None
    defect_type: str | None
    inspected_at: datetime | None
    created_at: datetime
