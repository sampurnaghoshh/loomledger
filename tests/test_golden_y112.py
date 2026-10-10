"""THE GOLDEN TEST — the demo, executed.

Seed -> Find Cause -> Recall scope -> Impact -> Apply recall -> Blocked movement -> Buyer portal.
Every expected value comes from seed/scenario.py; money is cross-checked against an
independent Python calculation, not against the SQL that produced it.
If this passes, the 5-minute demo works.
"""
from __future__ import annotations

from decimal import Decimal as D

import psycopg
import pytest

from seed import scenario as S
from seed.seed import buyer_token
from tests.conftest import loc_id, lot_id, rows


def _impact(conn) -> dict:
    return rows(conn, "SELECT * FROM recall_impact(%s)", (lot_id(conn, S.Y112),))[0]


def test_y112_golden_chain(fresh_db):
    conn = fresh_db
    y112 = lot_id(conn, S.Y112)

    # ---- ACT 2: Find Cause ---------------------------------------------------------------
    rejected = [lot_id(conn, c) for c in S.REJECTED_ROLLS]
    causes = {r["factor_label"]: r for r in rows(conn, "SELECT * FROM find_cause(%s)", (rejected,))}

    top = rows(conn, "SELECT * FROM find_cause(%s) LIMIT 1", (rejected,))[0]
    assert top["factor_label"] == "Yarn Lot Y-112"
    assert top["verdict"] == "root_cause"

    for label, (insp_in, rej_in, rate_in, insp_out, rej_out, rate_out, verdict) in S.EXPECTED_FIND_CAUSE.items():
        c = causes[label]
        assert (c["inspected_through"], c["rejected_through"], c["rate_through_pct"]) == (insp_in, rej_in, rate_in), label
        assert (c["inspected_outside"], c["rejected_outside"], c["rate_outside_pct"]) == (insp_out, rej_out, rate_out), label
        assert c["verdict"] == verdict, label
        assert c["selected_covered"] == 3, label

    inspected, rejected_total = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE result = 'reject') FROM v_latest_qc").fetchone()
    assert (inspected, rejected_total) == (S.EXPECTED_INSPECTED_TOTAL, S.EXPECTED_REJECTED_TOTAL)

    # ---- ACT 3: Recall scope ----------------------------------------------------------------
    scope = rows(conn, "SELECT * FROM recall_scope(%s)", (y112,))
    assert sorted(r["lot_code"].removesuffix("-G") for r in scope) == sorted(S.Y112_ROLLS)
    for r in scope:
        assert r["custody"] == S.Y112_ROLLS[r["lot_code"].removesuffix("-G")][1], r["lot_code"]
    assert sorted(r["lot_code"] for r in scope if r["custody"] == "at_customer") == S.EXPECTED_AT_CUSTOMER

    # ---- ACT 4: Business impact (before the recall is applied) ---------------------------------
    before = _impact(conn)
    for key, value in S.EXPECTED_SCOPE.items():
        assert before[key] == value, key
    assert before["remake_m"] == S.expected_remake_m() == D("600")
    assert before["bottleneck_stage"] == "weaving"
    assert before["throughput_m_per_day"] == S.expected_throughput() == D("250")
    assert before["additional_delay_days"] == S.expected_delay_days() == 3

    money = S.expected_money()
    for key in ("cost_already_incurred", "cost_in_factory", "cost_wip", "cost_at_customer",
                "recall_exposure", "quarantined_material_qty", "quarantined_material_value", "total_exposure"):
        assert before[key] == money[key].quantize(before[key]), key
    # the loss is exactly the sum of the seeded roll costs
    roll_costs = rows(conn, "SELECT lot_code, total FROM v_roll_cost WHERE lot_code LIKE 'R-12%%'")
    finished = [r["total"] for r in roll_costs if not r["lot_code"].endswith("-G")]
    assert finished and all(t == money["roll_cost_finished"] for t in finished)

    expected_orders = S.expected_order_impact()
    order_rows = rows(conn, "SELECT * FROM recall_order_impact(%s)", (y112,))
    assert [o["order_code"] for o in order_rows] == list(expected_orders)
    for o in order_rows:
        e = expected_orders[o["order_code"]]
        assert (o["affected_rolls"], o["remake_m"], o["delay_days"]) == (e["rolls"], e["remake_m"], e["delay_days"])
        assert (o["promised_date"], o["revised_promise_date"]) == (e["promised"], e["revised"])

    # ---- Apply the recall (and prove it is idempotent) ----------------------------------------
    recall_id = conn.execute("SELECT apply_recall(%s, 'Colour mismatch traced to yarn lot')", (y112,)).fetchone()[0]
    moves_after_first = conn.execute("SELECT count(*) FROM stock_move").fetchone()[0]
    assert conn.execute("SELECT apply_recall(%s, 'again')", (y112,)).fetchone()[0] == recall_id
    assert conn.execute("SELECT count(*) FROM stock_move").fetchone()[0] == moves_after_first
    conn.commit()

    status = dict(conn.execute("SELECT code, status::text FROM lot WHERE code LIKE 'R-12%%' OR code = 'Y-112'"))
    assert status["Y-112"] == "quarantined"
    assert status["R-1204"] == status["R-1205"] == "recalled"
    for code in ("R-1201", "R-1203", "R-1206", "R-1208", "R-1209", "R-1211", "R-1212-G"):
        assert status[code] == "quarantined", code

    quarantine = loc_id(conn, "QUARANTINE")
    yarn_store = loc_id(conn, "YARN-STORE")
    assert conn.execute("SELECT lot_on_hand(%s, %s)", (y112, quarantine)).fetchone()[0] == D("142.800")
    assert conn.execute("SELECT lot_on_hand(%s, %s)", (y112, yarn_store)).fetchone()[0] == 0
    for code in ("R-1201", "R-1206", "R-1209"):           # rejected, passed, awaiting QC: all segregated
        assert conn.execute("SELECT lot_on_hand(%s, %s)", (lot_id(conn, code), quarantine)).fetchone()[0] == 50

    # ---- The money moment: PostgreSQL itself refuses ---------------------------------------
    blocked_attempts = [
        ("Y-112", "QUARANTINE", "PRODUCTION", D("20"), "issue"),     # issue the bad yarn to a loom
        ("R-1206", "QUARANTINE", "CUSTOMERS", D("50"), "dispatch"),  # ship a quarantined roll
        ("R-1212-G", "PRODUCTION", "GREIGE-STORE", D("50"), "production"),  # finish the roll on the loom
    ]
    for lot, src, dst, qty, kind in blocked_attempts:
        with pytest.raises(psycopg.Error) as err:
            conn.execute(
                """INSERT INTO stock_move (lot_id, from_location_id, to_location_id, qty, kind, idempotency_key)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (lot_id(conn, lot), loc_id(conn, src), loc_id(conn, dst), qty, kind, f"demo:{lot}"))
        assert err.value.sqlstate == "LL001"
        assert f"lot {lot} is quarantined" in str(err.value)
        conn.rollback()

    # ---- Impact is identical after the recall (custody is derived from facts) ----------------
    after = _impact(conn)
    assert after == before

    # ---- The buyer sees it on their phone ---------------------------------------------------
    for order in ("SO-0412", "SO-0419"):
        e = expected_orders[order]
        page = conn.execute("SELECT buyer_order_status(%s)", (buyer_token(order),)).fetchone()[0]
        assert page["order"] == order
        assert page["delayed"] is True
        assert page["promised_date"] == e["promised"].isoformat()
        assert page["expected_date"] == e["revised"].isoformat()
        assert any(f"New expected dispatch: {e['revised'].day} {e['revised']:%b %Y}" in u["message"]
                   for u in page["updates"])

    hold = conn.execute("SELECT buyer_order_status(%s)", (buyer_token("SO-0412"),)).fetchone()[0]
    assert any("R-1204, R-1205" in u["message"] for u in hold["updates"])
    other = conn.execute("SELECT buyer_order_status(%s)", (buyer_token("SO-0405"),)).fetchone()[0]
    assert other["delayed"] is False                                  # unaffected orders stay untouched

    # ---- Close: month-end mass balance = the independent model, all of the gap on the leaky loom ----
    totals = rows(conn, "SELECT * FROM mass_balance('-infinity', 'infinity')")[0]
    for key, value in S.expected_mass_balance().items():
        assert totals[key] == value, key
    worst = rows(conn, "SELECT * FROM v_yarn_unaccounted_by_machine")[0]
    assert (worst["machine_code"], worst["runs"]) == (S.LEAKY_MACHINE, S.LEAKY_ROLLS)
    assert worst["unaccounted_kg"] == totals["unaccounted_kg"]

    # ---- Act 1: a busy floor at demo "now" ---------------------------------------------------
    busy = dict(conn.execute("SELECT code, current_lot FROM v_machine_now WHERE state = 'running'"))
    assert set(S.BUSY_FLOOR) | {S.Y112_ROLLS["R-1212"][0]} == set(busy)
    assert all(lot.endswith("-G") for lot in busy.values())                # each loom is weaving a WIP roll

    # ---- Evidence trail ---------------------------------------------------------------------
    audited = conn.execute(
        "SELECT count(*) FROM audit_log WHERE table_name = 'lot' AND new_data->>'status' IN ('quarantined', 'recalled')"
    ).fetchone()[0]
    assert audited == 13                     # yarn lot Y-112 + 11 finished rolls + the greige roll still on Loom 5

    # Quarantined yarn may still go back to the supplier (the recoverable part of the exposure)
    conn.execute(
        """INSERT INTO stock_move (lot_id, from_location_id, to_location_id, qty, kind, idempotency_key)
           VALUES (%s, %s, %s, 142.8, 'supplier_return', 'return:Y-112')""",
        (y112, quarantine, loc_id(conn, "SUPPLIERS")))
    conn.commit()
    assert conn.execute("SELECT lot_on_hand(%s, %s)", (y112, quarantine)).fetchone()[0] == 0
