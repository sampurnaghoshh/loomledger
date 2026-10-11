"""Inventory SQL. Stock is derived from the ledger (003 stock_on_hand); receipts append to it."""
from __future__ import annotations

from datetime import datetime

import psycopg

from app.listing import Filter, Listing

SUPPLIER_LOCATION = "SUPPLIERS"
YARN_STORE = "YARN-STORE"


def resolve_as_of(conn: psycopg.Connection, as_of: datetime) -> datetime:
    """Normalise to mill time (naive input is read as IST)."""
    return conn.execute("SELECT %s::timestamptz AS as_of", (as_of,)).fetchone()["as_of"]


def stock(conn: psycopg.Connection, as_of: datetime | None) -> list[dict]:
    return conn.execute(
        """SELECT s.location_code, s.lot_code, s.lot_kind::text AS lot_kind, s.product_code, s.qty, s.uom::text AS uom,
                  so.code AS order_code                                  -- yarn received for an order (014)
             FROM stock_on_hand(COALESCE(%s::timestamptz, 'infinity')) s
             JOIN lot l                 ON l.code = s.lot_code
             LEFT JOIN goods_receipt gr ON gr.id = l.goods_receipt_id
             LEFT JOIN sales_order so   ON so.id = gr.order_id
            ORDER BY s.location_code, s.lot_code""", (as_of,)).fetchall()


def suppliers(conn: psycopg.Connection) -> list[dict]:
    return conn.execute("SELECT code, name FROM party WHERE kind = 'supplier' ORDER BY code").fetchall()


def yarn_products(conn: psycopg.Connection) -> list[dict]:
    return conn.execute("SELECT code, name FROM product WHERE kind = 'yarn' ORDER BY code").fetchall()


def open_orders(conn: psycopg.Connection) -> list[dict]:
    """Orders a yarn receipt can be recorded for (014: the database refuses closed ones, LL010)."""
    return conn.execute(
        """SELECT so.code, b.name AS buyer FROM sales_order so JOIN party b ON b.id = so.buyer_id
            WHERE so.status NOT IN ('dispatched', 'cancelled') ORDER BY so.code""").fetchall()


def order_id(conn: psycopg.Connection, code: str) -> int | None:
    row = conn.execute("SELECT id FROM sales_order WHERE code = %s", (code,)).fetchone()
    return row["id"] if row else None


def low_stock(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """SELECT product_code, product_name, on_hand_kg, quarantined_kg, committed_kg, open_orders, available_kg,
                  reorder_level_kg, below_reorder_kg
             FROM v_yarn_low_stock ORDER BY product_code""").fetchall()


def receipt_by_key(conn: psycopg.Connection, idempotency_key: str) -> dict | None:
    return conn.execute(
        """SELECT gr.code AS receipt_code, l.code AS lot_code, m.qty AS kg, loc.code AS location, so.code AS order_code
             FROM stock_move m
             JOIN goods_receipt gr    ON gr.id = m.goods_receipt_id
             JOIN lot l               ON l.id = m.lot_id
             JOIN location loc        ON loc.id = m.to_location_id
             LEFT JOIN sales_order so ON so.id = gr.order_id
            WHERE m.idempotency_key = %s AND m.kind = 'receipt'""", (idempotency_key,)).fetchone()


def supplier_id(conn: psycopg.Connection, code: str) -> int | None:
    row = conn.execute("SELECT id FROM party WHERE code = %s AND kind = 'supplier'", (code,)).fetchone()
    return row["id"] if row else None


def yarn_product_id(conn: psycopg.Connection, code: str | None) -> int | None:
    """The yarn product by code; without a code, the yarn product if there is exactly one."""
    rows = conn.execute(
        "SELECT id FROM product WHERE kind = 'yarn' AND (%s::text IS NULL OR code = %s) LIMIT 2",
        (code, code)).fetchall()
    return rows[0]["id"] if len(rows) == 1 else None


def insert_goods_receipt(conn: psycopg.Connection, code: str, supplier_id: int, vehicle_no: str | None,
                         challan_no: str | None, user_id: int, order_id: int | None = None) -> int:
    """The database refuses an order that is no longer open (LL010)."""
    return conn.execute(
        """INSERT INTO goods_receipt (code, supplier_id, received_at, vehicle_no, challan_no, received_by, order_id)
           VALUES (%s, %s, now(), %s, %s, %s, %s) RETURNING id""",
        (code, supplier_id, vehicle_no, challan_no, user_id, order_id)).fetchone()["id"]


def insert_yarn_lot(conn: psycopg.Connection, code: str, product_id: int, kg: float, price_per_kg: float,
                    goods_receipt_id: int) -> int:
    return conn.execute(
        """INSERT INTO lot (code, kind, product_id, qty, unit_cost, goods_receipt_id)
           VALUES (%s, 'yarn', %s, %s, %s, %s) RETURNING id""",
        (code, product_id, kg, price_per_kg, goods_receipt_id)).fetchone()["id"]


def insert_receipt_move(conn: psycopg.Connection, lot_id: int, kg: float, goods_receipt_id: int,
                        idempotency_key: str, user_id: int) -> None:
    conn.execute(
        """INSERT INTO stock_move (lot_id, from_location_id, to_location_id, qty, kind,
                                   goods_receipt_id, idempotency_key, created_by)
           SELECT %s, f.id, t.id, %s, 'receipt', %s, %s, %s
             FROM location f, location t
            WHERE f.code = %s AND t.code = %s""",
        (lot_id, kg, goods_receipt_id, idempotency_key, user_id, SUPPLIER_LOCATION, YARN_STORE))


STOCK_LIST = Listing(
    source="""SELECT s.location_code, s.lot_code, s.lot_kind::text AS lot_kind, s.product_code, s.qty, s.uom::text AS uom,
                     so.code AS order_code, s.location_code || ':' || s.lot_code AS row_key
                FROM stock_on_hand('infinity') s
                JOIN lot l                 ON l.code = s.lot_code
                LEFT JOIN goods_receipt gr ON gr.id = l.goods_receipt_id
                LEFT JOIN sales_order so   ON so.id = gr.order_id""",
    sort={"location_code": "location_code", "lot_code": "lot_code", "product_code": "product_code", "qty": "qty",
          "lot_kind": "lot_kind"},
    default_sort="location_code", tiebreak="row_key",
    search=("lot_code", "product_code", "location_code", "order_code"),
    filters={"location_code": Filter("location_code"), "lot_kind": Filter("lot_kind"),
             "product_code": Filter("product_code")})
