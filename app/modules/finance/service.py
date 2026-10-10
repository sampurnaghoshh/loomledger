"""Month-end finance: yarn mass balance and true cost per roll."""
from __future__ import annotations

from datetime import datetime

import psycopg

from app.errors import ApiError
from app.modules.finance import repository as repo


def mass_balance(conn: psycopg.Connection, from_: datetime | None, to: datetime | None) -> dict:
    """Where every kilo of issued yarn went (fabric, recorded waste, still on the loom) — and what is
    unaccounted for, machine by machine."""
    window = repo.resolve_window(conn, from_, to)
    if window["from_"] is not None and window["to"] is not None and window["from_"] >= window["to"]:
        raise ApiError("VALIDATION_FAILED", "'from' must be before 'to'.", 422, fields={"from": "must be before to"})
    return {**window,
            "totals": repo.totals(conn, window["from_"], window["to"]),
            "by_machine": repo.unaccounted_by_machine(conn, window["from_"], window["to"])}


def roll_costs(conn: psycopg.Connection, order_code: str) -> list[dict]:
    """True cost of every roll reserved for an order: yarn + machine + labour + chemicals, rolled up the family tree."""
    if not repo.order_exists(conn, order_code):
        raise ApiError("NOT_FOUND", f"Order {order_code} not found.", 404, fields={"order_code": "not found"})
    return repo.roll_costs(conn, order_code)
