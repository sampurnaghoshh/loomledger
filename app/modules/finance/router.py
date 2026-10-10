"""Finance endpoints (month-end, P&L, buyer payments). Accounts (owner always)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.auth import Conn, require_permission
from app.listing import ListParams, Page
from app.modules.finance import service
from app.modules.finance.schemas import InvoiceRow, MassBalance, PaymentRequest, PaymentResponse, Pnl, RollCost

router = APIRouter(prefix="/api/finance", tags=["finance"])
Accounts = Annotated[dict, Depends(require_permission("finance.access"))]


@router.get("/mass-balance", response_model=MassBalance)
def mass_balance(conn: Conn, user: Accounts,
                 from_: Annotated[datetime | None, Query(alias="from")] = None,
                 to: datetime | None = None):
    return service.mass_balance(conn, from_, to)


@router.get("/roll-costs", response_model=list[RollCost])
def roll_costs(conn: Conn, user: Accounts, order_code: Annotated[str, Query(min_length=1, max_length=40)]):
    return service.roll_costs(conn, order_code)


@router.get("/pnl", response_model=Pnl)
def pnl(conn: Conn, user: Accounts,
        from_: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None):
    return service.pnl(conn, from_, to)


@router.post("/payments", response_model=PaymentResponse, status_code=201)
def record_payment(body: PaymentRequest, conn: Conn, response: Response, user: Accounts):
    result, created = service.record_payment(conn, body, user)
    if not created:
        response.status_code = 200      # idempotent replay: the original payment
    return result


@router.get("/invoices", response_model=Page[InvoiceRow])
def invoices_page(conn: Conn, user: Accounts, query: ListParams,
                  buyer: Annotated[str | None, Query(max_length=100)] = None,
                  order_code: Annotated[str | None, Query(max_length=40)] = None,
                  unpaid: bool | None = None):
    """Invoices with their dispatch and balance, paged: ?sort=(-)issued_at|code|amount|outstanding|buyer"""
    return service.page_invoices(conn, query, {"buyer": buyer, "order_code": order_code, "unpaid": unpaid})
