"""Rules the database enforces regardless of which client writes — UI, API or raw psql.

Each test that writes runs inside a transaction that is rolled back, so the module shares one seed.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

import psycopg
import pytest

from seed import scenario as S
from seed.seed import buyer_token
from tests.conftest import TEST_URL, loc_id, lot_id, rows


def expect_sqlstate(conn, sqlstate: str, sql: str, params: tuple = ()) -> psycopg.Error:
    with pytest.raises(psycopg.Error) as err:
        conn.execute(sql, params)
    conn.rollback()
    assert err.value.sqlstate == sqlstate, f"expected {sqlstate}, got {err.value.sqlstate}: {err.value}"
    return err.value


MOVE = """INSERT INTO stock_move (lot_id, from_location_id, to_location_id, qty, kind, idempotency_key)
          VALUES (%s, %s, %s, %s, %s, %s)"""


# ---------------------------------------------------------------- the ledger
def test_ledger_is_append_only(db):
    expect_sqlstate(db, "LL003", "UPDATE stock_move SET qty = qty + 1 WHERE id = (SELECT min(id) FROM stock_move)")
    expect_sqlstate(db, "LL003", "DELETE FROM stock_move WHERE id = (SELECT min(id) FROM stock_move)")


def test_cannot_issue_more_than_on_hand(db):
    err = expect_sqlstate(db, "LL002", MOVE, (lot_id(db, "Y-101"), loc_id(db, "YARN-STORE"),
                                              loc_id(db, "PRODUCTION"), D("1000"), "issue", "t:overdraw"))
    assert "insufficient stock: lot Y-101" in str(err)


def test_idempotency_key_prevents_double_posting(db):
    args = (lot_id(db, "Y-101"), loc_id(db, "YARN-STORE"), loc_id(db, "PRODUCTION"), D("1"), "issue", "t:once")
    db.execute(MOVE, args)
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(MOVE, args)
    db.rollback()


def test_a_roll_can_never_ship_twice(db):
    with db.transaction(force_rollback=True):
        did = db.execute(
            """INSERT INTO dispatch (code, order_id, dispatched_at)
               VALUES ('DSP-TEST', (SELECT id FROM sales_order WHERE code = 'SO-0412'), now()) RETURNING id""").fetchone()[0]
        with pytest.raises(psycopg.errors.UniqueViolation) as err:
            db.execute("INSERT INTO dispatch_line (dispatch_id, lot_id) VALUES (%s, %s)", (did, lot_id(db, "R-1204")))
        assert "one_dispatch_per_roll" in str(err.value)


def _dispatch_for(db, order_code: str, shade_override_reason: str | None = None) -> int:
    return db.execute(
        """INSERT INTO dispatch (code, order_id, dispatched_at, shade_override_reason)
           VALUES ('DSP-TEST', (SELECT id FROM sales_order WHERE code = %s), now(), %s) RETURNING id""",
        (order_code, shade_override_reason)).fetchone()[0]


def _ready_rolls_by_batch(db, order_code: str) -> dict[str, list[str]]:
    """Rolls of an order that passed QC and wait in the store, grouped by dye batch."""
    rows = db.execute(
        """SELECT r.code, c.lot_code FROM v_roll_custody c
             JOIN lot l ON l.id = c.lot_id JOIN process_run r ON r.id = l.produced_by_run_id
             JOIN reservation rs ON rs.lot_id = c.lot_id JOIN order_line ol ON ol.id = rs.order_line_id
             JOIN sales_order so ON so.id = ol.order_id
            WHERE so.code = %s AND c.custody = 'passed_in_store' ORDER BY 1, 2""", (order_code,)).fetchall()
    batches: dict[str, list[str]] = {}
    for batch, roll in rows:
        batches.setdefault(batch, []).append(roll)
    return batches


LINE = "INSERT INTO dispatch_line (dispatch_id, lot_id) VALUES (%s, %s)"


def test_one_dispatch_ships_one_dye_batch(db):
    batches = _ready_rolls_by_batch(db, "SO-0412")
    (b1, rolls1), (b2, rolls2) = list(batches.items())[:2]
    did = _dispatch_for(db, "SO-0412")
    db.execute(LINE, (did, lot_id(db, rolls1[0])))
    err = expect_sqlstate(db, "LL006", LINE, (did, lot_id(db, rolls2[0])))
    assert err.diag.message_detail == f"{b1}, {b2}"          # the API turns this into fields.batches


def test_a_recorded_shade_override_allows_mixing(db):
    batches = _ready_rolls_by_batch(db, "SO-0412")
    (_, rolls1), (_, rolls2) = list(batches.items())[:2]
    with db.transaction(force_rollback=True):
        did = _dispatch_for(db, "SO-0412", "Buyer approved mixed dye lots by email")
        db.execute(LINE, (did, lot_id(db, rolls1[0])))
        db.execute(LINE, (did, lot_id(db, rolls2[0])))       # accepted
    expect_sqlstate(db, "23514", "INSERT INTO dispatch (code, order_id, dispatched_at, shade_override_reason) "
                                 "VALUES ('DSP-BLANK', (SELECT id FROM sales_order WHERE code = 'SO-0412'), now(), '  ')")


def test_seeded_mixed_shipments_carry_their_override(db):
    rows = db.execute(
        """SELECT d.code, count(DISTINCT l.produced_by_run_id) AS batches, d.shade_override_reason
             FROM dispatch d JOIN dispatch_line dl ON dl.dispatch_id = d.id JOIN lot l ON l.id = dl.lot_id
            GROUP BY d.id""").fetchall()
    assert rows and all(reason for _, batches, reason in rows if batches > 1)


@pytest.mark.parametrize("roll", ["R-1201",          # rejected
                                  "R-1209"])         # awaiting QC
def test_only_qc_passed_rolls_can_ship(db, roll):
    did = _dispatch_for(db, "SO-0412")
    err = expect_sqlstate(db, "LL004", "INSERT INTO dispatch_line (dispatch_id, lot_id) VALUES (%s, %s)",
                          (did, lot_id(db, roll)))
    assert f"roll {roll} has not passed quality control" in str(err)


def test_a_roll_ships_only_on_its_own_order(db):
    passed_for_0412 = db.execute(
        """SELECT c.lot_code FROM v_roll_custody c JOIN reservation rs ON rs.lot_id = c.lot_id
             JOIN order_line ol ON ol.id = rs.order_line_id JOIN sales_order so ON so.id = ol.order_id
            WHERE so.code = 'SO-0412' AND c.custody = 'passed_in_store' ORDER BY 1 LIMIT 1""").fetchone()[0]
    did = _dispatch_for(db, "SO-0419")
    err = expect_sqlstate(db, "LL005", "INSERT INTO dispatch_line (dispatch_id, lot_id) VALUES (%s, %s)",
                          (did, lot_id(db, passed_for_0412)))
    assert "not reserved for order SO-0419" in str(err)


# ---------------------------------------------------------------- production rules
def test_machine_cannot_be_double_booked(db):
    # Loom 5 is weaving R-1212 right now (open-ended run); any overlapping run is refused
    err = expect_sqlstate(db, "23P01", """
        INSERT INTO process_run (code, machine_id, stage, shift_id, operator_id, started_at, ended_at)
        SELECT 'WV-TEST', m.id, 'weaving', s.id, w.id, now() + interval '1 day', now() + interval '1 day 6 hours'
          FROM machine m, shift s, worker w WHERE m.code = 'LOOM-5' AND s.code = 'A' AND w.code = 'W-05'""")
    assert "no_machine_double_booking" in str(err)


def test_run_stage_must_match_machine(db):
    expect_sqlstate(db, "23503", """
        INSERT INTO process_run (code, machine_id, stage, shift_id, operator_id, started_at, ended_at)
        SELECT 'BAD', m.id, 'dyeing', s.id, w.id, now() - interval '400 days', now() - interval '399 days'
          FROM machine m, shift s, worker w WHERE m.code = 'LOOM-1' AND s.code = 'A' AND w.code = 'W-01'""")


def test_lot_kind_must_match_product(db):
    expect_sqlstate(db, "23503", """
        INSERT INTO lot (code, kind, product_id, qty, produced_by_run_id, produced_by_stage)
        SELECT 'BAD', 'finished', p.id, 50, r.id, 'dyeing'
          FROM product p, process_run r WHERE p.code = 'YRN-C40' AND r.code = 'DB-01'""")


def test_failed_inspection_must_name_a_defect(db):
    expect_sqlstate(db, "23514", """
        INSERT INTO qc_inspection (lot_id, inspector_id, inspected_at, result)
        SELECT l.id, w.id, now(), 'reject' FROM lot l, worker w WHERE l.code = 'R-1209' AND w.code = 'Q-01'""")


def test_only_finished_fabric_can_be_sold(db):
    expect_sqlstate(db, "23503", """
        INSERT INTO order_line (order_id, product_id, qty_m, unit_price)
        SELECT o.id, p.id, 10, 100 FROM sales_order o, product p WHERE o.code = 'SO-0412' AND p.code = 'GRG-TWL'""")


# ---------------------------------------------------------------- chronology
def test_no_location_ever_went_negative_at_any_moment(db):
    """The guard checks totals at insert time; this proves the history itself is physically possible."""
    negative = db.execute("""
        WITH flows AS (
            SELECT id, lot_id, to_location_id AS loc, created_at,  qty FROM stock_move
            UNION ALL
            SELECT id, lot_id, from_location_id,      created_at, -qty FROM stock_move
        ), running AS (
            SELECT f.*, SUM(f.qty) OVER (PARTITION BY f.lot_id, f.loc ORDER BY f.created_at, f.id) AS balance
              FROM flows f JOIN location l ON l.id = f.loc AND l.kind IN ('internal', 'quarantine')
        )
        SELECT count(*) FROM running WHERE balance < 0""").fetchone()[0]
    assert negative == 0


def test_process_chronology_is_physically_possible(db):
    problems = rows(db, """
        SELECT fin.code, 'dyed before weaving finished' AS problem
          FROM lot fin
          JOIN lot_lineage ll  ON ll.child_lot_id = fin.id
          JOIN lot gr          ON gr.id = ll.parent_lot_id AND gr.kind = 'greige'
          JOIN process_run wv  ON wv.id = gr.produced_by_run_id
          JOIN process_run dy  ON dy.id = fin.produced_by_run_id
         WHERE dy.started_at < wv.ended_at
        UNION ALL
        SELECT l.code, 'inspected before dyeing finished'
          FROM qc_inspection q JOIN lot l ON l.id = q.lot_id JOIN process_run r ON r.id = l.produced_by_run_id
         WHERE q.inspected_at < r.ended_at
        UNION ALL
        SELECT l.code, 'dispatched before passing QC'
          FROM dispatch_line dl JOIN dispatch d ON d.id = dl.dispatch_id JOIN lot l ON l.id = dl.lot_id
          LEFT JOIN v_latest_qc q ON q.lot_id = l.id
         WHERE q.result IS DISTINCT FROM 'pass' OR q.inspected_at >= d.dispatched_at""")
    assert problems == []


# ---------------------------------------------------------------- derived truths
def test_time_travel_reconstructs_past_stock(db):
    received_at = db.execute("SELECT received_at FROM goods_receipt WHERE code = 'GRN-Y-112'").fetchone()[0]
    y112, store = lot_id(db, "Y-112"), loc_id(db, "YARN-STORE")
    on_hand = lambda t: db.execute("SELECT lot_on_hand(%s, %s, %s)", (y112, store, t)).fetchone()[0]  # noqa: E731
    assert on_hand(received_at - timedelta(minutes=1)) == 0
    assert on_hand(received_at) == D("330.000")
    assert on_hand("infinity") == D("142.800")
    snapshot = rows(db, "SELECT * FROM stock_on_hand(%s) WHERE lot_code = 'Y-112'", (received_at,))
    assert snapshot == [{"location_code": "YARN-STORE", "lot_code": "Y-112", "lot_kind": "yarn",
                         "product_code": "YRN-C40", "qty": D("330.000"), "uom": "kg"}]


def test_mass_balance_closes_and_finds_the_leaky_loom(db):
    totals = rows(db, "SELECT * FROM mass_balance('-infinity', 'infinity')")[0]
    assert totals["issued_kg"] == (totals["fabric_kg"] + totals["waste_kg"]
                                   + totals["wip_kg"] + totals["unaccounted_kg"])
    by_machine = rows(db, "SELECT * FROM v_yarn_unaccounted_by_machine")
    assert by_machine[0]["machine_code"] == S.LEAKY_MACHINE
    assert by_machine[0]["unaccounted_kg"] == S.LEAKY_EXTRA_KG * by_machine[0]["runs"]
    assert all(m["unaccounted_kg"] == 0 for m in by_machine[1:])


def test_roll_cost_components_add_up(db):
    for r in rows(db, "SELECT * FROM v_roll_cost"):
        assert abs(r["material"] + r["machine"] + r["labour"] + r["chemicals"] - r["total"]) <= D("0.02"), r["lot_code"]
    wip = rows(db, "SELECT * FROM v_roll_cost WHERE lot_code = 'R-1212-G'")[0]
    assert wip["machine"] == wip["labour"] == 0                    # conversion absorbed at completion
    assert wip["total"] == S.expected_y112_roll_cost(finished=False)


def test_find_cause_does_not_blame_a_partial_factor(db):
    rejected = [lot_id(db, c) for c in S.REJECTED_ROLLS]
    loom2 = rows(db, "SELECT * FROM find_cause(%s) WHERE factor_label = 'Loom 2'", (rejected,))[0]
    assert loom2["selected_covered"] == 2 and loom2["verdict"] == "partial"


def test_working_days_between_is_the_inverse_of_add_working_days(db):
    start = S.ANCHOR_DATE - timedelta(days=10)
    for n in range(0, 15):
        end = db.execute("SELECT add_working_days(%s, %s)", (start, n)).fetchone()[0]
        assert db.execute("SELECT working_days_between(%s, %s)", (start, end)).fetchone()[0] == n
    sunday = next(start + timedelta(days=i) for i in range(7) if (start + timedelta(days=i)).isoweekday() == 7)
    saturday, monday = sunday - timedelta(days=1), sunday + timedelta(days=1)
    assert db.execute("SELECT working_days_between(%s, %s)", (saturday, monday)).fetchone()[0] == 1   # Sunday skipped
    for a, b in ((monday, monday), (monday, saturday), (monday, None)):                                   # not later -> 0
        assert db.execute("SELECT working_days_between(%s, %s)", (a, b)).fetchone()[0] == 0


ATTEND = "INSERT INTO attendance (worker_id, work_date, shift_id, status) VALUES (%s, %s, (SELECT id FROM shift WHERE code = 'A'), %s)"


def _worker(db, code: str) -> int:
    return db.execute("SELECT id FROM worker WHERE code = %s", (code,)).fetchone()[0]


def test_attendance_cannot_be_marked_for_a_future_day(db):
    tomorrow = db.execute("SELECT (now() AT TIME ZONE 'Asia/Kolkata')::date + 1").fetchone()[0]
    err = expect_sqlstate(db, "LL007", ATTEND, (_worker(db, "W-01"), tomorrow, "present"))
    assert "in the future" in str(err)


def test_attendance_only_for_active_workers(db):
    with db.transaction(force_rollback=True):
        db.execute("UPDATE worker SET active = false WHERE code = 'Q-02'")
        with pytest.raises(psycopg.Error) as err:
            db.execute(ATTEND, (_worker(db, "Q-02"), S.ANCHOR_DATE - timedelta(days=60), "present"))
        assert err.value.sqlstate == "LL008"


def test_one_attendance_row_per_worker_per_day(db):
    expect_sqlstate(db, "23505", ATTEND, (_worker(db, "Q-01"), S.ANCHOR_DATE, "absent"))   # the seed already marked it


def test_wages_pay_shift_hours_times_rate(db):
    rows = db.execute("SELECT worker_code, hourly_wage, shifts_worked, gross_wage FROM wages(%s, %s)",
                              (S.ANCHOR_DATE - timedelta(days=S.ATTENDANCE_DAYS - 1), S.ANCHOR_DATE)).fetchall()
    assert rows and all(g == round(h * S.SHIFT_HOURS * s, 2) for _, h, s, g in rows)
    assert db.execute("SELECT shift_hours(id) FROM shift WHERE code = 'B'").fetchone()[0] == S.SHIFT_HOURS   # across midnight


# ---------------------------------------------------------------- money (013)
PAY = """INSERT INTO payment (invoice_id, amount, paid_at, method, idempotency_key)
         SELECT id, %s, now(), 'upi', %s FROM invoice WHERE code = %s"""
BILL = """INSERT INTO supplier_payment (goods_receipt_id, amount, paid_at, method, idempotency_key)
          SELECT id, %s, now(), 'cheque', %s FROM goods_receipt WHERE code = %s"""


def _outstanding_invoice(db, code: str) -> D:
    return db.execute("SELECT outstanding FROM v_invoice_balance WHERE code = %s", (code,)).fetchone()[0]


def test_buyer_cannot_pay_more_than_is_outstanding(db):
    left = _outstanding_invoice(db, "INV-0412-1")
    _, paid, *_ = S.BUYER_PAYMENTS[1]
    assert left == S.expected_invoices()["INV-0412-1"][1] - paid
    err = expect_sqlstate(db, "LL009", PAY, (left + D("0.01"), "t:over", "INV-0412-1"))
    assert "exceeds" in str(err) and err.diag.message_detail == f"{left:.2f}"
    expect_sqlstate(db, "LL009", PAY, (D("1"), "t:paid", "INV-0398-1"))                 # already paid in full


def test_two_payments_cannot_together_exceed_the_invoice(db):
    left = _outstanding_invoice(db, "INV-0412-1")
    with db.transaction(force_rollback=True):
        db.execute(PAY, (left - D("100"), "t:part1", "INV-0412-1"))
        with pytest.raises(psycopg.Error) as err:
            db.execute(PAY, (D("100.01"), "t:part2", "INV-0412-1"))
        assert err.value.sqlstate == "LL009"


def test_cannot_pay_a_supplier_more_than_the_bill(db):
    lot, part, *_ = S.SUPPLIER_PAYMENTS[-1]                                               # the part-paid bill
    _, bill = S.expected_bills()[f"GRN-{lot}"]
    expect_sqlstate(db, "LL009", BILL, (bill - part + D("0.01"), "t:bill-over", f"GRN-{lot}"))
    expect_sqlstate(db, "LL009", BILL, (D("1"), "t:bill-paid", "GRN-Y-101"))              # paid in full


@pytest.mark.parametrize("sql,code", [(PAY, "INV-0412-1"), (BILL, "GRN-Y-112")])
def test_payments_are_positive_and_keyed_once(db, sql, code):
    expect_sqlstate(db, "23514", sql, (D("0"), "t:zero", code))
    expect_sqlstate(db, "23514", sql, (D("-5"), "t:negative", code))
    with db.transaction(force_rollback=True):
        db.execute(sql, (D("10"), "t:once", code))
        with pytest.raises(psycopg.errors.UniqueViolation):
            db.execute(sql, (D("10"), "t:once", code))


def test_pnl_counts_labour_once(db):
    p = db.execute("SELECT monthly_pnl(%s, %s)", (S.ANCHOR_DATE.replace(day=1), S.ANCHOR_DATE)).fetchone()[0]
    a = p["accrual"]
    # COGS = lot_cost without its labour; labour enters only as wages() for the period
    assert a["cost_of_goods_sold"] == pytest.approx(a["material"] + a["machine"] + a["chemicals"])
    assert a["profit"] == pytest.approx(a["revenue"] - a["cost_of_goods_sold"] - a["wages"])
    assert a["labour_in_lot_cost_excluded"] > 0
    wages = db.execute("SELECT SUM(gross_wage) FROM wages(%s, %s)",
                       (S.ANCHOR_DATE.replace(day=1), S.ANCHOR_DATE)).fetchone()[0]
    assert D(str(a["wages"])) == wages


def test_add_working_days_skips_sundays(db):
    # Sat 10 Oct 2026 + 1 working day = Mon 12 Oct
    assert db.execute("SELECT add_working_days('2026-10-10', 1)").fetchone()[0].isoformat() == "2026-10-12"
    expect_sqlstate(db, "22023", "SELECT add_working_days('2026-10-10', -1)")


# ---------------------------------------------------------------- buyer portal security
def test_buyer_portal_rejects_unknown_and_expired_tokens(db):
    assert db.execute("SELECT buyer_order_status(gen_random_uuid())").fetchone()[0] is None
    with db.transaction(force_rollback=True):
        db.execute("UPDATE buyer_link SET expires_at = now() - interval '1 second' WHERE token = %s",
                   (buyer_token("SO-0412"),))
        assert db.execute("SELECT buyer_order_status(%s)", (buyer_token("SO-0412"),)).fetchone()[0] is None


def test_buyer_progress_adds_up_to_reserved_metres(db):
    page = db.execute("SELECT buyer_order_status(%s)", (buyer_token("SO-0412"),)).fetchone()[0]
    reserved = db.execute("""SELECT SUM(l.qty) FROM reservation r JOIN lot l ON l.id = r.lot_id
                               JOIN order_line ol ON ol.id = r.order_line_id
                               JOIN sales_order so ON so.id = ol.order_id WHERE so.code = 'SO-0412'""").fetchone()[0]
    progress = page["progress"]
    # rejected rolls are neither ready nor on hold before a recall, so they are the only gap
    rejected_m = D(50) * 3
    assert D(str(sum(progress.values()))) + rejected_m == reserved


# ---------------------------------------------------------------- real-time push
def test_machine_state_change_is_pushed_via_notify(db):
    # runs last in this module: it commits a breakdown on Dye Vat 2
    listener = psycopg.connect(TEST_URL, autocommit=True)
    writer = psycopg.connect(TEST_URL)
    try:
        listener.execute("LISTEN loomledger_floor")
        machine = writer.execute("SELECT id FROM machine WHERE code = 'VAT-2'").fetchone()[0]
        writer.execute("UPDATE machine_state_log SET ended_at = now() WHERE machine_id = %s AND ended_at IS NULL",
                       (machine,))
        writer.execute("INSERT INTO machine_state_log (machine_id, state, reason, started_at) "
                       "VALUES (%s, 'breakdown', 'test', now())", (machine,))
        writer.commit()
        notes = list(listener.notifies(timeout=5, stop_after=2))
        assert any('"state" : "breakdown"' in n.payload for n in notes)
    finally:
        listener.close()
        writer.close()
