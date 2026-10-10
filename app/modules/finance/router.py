"""Finance endpoints (month-end). Accounts (owner always)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth import Conn, require_role
from app.modules.finance import service
from app.modules.finance.schemas import MassBalance, RollCost

router = APIRouter(prefix="/api/finance", tags=["finance"])
Accounts = Annotated[dict, Depends(require_role("accounts"))]


@router.get("/mass-balance", response_model=MassBalance)
def mass_balance(conn: Conn, user: Accounts,
                 from_: Annotated[datetime | None, Query(alias="from")] = None,
                 to: datetime | None = None):
    return service.mass_balance(conn, from_, to)


@router.get("/roll-costs", response_model=list[RollCost])
def roll_costs(conn: Conn, user: Accounts, order_code: Annotated[str, Query(min_length=1, max_length=40)]):
    return service.roll_costs(conn, order_code)
