"""Workforce schemas. Field names = contract keys (workforce_attendance.json, workforce_wages.json)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["present", "absent", "half_day", "leave"]


class ShiftOut(BaseModel):
    code: str
    name: str
    starts_at: str            # "08:00"
    ends_at: str


class RegisterRow(BaseModel):
    worker_code: str
    full_name: str
    skill: str | None
    status: Status | None     # null = not marked yet that day
    shift_code: str | None


class Register(BaseModel):
    day: date
    shifts: list[ShiftOut]
    workers: list[RegisterRow]


class Mark(BaseModel):
    worker_code: str = Field(min_length=1, max_length=40)
    status: Status


class MarkRequest(BaseModel):
    day: date
    shift_code: str = Field(min_length=1, max_length=10)
    marks: list[Mark] = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @field_validator("marks")
    @classmethod
    def one_mark_per_worker(cls, v: list[Mark]) -> list[Mark]:
        codes = [m.worker_code for m in v]
        if len(set(codes)) != len(codes):
            raise ValueError("a worker can only be marked once per submission")
        return v


class MarkResponse(BaseModel):
    batch_id: int
    day: date
    shift_code: str
    marked: int
    marked_at: datetime


class WageRow(BaseModel):
    worker_code: str
    full_name: str
    skill: str | None
    hourly_wage: float
    days_worked: int
    shifts_worked: float
    half_days: int
    absent_days: int
    leave_days: int
    gross_wage: float


class WageTotals(BaseModel):
    workers: int
    days_worked: int
    shifts_worked: float
    gross_wage: float


class Wages(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(serialization_alias="from")    # both ends inclusive
    to: date
    totals: WageTotals
    workers: list[WageRow]
