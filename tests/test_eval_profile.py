"""Seed profile `eval` (seed/eval_profile.py): the story + ~300 rolls of history for evaluators.

Runs in its own database (<test db>_eval) so it never disturbs the shared test database. Proves: it seeds without
errors (every DB guard accepted every row), it is deterministic, the ledger balances, the history is varied and
dated before the story, the story's own numbers are unchanged inside it, and the DEMO profile is byte-identical
(the contract mocks re-exported from a demo seed equal docs/api-mocks).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from db.migrate import migrate, reset_schema
from scripts.ensure_db import ensure_database
from seed import eval_profile as E
from seed import scenario as S
from seed.seed import seed
from tests.conftest import TEST_URL

EVAL_URL = make_conninfo(TEST_URL, dbname=f"{conninfo_to_dict(TEST_URL)['dbname']}_eval")
MOCKS = Path(__file__).resolve().parent.parent / "docs" / "api-mocks"
EVAL_ROLL = r"^R-2\d{3}$"


def fresh(profile: str, *, autocommit: bool = True) -> psycopg.Connection:
    """Reset + seed the eval test database. autocommit (default): read queries hold no locks afterwards, so the
    next fresh() can drop the schema while this connection is still open."""
    ensure_database(EVAL_URL)
    conn = psycopg.connect(EVAL_URL, row_factory=dict_row)
    conn.execute("SET TIME ZONE 'Asia/Kolkata'")   # mill time, whether or not this database was set up before (001)
    conn.commit()
    reset_schema(conn)
    migrate(conn)
    seed(conn, profile=profile)
    conn.autocommit = autocommit
    return conn


def one(conn, sql: str, params: tuple = ()):
    return conn.execute(sql, params).fetchone()


@pytest.fixture(scope="module")
def ev():
    conn = fresh("eval")
    yield conn
    conn.close()


def fingerprint(conn) -> str:
    """Timestamps as epoch seconds: the same instant renders differently in a UTC and an IST session (the database's
    Asia/Kolkata default only reaches sessions opened after migration 001 ran — on a brand-new CI database the first
    connection is still UTC)."""
    rows = conn.execute("""
        SELECT string_agg(concat_ws('|', l.code, l.qty, l.status, extract(epoch FROM l.created_at)), ',' ORDER BY l.code) AS lots,
               (SELECT string_agg(concat_ws('|', l2.code, m.kind, m.qty, extract(epoch FROM m.created_at), m.idempotency_key), ','
                                  ORDER BY m.idempotency_key)
                  FROM stock_move m JOIN lot l2 ON l2.id = m.lot_id) AS moves,
               (SELECT string_agg(concat_ws('|', code, status, order_date, promised_date), ',' ORDER BY code)
                  FROM sales_order) AS orders
          FROM lot l""").fetchone()
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()


# ---------- volume and variety
def test_history_is_about_300_varied_records(ev):
    assert one(ev, "SELECT count(*) AS n FROM lot WHERE kind = 'greige' AND code ~ %s", (r"^R-2\d{3}-G$",))["n"] \
        == E.YARN_LOTS * E.ROLLS_PER_LOT
    assert one(ev, "SELECT count(*) AS n FROM party WHERE kind = 'buyer'")["n"] >= 15
    assert one(ev, "SELECT count(*) AS n FROM party WHERE kind = 'supplier'")["n"] >= 3
    assert one(ev, "SELECT count(*) AS n FROM sales_order")["n"] >= 60
    statuses = {r["status"] for r in ev.execute("SELECT DISTINCT status::text FROM sales_order")}
    assert statuses == {"confirmed", "in_production", "partially_dispatched", "dispatched", "cancelled"}
    results = {r["result"] for r in ev.execute("SELECT DISTINCT result::text FROM qc_inspection")}
    assert results == {"pass", "rework", "reject"}
    defects = {r["defect_type"] for r in ev.execute("SELECT DISTINCT defect_type FROM qc_inspection WHERE defect_type IS NOT NULL")}
    assert set(E.DEFECTS) <= defects
    custody = {r["custody"] for r in ev.execute("SELECT DISTINCT c.custody FROM v_roll_custody c JOIN lot l ON l.id = c.lot_id "
                                               "WHERE l.code ~ '^R-2'")}
    assert {"at_customer", "passed_in_store", "awaiting_qc", "rejected", "consumed"} <= custody
    for table in ("dispatch", "invoice", "payment", "supplier_payment", "attendance", "buyer_link"):
        assert one(ev, f"SELECT count(*) AS n FROM {table}")["n"] > 0, table      # noqa: S608 — fixed table names


def test_history_is_dated_before_the_story_window(ev):
    story_start = datetime.combine(S.ANCHOR_DATE, datetime.min.time(), ZoneInfo(S.TIMEZONE)) \
        + timedelta(days=-(S.ATTENDANCE_DAYS - 1))
    latest = one(ev, """SELECT greatest((SELECT max(m.created_at) FROM stock_move m JOIN lot l ON l.id = m.lot_id
                                          WHERE l.code ~ '^(R-2|Y-3)'),
                                         (SELECT max(paid_at) FROM payment p JOIN invoice i ON i.id = p.invoice_id
                                           WHERE i.code ~ '^INV-03[0-6][0-9]-'),
                                         (SELECT max(inspected_at) FROM qc_inspection q JOIN lot l ON l.id = q.lot_id
                                           WHERE l.code ~ '^R-2')) AS t""")["t"]
    assert latest < story_start


# ---------- ledger + rules
def test_the_ledger_balances(ev):
    # no lot is ever negative anywhere we hold stock
    negative = ev.execute("""
        SELECT l.code, f.location_id, SUM(f.qty) AS qty
          FROM (SELECT lot_id, to_location_id AS location_id, qty FROM stock_move
                UNION ALL SELECT lot_id, from_location_id, -qty FROM stock_move) f
          JOIN location loc ON loc.id = f.location_id AND loc.kind IN ('internal', 'quarantine')
          JOIN lot l ON l.id = f.lot_id
         GROUP BY l.code, f.location_id HAVING SUM(f.qty) < 0""").fetchall()
    assert negative == []
    # yarn: received = in store + issued to looms (each issue is the lineage's qty_consumed)
    for r in ev.execute("""SELECT l.code, l.qty,
                                  COALESCE((SELECT SUM(qty_consumed) FROM lot_lineage WHERE parent_lot_id = l.id), 0) AS issued,
                                  COALESCE((SELECT SUM(qty) FROM stock_on_hand() s WHERE s.lot_code = l.code), 0) AS on_hand
                             FROM lot l WHERE l.kind = 'yarn'"""):
        assert r["qty"] == r["issued"] + r["on_hand"], r["code"]
    # every roll that moved to a customer is dispatched, passed QC and was reserved for that order
    bad = ev.execute("""SELECT l.code FROM dispatch_line dl JOIN dispatch d ON d.id = dl.dispatch_id JOIN lot l ON l.id = dl.lot_id
                         LEFT JOIN v_latest_qc q ON q.lot_id = l.id
                         LEFT JOIN reservation rs ON rs.lot_id = l.id LEFT JOIN order_line ol ON ol.id = rs.order_line_id
                        WHERE q.result IS DISTINCT FROM 'pass' OR ol.order_id IS DISTINCT FROM d.order_id
                           OR l.status <> 'dispatched'""").fetchall()
    assert bad == []
    over = ev.execute("SELECT code FROM v_invoice_balance WHERE outstanding < 0").fetchall() \
        if one(ev, "SELECT to_regclass('v_invoice_balance') AS v")["v"] else []
    assert over == []


def test_the_story_is_unchanged_inside_the_eval_database(ev):
    y112 = one(ev, "SELECT id FROM lot WHERE code = %s", (S.Y112,))["id"]
    i = one(ev, "SELECT * FROM recall_impact(%s)", (y112,))
    for k, v in S.EXPECTED_SCOPE.items():
        assert i[k] == v, k
    assert i["total_exposure"] == S.expected_money()["total_exposure"].quantize(D("0.01"))
    orders = {r["order_code"]: r for r in ev.execute("SELECT * FROM recall_order_impact(%s)", (y112,))}
    for code, e in S.expected_order_impact().items():
        assert (orders[code]["delay_days"], orders[code]["revised_promise_date"]) == (e["delay_days"], e["revised"])
    cost = one(ev, "SELECT total FROM v_roll_cost WHERE lot_code = %s", (S.REJECTED_ROLLS[0],))["total"]
    assert cost == S.expected_y112_roll_cost(True).quantize(D("0.01"))


# ---------- determinism + the demo profile is untouched
def test_eval_profile_is_deterministic(ev):
    first = fingerprint(ev)
    with fresh("eval") as again:
        assert fingerprint(again) == first


def test_demo_profile_still_exports_the_exact_contract(tmp_path, monkeypatch):
    """Byte-identical demo: re-export every mock from a DEMO seed and compare with docs/api-mocks."""
    import scripts.export_mocks as X

    monkeypatch.setattr(X, "OUT", tmp_path)
    with fresh("demo", autocommit=False) as conn:        # export_mocks runs inside one transaction
        X.export(conn)
        conn.rollback()
    produced = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
    expected = {p.name: p.read_bytes() for p in MOCKS.glob("*.json")}
    assert sorted(produced) == sorted(expected)
    assert [n for n in expected if produced[n] != expected[n]] == []


def test_unknown_profile_is_refused():
    with psycopg.connect(EVAL_URL) as conn, pytest.raises(ValueError):
        seed(conn, profile="huge")
