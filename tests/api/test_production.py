"""Production: weaving runs through the API, with every database guard surfacing correctly.

LL001 (quarantine) -> 409 LOT_QUARANTINED, LL002 (stock) -> 422 INSUFFICIENT_STOCK,
23P01 (machine double-booked) -> 409 MACHINE_BUSY, and idempotent replay -> 200 + original body.
Tests run in file order; the recall (which quarantines Y-112) is applied last.
"""
from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.rows import dict_row

from seed import scenario as S
from tests.api.conftest import bearer, load_mock, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")
IST = ZoneInfo(S.TIMEZONE)
STARTS = "/api/production/weaving-runs"


def db():
    return psycopg.connect(TEST_URL, row_factory=dict_row, autocommit=True)


def one(sql: str, params: tuple = ()):
    with db() as conn:
        return conn.execute(sql, params).fetchone()


def on_hand(lot: str, location: str) -> D:
    return one("""SELECT lot_on_hand(l.id, loc.id) AS q FROM lot l, location loc
                   WHERE l.code = %s AND loc.code = %s""", (lot, location))["q"]


def count(table: str) -> int:
    return one(f"SELECT count(*) AS n FROM {table}")["n"]    # table names are test constants


def run_body(**overrides) -> dict:
    body = {"machine_code": "LOOM-2", "yarn_lot_code": "Y-101", "product_code": "GRG-TWL",
            "meters_planned": float(S.ROLL_LENGTH_M), "idempotency_key": str(uuid.uuid4())}
    return {**body, **overrides}


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {role: bearer(login(client, f"{role}@everest.test")) for role in ("owner", "floor", "store", "qc")}


@pytest.fixture(scope="module")
def started(client, auth) -> dict:
    """One weaving run on LOOM-2 from Y-101 for order SO-0419, shared by the start/finish tests."""
    before_kg = on_hand("Y-101", "YARN-STORE")
    expected_n = one("SELECT max(substring(code FROM '^R-([0-9]+)')::int) + 1 AS n FROM lot")["n"]
    body = run_body(order_code="SO-0419")
    res = client.post(STARTS, json=body, headers=auth["floor"])
    assert res.status_code == 201, res.text
    return {"body": body, "res": res.json(), "before_kg": before_kg, "n": expected_n}


# ---------- DB rules from 007, tied to scenario.py ----------
@pytest.mark.parametrize("product,family", [("GRG-TWL", "twill"), ("GRG-POP", "poplin")])
def test_yarn_issue_formula_matches_scenario(product, family):
    kg = one("SELECT weaving_yarn_issue_kg(id, %s) AS kg FROM product WHERE code = %s", (S.ROLL_LENGTH_M, product))["kg"]
    assert kg == S.fabric_kg(family) * (1 + S.YARN_WASTE_RATIO)


@pytest.mark.parametrize("hour,shift", [(8, "A"), (9, "A"), (19, "A"), (20, "B"), (23, "B"), (3, "B"), (7, "B")])
def test_shift_at_follows_the_mill_calendar(hour, shift):
    ts = datetime.combine(S.ANCHOR_DATE, time(hour, 30), IST)
    assert one("SELECT code FROM shift WHERE id = shift_at(%s)", (ts,))["code"] == shift


# ---------- start ----------
def test_start_creates_run_wip_roll_issue_lineage_reservation(started):
    res, n = started["res"], started["n"]
    issued = S.fabric_kg("twill") * (1 + S.YARN_WASTE_RATIO)
    assert res == {"run_code": f"WV-R-{n}", "lot_code": f"R-{n}-G", "yarn_issued_kg": float(issued)}

    assert on_hand("Y-101", "YARN-STORE") == started["before_kg"] - issued
    facts = one("""SELECT l.status::text AS status, c.custody, so.code AS order_code, ll.qty_consumed, y.code AS parent,
                          s.code AS shift, w.code AS operator
                     FROM lot l
                     JOIN v_roll_custody c ON c.lot_id = l.id
                     JOIN lot_lineage ll   ON ll.child_lot_id = l.id JOIN lot y ON y.id = ll.parent_lot_id
                     JOIN process_run r    ON r.id = l.produced_by_run_id
                     JOIN shift s ON s.id = r.shift_id JOIN worker w ON w.id = r.operator_id
                     JOIN reservation rs   ON rs.lot_id = l.id
                     JOIN order_line ol ON ol.id = rs.order_line_id JOIN sales_order so ON so.id = ol.order_id
                    WHERE l.code = %s""", (res["lot_code"],))
    assert (facts["status"], facts["custody"], facts["order_code"]) == ("wip", "wip", "SO-0419")
    assert (facts["parent"], facts["qty_consumed"]) == ("Y-101", issued)
    assert facts["shift"] == one("SELECT code FROM shift WHERE id = shift_at(now())")["code"]
    assert facts["operator"].startswith("W-")


def test_floor_board_shows_the_new_run(client, auth, started):
    loom2 = next(m for m in client.get("/api/floor/machines", headers=auth["qc"]).json() if m["code"] == "LOOM-2")
    assert (loom2["current_run"], loom2["current_lot"]) == (started["res"]["run_code"], started["res"]["lot_code"])
    assert (loom2["state"], loom2["reason"]) == ("running", None)            # start-run set the loom running
    open_rows = one("""SELECT count(*) AS n FROM machine_state_log s JOIN machine m ON m.id = s.machine_id
                        WHERE m.code = 'LOOM-2' AND s.ended_at IS NULL""")["n"]
    assert open_rows == 1


def test_start_replay_returns_original(client, auth, started):
    runs = count("process_run")
    again = client.post(STARTS, json=started["body"], headers=auth["floor"])
    assert again.status_code == 200 and again.json() == started["res"]
    assert count("process_run") == runs


def test_machine_busy_is_409_and_writes_nothing(client, auth, started):
    moves, runs, states = count("stock_move"), count("process_run"), count("machine_state_log")
    for loom in ("LOOM-2", "LOOM-5"):                       # our run, and the seeded roll still on Loom 5
        res = client.post(STARTS, json=run_body(machine_code=loom), headers=auth["floor"])
        assert res.status_code == 409, res.text
        assert (res.json()["error"]["code"], res.json()["error"]["sqlstate"]) == ("MACHINE_BUSY", "23P01")
    assert (count("stock_move"), count("process_run"), count("machine_state_log")) == (moves, runs, states)


def test_insufficient_stock_is_422_and_writes_nothing(client, auth):
    moves, runs, lots = count("stock_move"), count("process_run"), count("lot")
    too_much = float(on_hand("Y-102", "YARN-STORE") / (S.fabric_kg("twill") / S.ROLL_LENGTH_M) + 1)   # > all of it
    res = client.post(STARTS, json=run_body(machine_code="LOOM-3", yarn_lot_code="Y-102", meters_planned=too_much),
                      headers=auth["floor"])
    assert res.status_code == 422, res.text
    err = res.json()["error"]
    assert (err["code"], err["sqlstate"]) == ("INSUFFICIENT_STOCK", "LL002") and "Y-102" in err["message"]
    assert (count("stock_move"), count("process_run"), count("lot")) == (moves, runs, lots)   # one transaction


@pytest.mark.parametrize("overrides,field", [
    ({"machine_code": "LOOM-99"}, "machine_code"), ({"yarn_lot_code": "Y-999"}, "yarn_lot_code"),
    ({"product_code": "FIN-TWL-NVY"}, "product_code"),           # finished, not greige
    ({"order_code": "SO-9999"}, "order_code"), ({"operator_code": "W-99"}, "operator_code")])
def test_start_unknown_reference_is_404(client, auth, overrides, field):
    res = client.post(STARTS, json=run_body(**{"machine_code": "LOOM-1", **overrides}), headers=auth["floor"])
    assert res.status_code == 404, res.text
    assert field in res.json()["error"]["fields"]


@pytest.mark.parametrize("overrides,field", [
    ({"machine_code": "VAT-1"}, "machine_code"),                 # the DB's (machine, stage) FK, relabelled
    ({"meters_planned": 0}, "meters_planned"), ({"yarn_lot_code": "R-1201"}, "yarn_lot_code"),
    ({"idempotency_key": "x"}, "idempotency_key")])
def test_start_bad_body_is_422(client, auth, overrides, field):
    res = client.post(STARTS, json=run_body(**overrides), headers=auth["floor"])
    assert res.status_code == 422, res.text
    assert field in res.json()["error"]["fields"]


@pytest.mark.parametrize("role", ["store", "qc"])
def test_start_wrong_role_is_403(client, auth, role):
    assert client.post(STARTS, json=run_body(machine_code="LOOM-1"), headers=auth[role]).status_code == 403


def test_start_needs_token(client):
    assert client.post(STARTS, json=run_body(machine_code="LOOM-1")).status_code == 401


# ---------- finish ----------
def test_finish_closes_run_scraps_waste_and_stores_roll(client, auth, started):
    run, lot = started["res"]["run_code"], started["res"]["lot_code"]
    waste = float(S.yarn_waste_kg("twill"))
    body = {"waste_kg": waste, "idempotency_key": str(uuid.uuid4())}
    in_production = on_hand("Y-101", "PRODUCTION")
    res = client.post(f"{STARTS}/{run}/finish", json=body, headers=auth["owner"])
    assert res.status_code == 200, res.text
    assert res.json() == {"run_code": run, "lot_code": lot, "meters": float(S.ROLL_LENGTH_M)}

    assert on_hand(lot, "GREIGE-STORE") == S.ROLL_LENGTH_M
    assert in_production - on_hand("Y-101", "PRODUCTION") == S.yarn_waste_kg("twill")    # waste went to scrap
    facts = one("""SELECT l.status::text AS status, c.custody, r.ended_at IS NOT NULL AS ended, (lot_cost(l.id)).*
                     FROM lot l JOIN v_roll_custody c ON c.lot_id = l.id JOIN process_run r ON r.id = l.produced_by_run_id
                    WHERE l.code = %s""", (lot,))
    assert (facts["status"], facts["custody"], facts["ended"]) == ("active", "awaiting_qc", True)
    # conversion absorbed at completion: material from the yarn share, machine + labour from the run's hours
    issued = S.fabric_kg("twill") * (1 + S.YARN_WASTE_RATIO)
    assert facts["material"] == issued * S.YARN_LOTS["Y-101"][2]
    assert facts["machine"] > 0 and facts["labour"] > 0
    loom2 = next(m for m in client.get("/api/floor/machines", headers=auth["qc"]).json() if m["code"] == "LOOM-2")
    assert (loom2["state"], loom2["current_run"]) == ("idle", None)          # finish-run set it idle again
    started["finish"] = (body, res.json())


def test_finish_replay_returns_original(client, auth, started):
    body, first = started["finish"]
    moves = count("stock_move")
    again = client.post(f"{STARTS}/{first['run_code']}/finish", json=body, headers=auth["floor"])
    assert again.status_code == 200 and again.json() == first
    assert count("stock_move") == moves


def test_finish_twice_is_422(client, auth, started):
    run = started["res"]["run_code"]
    res = client.post(f"{STARTS}/{run}/finish", json={"waste_kg": 0, "idempotency_key": str(uuid.uuid4())},
                      headers=auth["floor"])
    assert res.status_code == 422 and res.json()["error"]["fields"] == {"run_code": "already finished"}


@pytest.mark.parametrize("run", ["WV-R-9999", "DB-01"])          # unknown, and a dyeing run
def test_finish_unknown_run_is_404(client, auth, run):
    res = client.post(f"{STARTS}/{run}/finish", json={"waste_kg": 0, "idempotency_key": str(uuid.uuid4())},
                      headers=auth["floor"])
    assert res.status_code == 404


def test_finish_bad_body_is_422(client, auth):
    res = client.post(f"{STARTS}/WV-R-1212/finish", json={"waste_kg": -1, "idempotency_key": str(uuid.uuid4())},
                      headers=auth["floor"])
    assert res.status_code == 422 and "waste_kg" in res.json()["error"]["fields"]


def test_finish_wrong_role_and_no_token(client, auth):
    body = {"waste_kg": 0, "idempotency_key": str(uuid.uuid4())}
    assert client.post(f"{STARTS}/WV-R-1212/finish", json=body, headers=auth["store"]).status_code == 403
    assert client.post(f"{STARTS}/WV-R-1212/finish", json=body).status_code == 401


# ---------- after the recall: the stage demo (keep these last) ----------
@pytest.fixture(scope="module")
def recalled():
    with db() as conn:
        conn.execute("SELECT apply_recall(id, 'Colour mismatch traced to yarn lot Y-112') FROM lot WHERE code = %s",
                     (S.Y112,))


def test_issuing_quarantined_yarn_is_refused_by_postgres(client, auth, recalled):
    moves, runs = count("stock_move"), count("process_run")
    res = client.post(STARTS, json=run_body(machine_code="LOOM-2", yarn_lot_code=S.Y112), headers=auth["floor"])
    assert res.status_code == 409, res.text
    err, mock = res.json()["error"], load_mock("error_lot_quarantined")["error"]
    assert err == {**mock, "fields": None}                        # exactly the contract's error example
    assert (count("stock_move"), count("process_run")) == (moves, runs)


def test_finishing_a_recalled_roll_on_the_loom_is_refused(client, auth, recalled):
    res = client.post(f"{STARTS}/WV-R-1212/finish", json={"waste_kg": 0, "idempotency_key": str(uuid.uuid4())},
                      headers=auth["floor"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "LOT_QUARANTINED"
    assert one("SELECT ended_at FROM process_run WHERE code = 'WV-R-1212'")["ended_at"] is None   # rolled back
