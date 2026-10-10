"""Orders, dispatch and the buyer portal."""
from __future__ import annotations

from uuid import UUID

import psycopg

from app import ledger
from app.db import write_tx
from app.errors import ApiError, is_idempotency_replay
from app.modules.orders import repository as repo
from app.modules.orders.schemas import DispatchRequest

TRACK_NOT_FOUND = "This tracking link is invalid or has expired."


def list_orders(conn: psycopg.Connection) -> list[dict]:
    return repo.list_orders(conn)


def yarn_check(conn: psycopg.Connection, code: str) -> dict:
    """Is there enough usable yarn to weave what this order still needs, after the orders due before it?"""
    order = repo.order_for_yarn_check(conn, code)
    if order is None:
        raise ApiError("NOT_FOUND", f"Order {code} not found.", 404, fields={"order_code": "not found"})
    lines = repo.yarn_plan_lines(conn, order["id"])
    if not lines:                                   # dispatched / cancelled: nothing left to weave
        return {"order_code": code, "status": "closed", "due": order["due"], "required_kg": 0, "shortfall_kg": 0,
                "orders_ahead": [], "lines": []}
    shortfall = sum(l["shortfall_kg"] for l in lines)
    return {"order_code": code, "status": "short" if shortfall > 0 else "ok", "due": order["due"],
            "required_kg": sum(l["required_kg"] for l in lines), "shortfall_kg": shortfall,
            "orders_ahead": repo.orders_ahead(conn, order["id"]), "lines": lines}


def track(conn: psycopg.Connection, token: str) -> dict:
    """Public buyer page. Malformed, unknown and expired tokens all get the same 404 — nothing to probe."""
    try:
        parsed = UUID(token)
    except ValueError:
        parsed = None
    page = repo.buyer_status(conn, parsed) if parsed else None
    if page is None:
        raise ApiError("NOT_FOUND", TRACK_NOT_FOUND, 404)
    return page


def _move_key(idempotency_key: str, lot_code: str) -> str:
    return f"{idempotency_key}:{lot_code}"


def dispatch(conn: psycopg.Connection, req: DispatchRequest, user: dict) -> tuple[dict, bool]:
    """Ship rolls of one order: dispatch + lines, each roll FG-STORE -> CUSTOMERS, invoice, order status
    and a buyer-visible update. The database decides which rolls may ship (QC pass + reserved for this
    order: 009; one dye batch per dispatch unless shade_override_reason is given: 008; not quarantined,
    actually in FG-STORE: 002; never twice: one_dispatch_per_roll)."""
    first_key = _move_key(req.idempotency_key, req.lot_codes[0])
    original = repo.dispatch_replay(conn, first_key)
    if original:
        return original, False
    try:
        with write_tx(conn):
            order = repo.lock_order(conn, req.order_code)
            if order is None:
                raise ApiError("NOT_FOUND", f"Order {req.order_code} not found.", 404,
                               fields={"order_code": "not found"})
            lots = {lot["code"]: lot for lot in repo.finished_lots(conn, req.lot_codes)}
            unknown = [c for c in req.lot_codes if c not in lots]
            if unknown:
                raise ApiError("NOT_FOUND", f"Unknown roll(s): {', '.join(unknown)}.", 404,
                               fields={"lot_codes": f"unknown: {', '.join(unknown)}"})

            n = repo.next_dispatch_number(conn, order["id"])
            dispatch_code = f"DSP-{order['code'].removeprefix('SO-')}-{n}"
            invoice_code = dispatch_code.replace("DSP", "INV", 1)
            dispatch_id = repo.insert_dispatch(conn, dispatch_code, order["id"], req.vehicle_no,
                                               req.shade_override_reason)
            for code in req.lot_codes:
                lot = lots[code]
                repo.insert_dispatch_line(conn, dispatch_id, lot["id"])
                ledger.post_move(conn, lot_id=lot["id"], src=repo.FG_STORE, dst=repo.CUSTOMERS, qty=lot["qty"],
                                 kind="dispatch", idempotency_key=_move_key(req.idempotency_key, code),
                                 user_id=user["id"], dispatch_id=dispatch_id)
            repo.mark_dispatched(conn, [lot["id"] for lot in lots.values()])

            metres = sum(lot["qty"] for lot in lots.values())
            amount = metres * order["unit_price"]
            repo.insert_invoice(conn, invoice_code, order["id"], dispatch_id, amount)
            repo.refresh_order_status(conn, order["id"])
            repo.insert_buyer_update(
                conn, order["id"],
                f"Dispatched {len(lots)} rolls ({metres:,.0f} m) on vehicle {req.vehicle_no}.")
    except psycopg.errors.UniqueViolation as exc:
        if is_idempotency_replay(exc) and (original := repo.dispatch_replay(conn, first_key)):
            return original, False
        raise
    return {"dispatch_code": dispatch_code, "invoice_code": invoice_code, "amount": amount}, True
