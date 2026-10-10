"""Recall SQL: scope (003 recall_scope), impact and money (004 recall_impact / recall_order_impact /
lot_cost), and apply_recall() — idempotent in the database."""
from __future__ import annotations

import psycopg


def lot_id(conn: psycopg.Connection, code: str) -> int | None:
    row = conn.execute("SELECT id FROM lot WHERE code = %s", (code,)).fetchone()
    return row["id"] if row else None


def recall_for(conn: psycopg.Connection, root_lot_id: int) -> dict | None:
    return conn.execute("SELECT code, initiated_at FROM recall WHERE root_lot_id = %s", (root_lot_id,)).fetchone()


def impact(conn: psycopg.Connection, root_lot_id: int) -> dict:
    return conn.execute("SELECT * FROM recall_impact(%s)", (root_lot_id,)).fetchone()


def order_impact(conn: psycopg.Connection, root_lot_id: int) -> list[dict]:
    return conn.execute("SELECT * FROM recall_order_impact(%s)", (root_lot_id,)).fetchall()


def rolls(conn: psycopg.Connection, root_lot_id: int) -> list[dict]:
    return conn.execute(
        """SELECT s.lot_code, s.kind::text AS kind, s.qty_m, s.custody, s.order_code, s.buyer_name,
                  round(c.total, 2) AS cost
             FROM recall_scope(%s) s CROSS JOIN LATERAL lot_cost(s.lot_id) c""", (root_lot_id,)).fetchall()


def apply(conn: psycopg.Connection, root_lot_id: int, reason: str, user_id: int) -> int:
    return conn.execute("SELECT apply_recall(%s, %s, %s) AS id", (root_lot_id, reason, user_id)).fetchone()["id"]
