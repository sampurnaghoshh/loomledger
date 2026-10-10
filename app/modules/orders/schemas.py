"""Orders, dispatch and buyer-portal schemas. Field names = contract keys (orders.json, track_*.json)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class OrderProgress(BaseModel):
    ready_m: float
    on_hold_m: float
    weaving_m: float
    dispatched_m: float
    quality_check_m: float


class OrderSummary(BaseModel):
    code: str
    buyer: str
    product: str
    ordered_m: float
    unit_price: float
    promised_date: date
    revised_promise_date: date | None
    delay_days: int                     # working days (Mon–Sat) from promised to revised; 0 when on time
    status: Literal["confirmed", "in_production", "partially_dispatched", "dispatched", "cancelled"]
    progress: OrderProgress
    tracking_token: UUID


class BuyerUpdate(BaseModel):
    at: datetime
    message: str


class BuyerOrderStatus(BaseModel):
    order: str
    buyer: str
    product: str
    ordered_m: float
    promised_date: date
    expected_date: date
    delayed: bool
    progress: OrderProgress
    updates: list[BuyerUpdate]          # newest first


class DispatchRequest(BaseModel):
    order_code: str = Field(min_length=1, max_length=40)
    lot_codes: list[str] = Field(min_length=1, max_length=200)
    vehicle_no: str = Field(min_length=1, max_length=40)
    idempotency_key: str = Field(min_length=8, max_length=100)
    shade_override_reason: str | None = Field(default=None, min_length=3, max_length=500)   # allows mixed dye batches

    @field_validator("lot_codes")
    @classmethod
    def distinct_roll_codes(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("a roll can only be listed once")
        if not all(c.startswith("R-") and c[2:].isdigit() for c in v):
            raise ValueError("finished roll codes look like R-1234")
        return v


class DispatchResponse(BaseModel):
    dispatch_code: str
    invoice_code: str
    amount: float
