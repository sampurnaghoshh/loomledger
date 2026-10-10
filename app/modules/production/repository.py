"""Production SQL. The yarn bridge and shift calendar are DB functions (007)."""
from __future__ import annotations

import psycopg

YARN_STORE = "YARN-STORE"
GREIGE_STORE = "GREIGE-STORE"
PRODUCTION = "PRODUCTION"
SCRAP = "SCRAP"


# ---------- lookups ----------
def machine(conn: psycopg.Connection, code: str) -> dict | None:
    """Row-locked, so a run start and a floor state change on the same machine apply one after the other."""
    return conn.execute("SELECT id, code, stage::text AS stage FROM machine WHERE code = %s AND active FOR UPDATE",
                        (code,)).fetchone()


def greige_product(conn: psycopg.Connection, code: str) -> dict | None:
    return conn.execute("SELECT id FROM product WHERE code = %s AND kind = 'greige'", (code,)).fetchone()


def yarn_lot(conn: psycopg.Connection, code: str) -> dict | None:
    return conn.execute("SELECT id FROM lot WHERE code = %s AND kind = 'yarn'", (code,)).fetchone()


def order_line_id(conn: psycopg.Connection, order_code: str) -> int | None:
    rows = conn.execute(
        """SELECT ol.id FROM order_line ol JOIN sales_order so ON so.id = ol.order_id
            WHERE so.code = %s ORDER BY ol.id LIMIT 2""", (order_code,)).fetchall()
    return rows[0]["id"] if len(rows) == 1 else None


def operator(conn: psycopg.Connection, stage: str, code: str | None) -> dict | None:
    """The named worker, or the first active worker of this stage not on another open run."""
    if code is not None:
        return conn.execute("SELECT id FROM worker WHERE code = %s AND active", (code,)).fetchone()
    return conn.execute(
        """SELECT w.id FROM worker w
            WHERE w.active AND w.skill = %s::machine_stage
              AND NOT EXISTS (SELECT 1 FROM process_run r WHERE r.operator_id = w.id AND r.ended_at IS NULL)
            ORDER BY w.code LIMIT 1""", (stage,)).fetchone()


def next_roll_number(conn: psycopg.Connection) -> int:
    """Next R-<n> number. The transaction-scoped lock serialises concurrent run starts."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('loomledger:roll-number'))")
    return conn.execute(
        "SELECT COALESCE(max(substring(code FROM '^R-([0-9]+)')::int), 1000) + 1 AS n FROM lot").fetchone()["n"]


def yarn_issue_kg(conn: psycopg.Connection, product_id: int, meters: float) -> float:
    return conn.execute("SELECT weaving_yarn_issue_kg(%s::bigint, %s::numeric) AS kg",
                        (product_id, meters)).fetchone()["kg"]


# ---------- start ----------
def start_replay(conn: psycopg.Connection, idempotency_key: str) -> dict | None:
    return conn.execute(
        """SELECT r.code AS run_code, g.code AS lot_code, m.qty AS yarn_issued_kg
             FROM stock_move m
             JOIN process_run r ON r.id = m.process_run_id
             JOIN lot g         ON g.produced_by_run_id = r.id
            WHERE m.idempotency_key = %s AND m.kind = 'issue'""", (idempotency_key,)).fetchone()


def insert_run(conn: psycopg.Connection, code: str, machine_id: int, stage: str, operator_id: int) -> int:
    return conn.execute(
        """INSERT INTO process_run (code, machine_id, stage, shift_id, operator_id, started_at)
           VALUES (%s, %s, %s, shift_at(now()), %s, now()) RETURNING id""",
        (code, machine_id, stage, operator_id)).fetchone()["id"]


def insert_greige_lot(conn: psycopg.Connection, code: str, product_id: int, meters: float, run_id: int) -> int:
    return conn.execute(
        """INSERT INTO lot (code, kind, product_id, qty, produced_by_run_id, produced_by_stage, status)
           VALUES (%s, 'greige', %s, %s, %s, 'weaving', 'wip') RETURNING id""",
        (code, product_id, meters, run_id)).fetchone()["id"]


def insert_lineage(conn: psycopg.Connection, parent_id: int, child_id: int, qty: float) -> None:
    conn.execute("INSERT INTO lot_lineage (parent_lot_id, child_lot_id, qty_consumed) VALUES (%s, %s, %s)",
                 (parent_id, child_id, qty))


def reserve(conn: psycopg.Connection, lot_id: int, order_line_id: int) -> None:
    conn.execute("INSERT INTO reservation (lot_id, order_line_id) VALUES (%s, %s)", (lot_id, order_line_id))


# ---------- finish ----------
def finish_replay(conn: psycopg.Connection, idempotency_key: str) -> dict | None:
    return conn.execute(
        """SELECT r.code AS run_code, g.code AS lot_code, m.qty AS meters
             FROM stock_move m
             JOIN process_run r ON r.id = m.process_run_id
             JOIN lot g         ON g.id = m.lot_id
            WHERE m.idempotency_key = %s AND m.kind = 'production'""", (idempotency_key,)).fetchone()


def lock_weaving_run(conn: psycopg.Connection, run_code: str) -> dict | None:
    return conn.execute(
        """SELECT r.id, r.code, r.ended_at, r.machine_id, g.id AS lot_id, g.code AS lot_code, g.qty AS meters,
                  (SELECT m.lot_id FROM stock_move m WHERE m.process_run_id = r.id AND m.kind = 'issue'
                    ORDER BY m.id LIMIT 1) AS yarn_lot_id
             FROM process_run r
             JOIN lot g     ON g.produced_by_run_id = r.id
             JOIN machine m ON m.id = r.machine_id
            WHERE r.code = %s AND r.stage = 'weaving'
              FOR UPDATE OF r, m""", (run_code,)).fetchone()


def end_run(conn: psycopg.Connection, run_id: int) -> None:
    conn.execute("UPDATE process_run SET ended_at = now() WHERE id = %s", (run_id,))


def activate_lot(conn: psycopg.Connection, lot_id: int) -> None:
    conn.execute("UPDATE lot SET status = 'active' WHERE id = %s AND status = 'wip'", (lot_id,))
