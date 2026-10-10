"""Rolls SQL: one roll's passport and the QR label set, read only from existing views/functions
(003 lot_ancestors / lot_descendants / v_roll_custody / v_latest_qc / recall_scope, 004 v_roll_cost)."""
from __future__ import annotations

import psycopg

from app.listing import Filter, Listing


def roll(conn: psycopg.Connection, code: str) -> dict | None:
    """A roll (greige or finished), its product and where it is (custody derived from facts, 003)."""
    return conn.execute(
        """SELECT l.id, l.code, l.kind::text AS kind, l.status::text AS status, c.custody, l.qty AS qty_m,
                  p.code AS product_code, p.name AS product, p.colour
             FROM lot l
             JOIN product p        ON p.id = l.product_id
             JOIN v_roll_custody c ON c.lot_id = l.id
            WHERE l.code = %s""", (code,)).fetchone()


def lineage(conn: psycopg.Connection, lot_id: int) -> list[dict]:
    """The roll and every ancestor, oldest first: how each lot came to be (goods receipt or production run)."""
    return conn.execute(
        """WITH fam AS (SELECT %(id)s::bigint AS lot_id, 0 AS depth
                        UNION ALL SELECT ancestor_id, depth FROM lot_ancestors(%(id)s))
           SELECT x.code AS lot_code, x.kind::text AS kind, p.name AS product, x.qty, p.uom::text AS uom, f.depth,
                  gr.code AS receipt_code, sup.name AS supplier, gr.received_at,
                  r.code AS run_code, r.stage::text AS stage, m.name AS machine, s.name AS shift,
                  w.full_name AS operator, r.started_at, r.ended_at
             FROM fam f
             JOIN lot x                 ON x.id = f.lot_id
             JOIN product p             ON p.id = x.product_id
             LEFT JOIN goods_receipt gr ON gr.id = x.goods_receipt_id
             LEFT JOIN party sup        ON sup.id = gr.supplier_id
             LEFT JOIN process_run r    ON r.id = x.produced_by_run_id
             LEFT JOIN machine m        ON m.id = r.machine_id
             LEFT JOIN shift s          ON s.id = r.shift_id
             LEFT JOIN worker w         ON w.id = r.operator_id
            ORDER BY f.depth DESC, x.code""", {"id": lot_id}).fetchall()


def latest_qc(conn: psycopg.Connection, lot_id: int) -> dict | None:
    return conn.execute(
        """SELECT q.result::text AS result, q.defect_type, q.defect_meters AS defect_m,
                  w.full_name AS inspector, q.inspected_at
             FROM v_latest_qc v
             JOIN qc_inspection q ON q.id = v.inspection_id
             JOIN worker w        ON w.id = q.inspector_id
            WHERE v.lot_id = %s""", (lot_id,)).fetchone()


def cost(conn: psycopg.Connection, lot_id: int) -> dict:
    """True cost (004 lot_cost via v_roll_cost): WIP carries material only."""
    return conn.execute(
        "SELECT material, machine, labour, chemicals, total, cost_per_m FROM v_roll_cost WHERE lot_id = %s",
        (lot_id,)).fetchone()


def order(conn: psycopg.Connection, lot_id: int) -> dict | None:
    return conn.execute(
        """SELECT so.code, b.name AS buyer, so.status::text AS status, so.promised_date, so.revised_promise_date
             FROM reservation rs
             JOIN order_line ol  ON ol.id = rs.order_line_id
             JOIN sales_order so ON so.id = ol.order_id
             JOIN party b        ON b.id = so.buyer_id
            WHERE rs.lot_id = %s""", (lot_id,)).fetchone()


def dispatch(conn: psycopg.Connection, lot_id: int) -> dict | None:
    return conn.execute(
        """SELECT d.code, d.dispatched_at, d.vehicle_no, i.code AS invoice_code
             FROM dispatch_line dl
             JOIN dispatch d     ON d.id = dl.dispatch_id
             LEFT JOIN invoice i ON i.dispatch_id = d.id
            WHERE dl.lot_id = %s""", (lot_id,)).fetchone()


def recall(conn: psycopg.Connection, lot_id: int) -> dict | None:
    """The recall whose root is this roll or one of its ancestors (the roll is in its scope)."""
    return conn.execute(
        """SELECT rc.code, root.code AS root_lot_code, rc.reason, rc.initiated_at
             FROM recall rc
             JOIN lot root ON root.id = rc.root_lot_id
            WHERE rc.root_lot_id = %(id)s
               OR rc.root_lot_id IN (SELECT ancestor_id FROM lot_ancestors(%(id)s))
            ORDER BY rc.initiated_at, rc.code
            LIMIT 1""", {"id": lot_id}).fetchone()


def lot_by_code(conn: psycopg.Connection, code: str) -> dict | None:
    return conn.execute("SELECT id, code FROM lot WHERE code = %s", (code,)).fetchone()


def last_rejection_yarn_lot(conn: psycopg.Connection) -> dict | None:
    """The yarn lot behind the most recent QC rejection: the default family to label."""
    return conn.execute(
        """SELECT y.id, y.code
             FROM v_latest_qc q
             CROSS JOIN LATERAL lot_ancestors(q.lot_id) a
             JOIN lot y ON y.id = a.ancestor_id AND y.kind = 'yarn'
            WHERE q.result = 'reject'
            ORDER BY q.inspected_at DESC, y.code
            LIMIT 1""").fetchone()


def scope_labels(conn: psycopg.Connection, root_id: int) -> list[dict]:
    """Every physical roll downstream of the root (003 recall_scope)."""
    return conn.execute(
        """SELECT s.lot_code AS code, p.name AS product, s.qty_m, s.custody, true AS in_scope
             FROM recall_scope(%s) s
             JOIN lot l     ON l.id = s.lot_id
             JOIN product p ON p.id = l.product_id
            ORDER BY s.lot_code""", (root_id,)).fetchall()


def clean_label(conn: psycopg.Connection, root_id: int | None) -> dict | None:
    """The most recently passed finished roll in store that is NOT downstream of the root."""
    return conn.execute(
        """SELECT c.lot_code AS code, p.name AS product, c.qty_m, c.custody, false AS in_scope
             FROM v_roll_custody c
             JOIN lot l         ON l.id = c.lot_id
             JOIN product p     ON p.id = l.product_id
             JOIN v_latest_qc q ON q.lot_id = c.lot_id
            WHERE c.kind = 'finished' AND c.custody = 'passed_in_store' AND l.status = 'active'
              AND c.lot_id NOT IN (SELECT descendant_id FROM lot_descendants(%s))
            ORDER BY q.inspected_at DESC, c.lot_code DESC
            LIMIT 1""", (root_id,)).fetchone()


ROLL_LIST = Listing(
    source="""SELECT c.lot_code AS code, c.kind::text AS kind, p.name AS product, c.qty_m, c.status::text AS status,
                     c.custody, so.code AS order_code, b.name AS buyer, q.result::text AS qc_result, q.defect_type,
                     q.inspected_at, l.created_at
                FROM v_roll_custody c
                JOIN lot l     ON l.id = c.lot_id
                JOIN product p ON p.id = l.product_id
                LEFT JOIN v_latest_qc q  ON q.lot_id = c.lot_id
                LEFT JOIN reservation rs ON rs.lot_id = c.lot_id
                LEFT JOIN order_line ol  ON ol.id = rs.order_line_id
                LEFT JOIN sales_order so ON so.id = ol.order_id
                LEFT JOIN party b        ON b.id = so.buyer_id
               WHERE c.custody <> 'consumed'""",
    sort={"code": "code", "custody": "custody", "status": "status", "qty_m": "qty_m", "order_code": "order_code",
          "inspected_at": "inspected_at", "created_at": "created_at"},
    default_sort="code", tiebreak="code",
    search=("code", "order_code", "buyer", "product", "defect_type"),
    filters={"custody": Filter("custody"), "status": Filter("status"), "kind": Filter("kind"),
             "qc_result": Filter("qc_result"), "order_code": Filter("order_code")})
