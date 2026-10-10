"""Quality SQL. Custody comes from v_roll_custody (facts), the latest result from v_latest_qc."""
from __future__ import annotations

from datetime import date

import psycopg

FG_STORE = "FG-STORE"
REJECT_BAY = "REJECT-BAY"


def queue(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """SELECT c.lot_code, p.name AS product, c.qty_m, r.code AS dye_batch, m.name AS dyed_on,
                  r.ended_at AS dyed_at, so.code AS order_code
             FROM v_roll_custody c
             JOIN lot l          ON l.id = c.lot_id
             JOIN product p      ON p.id = l.product_id
             JOIN process_run r  ON r.id = l.produced_by_run_id
             JOIN machine m      ON m.id = r.machine_id
             LEFT JOIN reservation rs ON rs.lot_id = l.id
             LEFT JOIN order_line ol  ON ol.id = rs.order_line_id
             LEFT JOIN sales_order so ON so.id = ol.order_id
            WHERE c.custody = 'awaiting_qc'
            ORDER BY c.lot_code""").fetchall()


def latest_rejection_day(conn: psycopg.Connection) -> date | None:
    """The mill-time date of the most recent rejection (what the Quality banner calls "latest")."""
    return conn.execute(
        """SELECT max((inspected_at AT TIME ZONE 'Asia/Kolkata')::date) AS day
             FROM qc_inspection WHERE result = 'reject'""").fetchone()["day"]


def rejections(conn: psycopg.Connection, day: date | None = None) -> list[dict]:
    """All rejections newest first; with `day`, only those inspected on that mill-time date."""
    return conn.execute(
        """SELECT l.code AS lot_code, q.defect_type, q.defect_meters, q.inspected_at, w.full_name AS inspector,
                  so.code AS order_code
             FROM qc_inspection q
             JOIN lot l    ON l.id = q.lot_id
             JOIN worker w ON w.id = q.inspector_id
             LEFT JOIN reservation rs ON rs.lot_id = l.id
             LEFT JOIN order_line ol  ON ol.id = rs.order_line_id
             LEFT JOIN sales_order so ON so.id = ol.order_id
            WHERE q.result = 'reject'
              AND (%(day)s::date IS NULL OR (q.inspected_at AT TIME ZONE 'Asia/Kolkata')::date = %(day)s::date)
            ORDER BY q.inspected_at DESC""", {"day": day}).fetchall()


def finished_lot(conn: psycopg.Connection, code: str) -> dict | None:
    return conn.execute("SELECT id, code, qty FROM lot WHERE code = %s AND kind = 'finished'", (code,)).fetchone()


def inspector(conn: psycopg.Connection, code: str | None) -> dict | None:
    """The named worker, or the first active QC inspector (workers with no machine skill)."""
    if code is not None:
        return conn.execute("SELECT id FROM worker WHERE code = %s AND active", (code,)).fetchone()
    return conn.execute("SELECT id FROM worker WHERE active AND skill IS NULL ORDER BY code LIMIT 1").fetchone()


def insert_inspection(conn: psycopg.Connection, lot_id: int, inspector_id: int, result: str,
                      defect_type: str | None, defect_meters: float | None, notes: str | None) -> int:
    return conn.execute(
        """INSERT INTO qc_inspection (lot_id, inspector_id, inspected_at, result, defect_type, defect_meters, notes)
           VALUES (%s, %s, now(), %s, %s, %s, %s) RETURNING id""",
        (lot_id, inspector_id, result, defect_type, defect_meters, notes)).fetchone()["id"]


def reject_replay(conn: psycopg.Connection, idempotency_key: str) -> dict | None:
    """The rejection recorded with this key: the reject move and the inspection made in the same transaction."""
    return conn.execute(
        """SELECT q.id AS inspection_id, l.code AS lot_code, q.result::text AS result
             FROM stock_move m
             JOIN lot l           ON l.id = m.lot_id
             JOIN qc_inspection q ON q.lot_id = m.lot_id AND q.result = 'reject'
                                 AND q.inspected_at = m.created_at
            WHERE m.idempotency_key = %s AND m.kind = 'transfer'
            ORDER BY q.id DESC LIMIT 1""", (idempotency_key,)).fetchone()
