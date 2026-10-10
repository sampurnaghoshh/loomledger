"""Orders SQL. Order progress and the buyer page come from buyer_order_status() (005)."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import psycopg

FG_STORE = "FG-STORE"
CUSTOMERS = "CUSTOMERS"


def list_orders(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """WITH yarn AS (                                              -- the yarn plan, computed once (014)
               SELECT yp.order_id, CASE WHEN SUM(yp.shortfall_kg) > 0 THEN 'short' ELSE 'ok' END AS status,
                      SUM(yp.required_kg) AS required_kg, SUM(yp.shortfall_kg) AS shortfall_kg,
                      string_agg(DISTINCT y.name, ', ') FILTER (WHERE yp.shortfall_kg > 0) AS short_of
                 FROM v_yarn_plan yp JOIN product y ON y.id = yp.yarn_product_id
                GROUP BY yp.order_id)
           SELECT so.code, b.name AS buyer, p.name AS product, ol.qty_m AS ordered_m, ol.unit_price,
                  so.promised_date, so.revised_promise_date,
                  working_days_between(so.promised_date, so.revised_promise_date) AS delay_days,
                  so.status::text AS status,
                  buyer_order_status(bl.token)->'progress' AS progress, bl.token AS tracking_token,
                  y.status AS yarn_status, y.required_kg AS yarn_required_kg, y.shortfall_kg AS yarn_shortfall_kg,
                  y.short_of AS yarn_short_of
             FROM sales_order so
             JOIN party b       ON b.id = so.buyer_id
             JOIN order_line ol ON ol.order_id = so.id
             JOIN product p     ON p.id = ol.product_id
             JOIN LATERAL (SELECT token FROM buyer_link                -- the order's current link
                            WHERE order_id = so.id AND expires_at > now()
                            ORDER BY created_at DESC LIMIT 1) bl ON true
             LEFT JOIN yarn y   ON y.order_id = so.id                    -- null for a closed order
            ORDER BY so.promised_date""").fetchall()


def buyer_status(conn: psycopg.Connection, token: UUID) -> dict | None:
    """NULL for an unknown or expired link — the function itself checks expiry."""
    return conn.execute("SELECT buyer_order_status(%s) AS page", (token,)).fetchone()["page"]


# ---------- dispatch ----------
def dispatch_replay(conn: psycopg.Connection, idempotency_key: str) -> dict | None:
    return conn.execute(
        """SELECT d.code AS dispatch_code, i.code AS invoice_code, i.amount
             FROM stock_move m
             JOIN dispatch d ON d.id = m.dispatch_id
             JOIN invoice i  ON i.dispatch_id = d.id
            WHERE m.idempotency_key = %s""", (idempotency_key,)).fetchone()


def lock_order(conn: psycopg.Connection, code: str) -> dict | None:
    """The order and its (single) line, row-locked so dispatches of one order are numbered in turn."""
    rows = conn.execute(
        """SELECT so.id, so.code, ol.unit_price
             FROM sales_order so JOIN order_line ol ON ol.order_id = so.id
            WHERE so.code = %s
            ORDER BY ol.id LIMIT 2
              FOR UPDATE OF so""", (code,)).fetchall()
    return rows[0] if len(rows) == 1 else None


def finished_lots(conn: psycopg.Connection, codes: list[str]) -> list[dict]:
    return conn.execute("SELECT id, code, qty FROM lot WHERE code = ANY(%s) AND kind = 'finished'",
                        (codes,)).fetchall()


def next_dispatch_number(conn: psycopg.Connection, order_id: int) -> int:
    return conn.execute("SELECT count(*) + 1 AS n FROM dispatch WHERE order_id = %s", (order_id,)).fetchone()["n"]


def insert_dispatch(conn: psycopg.Connection, code: str, order_id: int, vehicle_no: str,
                    shade_override_reason: str | None) -> int:
    return conn.execute(
        """INSERT INTO dispatch (code, order_id, vehicle_no, dispatched_at, shade_override_reason)
           VALUES (%s, %s, %s, now(), %s) RETURNING id""",
        (code, order_id, vehicle_no, shade_override_reason)).fetchone()["id"]


def insert_dispatch_line(conn: psycopg.Connection, dispatch_id: int, lot_id: int) -> None:
    conn.execute("INSERT INTO dispatch_line (dispatch_id, lot_id) VALUES (%s, %s)", (dispatch_id, lot_id))


def mark_dispatched(conn: psycopg.Connection, lot_ids: list[int]) -> None:
    conn.execute("UPDATE lot SET status = 'dispatched' WHERE id = ANY(%s)", (lot_ids,))


def insert_invoice(conn: psycopg.Connection, code: str, order_id: int, dispatch_id: int, amount: Decimal) -> None:
    conn.execute(
        """INSERT INTO invoice (code, order_id, dispatch_id, amount, issued_at)
           VALUES (%s, %s, %s, %s, now())""", (code, order_id, dispatch_id, amount))


def refresh_order_status(conn: psycopg.Connection, order_id: int) -> None:
    """partially_dispatched until every ordered metre has shipped, then dispatched."""
    conn.execute(
        """WITH shipped AS (
               SELECT COALESCE(SUM(l.qty), 0) AS m
                 FROM dispatch d JOIN dispatch_line dl ON dl.dispatch_id = d.id JOIN lot l ON l.id = dl.lot_id
                WHERE d.order_id = %(o)s),
                ordered AS (SELECT SUM(qty_m) AS m FROM order_line WHERE order_id = %(o)s)
           UPDATE sales_order so
              SET status = CASE WHEN shipped.m >= ordered.m THEN 'dispatched' ELSE 'partially_dispatched' END::order_status
             FROM shipped, ordered
            WHERE so.id = %(o)s
              AND so.status IS DISTINCT FROM
                  (CASE WHEN shipped.m >= ordered.m THEN 'dispatched' ELSE 'partially_dispatched' END)::order_status""",
        {"o": order_id})


def insert_buyer_update(conn: psycopg.Connection, order_id: int, message: str) -> None:
    conn.execute(
        """INSERT INTO order_event (order_id, kind, message, visible_to_buyer)
           VALUES (%s, 'dispatched', %s, true)""", (order_id, message))


# ---------------------------------------------------------------- yarn check (014)
def order_for_yarn_check(conn: psycopg.Connection, code: str) -> dict | None:
    return conn.execute(
        """SELECT so.id, so.code, so.status::text AS status, COALESCE(so.revised_promise_date, so.promised_date) AS due
             FROM sales_order so WHERE so.code = %s""", (code,)).fetchone()


def yarn_plan_lines(conn: psycopg.Connection, order_id: int) -> list[dict]:
    """This order's lines in the yarn plan: what is still to weave, the yarn it needs, what is left for it."""
    return conn.execute(
        """SELECT p.code AS product_code, p.name AS product, y.code AS yarn_product_code, y.name AS yarn_product,
                  yp.ordered_m, yp.covered_m, yp.unwoven_m, yp.required_kg, yp.available_kg, yp.shortfall_kg
             FROM v_yarn_plan yp
             JOIN product p ON p.id = yp.product_id
             JOIN product y ON y.id = yp.yarn_product_id
            WHERE yp.order_id = %s
            ORDER BY yp.order_line_id""", (order_id,)).fetchall()


def orders_ahead(conn: psycopg.Connection, order_id: int) -> list[str]:
    """Open orders that take the same yarn first (earlier due date)."""
    return [r["order_code"] for r in conn.execute(
        """SELECT DISTINCT o.order_code, o.due
             FROM v_yarn_plan o
             JOIN v_yarn_plan me ON me.order_id = %s AND me.yarn_product_id = o.yarn_product_id
            WHERE o.order_id <> me.order_id AND (o.due, o.order_code) < (me.due, me.order_code)
            ORDER BY o.due, o.order_code""", (order_id,))]
