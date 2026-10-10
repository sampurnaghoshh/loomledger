"""Production schemas. Field names = contract keys (types.ts StartWeavingRequest/Response)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class StartWeavingRequest(BaseModel):
    machine_code: str = Field(min_length=1, max_length=40)
    yarn_lot_code: str = Field(pattern=r"^Y-\d{3,}$")
    product_code: str = Field(min_length=1, max_length=40)        # the greige product the run makes
    meters_planned: float = Field(gt=0, le=10_000)
    order_code: str | None = Field(default=None, max_length=40)
    operator_code: str | None = Field(default=None, max_length=40)   # omitted = first free weaver
    idempotency_key: str = Field(min_length=8, max_length=100)


class StartWeavingResponse(BaseModel):
    run_code: str
    lot_code: str
    yarn_issued_kg: float


class FinishWeavingRequest(BaseModel):
    waste_kg: float = Field(ge=0, le=10_000)
    idempotency_key: str = Field(min_length=8, max_length=100)


class FinishWeavingResponse(BaseModel):
    run_code: str
    lot_code: str
    meters: float
