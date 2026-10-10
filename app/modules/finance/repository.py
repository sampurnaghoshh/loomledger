"""Finance SQL. Mass balance from 005 (mass_balance, v_yarn_balance_by_run); roll cost from 004 (v_roll_cost)."""
from __future__ import annotations

from datetime import datetime

import psycopg


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
