"""Quality schemas. Field names = contract keys (docs/api-mocks/quality_*.json, types.ts InspectionRequest)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

QcResult = Literal["pass", "rework", "reject"]


class QueueItem(BaseModel):
    lot_code: str
    product: str
    qty_m: float
    dye_batch: str
    dyed_on: str
    dyed_at: datetime
    order_code: str | None


class Rejection(BaseModel):
    lot_code: str
    defect_type: str
    defect_meters: float | None
    inspected_at: datetime
    inspector: str
    order_code: str | None


class InspectionRequest(BaseModel):
    lot_code: str = Field(pattern=r"^R-\d{3,}$")
    result: QcResult
    defect_type: str | None = Field(default=None, max_length=60, validate_default=True)
    defect_meters: float | None = Field(default=None, ge=0, le=10_000)
    notes: str | None = Field(default=None, max_length=500)
    inspector_code: str | None = Field(default=None, max_length=40)       # omitted = the QC inspector on record
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)   # protects reject replays

    @field_validator("defect_type")
    @classmethod
    def defect_matches_result(cls, v: str | None, info: ValidationInfo) -> str | None:
        # mirrors qc_inspection_check so the form gets a field error; the database still enforces it
        result = info.data.get("result")
        if result in ("rework", "reject") and not (v and v.strip()):
            raise ValueError("required when the roll does not pass")
        if result == "pass" and v:
            raise ValueError("must be empty when the roll passes")
        return v.strip() if v else v


class InspectionResponse(BaseModel):
    inspection_id: int
    lot_code: str
    result: QcResult
