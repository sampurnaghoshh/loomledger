"""Export REAL API responses from the seeded database into docs/api-mocks/*.json.

These files ARE the API contract: the frontend builds against them (mock mode) and the FastAPI
endpoints must return exactly the same shapes. Regenerate after any schema/seed change:

    python -m scripts.export_mocks          # resets + seeds DATABASE_URL, exports, re-seeds clean
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from db.migrate import database_url, migrate, reset_schema
from seed import scenario as S
from seed.seed import buyer_token, seed

from app.modules.rolls import service as rolls
from app.modules.rolls.schemas import RollLabels, RollPassport

OUT = Path(__file__).resolve().parent.parent / "docs" / "api-mocks"
IST = ZoneInfo(S.TIMEZONE)


def _default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, uuid.UUID):
        return str(o)
    raise TypeError(type(o))


def write(name: str, payload) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(payload, indent=2, default=_default, ensure_ascii=False) + "\n",
                                      encoding="utf-8")


def roll_mocks(conn, phase: str) -> None:
    """QR labels + one passport per banner (and the clean roll), through the API's own schemas."""
    labels = RollLabels.model_validate(rolls.labels(conn, None)).model_dump(mode="json")
    write(f"roll_labels_{phase}", labels)
    clean = next(r["code"] for r in labels["rolls"] if not r["in_scope"])
    for code in [*S.PASSPORT_ROLLS.values(), clean]:
        passport = RollPassport.model_validate(rolls.passport(conn, code)).model_dump(mode="json")
        write(f"roll_passport_{code}_{phase}", passport)


def q(conn, sql: str, params: tuple = ()) -> list[dict]:
    return conn.execute(sql, params).fetchall()


# --------------------------------------------------------------------------- shared builders (mirror the API)
NODE_SQL = """
    SELECT l.code, l.kind::text AS kind, p.name AS product, l.qty, p.uom::text AS uom, l.status::text AS status,
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
     ORDER BY l.kind, l.code"""

EDGE_SQL = """
    SELECT p.code AS "from", c.code AS "to", ll.qty_consumed
      FROM lot_lineage ll JOIN lot p ON p.id = ll.parent_lot_id JOIN lot c ON c.id = ll.child_lot_id
     WHERE ll.parent_lot_id = ANY(%s) AND ll.child_lot_id = ANY(%s)
     ORDER BY 1, 2"""


def graph(conn, ids: list[int]) -> dict:
    return {"nodes": q(conn, NODE_SQL, (ids,)), "edges": q(conn, EDGE_SQL, (ids, ids))}


def recall_payload(conn, lot_code: str) -> dict:
    root = conn.execute("SELECT id FROM lot WHERE code = %s", (lot_code,)).fetchone()["id"]
    return {
        "lot_code": lot_code,
        "impact": q(conn, "SELECT * FROM recall_impact(%s)", (root,))[0],
        "orders": q(conn, "SELECT * FROM recall_order_impact(%s)", (root,)),
        "rolls": q(conn, """SELECT s.lot_code, s.kind::text AS kind, s.qty_m, s.custody, s.order_code, s.buyer_name,
                                   round(c.total, 2) AS cost
                              FROM recall_scope(%s) s CROSS JOIN LATERAL lot_cost(s.lot_id) c""", (root,)),
        "calculation": None,
    }


def with_calculation(p: dict) -> dict:
    i = p["impact"]
    p["calculation"] = {
        "formula": "additional_delay_days = ceil(remake_m / throughput_m_per_day)",
        "remake_m": i["remake_m"],
        "throughput_m_per_day": i["throughput_m_per_day"],
        "raw_days": round(float(i["remake_m"]) / float(i["throughput_m_per_day"]), 2),
        "additional_delay_days": i["additional_delay_days"],
        "display": f'{float(i["remake_m"]):g} ÷ {float(i["throughput_m_per_day"]):g} = '
                   f'{float(i["remake_m"]) / float(i["throughput_m_per_day"]):g} → ceil = {i["additional_delay_days"]} working days',
    }
    return p


def export(conn) -> None:
    anchor = S.ANCHOR_DATE
    ids = lambda codes: [r["id"] for r in q(conn, "SELECT id FROM lot WHERE code = ANY(%s)", (codes,))]  # noqa: E731

    # ---- auth
    write("auth_login", {"token": "<signed token>",
                         "user": q(conn, "SELECT id, email, full_name, role::text AS role FROM app_user WHERE role = 'owner'")[0]})

    # ---- floor
    write("floor_machines", q(conn, """SELECT code, name, stage::text AS stage, state::text AS state, state_since, reason,
                                              current_run, current_lot, current_order
                                         FROM v_machine_now ORDER BY code"""))
    write("floor_output", {"day": anchor, "machines": q(conn, "SELECT * FROM floor_output(%s)", (anchor,))})
    window_from = datetime.combine(anchor - timedelta(days=30), datetime.min.time(), IST)
    window_to = datetime.combine(anchor, datetime.min.time(), IST)
    write("floor_availability", {
        "from": window_from.isoformat(),
        "to": window_to.isoformat(),
        "machines": q(conn, "SELECT * FROM machine_availability(%s, %s)", (window_from, window_to))})
    at = datetime.combine(anchor, S.PROGRESS_SNAPSHOT_AT, IST)
    write("floor_progress", {"at": at, "runs": q(conn, "SELECT *, state::text AS state FROM run_progress(%s)", (at,))})
    write("ws_floor_event", {"machine_id": 4, "machine_code": "LOOM-4", "state": "breakdown",
                             "reason": "Warp beam bearing failure", "started_at": f"{anchor}T09:12:00+05:30",
                             "ended_at": None})
    write("ws_alert_breakdown", conn.execute(
        "SELECT breakdown_alert_payload((SELECT id FROM machine WHERE code = 'LOOM-4'), 'Warp beam bearing failure', %s) AS j",
        (datetime.combine(anchor, time(9, 12), IST),)).fetchone()["j"])

    # ---- inventory
    write("inventory_masters", {
        "suppliers": q(conn, "SELECT code, name FROM party WHERE kind = 'supplier' ORDER BY code"),
        "yarn_products": q(conn, "SELECT code, name FROM product WHERE kind = 'yarn' ORDER BY code"),
        "open_orders": q(conn, """SELECT so.code, b.name AS buyer FROM sales_order so JOIN party b ON b.id = so.buyer_id
                                   WHERE so.status NOT IN ('dispatched', 'cancelled') ORDER BY so.code""")})
    stock_sql = """SELECT s.*, so.code AS order_code
                     FROM stock_on_hand(%s) s JOIN lot l ON l.code = s.lot_code
                     LEFT JOIN goods_receipt gr ON gr.id = l.goods_receipt_id LEFT JOIN sales_order so ON so.id = gr.order_id
                    ORDER BY s.location_code, s.lot_code"""
    write("inventory_stock_now", {"as_of": None, "rows": q(conn, stock_sql, ("infinity",))})
    received = conn.execute("SELECT received_at FROM goods_receipt WHERE code = 'GRN-Y-112'").fetchone()["received_at"]
    write("inventory_stock_as_of", {"as_of": received, "rows": q(conn, stock_sql, (received,))})
    low_stock = lambda: q(conn, """SELECT product_code, product_name, on_hand_kg, quarantined_kg, committed_kg,
                                          open_orders, available_kg, reorder_level_kg, below_reorder_kg
                                     FROM v_yarn_low_stock ORDER BY product_code""")  # noqa: E731
    write("inventory_low_stock", low_stock())

    # ---- workforce (G1)
    write("workforce_attendance", {
        "day": anchor,
        "shifts": q(conn, """SELECT code, name, to_char(starts_at, 'HH24:MI') AS starts_at, to_char(ends_at, 'HH24:MI') AS ends_at
                               FROM shift ORDER BY code"""),
        "workers": q(conn, """SELECT w.code AS worker_code, w.full_name, w.skill::text AS skill, a.status, s.code AS shift_code
                                FROM worker w LEFT JOIN attendance a ON a.worker_id = w.id AND a.work_date = %s
                                LEFT JOIN shift s ON s.id = a.shift_id WHERE w.active ORDER BY w.code""", (anchor,))})
    month_from = date(anchor.year, anchor.month, 1)
    wage_rows = q(conn, "SELECT * FROM wages(%s, %s)", (month_from, anchor))
    write("workforce_wages", {"from": month_from, "to": anchor,
                              "totals": {"workers": len(wage_rows),
                                         "days_worked": sum(r["days_worked"] for r in wage_rows),
                                         "shifts_worked": sum(r["shifts_worked"] for r in wage_rows),
                                         "gross_wage": sum(r["gross_wage"] for r in wage_rows)},
                              "workers": wage_rows})

    # ---- quality
    write("quality_queue", q(conn, """
        SELECT c.lot_code, p.name AS product, c.qty_m, r.code AS dye_batch, m.name AS dyed_on, r.ended_at AS dyed_at,
               so.code AS order_code
          FROM v_roll_custody c
          JOIN lot l ON l.id = c.lot_id JOIN product p ON p.id = l.product_id
          JOIN process_run r ON r.id = l.produced_by_run_id JOIN machine m ON m.id = r.machine_id
          LEFT JOIN reservation rs ON rs.lot_id = l.id LEFT JOIN order_line ol ON ol.id = rs.order_line_id
          LEFT JOIN sales_order so ON so.id = ol.order_id
         WHERE c.custody = 'awaiting_qc' ORDER BY c.lot_code"""))
    write("quality_rejections", q(conn, """
        SELECT l.code AS lot_code, q.defect_type, q.defect_meters, q.inspected_at, w.full_name AS inspector,
               so.code AS order_code
          FROM qc_inspection q JOIN lot l ON l.id = q.lot_id JOIN worker w ON w.id = q.inspector_id
          LEFT JOIN reservation rs ON rs.lot_id = l.id LEFT JOIN order_line ol ON ol.id = rs.order_line_id
          LEFT JOIN sales_order so ON so.id = ol.order_id
         WHERE q.result = 'reject' ORDER BY q.inspected_at DESC"""))

    latest = conn.execute("""SELECT max((inspected_at AT TIME ZONE 'Asia/Kolkata')::date) AS d
                               FROM qc_inspection WHERE result = 'reject'""").fetchone()["d"]
    write("quality_latest_rejections", {"day": latest, "rejections": q(conn, """
        SELECT l.code AS lot_code, q.defect_type, q.defect_meters, q.inspected_at, w.full_name AS inspector,
               so.code AS order_code
          FROM qc_inspection q JOIN lot l ON l.id = q.lot_id JOIN worker w ON w.id = q.inspector_id
          LEFT JOIN reservation rs ON rs.lot_id = l.id LEFT JOIN order_line ol ON ol.id = rs.order_line_id
          LEFT JOIN sales_order so ON so.id = ol.order_id
         WHERE q.result = 'reject' AND (q.inspected_at AT TIME ZONE 'Asia/Kolkata')::date = %s
         ORDER BY q.inspected_at DESC""", (latest,))})

    # ---- trace (Act 2)
    rejected = ids(S.REJECTED_ROLLS)
    write("trace_find_cause", {"selected": S.REJECTED_ROLLS,
                               "factors": q(conn, "SELECT * FROM find_cause(%s)", (rejected,))})
    up = sorted(set(rejected) | {r["ancestor_id"] for rid in rejected
                                 for r in q(conn, "SELECT ancestor_id FROM lot_ancestors(%s)", (rid,))})
    write("trace_graph_ancestors", {"lot_codes": S.REJECTED_ROLLS, **graph(conn, up)})
    y112 = ids([S.Y112])[0]
    down = [y112] + [r["descendant_id"] for r in q(conn, "SELECT descendant_id FROM lot_descendants(%s)", (y112,))]
    write("trace_graph_descendants", {"lot_code": S.Y112, **graph(conn, down)})

    # ---- recall (Acts 3–4)
    write("recall_preview", {"applied": False, "recall_code": None, **with_calculation(recall_payload(conn, S.Y112))})
    for order in ("SO-0412", "SO-0419"):
        write(f"track_{order}_before", conn.execute("SELECT buyer_order_status(%s) AS j",
                                                    (buyer_token(order),)).fetchone()["j"])

    # ---- monthly P&L (G2): the month to the demo day, before and after the recall
    month_from = date(anchor.year, anchor.month, 1)
    pnl = lambda: conn.execute("SELECT monthly_pnl(%s, %s) AS p", (month_from, anchor)).fetchone()["p"]  # noqa: E731
    write("finance_pnl", pnl())
    roll_mocks(conn, "before")

    with conn.transaction():
        conn.execute("SELECT apply_recall(%s, 'Colour mismatch traced to yarn lot Y-112', "
                     "(SELECT id FROM app_user WHERE role = 'qc'))", (y112,))
        # apply_recall stamps now(); pin its recall row and buyer messages to the story's clock so
        # re-exporting is deterministic (this database is re-seeded right after the export).
        recall_at = datetime.combine(anchor, S.RECALL_APPLIED_AT, IST)
        conn.execute("""UPDATE order_event SET created_at = %s
                         WHERE created_at = (SELECT initiated_at FROM recall WHERE root_lot_id = %s)""",
                     (recall_at, y112))
        conn.execute("UPDATE recall SET initiated_at = %s WHERE root_lot_id = %s", (recall_at, y112))
    rc = conn.execute("SELECT code, initiated_at FROM recall WHERE root_lot_id = %s", (y112,)).fetchone()
    # owner alert (016) as it went out at commit, pinned to the story clock like the recall row
    write("ws_alert_recall", conn.execute("SELECT recall_alert_payload(id) AS j FROM recall WHERE root_lot_id = %s",
                                          (y112,)).fetchone()["j"])
    write("recall_applied", {"applied": True, "recall_code": rc["code"], "applied_at": rc["initiated_at"],
                             **with_calculation(recall_payload(conn, S.Y112))})

    try:
        with conn.transaction():
            conn.execute("""INSERT INTO stock_move (lot_id, from_location_id, to_location_id, qty, kind, idempotency_key)
                            SELECT l.id, f.id, t.id, 20, 'issue', 'mock-blocked' FROM lot l, location f, location t
                             WHERE l.code = 'Y-112' AND f.code = 'QUARANTINE' AND t.code = 'PRODUCTION'""")
    except psycopg.Error as e:
        write("error_lot_quarantined", {"error": {"code": "LOT_QUARANTINED", "sqlstate": e.sqlstate,
                                                  "message": e.diag.message_primary, "hint": e.diag.message_hint}})

    for order in ("SO-0412", "SO-0419"):
        write(f"track_{order}_after", conn.execute("SELECT buyer_order_status(%s) AS j",
                                                   (buyer_token(order),)).fetchone()["j"])
    write("finance_pnl_after_recall", pnl())
    write("inventory_low_stock_after_recall", low_stock())
    roll_mocks(conn, "after")
    write("error_not_found", {"error": {"code": "NOT_FOUND", "message": "This tracking link is invalid or has expired."}})

    # ---- orders
    write("orders", q(conn, """
        WITH yarn AS (
            SELECT yp.order_id, CASE WHEN SUM(yp.shortfall_kg) > 0 THEN 'short' ELSE 'ok' END AS status,
                   SUM(yp.required_kg) AS required_kg, SUM(yp.shortfall_kg) AS shortfall_kg, SUM(yp.unwoven_m) AS to_weave_m,
                   string_agg(DISTINCT y.name, ', ') FILTER (WHERE yp.shortfall_kg > 0) AS short_of
              FROM v_yarn_plan yp JOIN product y ON y.id = yp.yarn_product_id
             GROUP BY yp.order_id)
        SELECT so.code, b.name AS buyer, p.name AS product, ol.qty_m AS ordered_m, ol.unit_price,
               so.promised_date, so.revised_promise_date,
               working_days_between(so.promised_date, so.revised_promise_date) AS delay_days,
               so.status::text AS status,
               buyer_order_status(bl.token)->'progress' AS progress, bl.token AS tracking_token,
               y.status AS yarn_status, y.required_kg AS yarn_required_kg, y.shortfall_kg AS yarn_shortfall_kg,
               y.short_of AS yarn_short_of, y.to_weave_m
          FROM sales_order so JOIN party b ON b.id = so.buyer_id
          JOIN order_line ol ON ol.order_id = so.id JOIN product p ON p.id = ol.product_id
          JOIN buyer_link bl ON bl.order_id = so.id
          LEFT JOIN yarn y ON y.order_id = so.id
         ORDER BY so.promised_date"""))

    # ---- yarn check per order (G3), after the recall like orders.json
    for o in S.ORDERS:
        order = conn.execute("""SELECT id, COALESCE(revised_promise_date, promised_date) AS due FROM sales_order
                                 WHERE code = %s""", (o.code,)).fetchone()
        lines = q(conn, """SELECT p.code AS product_code, p.name AS product, y.code AS yarn_product_code,
                                  y.name AS yarn_product, yp.ordered_m, yp.covered_m, yp.unwoven_m, yp.required_kg,
                                  yp.available_kg, yp.shortfall_kg
                             FROM v_yarn_plan yp JOIN product p ON p.id = yp.product_id
                             JOIN product y ON y.id = yp.yarn_product_id
                            WHERE yp.order_id = %s ORDER BY yp.order_line_id""", (order["id"],))
        ahead = [r["order_code"] for r in q(conn, """
            SELECT DISTINCT o.order_code, o.due FROM v_yarn_plan o
              JOIN v_yarn_plan me ON me.order_id = %s AND me.yarn_product_id = o.yarn_product_id
             WHERE o.order_id <> me.order_id AND (o.due, o.order_code) < (me.due, me.order_code)
             ORDER BY o.due, o.order_code""", (order["id"],))]
        shortfall = sum((r["shortfall_kg"] for r in lines), Decimal(0))
        write(f"orders_yarn_check_{o.code}", {
            "order_code": o.code,
            "status": "closed" if not lines else ("short" if shortfall > 0 else "ok"),
            "due": order["due"], "required_kg": sum((r["required_kg"] for r in lines), Decimal(0)), "shortfall_kg": shortfall,
            "orders_ahead": ahead if lines else [], "lines": lines})

    # ---- finance (month-end)
    write("finance_mass_balance", {"from": None, "to": None,
                                   "first_run_at": conn.execute(
                                       "SELECT min(started_at) AS t FROM v_yarn_balance_by_run").fetchone()["t"],
                                   "totals": q(conn, "SELECT * FROM mass_balance('-infinity', 'infinity')")[0],
                                   "by_machine": q(conn, "SELECT * FROM v_yarn_unaccounted_by_machine")})
    write("finance_roll_costs_SO-0412", q(conn, """
        SELECT rc.lot_code, rc.qty_m, rc.material, rc.machine, rc.labour, rc.chemicals, rc.total, rc.cost_per_m,
               c.custody, l.status::text AS status
          FROM v_roll_cost rc JOIN lot l ON l.id = rc.lot_id JOIN v_roll_custody c ON c.lot_id = rc.lot_id
          JOIN reservation rs ON rs.lot_id = rc.lot_id JOIN order_line ol ON ol.id = rs.order_line_id
          JOIN sales_order so ON so.id = ol.order_id
         WHERE so.code = 'SO-0412' ORDER BY rc.lot_code"""))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        reset_schema(conn); migrate(conn); seed(conn)
        export(conn)
        conn.rollback()        # discard the export's writes (incl. the recall's pending at-commit alert, 016): no NOTIFY
        reset_schema(conn); migrate(conn); seed(conn)          # leave a clean, un-recalled demo database
    print(f"wrote {len(list(OUT.glob('*.json')))} files to {OUT}")


if __name__ == "__main__":
    main()
