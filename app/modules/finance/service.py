"""Month-end finance: yarn mass balance, true cost per roll, the monthly P&L and buyer payments."""
from __future__ import annotations

from datetime import date, datetime

import psycopg

from app.db import write_tx
from app.errors import ApiError, is_idempotency_replay
from app.modules.finance import repository as repo
from app.modules.finance.schemas import PaymentRequest


def mass_balance(conn: psycopg.Connection, from_: datetime | None, to: datetime | None) -> dict:
    """Where every kilo of issued yarn went (fabric, recorded waste, still on the loom) — and what is
    unaccounted for, machine by machine."""
    window = repo.resolve_window(conn, from_, to)
    if window["from_"] is not None and window["to"] is not None and window["from_"] >= window["to"]:
        raise ApiError("VALIDATION_FAILED", "'from' must be before 'to'.", 422, fields={"from": "must be before to"})
    return {**window,
            "first_run_at": repo.first_run_at(conn, window["from_"], window["to"]),
            "totals": repo.totals(conn, window["from_"], window["to"]),
            "by_machine": repo.unaccounted_by_machine(conn, window["from_"], window["to"])}


def roll_costs(conn: psycopg.Connection, order_code: str) -> list[dict]:
    """True cost of every roll reserved for an order: yarn + machine + labour + chemicals, rolled up the family tree."""
    if not repo.order_exists(conn, order_code):
        raise ApiError("NOT_FOUND", f"Order {order_code} not found.", 404, fields={"order_code": "not found"})
    return repo.roll_costs(conn, order_code)


def pnl(conn: psycopg.Connection, from_: date | None, to: date | None) -> dict:
    """Did the mill make money? Profit on an accrual basis (invoiced revenue - cost of the invoiced rolls -
    the period's wages) beside cash (received - yarn bills paid - wages), with who owes us and whom we owe.
    Default: the month to date of the last working day."""
    default = repo.month_to_date(conn)
    from_, to = from_ or default["from_"], to or default["to"]
    if from_ > to:
        raise ApiError("VALIDATION_FAILED", "'from' must not be after 'to'.", 422, fields={"from": "after to"})
    p = repo.pnl(conn, from_, to)
    return {**p, "from_": p.pop("from")}


def record_payment(conn: psycopg.Connection, req: PaymentRequest, user: dict) -> tuple[dict, bool]:
    """A buyer pays (part of) an invoice. The database refuses more than is outstanding (LL009); a resend with
    the same idempotency_key returns the original payment. Returns (payment, created)."""
    original = repo.payment(conn, key=req.idempotency_key)
    if original:
        return original, False
    try:
        with write_tx(conn):
            invoice = repo.invoice_id(conn, req.invoice_code)
            if invoice is None:
                raise ApiError("NOT_FOUND", f"Invoice {req.invoice_code} not found.", 404,
                               fields={"invoice_code": "not found"})
            payment_id = repo.insert_payment(conn, invoice, req.amount, req.method, req.idempotency_key, user["id"])
            return repo.payment(conn, payment_id=payment_id), True
    except psycopg.errors.UniqueViolation as exc:
        if is_idempotency_replay(exc) and (original := repo.payment(conn, key=req.idempotency_key)):
            return original, False
        raise
