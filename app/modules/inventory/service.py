"""Inventory business flows."""
from __future__ import annotations

from datetime import datetime

import psycopg

from app.db import write_tx
from app.errors import ApiError, is_idempotency_replay, not_found
from app.modules.inventory import repository as repo
from app.modules.inventory.schemas import ReceiptRequest

DUPLICATE_LOT_CONSTRAINTS = {"lot_code_key", "goods_receipt_code_key"}


def masters(conn: psycopg.Connection) -> dict:
    """What the gate-entry form can choose from."""
    return {"suppliers": repo.suppliers(conn), "yarn_products": repo.yarn_products(conn),
            "open_orders": repo.open_orders(conn)}


def low_stock(conn: psycopg.Connection) -> list[dict]:
    """Yarn whose free stock (usable on hand - still needed by open orders) is below its reorder level."""
    return repo.low_stock(conn)


def stock(conn: psycopg.Connection, as_of: datetime | None) -> dict:
    as_of = repo.resolve_as_of(conn, as_of) if as_of is not None else None
    return {"as_of": as_of, "rows": repo.stock(conn, as_of)}


def receive_yarn(conn: psycopg.Connection, req: ReceiptRequest, user: dict) -> tuple[dict, bool]:
    """Gate entry: a goods receipt, a new yarn lot and its receipt move into the yarn store.

    Returns (result, created). Replaying an idempotency_key returns the original result, created=False.
    """
    original = repo.receipt_by_key(conn, req.idempotency_key)
    if original:
        return original, False
    try:
        with write_tx(conn):
            supplier_id = repo.supplier_id(conn, req.supplier_code)
            if supplier_id is None:
                raise ApiError("NOT_FOUND", f"Supplier {req.supplier_code} not found.", 404,
                               fields={"supplier_code": "unknown supplier"})
            product_id = repo.yarn_product_id(conn, req.product_code)
            if product_id is None:
                raise ApiError("NOT_FOUND", "Yarn product not found.", 404,
                               fields={"product_code": "unknown yarn product"})
            order_id = None
            if req.order_code is not None:
                order_id = repo.order_id(conn, req.order_code)
                if order_id is None:
                    raise ApiError("NOT_FOUND", f"Order {req.order_code} not found.", 404,
                                   fields={"order_code": "unknown order"})
            receipt_code = f"GRN-{req.lot_code}"
            grn_id = repo.insert_goods_receipt(conn, receipt_code, supplier_id, req.vehicle_no, req.challan_no,
                                               user["id"], order_id)
            lot_id = repo.insert_yarn_lot(conn, req.lot_code, product_id, req.kg, req.price_per_kg, grn_id)
            repo.insert_receipt_move(conn, lot_id, req.kg, grn_id, req.idempotency_key, user["id"])
    except psycopg.errors.UniqueViolation as exc:
        # a concurrent submit of the same form won the race: hand back its result
        if is_idempotency_replay(exc) or exc.diag.constraint_name in DUPLICATE_LOT_CONSTRAINTS:
            original = repo.receipt_by_key(conn, req.idempotency_key)
            if original:
                return original, False
        if exc.diag.constraint_name in DUPLICATE_LOT_CONSTRAINTS:
            raise ApiError("VALIDATION_FAILED", f"Lot {req.lot_code} already exists.", 422,
                           fields={"lot_code": "already exists"}, sqlstate=exc.sqlstate) from exc
        raise
    return {"receipt_code": receipt_code, "lot_code": req.lot_code, "kg": req.kg, "location": repo.YARN_STORE,
            "order_code": req.order_code}, True
