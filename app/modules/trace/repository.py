"""Trace SQL: the family tree (003 lot_ancestors / lot_descendants) and find_cause()."""
from __future__ import annotations

import psycopg


def lot_ids(conn: psycopg.Connection, codes: list[str]) -> dict[str, int]:
    rows = conn.execute("SELECT code, id FROM lot WHERE code = ANY(%s)", (codes,)).fetchall()
    return {r["code"]: r["id"] for r in rows}


def find_cause(conn: psycopg.Connection, ids: list[int]) -> list[dict]:
    """Already ranked by the database; the API must not re-order or re-judge."""
    return conn.execute("SELECT * FROM find_cause(%s)", (ids,)).fetchall()


def with_ancestors(conn: psycopg.Connection, ids: list[int]) -> list[int]:
    rows = conn.execute(
        """SELECT s.id FROM unnest(%(ids)s::bigint[]) s(id)
           UNION
           SELECT a.ancestor_id FROM unnest(%(ids)s::bigint[]) s(id), lot_ancestors(s.id) a""",
        {"ids": ids}).fetchall()
    return [r["id"] for r in rows]


def with_descendants(conn: psycopg.Connection, ids: list[int]) -> list[int]:
    rows = conn.execute(
        """SELECT s.id FROM unnest(%(ids)s::bigint[]) s(id)
           UNION
           SELECT d.descendant_id FROM unnest(%(ids)s::bigint[]) s(id), lot_descendants(s.id) d""",
        {"ids": ids}).fetchall()
    return [r["id"] for r in rows]


def nodes(conn: psycopg.Connection, ids: list[int]) -> list[dict]:
    return conn.execute(
        """SELECT l.code, l.kind::text AS kind, p.name AS product, l.qty, p.uom::text AS uom, l.status::text AS status,
                  c.custody, m.name AS machine, r.stage::text AS stage, s.name AS shift, r.code AS run_code,
                  COALESCE(r.ended_at, r.started_at, gr.received_at) AS produced_at,
                  sup.name AS supplier
             FROM lot l
             JOIN product p ON p.id = l.product_id
             LEFT JOIN v_roll_custody c ON c.lot_id = l.id
             LEFT JOIN process_run r    ON r.id = l.produced_by_run_id
             LEFT JOIN machine m        ON m.id = r.machine_id
             LEFT JOIN shift s          ON s.id = r.shift_id
             LEFT JOIN goods_receipt gr ON gr.id = l.goods_receipt_id
             LEFT JOIN party sup        ON sup.id = gr.supplier_id
            WHERE l.id = ANY(%s)
            ORDER BY l.kind, l.code""", (ids,)).fetchall()


def edges(conn: psycopg.Connection, ids: list[int]) -> list[dict]:
    """Lineage edges between the given lots only (parent -> child)."""
    return conn.execute(
        """SELECT p.code AS from_, c.code AS "to", ll.qty_consumed
             FROM lot_lineage ll
             JOIN lot p ON p.id = ll.parent_lot_id
             JOIN lot c ON c.id = ll.child_lot_id
            WHERE ll.parent_lot_id = ANY(%(ids)s) AND ll.child_lot_id = ANY(%(ids)s)
            ORDER BY 1, 2""", {"ids": ids}).fetchall()
