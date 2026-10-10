"""Users schemas (017)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

Role = Literal["owner", "store", "floor_supervisor", "qc", "accounts"]


class UserRow(BaseModel):
    id: int
    email: str
    full_name: str
    role: Role
    active: bool
    created_at: datetime


class AccessChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def something_to_change(self):
        if self.role is None and self.active is None:
            raise ValueError("send role and/or active")
        return self
