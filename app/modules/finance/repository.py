"""Finance SQL. Mass balance from 005 (mass_balance, v_yarn_balance_by_run); roll cost from 004 (v_roll_cost);
monthly_pnl() and buyer payments from 013."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import psycopg

from app.listing import Filter, Listing


def resolve_window(conn: psycopg.Connection, from_: datetime | None, to: datetime | None) -> dict:
    """Mill-time bounds; naive input is read as IST. Missing bounds stay null (= open-ended)."""
    return conn.execute('SELECT %s::timestamptz AS from_, %s::timestamptz AS "to"', (from_, to)).fetchone()


def totals(conn: psycopg.Connection, from_: datetime | None, to: datetime | None) -> dict:
    """An empty window balances to zero (mass_balance sums to NULL there); the percentage stays null."""
    return conn.execute(
        """SELECT received_kg, COALESCE(issued_kg, 0) AS issued_kg, COALESCE(fabric_kg, 0) AS fabric_kg,
                  COALESCE(waste_kg, 0) AS waste_kg, COALESCE(wip_kg, 0) AS wip_kg,
                  COALESCE(unaccounted_kg, 0) AS unaccounted_kg, unaccounted_pct
             FROM mass_balance(COALESCE(%s::timestamptz, '-infinity'), COALESCE(%s::timestamptz, 'infinity'))""",
        (from_, to)).fetchone()


def unaccounted_by_machine(conn: psycopg.Connection, from_: datetime | None, to: datetime | None) -> list[dict]:
    """v_yarn_unaccounted_by_machine, restricted to runs started in the window (same window rule as
    mass_balance). Ties are ordered by machine so the list is stable."""
    return conn.execute(
        """SELECT machine_code, machine_name,
                  count(*)::int                  AS runs,
                  round(SUM(issued_kg), 3)       AS issued_kg,
                  round(SUM(unaccounted_kg), 3)  AS unaccounted_kg,
                  round(100.0 * SUM(unaccounted_kg) / NULLIF(SUM(issued_kg), 0), 2) AS unaccounted_pct
             FROM v_yarn_balance_by_run
            WHERE started_at >= COALESCE(%s::timestamptz, '-infinity')
              AND started_at <  COALESCE(%s::timestamptz, 'infinity')
            GROUP BY machine_code, machine_name
            ORDER BY unaccounted_kg DESC, machine_code""", (from_, to)).fetchall()


def first_run_at(conn: psycopg.Connection, from_: datetime | None, to: datetime | None) -> datetime | None:
    """When the earliest weaving run in the window started (what "to date" counts from)."""
    return conn.execute(
        """SELECT min(started_at) AS t FROM v_yarn_balance_by_run
            WHERE started_at >= COALESCE(%s::timestamptz, '-infinity')
              AND started_at <  COALESCE(%s::timestamptz, 'infinity')""", (from_, to)).fetchone()["t"]


def order_exists(conn: psycopg.Connection, order_code: str) -> bool:
    return conn.execute("SELECT 1 FROM sales_order WHERE code = %s", (order_code,)).fetchone() is not None


def roll_costs(conn: psycopg.Connection, order_code: str) -> list[dict]:
    return conn.execute(
        """SELECT rc.lot_code, rc.qty_m, rc.material, rc.machine, rc.labour, rc.chemicals, rc.total, rc.cost_per_m,
                  c.custody, l.status::text AS status
             FROM v_roll_cost rc
             JOIN lot l            ON l.id = rc.lot_id
             JOIN v_roll_custody c ON c.lot_id = rc.lot_id
             JOIN reservation rs   ON rs.lot_id = rc.lot_id
             JOIN order_line ol    ON ol.id = rs.order_line_id
             JOIN sales_order so   ON so.id = ol.order_id
            WHERE so.code = %s
            ORDER BY rc.lot_code""", (order_code,)).fetchall()


# ---------------------------------------------------------------- monthly P&L + buyer payments (013)
def month_to_date(conn: psycopg.Connection) -> dict:
    """The month of the last working day (Sunday -> Saturday), up to that day."""
    return conn.execute(
        """SELECT date_trunc('month', d)::date AS from_, d AS "to"
             FROM last_working_day((now() AT TIME ZONE 'Asia/Kolkata')::date) AS d""").fetchone()


def pnl(conn: psycopg.Connection, from_: date, to: date) -> dict:
    return conn.execute("SELECT monthly_pnl(%s, %s) AS p", (from_, to)).fetchone()["p"]


def invoice_id(conn: psycopg.Connection, code: str) -> int | None:
    row = conn.execute("SELECT id FROM invoice WHERE code = %s", (code,)).fetchone()
    return row["id"] if row else None


def insert_payment(conn: psycopg.Connection, invoice: int, amount: Decimal, method: str, key: str, user_id: int) -> int:
    """The database refuses more than the outstanding amount (LL009)."""
    return conn.execute(
        """INSERT INTO payment (invoice_id, amount, paid_at, method, idempotency_key, recorded_by)
           VALUES (%s, %s, now(), %s, %s, %s) RETURNING id""", (invoice, amount, method, key, user_id)).fetchone()["id"]


def payment(conn: psycopg.Connection, *, payment_id: int | None = None, key: str | None = None) -> dict | None:
    """One payment with the balance right after it (payments are append-only, so this never changes)."""
    return conn.execute(
        """SELECT p.id AS payment_id, i.code AS invoice_code, p.amount, p.method, p.paid_at, i.amount AS invoice_amount,
                  i.amount - (SELECT SUM(q.amount) FROM payment q WHERE q.invoice_id = p.invoice_id AND q.id <= p.id)
                      AS outstanding_after
             FROM payment p JOIN invoice i ON i.id = p.invoice_id
            WHERE p.id = %s OR p.idempotency_key = %s""", (payment_id, key)).fetchone()


INVOICE_LIST = Listing(
    source="""SELECT ib.code, so.code AS order_code, b.name AS buyer, d.code AS dispatch_code, d.dispatched_at,
                     (SELECT count(*) FROM dispatch_line dl WHERE dl.dispatch_id = d.id)::int AS rolls,
                     ib.amount, ib.paid, ib.outstanding, ib.issued_at
                FROM v_invoice_balance ib
                JOIN invoice i      ON i.id = ib.invoice_id
                JOIN dispatch d     ON d.id = i.dispatch_id
                JOIN sales_order so ON so.id = ib.order_id
                JOIN party b        ON b.id = so.buyer_id""",
    sort={"issued_at": "issued_at", "code": "code", "amount": "amount", "outstanding": "outstanding", "buyer": "buyer"},
    default_sort="-issued_at", tiebreak="code",
    search=("code", "order_code", "buyer", "dispatch_code"),
    filters={"buyer": Filter("buyer"), "order_code": Filter("order_code"), "unpaid": Filter("outstanding", "positive")})
