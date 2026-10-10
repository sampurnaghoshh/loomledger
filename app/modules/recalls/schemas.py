"""Recall schemas. Field names = contract keys (recall_preview.json, recall_applied.json)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Stage = Literal["spinning", "weaving", "dyeing", "finishing"]


class RecallImpact(BaseModel):
    root_lot_code: str
    rolls_total: int
    rolls_rejected: int
    rolls_at_risk: int
    rolls_passed_in_store: int
    rolls_awaiting_qc: int
    rolls_wip: int
    rolls_at_customer: int
    orders_affected: int
    buyers_affected: int
    buyers_holding_goods: int
    remake_m: float
    bottleneck_stage: Stage | None
    throughput_m_per_day: float | None
    additional_delay_days: int
    cost_already_incurred: float
    cost_in_factory: float
    cost_wip: float
    cost_at_customer: float
    recall_exposure: float
    quarantined_material_qty: float
    quarantined_material_value: float
    total_exposure: float


class RecallOrderImpact(BaseModel):
    order_id: int
    order_code: str
    buyer_name: str
    product_code: str
    affected_rolls: int
    rolls_at_customer: int
    at_customer_codes: str | None
    remake_m: float
    bottleneck_stage: Stage
    throughput_m_per_day: float
    cumulative_remake_m: float
    delay_days: int
    promised_date: date
    revised_promise_date: date


class RecallRoll(BaseModel):
    lot_code: str
    kind: Literal["yarn", "greige", "finished"]
    qty_m: float
    custody: str
    order_code: str | None
    buyer_name: str | None
    cost: float


class Calculation(BaseModel):
    formula: str
    remake_m: float
    throughput_m_per_day: float | None
    raw_days: float
    additional_delay_days: int
    display: str                        # "600 ÷ 250 = 2.4 → ceil = 3 working days"


class _RecallBody(BaseModel):
    lot_code: str
    impact: RecallImpact
    orders: list[RecallOrderImpact]
    rolls: list[RecallRoll]
    calculation: Calculation


class RecallPreview(_RecallBody):
    applied: Literal[False]
    recall_code: None


class RecallApplied(_RecallBody):
    applied: Literal[True]
    recall_code: str
    applied_at: datetime


class ApplyRecallRequest(BaseModel):
    lot_code: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=3, max_length=500)
