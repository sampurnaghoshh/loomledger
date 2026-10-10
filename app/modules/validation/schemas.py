"""Validation log schemas (018)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ValidationLogRow(BaseModel):
    id: int
    at: datetime
    user_email: str | None
    role: str | None
    method: str
    path: str
    status: int
    error_code: str
    sqlstate: str | None
    message: str
    input_summary: Any
